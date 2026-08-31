"""Tests for teammate-idle.py (TeammateIdle)."""
import json
from conftest import run_hook

HOOK = "teammate-idle.py"


def test_minimal_activity_warns():
    rc, out, err = run_hook(HOOK, {
        "agent_id": "agent-abc-12345",
        "transcript": "",
    })
    assert rc == 0
    data = json.loads(out)
    assert data["result"] == "warn"
    assert "minimal activity" in data["message"]


def test_sufficient_activity_passes():
    rc, out, err = run_hook(HOOK, {
        "agent_id": "x",
        "transcript": '"tool_use" something "tool_use" git commit done',
    })
    assert rc == 0
    data = json.loads(out)
    assert data["result"] == "pass"


def test_file_changes_even_with_few_tools():
    rc, out, err = run_hook(HOOK, {
        "agent_id": "y",
        "transcript": '"tool_use" "Write" to file',
    })
    assert rc == 0
    data = json.loads(out)
    assert data["result"] == "pass"
