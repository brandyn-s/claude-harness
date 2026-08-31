"""macOS desktop notifications for lifecycle hooks.

notify() is a strict no-op off darwin and when CLAUDE_NOTIFY=0, never
raises, and never writes to stdout/stderr — hook JSON output contracts
stay clean. Title/message reach AppleScript via argv (`on run argv`), so
arbitrary quotes/newlines in messages cannot break the script.

Noise policy (who calls this, and when):
  - task-completed.py: BLOCK path always (rare, needs attention);
    pass path only when CLAUDE_NOTIFY_TASKS=1 (a team run completes many).
  - teammate-idle.py: on idle (infrequent — a teammate finished its queue).
Global kill switch for all of the above: CLAUDE_NOTIFY=0.
"""
from __future__ import annotations

import os
import subprocess
import sys

_OSA_SCRIPT = (
    "on run argv\n"
    "display notification (item 2 of argv) with title (item 1 of argv)\n"
    "end run"
)

# Keep notifications glanceable; Notification Center truncates anyway.
_TITLE_MAX = 120
_MESSAGE_MAX = 240


def notify(title: str, message: str) -> bool:
    """Post a Notification Center banner. True only on confirmed post."""
    if sys.platform != "darwin":
        return False
    if os.environ.get("CLAUDE_NOTIFY") == "0":
        return False
    try:
        r = subprocess.run(
            [
                "osascript",
                "-e",
                _OSA_SCRIPT,
                str(title)[:_TITLE_MAX],
                str(message)[:_MESSAGE_MAX],
            ],
            capture_output=True,
            timeout=3,
        )
        return r.returncode == 0
    except Exception:
        return False
