"""Tests for bash-security-audit.py (PostToolUse:Bash).

Every test runs against an ISOLATED home. The previous version asserted
against the real `~/.claude/audit/bash-security-<date>.jsonl`, which had two
consequences: it appended a fixture record on every run (all 184 records this
hook has ever produced are its own `test1234` fixtures), and it read
`lines[-1]` from a file other live sessions append to concurrently.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "bash-security-audit.py"


def run_isolated(payload: dict, home: Path) -> tuple[int, list[dict]]:
    """Invoke the hook with an isolated home; return (rc, records written).

    CLAUDE_HOOK_TEST is explicitly cleared: conftest sets it process-wide and
    the hook now honours it, so leaving it set would make every assertion here
    vacuously pass against zero records.

    BOTH HOME and USERPROFILE are set because `Path.home()` reads HOME on POSIX
    and USERPROFILE on Windows, and this dict REPLACES the environment.
    """
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload), capture_output=True, text=True,
        timeout=30, env=env, check=False,
    )
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log = home / ".claude" / "audit" / f"bash-security-{today}.jsonl"
    records = []
    if log.exists():
        records = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()
                   if ln.strip()]
    return proc.returncode, records


def make_post_payload(command: str, **extra) -> dict:
    """A realistic PostToolUse:Bash payload. Note it carries NO
    hookSpecificOutput: that is a PreToolUse OUTPUT field, so production
    payloads never include it."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": "", "stderr": "", "interrupted": False},
        "session_id": "test12345678",
    }
    payload.update(extra)
    return payload


def test_blocked_decision_logged_with_session_prefix(tmp_path):
    """Known-positive: given the decision field, the writer works."""
    rc, records = run_isolated(make_post_payload(
        "rm -rf /",
        hookSpecificOutput={"permissionDecision": "block", "reason": "destructive"},
    ), tmp_path)
    assert rc == 0
    assert len(records) == 1, f"expected exactly 1 record, got {records}"
    assert records[0]["action"] == "blocked"
    assert records[0]["session_id"] == "test1234"  # first 8 chars
    assert records[0]["reason"] == "destructive"


def test_autofix_decision_logged(tmp_path):
    rc, records = run_isolated(make_post_payload(
        "python -c 'x=1'",
        hookSpecificOutput={"updatedInput": {"command": "python3 /tmp/x.py"}},
    ), tmp_path)
    assert rc == 0
    assert len(records) == 1
    assert records[0]["action"] == "auto-fixed"


def test_realistic_payload_writes_nothing(tmp_path):
    """Negative control, and the measured production reality.

    A real PostToolUse payload has no hookSpecificOutput, so the decision
    classifies as passthrough and nothing is written. Asserting an exact record
    COUNT (not an unchanged file size) is what makes this able to fail.
    """
    rc, records = run_isolated(make_post_payload("ls -la"), tmp_path)
    assert rc == 0
    assert records == [], f"expected no records, got {records}"


def test_non_bash_tool_ignored(tmp_path):
    rc, records = run_isolated({
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/x"},
        "hookSpecificOutput": {"permissionDecision": "block", "reason": "nope"},
        "session_id": "test12345678",
    }, tmp_path)
    assert rc == 0
    assert records == []


def test_hook_test_env_suppresses_writes(tmp_path):
    """The regression this file exists to prevent: with CLAUDE_HOOK_TEST set,
    a decision-bearing payload must not touch the audit log."""
    env = {
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "CLAUDE_HOOK_TEST": "1",
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(make_post_payload(
            "rm -rf /",
            hookSpecificOutput={"permissionDecision": "block", "reason": "x"})),
        capture_output=True, text=True, timeout=30, env=env, check=False,
    )
    assert proc.returncode == 0
    assert not (tmp_path / ".claude" / "audit").exists(), \
        "CLAUDE_HOOK_TEST must suppress the write entirely"
