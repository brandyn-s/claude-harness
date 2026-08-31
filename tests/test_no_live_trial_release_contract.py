"""Gather-family changes must qualify before any live application."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

GATHER_POLICY_FILES = (
    ROOT / "skills" / "_shared" / "gather-conventions.md",
    ROOT / "skills" / "gather-claude" / "SKILL.md",
    ROOT / "skills" / "gather-claude" / "references" / "report-format.md",
    ROOT / "skills" / "gather-vendor" / "SKILL.md",
    ROOT / "skills" / "gather-claude-endpoints" / "SKILL.md",
)

LIVE_OBSERVATION_MARKERS = (
    "| **trial** |",
    "adopt | trial",
    "try-by:",
    "re-trial",
    "trial period elapsed",
    "apply with re-eval date",
    "apply + `try-by",
)


def assert_direct_qualification_contract(text: str) -> None:
    lowered = text.lower()
    for marker in LIVE_OBSERVATION_MARKERS:
        assert marker not in lowered, marker
    assert "qualify" in lowered
    assert "qualification" in lowered
    assert "same run" in lowered
    assert "not applied" in lowered or "do not apply" in lowered
    assert "passed — <command and result>" in lowered


@pytest.mark.parametrize("path", GATHER_POLICY_FILES, ids=lambda path: path.name)
def test_gather_policy_qualifies_before_live_application(path: Path) -> None:
    assert_direct_qualification_contract(path.read_text(encoding="utf-8"))


def test_canonical_verdict_and_field_spellings_match_every_consumer() -> None:
    canonical = (ROOT / "skills" / "_shared" / "gather-conventions.md").read_text(
        encoding="utf-8"
    )
    expected_verdicts = "ADOPT | QUALIFY | DEFER | REJECT"
    expected_field = "- **Qualification**:"
    assert expected_verdicts in canonical
    assert expected_field in canonical
    for path in GATHER_POLICY_FILES[1:]:
        text = path.read_text(encoding="utf-8")
        assert expected_verdicts in text, path
        assert expected_field in text, path


@pytest.mark.parametrize(
    "mutation",
    (
        "| **TRIAL** | Apply with re-eval date |",
        "Apply + `try-by: YYYY-MM-DD` (default +30d)",
        "ADOPT | TRIAL | DEFER | REJECT",
        "re-TRIAL with a new date",
        "trial period elapsed without evaluation",
    ),
)
def test_live_observation_contract_mutations_are_rejected(mutation: str) -> None:
    with pytest.raises(AssertionError):
        assert_direct_qualification_contract(
            "QUALIFY is not applied and must resolve in the same run.\n"
            "Qualification: PASSED — <command and result>\n" + mutation
        )
