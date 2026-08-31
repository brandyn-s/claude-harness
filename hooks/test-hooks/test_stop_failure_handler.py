"""Tests for stop-failure-handler.py (StopFailure)."""
import json
import os
from conftest import run_hook

HOOK = "stop-failure-handler.py"


def test_rate_limit_recovery():
    rc, out, err = run_hook(HOOK, {"stop_reason": "rate_limit"})
    assert rc == 0
    data = json.loads(out)
    assert "Rate limited" in data["recovery"]


def test_server_error_recovery():
    rc, out, err = run_hook(HOOK, {"type": "server_error"})
    assert rc == 0
    data = json.loads(out)
    assert "server error" in data["recovery"].lower() or "retry" in data["recovery"].lower()


def test_unknown_failure():
    rc, out, err = run_hook(HOOK, {})
    assert rc == 0
    data = json.loads(out)
    assert "unknown" in data["recovery"].lower()


def test_log_file_written():
    log_dir = os.path.expanduser("~/.claude/logs")
    rc, out, err = run_hook(HOOK, {"stop_reason": "billing_error"})
    assert rc == 0
    # Verify log file exists
    log_files = [f for f in os.listdir(log_dir) if f.startswith("stop-failures")]
    assert len(log_files) > 0
