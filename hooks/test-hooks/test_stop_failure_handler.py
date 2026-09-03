"""Tests for stop-failure-handler.py (StopFailure).

Every test points the hook at tmp_path via CLAUDE_STOP_FAILURE_LOG. Before
2026-09-02 this file's four fixtures were appended to the PRODUCTION log
(~/.claude/logs/stop-failures.jsonl) on every run -- 880 of its 1,512 rows --
and, because the fixtures used a synthetic {"stop_reason": ...} shape the
runtime never sends, the suite was green while the hook misclassified 100% of
real events. REAL_EVENT below is the captured production shape.
"""
import json
import os

from conftest import run_hook

HOOK = "stop-failure-handler.py"

# Captured 2026-09-02 from the production log; identifiers redacted.
REAL_EVENT = {
    "session_id": "00000000-0000-4000-8000-000000000000",
    "transcript_path": "/Users/x/.claude/projects/-Users-x/0000.jsonl",
    "cwd": "/Users/x",
    "hook_event_name": "StopFailure",
    "error": "invalid_request",
    "error_details": "400 prompt is too long: 215310 tokens > 200000 maximum",
    "last_assistant_message": "API Error: 400 prompt is too long",
    "effort": {"level": "high"},
    "agent_id": "ae473ff1a8266c450",
    "agent_type": "worker",
    "prompt_id": "p-1",
}


def _run(tmp_path, payload, extra_env=None):
    log = tmp_path / "stop-failures.jsonl"
    env = {"CLAUDE_STOP_FAILURE_LOG": str(log)}
    if extra_env:
        env.update(extra_env)
    rc, out, _err = run_hook(HOOK, payload, env=env)
    rows = []
    if log.exists():
        rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l]
    return rc, out, rows


def test_real_event_classifies_by_documented_error_field(tmp_path):
    rc, _out, rows = _run(tmp_path, REAL_EVENT)
    assert rc == 0
    assert len(rows) == 1
    row = rows[0]
    assert row["failure_type"] == "invalid_request"  # was "unknown" for 632/632 real events
    assert row["error_details"] == REAL_EVENT["error_details"]
    assert row["agent_id"] == "ae473ff1a8266c450"
    assert row["agent_type"] == "worker"
    assert row["session_id"] == REAL_EVENT["session_id"]
    assert row["aup_refusal"] is False
    assert row["guidance"]  # a mapped type carries guidance


def test_error_field_outranks_legacy_names(tmp_path):
    payload = dict(REAL_EVENT, error="server_error", stop_reason="rate_limit")
    _, _, rows = _run(tmp_path, payload)
    assert rows[0]["failure_type"] == "server_error"


def test_aup_refusal_flagged_from_message(tmp_path):
    msg = ("API Error: Claude Code is unable to respond to this request, which appears "
           "to violate our Usage Policy (https://www.anthropic.com/legal/aup).")
    payload = dict(REAL_EVENT, error="invalid_request", error_details=None,
                   last_assistant_message=msg)
    _, out, rows = _run(tmp_path, payload)
    assert rows[0]["aup_refusal"] is True
    assert rows[0]["failure_type"] == "invalid_request"  # AUP is NOT a distinct type
    assert json.loads(out)["aup_refusal"] is True


def test_legacy_synthetic_shape_still_classifies(tmp_path):
    _, _, rows = _run(tmp_path, {"stop_reason": "rate_limit"})
    assert rows[0]["failure_type"] == "rate_limit"
    assert "Rate limited" in rows[0]["guidance"]


def test_unknown_when_no_type_present(tmp_path):
    rc, _out, rows = _run(tmp_path, {})
    assert rc == 0
    assert rows[0]["failure_type"] == "unknown"
    assert rows[0]["guidance"] is None


def test_config_dir_fallback(tmp_path):
    # Empty CLAUDE_STOP_FAILURE_LOG must read as unset, then CLAUDE_CONFIG_DIR wins.
    rc, out, _err = run_hook(
        HOOK, REAL_EVENT,
        env={"CLAUDE_STOP_FAILURE_LOG": "", "CLAUDE_CONFIG_DIR": str(tmp_path)},
    )
    assert rc == 0
    expected = tmp_path / "logs" / "stop-failures.jsonl"
    assert expected.exists(), "hook must honor CLAUDE_CONFIG_DIR when no explicit log is set"
    assert json.loads(out)["logged"] == str(expected)


def test_suite_never_touches_production_log(tmp_path):
    prod = os.path.expanduser("~/.claude/logs/stop-failures.jsonl")

    def count():
        if not os.path.exists(prod):
            return 0
        with open(prod, encoding="utf-8") as f:
            return sum(1 for _ in f)

    before = count()
    for payload in ({"stop_reason": "rate_limit"}, {"type": "server_error"}, {}, REAL_EVENT):
        _run(tmp_path, payload)
    assert count() == before, "a test run appended to the PRODUCTION log"
