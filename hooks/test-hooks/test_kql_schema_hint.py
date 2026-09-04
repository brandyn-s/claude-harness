"""Tests for kql-schema-hint.py (PreToolUse hook on msgraph_run_hunting_query).

Backs RC1 from the 2026-05-28 retro. The hook nudges toward `| getschema`
when a hunting query projects columns from a watched Defender table
without a prior schema lookup in the session.
"""
import json

from conftest import run_hook

HOOK = "kql-schema-hint.py"


def test_non_hunting_tool_passes_silently():
    """Hook only fires on msgraph_run_hunting_query. Other tools pass."""
    rc, out, err = run_hook(HOOK, {
        "tool_input": {"name": "msgraph_list_users", "arguments": {}},
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing


def test_hunting_query_without_project_passes():
    """Queries without a multi-column | project clause don't trigger."""
    rc, out, _ = run_hook(HOOK, {
        "tool_input": {
            "name": "msgraph_run_hunting_query",
            "arguments": {"query": "DeviceInfo | take 5"},
        },
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing


def test_single_column_project_passes():
    """Single-column projects are safe — well-known column references."""
    rc, out, _ = run_hook(HOOK, {
        "tool_input": {
            "name": "msgraph_run_hunting_query",
            "arguments": {"query": "DeviceInfo | project DeviceName"},
        },
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing


def test_multi_column_project_without_getschema_fires_hint(tmp_path):
    """The high-risk pattern: multi-column project from a watched table
    with no prior `| getschema` in the session transcript."""
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        '{"type":"user","message":{"role":"user","content":"hi"}}\n',
        encoding="utf-8",
    )
    rc, out, _ = run_hook(HOOK, {
        "tool_input": {
            "name": "msgraph_run_hunting_query",
            "arguments": {
                "query": "DeviceInfo | project DeviceId, DeviceName, RiskScore, ExposureLevel",
            },
        },
        "transcript_path": str(transcript),
    })
    assert rc == 0
    data = json.loads(out)
    # additionalContext is the documented model-facing channel; systemMessage only
    # reached the user (live-probed 2026-09-03), so the hint never nudged the model.
    assert data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    hint = data["hookSpecificOutput"]["additionalContext"]
    assert "DeviceInfo" in hint
    assert "getschema" in hint


def test_prior_getschema_in_transcript_suppresses_hint(tmp_path):
    """If the session has already run `<Table> | getschema`, the model
    has the schema in context — no hint needed."""
    transcript = tmp_path / "transcript.jsonl"
    # Embed a prior assistant tool_use containing the getschema call
    prior = (
        '{"type":"assistant","message":{"role":"assistant","content":['
        '{"type":"tool_use","id":"t1","name":"msgraph_run_hunting_query",'
        '"input":{"query":"DeviceInfo | getschema | project ColumnName, ColumnType"}}'
        ']}}\n'
    )
    transcript.write_text(prior, encoding="utf-8")
    rc, out, _ = run_hook(HOOK, {
        "tool_input": {
            "name": "msgraph_run_hunting_query",
            "arguments": {
                "query": "DeviceInfo | project DeviceId, DeviceName, ExposureLevel",
            },
        },
        "transcript_path": str(transcript),
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing


def test_non_watched_table_passes():
    """Queries against tables not in WATCHED_TABLES pass without a hint."""
    rc, out, _ = run_hook(HOOK, {
        "tool_input": {
            "name": "msgraph_run_hunting_query",
            "arguments": {
                "query": "UnknownTable | project A, B, C",
            },
        },
    })
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing


def test_empty_input_passes():
    """Empty/missing input doesn't crash."""
    rc, out, _ = run_hook(HOOK, {})
    assert rc == 0
    assert out.strip() == ""  # a pass emits nothing


def test_missing_transcript_path_treats_as_no_prior_getschema(tmp_path):
    """Without a transcript_path the hook conservatively assumes no
    prior getschema and emits the hint."""
    rc, out, _ = run_hook(HOOK, {
        "tool_input": {
            "name": "msgraph_run_hunting_query",
            "arguments": {
                "query": "AlertInfo | project AlertId, Title, Severity, Category",
            },
        },
    })
    assert rc == 0
    data = json.loads(out)
    assert "AlertInfo" in data["hookSpecificOutput"]["additionalContext"]
