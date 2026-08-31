"""PostToolUse hook: proactive context usage warnings.

Tracks tool call count as a heuristic for context window consumption.
Fires escalating warnings at 60%/80%/90% thresholds.

On 1M context with Opus 4.6, calibrated to 300 tool calls ~ 100%.
Each warning fires once per session. 60s throttle below warning level.

Selectively cloned from flonat/claude-research (2026-03-30).
Adapted from Python 3 with Windows-compatible paths.
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomic_write import atomic_write

# --- Configuration ---
# 1M context: ~300 tool calls before exhaustion (conservative estimate).
# 200K context: ~150 calls. Adjust if context window changes.
MAX_TOOL_CALLS = 300

THRESHOLDS = [
    (0.90, "critical", "Context at ~90%. Complete current task and wrap up."),
    (0.80, "warning", "Context at ~80%. Auto-compact approaching. Save key decisions."),
    (0.60, "info", "Context at ~60%. Consider checkpointing important state."),
]

THROTTLE_SECONDS = 60  # Minimum seconds between info-level messages

# --- Paths ---
SESSIONS_BASE = Path.home() / ".claude" / "sessions"


def project_hash():
    """Deterministic hash of the project directory."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    return hashlib.sha256(project_dir.encode()).hexdigest()[:12]


def session_dir():
    d = SESSIONS_BASE / project_hash()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_file(sdir, session_id):
    # Per-session state file: two concurrent sessions in the SAME project must
    # not share a counter (the old single file conflated their tool counts and
    # cross-suppressed warnings). Fall back to a shared name when no session id.
    sid = "".join(c for c in (session_id or "") if c.isalnum() or c in "-_")[:32]
    name = f"context-monitor-{sid}.json" if sid else "context-monitor-state.json"
    return sdir / name


def load_state(sdir, session_id=""):
    state_file = _state_file(sdir, session_id)
    if state_file.is_file():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"tool_calls": 0, "fired": [], "last_message_time": 0}


def save_state(sdir, state, session_id=""):
    # atomic_write so a concurrent reader never sees a torn file (which the
    # bare-except in load_state would silently reset to tool_calls=0).
    atomic_write(_state_file(sdir, session_id), json.dumps(state, indent=2))


def main():
    # Fast-path: at low effort, skip context-usage warnings (the user
    # already opted into speed-over-thoroughness). $CLAUDE_EFFORT set
    # by /effort low (v2.1.128+).
    if os.environ.get("CLAUDE_EFFORT") == "low":
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        sys.exit(0)

    session_id = data.get("session_id", "") if isinstance(data, dict) else ""
    sdir = session_dir()
    state = load_state(sdir, session_id)

    # Increment call count
    state["tool_calls"] = state.get("tool_calls", 0) + 1
    count = state["tool_calls"]
    pct = count / MAX_TOOL_CALLS

    now = time.time()
    fired = set(state.get("fired", []))

    for threshold, level, message in THRESHOLDS:
        if pct >= threshold and level not in fired:
            # Fire this threshold
            fired.add(level)
            state["fired"] = list(fired)
            state["last_message_time"] = now
            save_state(sdir, state, session_id)

            # Output as stderr message (non-blocking, informational)
            sys.stderr.write(f"[context-monitor] {level.upper()}: {message} "
                             f"({count}/{MAX_TOOL_CALLS} tool calls, ~{pct:.0%})\n")
            sys.exit(0)

    # Below any threshold — throttle info messages
    last_time = state.get("last_message_time", 0)
    if now - last_time < THROTTLE_SECONDS:
        save_state(sdir, state, session_id)
        sys.exit(0)

    # Save state silently
    save_state(sdir, state, session_id)
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)