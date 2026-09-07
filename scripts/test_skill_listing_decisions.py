#!/usr/bin/env python3
"""settings.json skillOverrides and docs/skill-listing-decisions.md agree with the tree.

Every name-only override names a skill that exists; every skill the decisions
document marks applied (D1, D2) is name-only in settings.json; `frame` (D4) is
not. The decisions document is the record of a measurement -- this test keeps the
record and the setting from drifting apart.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "skill-listing-decisions.md"
D1 = {"audit-architecture", "audit-fix", "audit-rules", "gather-claude", "gather-intel", "gather-openai-endpoints",
      "gather-research", "gather-vendor", "threat-model"}
D2 = {"gather-repos", "scout", "scout-frontier", "scout-skills", "superplan-loop", "superplan-status"}


def _overrides() -> dict:
    return json.loads((REPO / "settings.json").read_text(encoding="utf-8")).get("skillOverrides") or {}


def test_every_override_names_a_skill_in_the_tree():
    for name, value in _overrides().items():
        assert (REPO / "skills" / name / "SKILL.md").is_file(), f"skillOverrides names a missing skill: {name}"
        assert value == "name-only", (name, value)


def test_applied_decisions_are_in_settings_and_frame_is_listed():
    ov = _overrides()
    for name in D1 | D2:
        assert ov.get(name) == "name-only", f"{name} is decided name-only (docs/skill-listing-decisions.md) but not in settings.json"
    assert "frame" not in ov, "D4: frame stays listed until it has a window"


def test_decisions_document_names_every_applied_skill():
    text = DOC.read_text(encoding="utf-8")
    for name in D1 | D2:
        assert f"`{name}`" in text, f"{name} is name-only but the decisions document does not say so"
    assert "bin/skill-usage-report.py" in text
    assert re.search(r"3,403 transcripts", text), "the measurement the decisions rest on is stated"
