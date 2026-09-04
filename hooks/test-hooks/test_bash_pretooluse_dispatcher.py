"""Behaviour, telemetry, wiring-parity and timing tests for hooks/bash-pretooluse-dispatcher.py.

Contract: PreToolUse matcher "Bash|PowerShell". ONE process reads the payload once and
runs the six formerly-unconditional Bash hooks in-process (runpy, each hook's own
__main__ block, nothing refactored), in this order:

    bash-security-guard, destructive-ops-guard, git-destructive-checkout-guard,
    bash-tail-buffering-guard, zsh-dialect-guard, poll-loop-nudge

  * the first exit 2 wins: its stderr is forwarded and later hooks do not run
  * an exit-0 rewrite (hookSpecificOutput.updatedInput) is what the remaining hooks see,
    and the LAST rewrite reaches the runtime exactly once
  * additionalContext / systemMessage / permissionDecision from exit-0 hooks are merged
    into ONE JSON object; nothing is printed when no hook had anything to say
  * one fire row per hook it ran, in run-hook's format and location, so
    bin/hook-fire-report.py and the guards' liveness checks see each hook as before;
    run-hook writes the dispatcher's OWN row, so the dispatcher must not (double count)
  * a PowerShell payload reaches only destructive-ops-guard, the one hook whose matcher
    ever included PowerShell (poll-loop-nudge does not gate on tool_name — measured — so
    running it there would be a behaviour change)

Two styles of test, deliberately:
  * REAL: the shipped guards through conftest.run_hook — pins that the merge works on
    the hooks that actually run in production (a stub-only suite can pass while the
    real guards misbehave under a StringIO stdin).
  * SANDBOX: the dispatcher copied beside stub hooks carrying the six names (the
    test_write_edit_dispatcher.py pattern) — pins each merge rule on its own, where the
    real guards cannot be made to exercise it deterministically.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import HOOKS_DIR, PYTHON, make_bash_input, make_powershell_input, run_hook

HOOK = "bash-pretooluse-dispatcher.py"
REPO = HOOKS_DIR.parent
RUN_HOOK = HOOKS_DIR / "run-hook"
ORDER = [
    "bash-security-guard.py",
    "destructive-ops-guard.py",
    "git-destructive-checkout-guard.py",
    "bash-tail-buffering-guard.py",
    "zsh-dialect-guard.py",
    "poll-loop-nudge.py",
]
LEGACY_KEYS = ("updated_input", '"decision"', '"message"', '"result"', '"ok"')

needs_bash_launcher = pytest.mark.skipif(
    sys.platform == "win32", reason="run-hook is a bash launcher; Windows needs Git Bash + pythonw"
)


# ── helpers ───────────────────────────────────────────────────────────────

def _load_dispatcher():
    """Import the (hyphenated) dispatcher by path without running main()."""
    spec = importlib.util.spec_from_file_location("bash_pretooluse_dispatcher", HOOKS_DIR / HOOK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows(cfg: Path) -> list[dict]:
    """Fire rows the dispatcher (or run-hook) wrote under <cfg>/audit, in write order."""
    audit = cfg / "audit"
    if not audit.is_dir():
        return []
    rows = []
    for path in sorted(audit.glob("hook-fires-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _dispatch(payload: dict, cfg: Path, **env: str):
    """Run the REAL dispatcher with the fire log redirected to an isolated config dir
    (CLAUDE_CONFIG_DIR is the first location run-hook itself honours)."""
    return run_hook(HOOK, payload, timeout=30, env={"CLAUDE_CONFIG_DIR": str(cfg), **env})


_SILENT = "import sys\nsys.exit(0)\n"
_CRASH_AT_IMPORT = "raise RuntimeError('boom')\n"  # escapes any __main__ handler
_EXIT_ONE = "import sys\nsys.stderr.write('oops from git guard\\n')\nsys.exit(1)\n"
_REWRITE = """import json, sys
data = json.load(sys.stdin)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
    "permissionDecision": "allow", "permissionDecisionReason": "rewrote",
    "updatedInput": {**data["tool_input"], "command": %(cmd)r}}}))
"""
_RECORD = """import json, os, sys
raw = sys.stdin.read()
try:
    command = json.loads(raw)["tool_input"]["command"]
except Exception:
    command = raw
with open(%(path)r, "w", encoding="utf-8") as fh:
    json.dump({"command": command, "cwd": os.getcwd(), "argv": sys.argv[1:], "path": sys.path}, fh)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
    "additionalContext": "saw: " + command}}))
"""
_CONTEXT = """import json
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": %(text)r}}))
"""
_SYSMSG = "import json\nprint(json.dumps({'systemMessage': %(text)r}))\n"
_DECISION = """import json
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
    "permissionDecision": %(d)r, "permissionDecisionReason": %(r)r}}))
"""
_MUTATE = """import os, sys
os.chdir(%(d)r)
sys.argv.append("junk")
sys.path.insert(0, "/nowhere")
sys.stdout = None
sys.stderr = None
"""
_STDERR_OK = "import sys\nsys.stderr.write('advisory on stderr\\n')\nsys.exit(0)\n"


def _sandbox(tmp_path: Path, stubs: dict[str, str]) -> Path:
    """Copy the dispatcher into tmp_path beside stub hooks carrying the six real names.
    Every name gets a stub (default: silent exit 0); `stubs` overrides by filename."""
    shutil.copy2(HOOKS_DIR / HOOK, tmp_path / HOOK)
    for name in ORDER:
        (tmp_path / name).write_text(stubs.get(name, _SILENT), encoding="utf-8")
    return tmp_path / HOOK


def _run_sandbox(tmp_path: Path, stubs: dict[str, str], payload: dict | None = None,
                 raw: str | None = None):
    dispatcher = _sandbox(tmp_path, stubs)
    cfg = tmp_path / "cfg"
    start = tmp_path / "start"
    start.mkdir(exist_ok=True)
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg)}
    r = subprocess.run(
        [PYTHON, str(dispatcher)],
        input=raw if raw is not None else json.dumps(payload or make_bash_input("ls -la")),
        capture_output=True, text=True, encoding="utf-8", timeout=30, env=env, cwd=str(start), check=False,
    )
    return r.returncode, r.stdout, r.stderr, _rows(cfg)


def _names(rows):
    return [r["hook"] for r in rows]


# ── REAL guards: verdict merging ─────────────────────────────────────────

def test_catastrophic_command_short_circuits_and_later_hooks_never_run(tmp_path):
    rc, out, err = _dispatch(make_bash_input("rm -rf /"), tmp_path)
    assert rc == 2
    assert "[dangerous-command-guard] BLOCKED" in err  # bash-security-guard's own text
    assert out == ""
    rows = _rows(tmp_path)
    assert _names(rows) == ["bash-security-guard.py"], rows  # NO rows for the other five
    assert rows[0]["exit"] == 2


def test_a_block_from_the_second_hook_stops_the_chain_there(tmp_path):
    # bash-security-guard allows `rm -rf manifests/`; destructive-ops-guard blocks it.
    rc, out, err = _dispatch(make_bash_input("rm -rf manifests/"), tmp_path)
    assert rc == 2
    assert "[destructive-ops-guard] BLOCKED (Bash)" in err
    assert out == ""
    rows = _rows(tmp_path)
    assert _names(rows) == ["bash-security-guard.py", "destructive-ops-guard.py"], rows
    assert [r["exit"] for r in rows] == [0, 2]


def test_benign_command_prints_nothing_and_exits_zero(tmp_path):
    rc, out, err = _dispatch(make_bash_input("ls -la"), tmp_path)
    assert (rc, out, err) == (0, "", "")


def test_real_rewrite_chain_yields_one_updated_input_that_the_later_hook_saw(tmp_path):
    """Two REAL rewrites in sequence prove both halves of the contract at once.

    bash-security-guard (policy pack `all`, set by conftest) swaps `python3 x.py` for
    `python x.py` when x.py imports boto3. bash-tail-buffering-guard runs after it and
    rewrites `producer | tail -N` into a file redirect. If the tail guard had seen the
    ORIGINAL command its output would still begin with `python3`; a final command that
    begins with `python ` AND carries the tailbuf redirect can only come from the tail
    guard rewriting the security guard's rewrite."""
    script = tmp_path / "s3_probe.py"
    script.write_text("import boto3\nprint(boto3.__version__)\n", encoding="utf-8")
    rc, out, err = _dispatch(make_bash_input(f"python3 {script} | tail -20"), tmp_path / "cfg")
    assert rc == 0, err
    assert out.count("updatedInput") == 1, out
    hso = json.loads(out)["hookSpecificOutput"]
    final = hso["updatedInput"]["command"]
    assert final.startswith("python "), final
    assert "tailbuf_" in final and "tail -20" in final, final
    assert hso["permissionDecision"] == "allow"
    assert "python3->python" in hso["permissionDecisionReason"]
    assert "tail-buffering-guard" in hso["permissionDecisionReason"]
    assert hso["hookEventName"] == "PreToolUse"
    for legacy in LEGACY_KEYS:
        assert legacy not in out, legacy


def test_real_advisory_on_stderr_passes_through_with_exit_zero(tmp_path):
    rc, out, err = _dispatch(make_bash_input("sleep 90"), tmp_path)
    assert rc == 0
    assert "[poll-loop-nudge] ADVISORY" in err
    assert out == ""  # the nudge speaks on stderr only; nothing to merge


def test_real_additional_context_reaches_stdout_as_one_object(tmp_path):
    rc, out, err = _dispatch(make_bash_input("grep -rn x hooks/ --include=*.py"), tmp_path)
    assert rc == 0, err
    result = json.loads(out)
    assert "[zsh-dialect-guard]" in result["hookSpecificOutput"]["additionalContext"]
    assert "permissionDecision" not in result["hookSpecificOutput"]  # nobody decided
    assert "systemMessage" not in result


# ── REAL guards: telemetry ───────────────────────────────────────────────

def test_fire_rows_are_written_for_each_hook_in_run_order(tmp_path):
    _dispatch(make_bash_input("ls -la"), tmp_path)
    rows = _rows(tmp_path)
    assert _names(rows) == ORDER, rows
    for row in rows:
        assert set(row) == {"ts", "hook", "exit", "ms"}, row  # run-hook's exact schema
        assert row["exit"] == 0
        assert isinstance(row["ts"], int) and isinstance(row["ms"], int)
    # run-hook logs the dispatcher's own fire; a second row here would double-count it.
    assert HOOK not in _names(rows)


@needs_bash_launcher
def test_through_run_hook_the_dispatcher_row_appears_exactly_once(tmp_path):
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path)}
    done = subprocess.run(
        [str(RUN_HOOK), HOOK], input=json.dumps(make_bash_input("ls -la")),
        capture_output=True, text=True, encoding="utf-8", timeout=60, env=env, cwd=str(REPO), check=False,
    )
    assert done.returncode == 0, done.stderr
    names = _names(_rows(tmp_path))
    assert names.count(HOOK) == 1, names
    assert names[:6] == ORDER, names  # the six land before the launcher's own row


# ── REAL guards: PowerShell scope ────────────────────────────────────────

def test_powershell_payload_reaches_only_destructive_ops_guard(tmp_path):
    rc, _out, err = _dispatch(make_powershell_input("Remove-Item -Recurse -Force ./indexes"), tmp_path)
    assert rc == 2
    assert "[destructive-ops-guard] BLOCKED (PowerShell)" in err
    assert _names(_rows(tmp_path)) == ["destructive-ops-guard.py"]


def test_benign_powershell_payload_runs_one_hook_and_says_nothing(tmp_path):
    rc, out, err = _dispatch(make_powershell_input("Get-ChildItem ."), tmp_path)
    assert (rc, out, err) == (0, "", "")
    assert _names(_rows(tmp_path)) == ["destructive-ops-guard.py"]


# ── SANDBOX: merge rules in isolation ────────────────────────────────────

def test_rewrite_is_applied_to_later_hooks_and_emitted_exactly_once(tmp_path):
    seen = tmp_path / "seen.json"
    rc, out, err, rows = _run_sandbox(tmp_path, {
        "bash-tail-buffering-guard.py": _REWRITE % {"cmd": "REWRITTEN"},
        "zsh-dialect-guard.py": _RECORD % {"path": str(seen)},
    })
    assert rc == 0, err
    assert json.loads(seen.read_text(encoding="utf-8"))["command"] == "REWRITTEN"
    assert out.count("updatedInput") == 1
    hso = json.loads(out)["hookSpecificOutput"]
    assert hso["updatedInput"]["command"] == "REWRITTEN"
    assert hso["additionalContext"] == "saw: REWRITTEN"
    assert _names(rows) == ORDER


def test_two_additional_contexts_are_both_present_and_joined_with_a_blank_line(tmp_path):
    rc, out, err, _ = _run_sandbox(tmp_path, {
        "zsh-dialect-guard.py": _CONTEXT % {"text": "ctx-one"},
        "poll-loop-nudge.py": _CONTEXT % {"text": "ctx-two"},
    })
    assert rc == 0, err
    result = json.loads(out)
    assert result["hookSpecificOutput"]["additionalContext"] == "ctx-one\n\nctx-two"
    assert set(result) == {"hookSpecificOutput"}
    assert set(result["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}


@pytest.mark.parametrize("first,second,expected", [
    ("allow", "ask", "ask"),
    ("ask", "deny", "deny"),
    ("deny", "allow", "deny"),
    ("allow", "allow", "allow"),
])
def test_strictest_permission_decision_wins_and_reasons_join(tmp_path, first, second, expected):
    rc, out, err, _ = _run_sandbox(tmp_path, {
        "bash-security-guard.py": _DECISION % {"d": first, "r": "reason-one"},
        "bash-tail-buffering-guard.py": _DECISION % {"d": second, "r": "reason-two"},
    })
    assert rc == 0, err
    hso = json.loads(out)["hookSpecificOutput"]
    assert hso["permissionDecision"] == expected
    assert "reason-one" in hso["permissionDecisionReason"]
    assert "reason-two" in hso["permissionDecisionReason"]


def test_system_messages_are_joined_at_top_level(tmp_path):
    rc, out, err, _ = _run_sandbox(tmp_path, {
        "destructive-ops-guard.py": _SYSMSG % {"text": "msg-one"},
        "poll-loop-nudge.py": _SYSMSG % {"text": "msg-two"},
    })
    assert rc == 0, err
    result = json.loads(out)
    assert result["systemMessage"] == "msg-one\nmsg-two"
    assert "hookSpecificOutput" not in result  # nothing to say inside it


def test_exit_one_forwards_stderr_and_the_chain_continues(tmp_path):
    seen = tmp_path / "seen.json"
    rc, _out, err, rows = _run_sandbox(tmp_path, {
        "git-destructive-checkout-guard.py": _EXIT_ONE,
        "zsh-dialect-guard.py": _RECORD % {"path": str(seen)},
    })
    assert rc == 0
    assert "oops from git guard" in err
    assert seen.exists()
    assert [r["exit"] for r in rows] == [0, 0, 1, 0, 0, 0]


def test_exit_zero_stderr_passes_through_unchanged(tmp_path):
    rc, out, err, _ = _run_sandbox(tmp_path, {"poll-loop-nudge.py": _STDERR_OK})
    assert (rc, out) == (0, "")
    assert err == "advisory on stderr\n"


def test_hook_global_state_is_restored_before_the_next_hook(tmp_path):
    """A hook that chdirs, appends to argv, prepends to sys.path and even clobbers
    sys.stdout must not leak any of it into the next hook or crash the dispatcher."""
    seen = tmp_path / "seen.json"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    rc, out, err, rows = _run_sandbox(tmp_path, {
        "bash-security-guard.py": _MUTATE % {"d": str(elsewhere)},
        "destructive-ops-guard.py": _RECORD % {"path": str(seen)},
    })
    assert rc == 0, err
    state = json.loads(seen.read_text(encoding="utf-8"))
    assert Path(state["cwd"]).resolve() == (tmp_path / "start").resolve()
    assert "junk" not in state["argv"]
    assert "/nowhere" not in state["path"]
    assert json.loads(out)["hookSpecificOutput"]["additionalContext"] == "saw: ls -la"
    assert _names(rows) == ORDER


# ── SANDBOX: crash policy per hook ───────────────────────────────────────

def test_crash_in_the_fail_closed_guard_blocks_with_its_own_message(tmp_path):
    rc, out, err, rows = _run_sandbox(tmp_path, {"bash-security-guard.py": _CRASH_AT_IMPORT})
    assert rc == 2
    assert "[bash-security-guard] BLOCKED: hook crashed (RuntimeError: boom)" in err
    assert out == ""
    assert _names(rows) == ["bash-security-guard.py"]  # nothing after it ran
    assert rows[0]["exit"] == 1  # a crash is a crash in the telemetry, not a block


def test_crash_in_destructive_ops_guard_is_loud_but_fails_open(tmp_path):
    rc, _out, err, rows = _run_sandbox(tmp_path, {"destructive-ops-guard.py": _CRASH_AT_IMPORT})
    assert rc == 0
    assert "[destructive-ops-guard] WARNING: guard crashed (RuntimeError: boom); command allowed unchecked." in err
    assert _names(rows) == ORDER
    assert rows[1]["exit"] == 1


def test_crash_in_an_advisory_hook_is_silent_and_fails_open(tmp_path):
    rc, out, err, rows = _run_sandbox(tmp_path, {"zsh-dialect-guard.py": _CRASH_AT_IMPORT})
    assert (rc, out, err) == (0, "", "")
    assert _names(rows) == ORDER
    assert rows[4]["exit"] == 1


def test_missing_advisory_hook_file_is_skipped_silently(tmp_path):
    dispatcher = _sandbox(tmp_path, {})
    (tmp_path / "poll-loop-nudge.py").unlink()
    r = subprocess.run([PYTHON, str(dispatcher)], input=json.dumps(make_bash_input("ls")),
                       capture_output=True, text=True, encoding="utf-8", timeout=30,
                       env={**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}, check=False)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


# ── in-process: a fault in the dispatcher itself ─────────────────────────

def _fault(*_args, **_kwargs):
    raise RuntimeError("merge bug")


def test_dispatcher_fault_before_the_closed_verdict_fails_closed(monkeypatch, capsys, tmp_path):
    mod = _load_dispatcher()
    monkeypatch.setattr(mod, "_run_hook", _fault)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(make_bash_input("ls -la"))))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert mod.main() == 2
    assert "[bash-pretooluse-dispatcher] BLOCKED: dispatcher crashed (RuntimeError: merge bug)" in capsys.readouterr().err


def test_dispatcher_fault_with_no_closed_guard_pending_fails_open_loudly(monkeypatch, capsys, tmp_path):
    mod = _load_dispatcher()
    monkeypatch.setattr(mod, "_run_hook", _fault)
    # PowerShell selects destructive-ops-guard only — nothing fail-closed is pending.
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(make_powershell_input("dir"))))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert mod.main() == 0
    assert "[bash-pretooluse-dispatcher] WARNING: dispatcher crashed" in capsys.readouterr().err


# ── payload edge cases ───────────────────────────────────────────────────

def test_unparseable_payload_is_handed_to_every_hook_untouched(tmp_path):
    """The dispatcher never decides on a hook's behalf: an unparseable payload reaches
    each hook as the raw text so each applies its OWN parse-failure policy."""
    seen = tmp_path / "seen.json"
    rc, _out, err, rows = _run_sandbox(tmp_path, {"zsh-dialect-guard.py": _RECORD % {"path": str(seen)}},
                                       raw="this is not json {{{")
    assert rc == 0, err
    assert json.loads(seen.read_text(encoding="utf-8"))["command"] == "this is not json {{{"
    assert _names(rows) == ORDER


def test_payload_for_a_tool_no_hook_was_matched_on_runs_nothing(tmp_path):
    rc, out, err, rows = _run_sandbox(tmp_path, {}, payload={"tool_name": "Read", "tool_input": {"file_path": "/x"}})
    assert (rc, out, err) == (0, "", "")
    assert rows == []


# ── wiring parity ────────────────────────────────────────────────────────

def _pretooluse_command_entries(path: Path):
    settings = json.loads(path.read_text(encoding="utf-8"))
    for group in settings["hooks"]["PreToolUse"]:
        matcher = group.get("matcher") or ""
        for hook in group.get("hooks", []) or []:
            if hook.get("type") != "command":
                continue
            script = next((a for a in hook.get("args") or [] if isinstance(a, str) and a.endswith(".py")), None)
            if script:
                yield matcher, script, hook.get("if"), hook.get("timeout")


def _matches_bash(matcher: str) -> bool:
    """Claude Code matchers are regexes against the tool name; empty/`*` match all."""
    return matcher in ("", "*") or re.fullmatch(matcher, "Bash") is not None


@pytest.mark.parametrize("settings_file", ["settings.json", "settings.example.json"])
def test_dispatcher_owns_exactly_the_unconditional_bash_pretooluse_hooks(settings_file):
    """Nobody adds an unconditional Bash hook to settings without the dispatcher, or to
    the dispatcher while it is still wired in settings (which would run it twice)."""
    mod = _load_dispatcher()
    inside = [filename for _name, filename, _posture in mod.GUARDS]
    entries = list(_pretooluse_command_entries(REPO / settings_file))

    unconditional_bash = {script for matcher, script, cond, _ in entries if _matches_bash(matcher) and not cond}
    assert unconditional_bash == {HOOK}, (
        f"{settings_file}: every unconditional Bash PreToolUse hook must run inside the "
        f"dispatcher; found wired directly: {sorted(unconditional_bash - {HOOK})}"
    )
    on_bash = {script for matcher, script, _cond, _ in entries if _matches_bash(matcher)}
    assert not (set(inside) & on_bash), f"{settings_file}: wired twice: {sorted(set(inside) & on_bash)}"

    own = [(matcher, cond, timeout) for matcher, script, cond, timeout in entries if script == HOOK]
    assert own == [("Bash|PowerShell", None, 30)], own

    assert inside == ORDER  # the six, in the order settings.json used to evaluate them
    assert mod.RUNS_ON_POWERSHELL == {"destructive-ops-guard"}
    for filename in inside:
        assert (HOOKS_DIR / filename).is_file(), filename


def test_if_gated_bash_hooks_stay_outside_the_dispatcher():
    entries = list(_pretooluse_command_entries(REPO / "settings.json"))
    gated = {script: cond for matcher, script, cond, _ in entries if cond and _matches_bash(matcher)}
    assert gated == {
        "git-empty-push-guard.py": "Bash(git push*)",
        "staged-additions-guard.py": "Bash(git commit*)",
        "pr-duplicate-preflight.py": "Bash(gh pr create*)",
    }


def test_manifest_matches_the_wiring():
    text = (HOOKS_DIR / "manifests" / "bash-pretooluse-dispatcher.yaml").read_text(encoding="utf-8")
    assert "event: PreToolUse" in text
    assert 'matcher: "Bash|PowerShell"' in text
    assert "if_condition: null" in text
    for filename in ORDER:
        assert filename in text, filename


def test_dispatcher_is_documented_where_the_hooks_it_hosts_are():
    arch = (REPO / "ARCHITECTURE.md").read_text(encoding="utf-8")
    readme = (HOOKS_DIR / "README.md").read_text(encoding="utf-8")
    assert f"`{HOOK}`" in arch
    assert f"`{HOOK}`" in readme


# ── timing ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def timings(tmp_path_factory):
    """(dispatcher_ms, six_separately_ms): medians of 5 wall-clock runs of `ls -la`
    through run-hook — the production launch shape for both sides."""
    if sys.platform == "win32":
        pytest.skip("run-hook is a bash launcher")
    cfg = tmp_path_factory.mktemp("cfg")
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(cfg)}
    payload = json.dumps(make_bash_input("ls -la"))

    def via_run_hook(name: str) -> float:
        start = time.perf_counter()
        done = subprocess.run([str(RUN_HOOK), name], input=payload, capture_output=True, text=True,
                              encoding="utf-8", timeout=60, env=env, cwd=str(REPO), check=False)
        elapsed = (time.perf_counter() - start) * 1000
        # A run that did not succeed measured nothing (a missing hook exits in 20 ms).
        assert done.returncode == 0, f"{name}: rc={done.returncode} stderr={done.stderr!r}"
        return elapsed

    via_run_hook(HOOK)  # warm-up: first spawns pay for pyc writes and cold caches
    for name in ORDER:
        via_run_hook(name)
    dispatcher = statistics.median(via_run_hook(HOOK) for _ in range(5))
    six = statistics.median(sum(via_run_hook(name) for name in ORDER) for _ in range(5))
    return dispatcher, six


@needs_bash_launcher
def test_timing_median_of_five_is_under_the_absolute_budget(timings):
    dispatcher, six = timings
    assert dispatcher < 350, f"dispatcher median {dispatcher:.0f} ms (six separately: {six:.0f} ms)"


@needs_bash_launcher
def test_timing_dispatcher_is_at_least_40_percent_faster_than_six_spawns(timings):
    dispatcher, six = timings
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    cpus = os.cpu_count() or 1
    if load > cpus:
        pytest.skip(f"machine under load (1-min loadavg {load:.1f} > {cpus} cpus): the ratio is "
                    f"not meaningful here; measured dispatcher {dispatcher:.0f} ms vs six {six:.0f} ms")
    assert dispatcher <= 0.6 * six, (
        f"dispatcher {dispatcher:.0f} ms is not >=40% faster than six run-hook spawns {six:.0f} ms"
    )
