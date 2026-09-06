#!/usr/bin/env python3
"""Tests for session_start_modules/model_notes.py -- the per-model note that
replaces a would-be ambient rule. Pure functions; no subprocess."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from session_start_modules.model_notes import (  # noqa: E402 -- resolves via the sys.path insert above
    NOTES, model_notes_context, normalise_model_id, note_for)


def test_opus_5_gets_the_over_verification_correction():
    key, note = note_for("claude-opus-5")
    assert key == "claude-opus-5"
    assert "verification" in note and "scope" in note


def test_fable_5_1_and_dated_snapshots_resolve_to_the_fable_block():
    for mid in ("claude-fable-5-1", "claude-fable-5", "claude-fable-5-1-20260901"):
        key, note = note_for(mid)
        assert key == "claude-fable-5", mid
        assert "narrate" in note


def test_bedrock_prefixed_ids_are_normalised():
    assert normalise_model_id("us-gov.anthropic.claude-opus-5-20260724-v1:0") == "claude-opus-5"
    assert note_for("us.anthropic.claude-sonnet-5-v1:0")[0] == "claude-sonnet-5"


def test_unknown_or_empty_model_yields_nothing():
    assert note_for("") == ("", "")
    assert note_for(None) == ("", "")
    assert note_for("gpt-6-astra") == ("", "")
    assert model_notes_context("gpt-6-astra") == ("", "")


def test_context_is_a_tagged_block_and_summary_names_the_key():
    ctx, summary = model_notes_context("claude-fable-5-1")
    assert ctx.startswith('<model-notes model="claude-fable-5-1">') and ctx.endswith("</model-notes>")
    assert summary == "model notes: claude-fable-5"


def test_every_note_is_short_enough_to_be_free():
    for key, note in NOTES.items():
        assert len(note.encode("utf-8")) < 600, key
