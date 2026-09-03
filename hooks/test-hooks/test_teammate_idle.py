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
    assert data["hookSpecificOutput"]["hookEventName"] == "TeammateIdle"
    assert "minimal activity" in data["hookSpecificOutput"]["additionalContext"]


def test_sufficient_activity_passes():
    rc, out, err = run_hook(HOOK, {
        "agent_id": "x",
        "transcript": '"tool_use" something "tool_use" git commit done',
    })
    assert rc == 0
    assert out.strip() == "", "a pass emits nothing: top-level result/message never reached the model"


def test_file_changes_even_with_few_tools():
    rc, out, err = run_hook(HOOK, {
        "agent_id": "y",
        "transcript": '"tool_use" "Write" to file',
    })
    assert rc == 0
    assert out.strip() == "", "a pass emits nothing: top-level result/message never reached the model"
