"""
PostToolUse hook for mcp__tavily__tavily_research.

When tavily_research returns a timeout status, injects instructions telling
Claude to automatically poll tavily_research_status until completion, with
visible progress updates and hung detection.

When research completes successfully, passes through silently.
"""
import json
import sys


# After this many total seconds, warn about potential hang
HUNG_THRESHOLD_SECONDS = 600


def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # PostToolUse field name varies across Claude Code versions; read all.
    tool_result = (
        data.get("tool_response")
        or data.get("tool_result")
        or data.get("response")
        or ""
    )

    # tool_result is a dict with a "result" key containing a JSON string
    inner = None
    if isinstance(tool_result, dict):
        raw = tool_result.get("result", "")
        try:
            inner = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            inner = None
    elif isinstance(tool_result, str):
        try:
            inner = json.loads(tool_result)
        except (json.JSONDecodeError, TypeError):
            inner = None

    if not inner or not isinstance(inner, dict):
        sys.exit(0)

    status = inner.get("status", "")
    request_id = inner.get("request_id", "")
    elapsed = inner.get("elapsed_seconds", 0)
    model = inner.get("model", "unknown")

    if status == "timeout" and request_id:
        instructions = (
            f"TAVILY RESEARCH AUTO-POLL REQUIRED\n"
            f"Model: {model} | Elapsed so far: {elapsed}s | Request ID: {request_id}\n"
            f"\n"
            f"The research task is still running server-side. You MUST poll until completion:\n"
            f"\n"
            f"1. Call tavily_research_status(request_id=\"{request_id}\")\n"
            f"2. Report the status to the user: \"Research in progress... [Xs elapsed]\"\n"
            f"3. If status is \"in_progress\", wait ~30 seconds (use: sleep 30), then poll again\n"
            f"4. If status is \"completed\", present the full results to the user\n"
            f"5. If status is \"failed\", report the error\n"
            f"6. If still \"in_progress\" after {HUNG_THRESHOLD_SECONDS}s total elapsed, warn the user:\n"
            f"   \"Research has been running for over {HUNG_THRESHOLD_SECONDS // 60} minutes and may be hung. "
            f"Continue waiting or cancel?\"\n"
            f"\n"
            f"IMPORTANT: Do NOT return the timeout to the user as a final result. "
            f"Keep polling until you get a terminal status (completed or failed).\n"
            f"IMPORTANT: Report progress between each poll so the user knows it is working."
        )
        # Documented PostToolUse channel to the model; the former top-level
        # {"decision": "approve", "reason": ...} was ignored (probed 2026-09-03).
        result = {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                         "additionalContext": instructions}}
        json.dump(result, sys.stdout)
        sys.exit(0)

    # Completed, failed, or other status - pass through silently
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)