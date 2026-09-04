#!/usr/bin/env python3
"""Atomic+locked state mutation helpers shared by supergoal scripts.

Wraps OS-level file locking (fcntl on POSIX, msvcrt on Windows) plus
atomic-rename around the state.json read/write cycle. Used by
check_prior_arcs.py, write_terminal.py, and any future scripts that
touch the per-plan state. The type:agent Stop hook implements the
same pattern inline in its agent prompt (Bash-only, no Python import
available there).

claude-code#28923 documents the failure mode this prevents: concurrent
writes to a single state file produce up to 369 corrupted backups per
day under subagent fan-out. Per-plan dir + lock + atomic rename
eliminates the race.

Cross-platform: works on Linux, Mac, and Windows. fcntl is POSIX-only;
on Windows, msvcrt.locking() provides equivalent exclusive locking.
"""

import contextlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    import msvcrt

    def _lock_exclusive(fileobj):
        msvcrt.locking(fileobj.fileno(), msvcrt.LK_LOCK, 0x7fffffff)

    def _unlock(fileobj):
        msvcrt.locking(fileobj.fileno(), msvcrt.LK_UNLCK, 0x7fffffff)
else:
    import fcntl

    def _lock_exclusive(fileobj):
        fcntl.flock(fileobj.fileno(), fcntl.LOCK_EX)

    def _unlock(fileobj):
        fcntl.flock(fileobj.fileno(), fcntl.LOCK_UN)


class CorruptStateError(RuntimeError):
    pass


@contextlib.contextmanager
def locked_state(state_path):
    state_path = Path(state_path)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        _lock_exclusive(lock)
        try:
            if state_path.exists():
                raw = state_path.read_text(encoding="utf-8")
                if not raw.strip():
                    data = {}
                else:
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError as e:
                        corrupt_archive = state_path.with_suffix(
                            state_path.suffix + f".corrupt-{int(__import__('time').time())}"
                        )
                        state_path.rename(corrupt_archive)
                        raise CorruptStateError(
                            f"state file at {state_path} is malformed JSON "
                            f"(archived to {corrupt_archive}). "
                            f"Re-run parse_plan.py with --reset to rebuild, "
                            f"or restore manually. Original error: {e}"
                        ) from e
            else:
                data = {}
            yield data
            tmp = state_path.with_suffix(state_path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, state_path)
        finally:
            _unlock(lock)


def append_event(events_path, event):
    events_path = Path(events_path)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    event.setdefault("ts", datetime.now(timezone.utc).isoformat())
    line = json.dumps(event) + "\n"
    with events_path.open("a", encoding="utf-8") as f:
        _lock_exclusive(f)
        try:
            f.write(line)
        finally:
            _unlock(f)


def find_state_dir(plan_path_or_slug, root=None):
    root = Path(root) if root else Path.home() / ".claude" / "supergoal"
    if Path(plan_path_or_slug).suffix == ".md":
        slug = Path(plan_path_or_slug).stem
    else:
        slug = plan_path_or_slug
    return root / slug


def _resolve_state_path(arg):
    root = Path.home() / ".claude" / "supergoal"
    if arg:
        p = Path(arg).expanduser()
        if p.suffix == ".json":
            return p
        if "/" not in arg and not p.is_absolute() and not p.exists():
            return root / arg / "state.json"
        return p / "state.json"
    active = root / ".active"
    if active.exists():
        return Path(active.read_text(encoding="utf-8").strip())
    candidates = sorted(root.glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit(f"no active supergoal state found in {root}")
    return candidates[0]


_USAGE = (
    "usage: state_io.py {--pause|--resume|--show} [state-dir-or-state-json]\n"
    "\n"
    "Pause, resume, or inspect an active supergoal arc.\n"
    "\n"
    "Commands:\n"
    "  --pause   stop the loop after the current turn; preserves state\n"
    "  --resume  resume a paused arc; refuses if the plan SHA changed\n"
    "  --show    print a one-shot status dump as JSON\n"
    "\n"
    "Positional:\n"
    "  [state-dir-or-state-json]  state path; defaults to ~/.claude/supergoal/.active\n"
    "\n"
    "  -h, --help  show this help message and exit\n"
)


def _cli(argv):
    if any(a in ("-h", "--help") for a in argv[1:]):
        print(_USAGE)
        return 0
    if len(argv) < 2:
        raise SystemExit(_USAGE)
    cmd = argv[1]
    arg = argv[2] if len(argv) > 2 else None
    state_path = _resolve_state_path(arg)
    if cmd in ("--pause", "--resume") and not state_path.exists():
        # locked_state treats a missing file as {} and WRITES it back on
        # exit — so pausing/resuming a typo'd slug used to fabricate a
        # phantom arc dir (state.json + paused event) under the live
        # runtime root and report success. Mirror --show's refusal.
        raise SystemExit(f"no state at {state_path}; nothing to {cmd.lstrip('-')}")
    if cmd == "--pause":
        with locked_state(state_path) as state:
            if state.get("exit_reason"):
                raise SystemExit(f"plan already exited ({state['exit_reason']}); cannot pause")
            if state.get("paused_at"):
                print(f"already paused at {state['paused_at']}")
                return 0
            now = datetime.now(timezone.utc)
            lva = state.get("last_verified_at")
            if lva:
                try:
                    prior_active = (now - datetime.fromisoformat(lva)).total_seconds()
                    if prior_active > 0:
                        state["wallclock_used_seconds"] = state.get("wallclock_used_seconds", 0) + int(prior_active)
                except (ValueError, TypeError):
                    # ValueError: unparseable timestamp. TypeError: a tz-naive
                    # last_verified_at (aware-minus-naive subtraction) — both
                    # mean "skip the wallclock add", not "crash the pause".
                    pass
            state["paused_at"] = now.isoformat()
            state["last_verified_at"] = now.isoformat()
            slug = state.get("plan_slug", "?")
            turn = state.get("turn_budget_total", 0) - state.get("turn_budget_remaining", 0)
        events = state_path.parent / "events.jsonl"
        append_event(events, {"turn": turn, "event": "paused"})
        print(f"PAUSED {slug} at turn {turn} (state={state_path})")
    elif cmd == "--resume":
        with locked_state(state_path) as state:
            if not state.get("paused_at"):
                print("not paused; nothing to do")
                return 0
            plan_path = Path(state.get("plan_path", ""))
            if not plan_path.exists():
                raise SystemExit(
                    f"plan file missing at {plan_path} (was deleted while paused). "
                    f"Re-run /superplan to update and re-attest, "
                    f"then re-invoke /supergoal. Refusing auto-resume with missing plan."
                )
            import hashlib
            current_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            if current_sha != state.get("plan_sha256"):
                raise SystemExit(
                    f"plan SHA-256 changed while paused (expected {(state.get('plan_sha256') or '?')[:12]}, "
                    f"got {current_sha[:12]}). Re-run /superplan to update and re-attest, "
                    f"then re-invoke /supergoal. Refusing auto-resume into different plan."
                )
            state["paused_at"] = None
            state["last_verified_at"] = datetime.now(timezone.utc).isoformat()
            slug = state.get("plan_slug", "?")
            turn = state.get("turn_budget_total", 0) - state.get("turn_budget_remaining", 0)
            remaining = state.get("turn_budget_remaining", 0)
        events = state_path.parent / "events.jsonl"
        append_event(events, {"turn": turn, "event": "resumed"})
        print(f"RESUMED {slug} at turn {turn} ({remaining} turns remaining)")
    elif cmd == "--show":
        if not state_path.exists():
            raise SystemExit(f"no state at {state_path}")
        # Read-only load — deliberately NOT locked_state: that helper's
        # corrupt-archive branch RENAMES the live state file and its exit
        # path REWRITES it, so a status read used to remove an in-flight
        # loop's state.json from its live path (2026-06-12 finding).
        raw = state_path.read_text(encoding="utf-8")
        try:
            state = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            raise CorruptStateError(
                f"state file at {state_path} is malformed JSON (left in "
                f"place — --show is read-only). Re-run parse_plan.py with "
                f"--reset to rebuild, or repair manually. Original error: {e}"
            ) from e
        print(json.dumps({
            "plan_slug": state.get("plan_slug"),
            "plan_path": state.get("plan_path"),
            "paused_at": state.get("paused_at"),
            "exit_reason": state.get("exit_reason"),
            "turn_used": state.get("turn_budget_total", 0) - state.get("turn_budget_remaining", 0),
            "turn_total": state.get("turn_budget_total"),
            "wallclock_used_seconds": state.get("wallclock_used_seconds"),
            "consecutive_blocks": state.get("consecutive_blocks", 0),
            "consecutive_no_progress": state.get("consecutive_no_progress", 0),
            "prior_arc_count": state.get("prior_arc_count", 0),
            "last_verified_at": state.get("last_verified_at"),
        }, indent=2))
    else:
        raise SystemExit(f"unknown command: {cmd}")
    return 0


if __name__ == "__main__":
    import sys
    try:
        sys.exit(_cli(sys.argv))
    except CorruptStateError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
