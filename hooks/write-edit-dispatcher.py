"""Consolidated PreToolUse:Write|Edit dispatcher.

Runs the five individual guards in a single process to avoid 5x Python
startup overhead per Write/Edit (estimated 60-85ms -> 25-35ms):

  1. memory-write-guard  - blocks prompt injection / oversize entries
  2. config-guard         - blocks settings.json edits that disable hooks
  3. worktree-enforcement - blocks subagent writes to protected repos
  4. rule-size-guard      - enforces per-file and aggregate ambient-rule budgets
  5. home-scratch-guard   - warns on non-dotfiles written to the home root

Each guard exposes a check(hook_input) function returning
  (exit_code, stderr_payload, stdout_payload)
where exit_code is 0 (allow / warn) or 2 (block). The first guard to
return 2 short-circuits; warnings from preceding allow-with-warning
returns are emitted before exit.

Fail posture (B2/F4 owner decision, 2026-06-10): each guard declares
"open" or "closed" in GUARDS. A "closed" guard that is missing, fails
to load, or raises BLOCKS the edit (exit 2) — config-guard is the
self-protection guard, and a crashed self-protection guard failing
open meant a prompt-injected settings.json edit could ride a guard
bug. "open" guards log loudly and continue — a bug in an advisory
guard must not brick all editing.

Standalone hooks still work — their main() functions are unchanged.
This dispatcher is wired into settings.json instead of registering all
five separately.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent

# (name, filename, fail_posture). Posture semantics in the module
# docstring. Only config-guard is "closed" per the B2/F4 decision;
# worktree-enforcement stays "open" because a load-failure there would
# brick main-thread editing too (its blocking scope is subagents only,
# which the dispatcher can't determine without loading it).
GUARDS = [
    ("memory-write-guard", "memory-write-guard.py", "open"),
    ("config-guard", "config-guard.py", "closed"),
    ("worktree-enforcement", "worktree-enforcement.py", "open"),
    ("rule-size-guard", "rule-size-guard.py", "open"),
    # warn-only (never returns 2); "open" so a load failure can't block editing.
    ("home-scratch-guard", "home-scratch-guard.py", "open"),
]


def _fail_closed(name: str, reason: str,
                 pending_stderr: list, pending_stdout: list) -> None:
    """Block the edit because a fail-closed guard cannot run.

    Returns (instead of exiting) when SKIP_CONFIG_GUARD is set — the same
    documented bypass config-guard.check() honors. Without this valve a
    broken config-guard.py would brick ALL editing, including the Edit
    that fixes config-guard.py itself."""
    import os
    if os.environ.get("SKIP_CONFIG_GUARD", "").strip().lower() in ("1", "true", "yes"):
        sys.stderr.write(
            f"[write-edit-dispatcher] WARNING: fail-closed guard '{name}' "
            f"could not run ({reason}) but SKIP_CONFIG_GUARD is set — "
            f"proceeding (deliberate, audited bypass).\n"
        )
        return
    for msg in pending_stderr:
        sys.stderr.write(msg + "\n")
    for msg in pending_stdout:
        print(msg)
    sys.stderr.write(
        f"[write-edit-dispatcher] BLOCKED: fail-closed guard '{name}' "
        f"could not run ({reason}). This guard protects the hook "
        f"config itself, so the edit is denied rather than waved "
        f"through. Fix or restore hooks/{name}.py, or set "
        f"SKIP_CONFIG_GUARD=1 for a deliberate, audited bypass.\n"
    )
    sys.exit(2)


def _load(name: str, filename: str):
    path = HOOKS_DIR / filename
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    return mod


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        sys.exit(0)

    pending_stderr: list[str] = []
    pending_stdout: list[str] = []

    for name, filename, posture in GUARDS:
        mod = _load(name, filename)
        if mod is None or not hasattr(mod, "check"):
            if posture == "closed":
                # Exits 2 unless SKIP_CONFIG_GUARD bypass is active.
                _fail_closed(name, "missing or failed to load",
                             pending_stderr, pending_stdout)
            # Open guard missing/unrefactored (or bypassed) — skip it.
            continue
        try:
            code, stderr_msg, stdout_msg = mod.check(hook_input)
        except Exception as e:
            if posture == "closed":
                # Exits 2 unless SKIP_CONFIG_GUARD bypass is active.
                _fail_closed(name, f"raised {type(e).__name__}: {e}",
                             pending_stderr, pending_stdout)
                continue
            # An open guard's crash must not block the edit. Surface a hint
            # and continue.
            pending_stderr.append(
                f"[write-edit-dispatcher] guard '{name}' raised {type(e).__name__}: {e}"
            )
            continue
        if stderr_msg:
            pending_stderr.append(stderr_msg)
        if stdout_msg:
            pending_stdout.append(stdout_msg)
        if code == 2:
            # Flush warnings from earlier guards before the block message
            for msg in pending_stderr:
                sys.stderr.write(msg + "\n")
            for msg in pending_stdout:
                print(msg)
            sys.exit(2)

    # All guards passed (with possible warnings).
    for msg in pending_stderr:
        sys.stderr.write(msg + "\n")
    for msg in pending_stdout:
        print(msg)
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
