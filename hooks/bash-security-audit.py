"""PostToolUse audit hook — logs a Bash security decision to JSONL.

Classifies the decision from `hookSpecificOutput`, which is a PreToolUse
OUTPUT field. Measured 2026-08-29 over 81 retained days / 8,302 audit records:
this hook has produced ZERO production records, because real PostToolUse
payloads do not carry it — and a BLOCKED command never reaches PostToolUse at
all, since the tool never runs. bash-security-guard.py's own `_audit_log`
writes every one of the 8,118 real records (4,441 auto-fixed, 3,586 blocked,
91 warned).

Retained rather than deleted: 15 consumers reference it (SECURITY.md,
ARCHITECTURE.md, install.sh, the safety-net marketplace plugin, a manifest,
and this hook's test), so removal is a contract change of its own.

Register on PostToolUse:Bash in settings.json.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DIR = Path.home() / ".claude" / "audit"


def main():
    # Skips under CLAUDE_HOOK_TEST for the same reason bash-security-guard.py's
    # _audit_log does: bin/hook-fire-report.py reads this log as a friction
    # instrument. Without this guard the suite wrote into the REAL log — all 184
    # records this hook has ever emitted are its own `test1234` fixtures.
    if os.environ.get("CLAUDE_HOOK_TEST"):
        return
    # Fast-path: at low effort, skip audit logging (security GUARD still
    # runs in PreToolUse — this is just the audit log). $CLAUDE_EFFORT
    # set by /effort low (v2.1.128+).
    if os.environ.get("CLAUDE_EFFORT") == "low":
        return

    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    tool_name = hook_input.get("tool_name", "")
    if tool_name not in ("Bash", "PowerShell"):
        return

    tool_input = hook_input.get("tool_input", {})
    # PostToolUse field name varies across Claude Code versions: prefer the
    # canonical `tool_response`, fall back to legacy `tool_result` / `response`.
    tool_result = (
        hook_input.get("tool_response")
        or hook_input.get("tool_result")
        or hook_input.get("response")
        or {}
    )
    command = tool_input.get("command", "")

    if not command:
        return

    # Extract security hook output if present
    hook_output = hook_input.get("hookSpecificOutput", {})
    decision = hook_output.get("permissionDecision", "none")
    reason = hook_output.get("reason", "")
    updated = bool(hook_output.get("updatedInput"))

    # Classify the decision
    if decision == "block":
        action = "blocked"
    elif updated:
        action = "auto-fixed"
    elif decision == "approve":
        action = "approved"
    else:
        action = "passthrough"

    # Only log security-relevant events (blocks, auto-fixes, and advisories)
    # Skip passthrough to avoid logging every single Bash command
    if action == "passthrough":
        return

    # Build audit entry
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": command[:500],  # Truncate long commands
        "action": action,
        "reason": reason[:200] if reason else "",
        "session_id": hook_input.get("session_id", "unknown")[:8],
    }

    # Write to daily JSONL file
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit_file = AUDIT_DIR / f"bash-security-{date_str}.jsonl"

    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # Never block session for audit logging


if __name__ == "__main__":
    main()
