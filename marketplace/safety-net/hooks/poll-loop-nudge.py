"""PreToolUse:Bash ADVISORY nudge — foreground poll-loops that SIGTERM at the timeout.

WHY (2026-07-24 14d retro, Gap P3): a foreground `sleep N; <check>` or
`while/for ... sleep N ... done` poll loop that waits on an async operation
(CI, merge-queue, Athena query, a background PID, a growing log) hits the Bash
tool's 120s default timeout and gets SIGTERM'd (exit 143) — the run keeps going
untouched, so the timeout is pure wasted turn. Documented in
platform-constraints.md (`foreground_sleep_or_poll_loop_longer_than_the_bash_timeout`)
and claude-code-config.md ("confirmed, reconfirmed 2026-06-18"), but with NO
enforcement — 75 occurrences across 23 sessions in the 14d window.

This is ADVISORY ONLY (exit 0 + stderr): it never blocks. A legitimate long
wait must still run; blocking it would be the DoS. It just reminds the model to
use `run_in_background: true` (the harness re-invokes on completion, no turn
burned) or the `/run-status` skill.

Fire rate validated against 11,814 historical Bash commands: 5.22% (well under
the 10% DoS line; advisory not block). Fires on the shape that actually times
out — a >=60s single foreground sleep, or a state-polling loop whose worst-case
foreground time can approach 120s — NOT on every command containing `sleep`
(short `sleep 5` waits do not fire).
"""
import json
import re
import sys

SLEEP_RE = re.compile(r"\bsleep\s+(\d+(?:\.\d+)?)")
LOOP_RE = re.compile(r"\b(while|for)\b")
# State-poll tokens: the loop is waiting on something async to change.
POLL_TOKENS = re.compile(
    r"\b(pgrep|ps -p|ps -o|gh (pr|run) (view|list|checks)|"
    r"aws\b.*\b(get-query-results|describe|wait)|mergeQueueEntry|"
    r"\bstate\b|\bstatus\b|\btail\b|\bcat\b|\bgrep\b)"
)
SEQ_RE = re.compile(r"for\s+\w+\s+in\s+\$\(seq\s+\d+\s+(\d+)\)")
NUMLIST_RE = re.compile(r"for\s+\w+\s+in\s+((?:\d+\s+){2,}\d+)")

_MSG = (
    "[poll-loop-nudge] ADVISORY: this looks like a foreground wait/poll that can "
    "hit the 120s Bash timeout (SIGTERM exit 143) — the timeout kills the SLEEP, "
    "not the work you're waiting on, so it wastes a turn and tells you nothing.\n"
    "  PREFER: run_in_background: true (the harness re-invokes you when it exits/stalls; "
    "no turn burned), or the /run-status skill for durable background jobs.\n"
    "  This is advisory only — the command was NOT blocked.\n"
    "  Reference: rules/platform-constraints.md "
    "foreground_sleep_or_poll_loop_longer_than_the_bash_timeout"
)


def fires(cmd: str) -> bool:
    sleeps = [float(x) for x in SLEEP_RE.findall(cmd)]
    if not sleeps:
        return False
    has_loop = bool(LOOP_RE.search(cmd))
    max_sleep = max(sleeps)
    # Shape A: single long foreground sleep (no loop), N >= 60s.
    if not has_loop and max_sleep >= 60:
        return True
    # Shape B: a state-polling loop.
    if has_loop and POLL_TOKENS.search(cmd):
        iters = None
        m = SEQ_RE.search(cmd)
        if m:
            iters = int(m.group(1))
        else:
            m2 = NUMLIST_RE.search(cmd)
            if m2:
                iters = len(m2.group(1).split())
        if iters is None:
            # unbounded `while` — dangerous if per-iter sleep >= 20s
            return max_sleep >= 20
        return iters * max_sleep >= 90
    return False


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)
    if data.get("tool_name") not in (None, "Bash"):
        # matcher already scopes to Bash, but be defensive
        pass
    cmd = (data.get("tool_input", {}) or {}).get("command", "")
    if not cmd:
        sys.exit(0)
    try:
        if fires(cmd):
            sys.stderr.write(_MSG + "\n")
    except Exception:  # noqa: S110, BLE001 -- fail-open: an advisory must never block
        pass  # fail-open: advisory only
    sys.exit(0)  # ADVISORY: never block


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
