"""StopFailure hook - logs API failures and prints recovery guidance."""
import json
import os
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

RECOVERY_GUIDANCE = {
    "rate_limit": "Rate limited. Wait 60s before retrying. Check statusline RL% indicator.",
    "authentication_failed": "Auth failure. Check API key validity.",
    "max_output_tokens": "Output token limit hit. Break response into smaller chunks.",
    "server_error": "Anthropic server error. Transient - retry in 30s.",
    "billing_error": "Billing issue. Check account status.",
}


def main():
    # Read event JSON from stdin
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)

    # Extract failure type - check multiple possible field names
    failure_type = (
        event.get("stop_reason")
        or event.get("failure_type")
        or event.get("reason")
        or event.get("error_type")
        or event.get("type")
        or "unknown"
    )

    session_id = (
        event.get("session_id")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("SESSION_ID", "unknown")
    )

    # Ensure log directory exists
    log_dir = os.path.expanduser("~/.claude/logs")
    os.makedirs(log_dir, exist_ok=True)

    # Write structured log entry
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "failure_type": failure_type,
        "session_id": session_id,
        "raw_event": event,
    }
    log_path = os.path.join(log_dir, "stop-failures.jsonl")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Never fail the hook due to logging issues

    # Print recovery guidance as JSON
    message = RECOVERY_GUIDANCE.get(
        failure_type,
        f"Unknown stop failure: {failure_type}. Check ~/.claude/logs/stop-failures.jsonl",
    )
    print(json.dumps({"recovery": message}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
