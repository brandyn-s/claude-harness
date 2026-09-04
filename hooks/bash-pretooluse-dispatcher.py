"""Consolidated PreToolUse:Bash|PowerShell dispatcher — six hooks, one interpreter.

Runs, IN-PROCESS and in this order, the six hooks that used to be wired as separate
unconditional PreToolUse entries in settings.json:

  1. bash-security-guard             fail-closed catastrophic guard
  2. destructive-ops-guard           the one guard that also covers PowerShell
  3. git-destructive-checkout-guard
  4. bash-tail-buffering-guard
  5. zsh-dialect-guard
  6. poll-loop-nudge

WHY. Every Bash call paid 6 x (bash run-hook + python3 start-up): 210 ms median for
`ls -la` on the author's machine (2026-09-03), for hook bodies that total ~18 ms. One
interpreter does the same work in ~50 ms. The three `if`-gated Bash hooks
(git-empty-push-guard, staged-additions-guard, pr-duplicate-preflight) stay outside:
their `if` already keeps them from spawning on most calls.

NOTHING IS REFACTORED. Each hook is executed with runpy.run_path(run_name="__main__")
in a fresh namespace, reading the payload from a StringIO stdin with stdout/stderr
captured, so its own __main__ block — including its own crash policy — runs exactly as
it does standalone, and every hook still works standalone. sys.stdin/stdout/stderr,
sys.argv, sys.path and the cwd are restored after each hook.

MERGE RULES
  * exit 2 from any hook: forward that hook's stderr, exit 2, stop — later hooks do not run
  * exit 0 with JSON stdout: hookSpecificOutput.updatedInput replaces tool_input for the
    remaining hooks and the LAST rewrite is the one emitted; additionalContext values
    are joined with blank lines; the strictest permissionDecision wins (deny > ask >
    allow) and the reasons are joined; top-level systemMessage strings are joined
  * exit 0 stderr, and the stderr of any other exit code (1 = non-blocking error), pass
    through unchanged and the run continues
  * an exception that escapes a hook's own __main__ (an import-time failure, or a
    missing file) follows that hook's posture, see the GUARDS table
  * exactly one JSON object is printed, and nothing at all when no hook had anything to
    say; the legacy updated_input / decision / message / result / ok keys are never emitted

TELEMETRY. One fire row per hook it ran, in run-hook's format and location
({"ts","hook","exit","ms"} -> <config>/audit/hook-fires-YYYYMMDD.jsonl), so
bin/hook-fire-report.py and the guards' liveness checks see each hook exactly as
before. The dispatcher's OWN row is written by run-hook, which launches it; writing a
second one here would double-count it.

SCOPE. All six were matched on "Bash"; destructive-ops-guard alone was "Bash|PowerShell".
A PowerShell payload therefore reaches only destructive-ops-guard — poll-loop-nudge does
not gate on tool_name, so running it there would have been new behaviour. A payload the
old matchers would never have fired on runs nothing. An UNPARSEABLE payload is handed to
every hook untouched so each applies its own parse-failure policy.
"""
from __future__ import annotations

import io
import json
import os
import runpy
import sys
import time
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent

# (name, filename, posture) — the tuple shape bin/architecture-drift-check.py and
# manifests/compile.py parse to count these hooks as wired through a dispatcher.
# Posture applies ONLY to an exception that escapes the hook's own __main__ block
# (import-time failure, missing file); anything inside main() is the hook's own business:
#   closed  block (exit 2) with the hook's own BLOCKED text   — bash-security-guard's policy
#   warn    allow, but print the hook's own WARNING text       — destructive-ops-guard's policy
#   open    allow silently                                     — the advisory hooks' policy
GUARDS = [
    ("bash-security-guard", "bash-security-guard.py", "closed"),
    ("destructive-ops-guard", "destructive-ops-guard.py", "warn"),
    ("git-destructive-checkout-guard", "git-destructive-checkout-guard.py", "open"),
    ("bash-tail-buffering-guard", "bash-tail-buffering-guard.py", "open"),
    ("zsh-dialect-guard", "zsh-dialect-guard.py", "open"),
    ("poll-loop-nudge", "poll-loop-nudge.py", "open"),
]
# The only hook whose settings.json matcher ever included PowerShell.
RUNS_ON_POWERSHELL = frozenset({"destructive-ops-guard"})

_STRICTNESS = {"allow": 0, "ask": 1, "deny": 2}


def _config_dir() -> Path:
    """Same resolution order as hooks/run-hook: explicit config root, platform home,
    then this launcher's own tree (Claude Code may omit HOME, #79509)."""
    explicit = os.environ.get("CLAUDE_CONFIG_DIR")
    if explicit:
        return Path(explicit)
    profile = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if profile:
        return Path(profile) / ".claude"
    return HOOKS_DIR.parent


def _log_fire(hook: str, code: int, ms: float) -> None:
    """Append a run-hook-format fire row. Best-effort; never alters the verdict."""
    try:
        audit = _config_dir() / "audit"
        audit.mkdir(parents=True, exist_ok=True)
        row = {"ts": int(time.time()), "hook": hook, "exit": code, "ms": int(ms)}
        path = audit / f"hook-fires-{time.strftime('%Y%m%d')}.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001, S110 — telemetry is best-effort, like run-hook's `|| true`
        pass


def _exit_code(code: object) -> int:
    """SystemExit.code the way the interpreter reads it: None -> 0, int -> int,
    anything else is printed to stderr and means 1."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def _run_hook(path: Path, stdin_text: str) -> tuple[int, str, str, Exception | None]:
    """Execute one hook in-process as __main__.

    Returns (exit_code, stdout, stderr, escaped) where `escaped` is an exception the
    hook's own __main__ block did not handle (import-time failure, missing file)."""
    saved_streams = (sys.stdin, sys.stdout, sys.stderr)
    saved_argv, saved_path = list(sys.argv), list(sys.path)
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = None
    out_buf, err_buf = io.StringIO(), io.StringIO()
    sys.stdin, sys.stdout, sys.stderr = io.StringIO(stdin_text), out_buf, err_buf
    code, escaped = 0, None
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        code = _exit_code(exc.code)
    except Exception as exc:  # noqa: BLE001 — the posture table decides, not us
        escaped = exc
    finally:
        sys.stdin, sys.stdout, sys.stderr = saved_streams
        sys.argv[:] = saved_argv
        sys.path[:] = saved_path
        if cwd is not None:
            try:
                if os.getcwd() != cwd:
                    os.chdir(cwd)
            except OSError:
                pass
    return code, out_buf.getvalue(), err_buf.getvalue(), escaped


def _json_object(text: str) -> dict | None:
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def main() -> int:
    # Until we know otherwise, assume the fail-closed guard still owes a verdict: a
    # fault in THIS file must not silently approve a command that guard never saw.
    pending_closed = {name for name, _f, posture in GUARDS if posture == "closed"}
    try:
        raw = sys.stdin.read()
        data = _json_object(raw)
        if data is None:
            selected = GUARDS  # unparseable: every hook applies its own policy to the raw text
        else:
            tool = data.get("tool_name")
            if tool == "Bash":
                selected = GUARDS
            elif tool == "PowerShell":
                selected = [g for g in GUARDS if g[0] in RUNS_ON_POWERSHELL]
            else:
                selected = []  # the old matchers never fired these hooks for any other tool
        pending_closed = {name for name, _f, posture in selected if posture == "closed"}

        stdin_text = raw
        contexts: list[str] = []
        messages: list[str] = []
        reasons: list[str] = []
        decision: str | None = None
        updated: dict | None = None

        for name, filename, posture in selected:
            start = time.perf_counter()
            code, out, err, escaped = _run_hook(HOOKS_DIR / filename, stdin_text)
            ms = (time.perf_counter() - start) * 1000
            pending_closed.discard(name)

            if escaped is not None:
                _log_fire(filename, 1, ms)  # what run-hook records for a traceback
                detail = f"{type(escaped).__name__}: {escaped}"
                if posture == "closed":
                    sys.stderr.write(f"[{name}] BLOCKED: hook crashed ({detail})\n")
                    return 2
                if posture == "warn":
                    sys.stderr.write(f"[{name}] WARNING: guard crashed ({detail}); "
                                     "command allowed unchecked.\n")
                continue

            _log_fire(filename, code, ms)
            if code == 2:
                sys.stderr.write(err)
                return 2
            if err:
                sys.stderr.write(err)
            if code != 0:
                continue  # non-blocking error: stderr forwarded, verdict unaffected

            result = _json_object(out)
            if result is None:
                if out.strip():
                    # Plain text on exit 0: keep it visible without corrupting the one
                    # JSON object this process is allowed to print.
                    sys.stderr.write(out)
                continue
            hso = result.get("hookSpecificOutput")
            if isinstance(hso, dict):
                new_input = hso.get("updatedInput")
                if isinstance(new_input, dict):
                    updated = new_input
                    if data is not None:
                        data["tool_input"] = new_input
                        stdin_text = json.dumps(data)
                context = hso.get("additionalContext")
                if isinstance(context, str) and context:
                    contexts.append(context)
                verdict = hso.get("permissionDecision")
                if verdict in _STRICTNESS and (
                    decision is None or _STRICTNESS[verdict] > _STRICTNESS[decision]
                ):
                    decision = verdict
                reason = hso.get("permissionDecisionReason")
                if isinstance(reason, str) and reason:
                    reasons.append(reason)
            message = result.get("systemMessage")
            if isinstance(message, str) and message:
                messages.append(message)

        hso_out: dict = {"hookEventName": "PreToolUse"}
        if decision is not None:
            hso_out["permissionDecision"] = decision
            if reasons:
                hso_out["permissionDecisionReason"] = "; ".join(reasons)
        if updated is not None:
            hso_out["updatedInput"] = updated
        if contexts:
            hso_out["additionalContext"] = "\n\n".join(contexts)
        merged: dict = {}
        if len(hso_out) > 1:
            merged["hookSpecificOutput"] = hso_out
        if messages:
            merged["systemMessage"] = "\n".join(messages)
        if merged:
            print(json.dumps(merged))
        return 0
    except Exception as exc:  # noqa: BLE001 — a fault in the dispatcher itself
        # The hooks that ran applied their own policies; this is ours. If the fail-closed
        # guard has not delivered its verdict the command is uninspected and must not
        # proceed (its policy, applied for it); otherwise fail open and say so.
        kind = "BLOCKED" if pending_closed else "WARNING"
        sys.stderr.write(f"[bash-pretooluse-dispatcher] {kind}: dispatcher crashed "
                         f"({type(exc).__name__}: {exc})\n")
        return 2 if pending_closed else 0


if __name__ == "__main__":
    # Windows consoles default to cp1252; the guards' messages carry em-dashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    sys.exit(main())
