"""StopFailure hook - logs API failures using the DOCUMENTED `error` field.

Contract (first-party hooks reference, read 2026-09-02): a StopFailure event
carries `error` (the error type; also what matcher filtering keys on), optional
`error_details`, and optional `last_assistant_message`, on top of the common
fields (`session_id`, `transcript_path`, `cwd`, `hook_event_name`, and for
subagent failures `agent_id` / `agent_type`). Claude Code IGNORES this hook's
stdout and exit code (apart from `terminalSequence`), so nothing printed here
reaches the model or the user. THE LOG FILE IS THE DELIVERABLE.

Two defects fixed 2026-09-02, both measured on the production log
(1,512 rows, 0 malformed):
  * The type was guessed from stop_reason/failure_type/reason/error_type/type
    -- none of which the runtime sends -- so ALL 632 real events logged as
    `failure_type: "unknown"` and the recovery-guidance map never matched once.
    `error` now comes first; the legacy names remain as fallbacks so old
    synthetic payloads still classify.
  * The log path was not overridable, so the test suite's four fixtures were
    appended to the PRODUCTION log on every run: 880 of 1,512 rows (58.2%).
    Resolution is now CLAUDE_STOP_FAILURE_LOG > $CLAUDE_CONFIG_DIR/logs/... >
    ~/.claude/logs/stop-failures.jsonl, and the tests point at tmp_path.

Also logged: `aup_refusal` -- True when `last_assistant_message` carries the
Usage-Policy refusal text. That refusal arrives as `error: "invalid_request"`,
not as a distinct type, which is why an absence check on the type alone
(PLATFORM_NOTES "zero policy/AUP entries", 2026-06-05) missed two real ones.

INTERRUPTION: safe -- a single append of one JSON line; a partial line is
skipped by readers that parse per-line and tolerate one malformed row.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Inert by contract (the runtime discards StopFailure stdout) but kept in the
# LOG ENTRY as `guidance`, where a human reading the file can use it.
RECOVERY_GUIDANCE = {
    "rate_limit": "Rate limited. Wait 60s before retrying. Check statusline RL% indicator.",
    "authentication_failed": "Auth failure. Check API key validity.",
    "max_output_tokens": "Output token limit hit. Break response into smaller chunks.",
    "server_error": "Anthropic server error. Transient - retry in 30s.",
    "billing_error": "Billing issue. Check account status.",
    "invalid_request": "400 from the API. Read error_details (prompt too long, unsupported "
                       "parameter, or an AUP refusal -- see aup_refusal).",
    "model_not_found": "Requested model unavailable on this provider/lane. Check the "
                       "model id and the provider's model table.",
}

AUP_MARKERS = ("usage policy", "/legal/aup")


def resolve_log_path():
    """CLAUDE_STOP_FAILURE_LOG > $CLAUDE_CONFIG_DIR/logs/... > ~/.claude/logs/..."""
    explicit = os.environ.get("CLAUDE_STOP_FAILURE_LOG", "").strip()
    if explicit:
        return explicit
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    base = config_dir if config_dir else os.path.expanduser("~/.claude")
    return os.path.join(base, "logs", "stop-failures.jsonl")


def classify(event):
    """The documented `error` field first; legacy synthetic names as fallbacks."""
    return (
        event.get("error")
        or event.get("stop_reason")
        or event.get("failure_type")
        or event.get("reason")
        or event.get("error_type")
        or event.get("type")
        or "unknown"
    )


def is_aup_refusal(event):
    msg = (event.get("last_assistant_message") or "").lower()
    return any(m in msg for m in AUP_MARKERS)


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)
    if not isinstance(event, dict):
        event = {}

    failure_type = classify(event)
    session_id = (
        event.get("session_id")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("SESSION_ID", "unknown")
    )

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "failure_type": failure_type,
        "error_details": event.get("error_details"),
        "aup_refusal": is_aup_refusal(event),
        "session_id": session_id,
        "agent_id": event.get("agent_id"),
        "agent_type": event.get("agent_type"),
        "guidance": RECOVERY_GUIDANCE.get(failure_type),
        "raw_event": event,
    }

    log_path = resolve_log_path()
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: S110, BLE001 -- fail-open: logging must never fail the hook
        pass  # Never fail the hook due to logging issues

    # Discarded by the runtime; emitted for anyone running the hook by hand.
    print(json.dumps({"logged": log_path, "failure_type": failure_type,
                      "aup_refusal": log_entry["aup_refusal"]}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: S110, BLE001 -- fail-open: a Stop hook must never fail the session
        pass  # fail-open: never fail the session on a handler error
    sys.exit(0)
