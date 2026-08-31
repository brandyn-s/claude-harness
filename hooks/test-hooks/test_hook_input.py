"""Tests for the canonical hook-input accessors.

These accessors collapse the schema-drift bug class fixed in the
2026-05-23 audit (PreToolUse `tool_input` vs `input`; PostToolUse
`tool_response` vs `tool_result` vs `response`; SubagentStop
`transcript_path` vs inline `transcript`). New hooks should use the
accessors instead of maintaining per-hook fallback chains.
"""
import sys
from pathlib import Path

# Make hooks/ importable so we can pull in hook_input as a sibling module.
HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

from hook_input import (  # noqa: E402
    cwd,
    session_id,
    tool_input,
    tool_name,
    tool_response,
    tool_response_str,
    transcript_text,
)


# ── tool_input ─────────────────────────────────────────────────────

def test_tool_input_canonical_key():
    assert tool_input({"tool_input": {"a": 1}}) == {"a": 1}


def test_tool_input_falls_back_to_legacy_input():
    assert tool_input({"input": {"a": 1}}) == {"a": 1}


def test_tool_input_prefers_canonical_over_legacy():
    # When both are present (transitional payloads), canonical wins.
    assert tool_input({"tool_input": {"new": 1}, "input": {"old": 1}}) == {"new": 1}


def test_tool_input_missing_returns_empty_dict():
    assert tool_input({}) == {}


def test_tool_input_non_dict_value_returns_empty_dict():
    assert tool_input({"tool_input": "not a dict"}) == {}


def test_tool_input_non_dict_payload_returns_empty_dict():
    assert tool_input(None) == {}
    assert tool_input("string") == {}


# ── tool_response ───────────────────────────────────────────────────

def test_tool_response_canonical_key():
    assert tool_response({"tool_response": "hello"}) == "hello"


def test_tool_response_falls_back_to_tool_result():
    assert tool_response({"tool_result": "legacy"}) == "legacy"


def test_tool_response_falls_back_to_bare_response():
    assert tool_response({"response": "mcp-trimmer-style"}) == "mcp-trimmer-style"


def test_tool_response_precedence_canonical_first():
    assert tool_response({
        "tool_response": "new",
        "tool_result": "mid",
        "response": "old",
    }) == "new"


def test_tool_response_precedence_tool_result_over_response():
    assert tool_response({"tool_result": "mid", "response": "old"}) == "mid"


def test_tool_response_returns_empty_string_when_missing():
    assert tool_response({}) == ""


def test_tool_response_preserves_dict_type():
    """A dict response (common for MCP tools) must not be coerced."""
    payload = {"result": {"items": [1, 2, 3]}}
    assert tool_response({"tool_response": payload}) == payload


# ── tool_response_str ───────────────────────────────────────────────

def test_tool_response_str_passes_strings_through():
    assert tool_response_str({"tool_response": "raw"}) == "raw"


def test_tool_response_str_json_encodes_dict():
    s = tool_response_str({"tool_response": {"a": 1}})
    assert '"a"' in s and "1" in s


def test_tool_response_str_empty_for_missing():
    assert tool_response_str({}) == ""


# ── tool_name ───────────────────────────────────────────────────────

def test_tool_name_returns_value():
    assert tool_name({"tool_name": "Bash"}) == "Bash"


def test_tool_name_missing_returns_empty():
    assert tool_name({}) == ""


def test_tool_name_non_string_returns_empty():
    assert tool_name({"tool_name": 42}) == ""


# ── transcript_text ─────────────────────────────────────────────────

def test_transcript_text_reads_path(tmp_path):
    p = tmp_path / "tx.txt"
    p.write_text("hello from file", encoding="utf-8")
    assert transcript_text({"transcript_path": str(p)}) == "hello from file"


def test_transcript_text_falls_back_to_inline_when_no_path():
    assert transcript_text({"transcript": "inline content"}) == "inline content"


def test_transcript_text_prefers_path_over_inline(tmp_path):
    """transcript_path should win when both keys present."""
    p = tmp_path / "tx.txt"
    p.write_text("from file", encoding="utf-8")
    out = transcript_text({"transcript_path": str(p), "transcript": "inline"})
    assert out == "from file"


def test_transcript_text_missing_file_returns_empty(tmp_path):
    assert transcript_text({"transcript_path": str(tmp_path / "nope.txt")}) == ""


def test_transcript_text_missing_keys_returns_empty():
    assert transcript_text({}) == ""


def test_transcript_text_max_bytes_caps_read(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("a" * 1000 + "TAIL", encoding="utf-8")
    # Read only the last 10 bytes; should contain TAIL but not the leading As.
    out = transcript_text({"transcript_path": str(p)}, max_bytes=10)
    assert "TAIL" in out
    assert len(out) <= 10


def test_transcript_text_max_bytes_zero_reads_all(tmp_path):
    p = tmp_path / "small.txt"
    p.write_text("complete", encoding="utf-8")
    assert transcript_text({"transcript_path": str(p)}, max_bytes=0) == "complete"


# ── session_id / cwd ────────────────────────────────────────────────

def test_session_id_returns_value():
    assert session_id({"session_id": "abc123"}) == "abc123"


def test_session_id_missing_returns_empty():
    assert session_id({}) == ""


def test_cwd_returns_value():
    assert cwd({"cwd": "/home/user"}) == "/home/user"


def test_cwd_missing_returns_empty():
    assert cwd({}) == ""
