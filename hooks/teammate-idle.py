"""TeammateIdle hook - quality gate when an Agent Teams teammate finishes work.

Fires when a teammate is about to go idle. Checks if the teammate produced
meaningful output and warns if it appears to have done nothing useful.
"""
import json
import sys

if sys.platform == "win32":
    import ctypes

    _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if _hwnd:
        ctypes.windll.user32.ShowWindow(_hwnd, 0)

# Desktop notification (macOS only; no-op elsewhere). Guarded import so a
# missing/broken helper can never affect this hook's output.
try:
    from macos_notify import notify as _notify
except Exception:  # pragma: no cover - defensive
    def _notify(title, message):
        return False


def main():
    try:
        if sys.stdin and not sys.stdin.closed:
            hook_input = json.load(sys.stdin)
        else:
            hook_input = {}
    except Exception:
        hook_input = {}

    agent_id = hook_input.get("agent_id", "unknown")
    transcript = hook_input.get("transcript", "")

    # Check for signs of meaningful work
    tool_call_count = transcript.count('"tool_use"') if transcript else 0
    has_file_changes = (
        any(
            marker in transcript
            for marker in ['"Write"', '"Edit"', "git commit", "git add"]
        )
        if transcript
        else False
    )

    # Teammates idle infrequently (end of their queue), so a banner per
    # event is signal, not noise — the user usually wants to assign more
    # work or review output at exactly this moment.
    if tool_call_count < 2 and not has_file_changes:
        _notify(
            "Claude teammate idle",
            f"{agent_id[:8]} went idle with minimal activity "
            f"({tool_call_count} tool calls) — task may have been too small.",
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "TeammateIdle",
                        "additionalContext": (
                            f"[TeammateIdle] Teammate {agent_id[:8]} going idle with "
                            f"minimal activity ({tool_call_count} tool calls, "
                            f"no file changes). Review if task was too small for a teammate."
                        ),
                    }
                }
            )
        )
    else:
        # A pass emits nothing: the former {"result": "pass"} never reached the model.
        _notify("Claude teammate idle", f"{agent_id[:8]} finished its work and is idle.")


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)