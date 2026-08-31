#!/usr/bin/env python3
"""PreCompact hook: save structured context state before compaction.

Reads the hook input for context about the current session state and
saves it to a JSON checkpoint file. After compaction, the instructions
re-injected by the echo command reference this file so the model can
recover key state without re-reading everything.

Output: JSON checkpoint at ~/.claude/.precompact-state.json
"""
import json
import sys
import time
from pathlib import Path

CHECKPOINT_PATH = Path.home() / ".claude" / ".precompact-state.json"


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        data = {}

    # Extract what we can from the hook input
    cwd = data.get("cwd", "")
    session_id = data.get("session_id", "unknown")

    # Build a minimal state checkpoint
    state = {
        "timestamp": time.time(),
        "session_id": session_id[:8] if session_id else "unknown",
        "cwd": cwd,
        "hint": (
            "Context was compacted. Key state was saved pre-compaction. "
            "Re-read CLAUDE.md delegation rules. Check git status for in-progress work. "
            "If a task was in progress, check TaskList for current state."
        ),
    }

    # Fail OPEN on transient write failures. Compaction is auto-triggered
    # near the context limit; if we exit non-zero here the entire session
    # corrupts (compaction blocked, no recovery path). The checkpoint is
    # advisory — losing one is not catastrophic — but blocking compaction
    # IS. The prior fail-closed behavior turned a recoverable hiccup
    # (disk full, transient permission error, locked parent dir) into a
    # session-ending failure.
    try:
        # Ensure parent exists before writing.
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_PATH.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except Exception as e:
        # Log to stderr (visible to operator) but exit 0 so compaction
        # proceeds. A missing checkpoint is recoverable; a blocked
        # compaction is not.
        try:
            print(
                f"[precompact-checkpoint] WARN: checkpoint write failed: {e}. "
                "Compaction proceeding without checkpoint.",
                file=sys.stderr,
            )
        except OSError:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()
