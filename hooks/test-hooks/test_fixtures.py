"""Smoke tests for shared hook test fixtures.

Backs RC2 from the 2026-05-28 retro. Hook tests historically used plain-text
transcript fixtures only — JSONL-specific bugs (subagent-stop.py treating
attachment payloads as agent learnings) were invisible to those tests. The
fixtures/ directory provides realistic Claude Code session JSONL events
that future hook tests can consume to surface JSONL-specific bugs.

This file just verifies the fixtures parse cleanly and contain the event
types we expect. Per-hook tests using these fixtures live in the relevant
test_<hook>.py files.
"""
import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SAMPLE_TRANSCRIPT = FIXTURES_DIR / "sample-transcript.jsonl"


def _load_jsonl(path):
    entries = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            pytest.fail(f"{path.name} line {i} is not valid JSON: {exc}")
    return entries


def test_sample_transcript_fixture_exists():
    assert SAMPLE_TRANSCRIPT.exists(), (
        f"Missing fixture {SAMPLE_TRANSCRIPT}. Hook tests consuming "
        "realistic Claude Code JSONL depend on this file."
    )


def test_sample_transcript_is_valid_jsonl():
    """One JSON object per non-blank line."""
    entries = _load_jsonl(SAMPLE_TRANSCRIPT)
    assert len(entries) >= 5, "sample-transcript.jsonl too short to be useful"


def test_sample_transcript_covers_critical_event_types():
    """A realistic Claude Code session has at minimum: user message,
    assistant text block, tool_use, tool_result, attachment.

    Hook bugs that only manifest on JSONL (not plain text) typically
    involve one of these event shapes — subagent-stop.py's attachment-
    parsing bug being the canonical example.
    """
    entries = _load_jsonl(SAMPLE_TRANSCRIPT)
    types_seen = {e.get("type") for e in entries}
    # User and assistant message wrappers
    assert "user" in types_seen, "fixture needs at least one user message"
    assert "assistant" in types_seen, "fixture needs at least one assistant message"
    # Attachment events (the shape that triggered the 2026-05-28 msgraph.md pollution)
    assert "attachment" in types_seen, (
        "fixture needs at least one attachment event — the shape that "
        "broke subagent-stop.py. Tests using this fixture rely on the "
        "attachment being present to verify the hook correctly ignores it."
    )
    # Inner content-block types embedded in message.content arrays
    content_block_types = set()
    for entry in entries:
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type:
                        content_block_types.add(block_type)
    assert "text" in content_block_types, "fixture needs assistant text blocks"
    assert "tool_use" in content_block_types, "fixture needs tool_use blocks"
    assert "tool_result" in content_block_types, "fixture needs tool_result blocks"


def test_sample_transcript_has_pollution_decoy():
    """The fixture must contain an [observed] token inside an attachment
    payload AND inside a tool_result content string — these are the two
    decoys that previously fooled subagent-stop.py's plain-text regex
    scan. Tests checking that hooks correctly distinguish prose from
    structured payloads rely on these decoys being present.
    """
    raw = SAMPLE_TRANSCRIPT.read_text(encoding="utf-8")
    attachment_decoy_found = False
    tool_result_decoy_found = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("type") == "attachment" and "[observed]" in line:
            attachment_decoy_found = True
        msg = entry.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and "[observed]" in json.dumps(block, ensure_ascii=False)
                ):
                    tool_result_decoy_found = True
    assert attachment_decoy_found, (
        "fixture must embed [observed] inside an attachment payload — "
        "the structural decoy that subagent-stop.py's regex misclassified."
    )
    assert tool_result_decoy_found, (
        "fixture must embed [observed] inside a tool_result content — "
        "second decoy shape for hook learning-extraction tests."
    )
