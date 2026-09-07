#!/usr/bin/env python3
"""SessionStart module: inject the behavioural note for the ACTIVE model only.

WHY A MODULE AND NOT A RULE
    The vendors' September 2026 prompting guides correct model-specific habits:
    Opus 5 over-verifies when told to verify and expands scope; Fable 5.1 fixes
    nearby code, over-commits tests, takes one tool call per turn and narrates
    instead of acting; Sonnet/Haiku want explicit plans. A rule would load every
    block for every model on every turn and cost ambient budget for text that is
    wrong for the model reading it. SessionStart knows the model (`model` in the
    payload) and can inject ~400 bytes once, so this is the only place the
    correction is both cheap and correctly targeted.

SOURCES (the WHY is the vendors', not ours)
    Claude Opus 5 prompting guide, 2026-07-24: explicit verification instructions
    "cause over-verification... removing them reduces wasted tokens with no loss
    in quality"; "can expand the scope of a task"; "use low and medium liberally".
    Claude Fable 5.1 what's-new, 2026-09-01: may fix nearby code or commit more
    test files than the change warrants; one tool call per turn; narrates the
    next step instead of taking it.

MATCHING
    Provider prefixes (`us.anthropic.`, `anthropic.`, `us-gov.anthropic.`) and
    dated snapshot suffixes are stripped; the longest key that prefixes the
    normalised id wins, so `claude-fable-5-1` resolves to the fable block and
    `claude-opus-5-20260724` to the opus block. Unknown model -> ("", "").

Returns (additional_context, banner_summary); never raises.
"""
from __future__ import annotations

import re

NOTES: dict[str, str] = {
    "claude-opus-5": (
        "Opus 5: take the complete task and run; delegate only sizeable independent tracks. "
        "Do not add verification passes beyond what the outcome contract asks -- you verify "
        "by default and re-checking a verified result is waste; when evidence answers the "
        "decision, stop. Watch scope: you tend to expand a task; propose expansions in one "
        "line instead. Routine work at medium or low effort; reserve high for the hard step."
    ),
    "claude-fable-5": (
        "Fable 5.x: batch independent tool calls in one turn; do not narrate the next step "
        "instead of taking it. Stay in scope -- no nearby fixes, no extra test files, no "
        "whole-file rewrites where a targeted edit will do. Run autonomously to the "
        "done-criteria and end the turn when the task is complete and evidenced, not before "
        "and not after."
    ),
    "claude-mythos-5": (
        "Mythos 5.x: same contracts as Fable -- batch independent tool calls, stay in scope, "
        "end the turn at the evidenced done-criteria."
    ),
    "claude-sonnet-5": (
        "Sonnet 5: same contracts; write an explicit plan for multi-step work and ask when "
        "two readings of a request lead to different code."
    ),
    "claude-haiku": (
        "Haiku: same contracts; write an explicit plan for multi-step work and ask when two "
        "readings of a request lead to different code."
    ),
}

_PREFIX_RE = re.compile(r"^(?:(?:us-gov|us|eu|apac|global)\.)?anthropic\.", re.IGNORECASE)


def normalise_model_id(model: str | None) -> str:
    m = (model or "").strip().lower()
    m = _PREFIX_RE.sub("", m)
    m = re.sub(r"-v\d+(?::\d+)?$", "", m)          # Bedrock `-v1:0`
    m = re.sub(r"-\d{8}$", "", m)                   # dated snapshot
    return m


def note_for(model: str | None) -> tuple[str, str]:
    """(key, note) for the longest matching key, or ("", "")."""
    m = normalise_model_id(model)
    if not m:
        return "", ""
    best = ""
    for key in NOTES:
        if m.startswith(key) and len(key) > len(best):
            best = key
    return (best, NOTES[best]) if best else ("", "")


def model_notes_context(model: str | None) -> tuple[str, str]:
    """Return (additional_context, banner_summary) for session-start.py. Never raises."""
    try:
        key, note = note_for(model)
    except Exception:
        return "", ""
    if not key:
        return "", ""
    ctx = f"<model-notes model=\"{normalise_model_id(model)}\">\n{note}\n</model-notes>"
    return ctx, f"model notes: {key}"
