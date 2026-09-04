#!/usr/bin/env python3
"""M9 -- skills disagreed with each other about the live workflow.

THE DEFECT

Three skills described the same orchestration edge three different ways, and
nothing checked them against each other:

  * `skills/retro/SKILL.md:187`  -- "## Step 5: Ship Session Artifacts (mandatory)"
    ... "invoke the `/ship` skill (Skill tool)". Ship is a MANDATORY child.
  * `skills/retrospective/SKILL.md:238,241` -- "`/ship` is opt-in ... not
    auto-chained by `/retro`. The `/retro` skill chains `/distill` + `/capture`
    only" and "`retro>ship` does not exist in the current architecture."

The second is a MEASUREMENT METHODOLOGY. `/retrospective` counts ship sessions,
ToB gate fires, and skip rates on the premise that the `retro -> ship` edge
cannot exist. Measured over all 602 local transcripts: it occurs in 2 sessions.
Rare, but non-zero -- so a methodology that treats it as impossible silently
mis-attributes those sessions.

A SECOND, INDEPENDENT HALF of the same finding: `/retrospective` (lines 247-253,
270-272) expects FOUR security gates inside `/ship` -- `insecure-defaults`,
`differential-review`, `agentic-actions-auditor`, `semgrep`. Live `/ship`
implements exactly ONE: the conditional `differential-review` gate at Step 4.
So three of its gate-fire denominators can never be non-zero, and a reader sees
"0 fires" where the correct statement is "not implemented".

WHY THIS IS A VALIDATION GAP, NOT A MISSING CONTRACT

The report's remediation proposed building "one machine-readable workflow
contract". That contract ALREADY EXISTS and is ALREADY CORRECT:

    retro/manifest.yaml -> requires_skills: [distill, capture, ship, mega-distill]
    ship/manifest.yaml  -> requires_skills: []   (differential-review is
                                                  conditional, not a hard dep)

So no new source of truth is needed -- and inventing one would create a third
thing to drift. What was missing is that NOTHING cross-checks a skill's prose
against the manifest graph. These tests close that gap: the manifest is the
contract, and prose that contradicts it fails.

Deliberately NOT asserted here: that prose must MENTION every declared child.
Prose legitimately omits detail. The check is one-directional -- prose may not
DENY an edge the manifest declares, which is the failure mode that actually
occurred.

Run: pytest manifests/test_orchestration_prose_matches_manifest.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"

sys.path.insert(0, str(REPO / "manifests"))
import query_engine as Q  # noqa: E402 -- resolves via the sys.path insert above


def load_components():
    """Return the manifest graph as a {id: component} mapping.

    `Q.load_all` returns a DICT keyed by component id (either the compiled
    graph.json or manifests loaded individually) -- not a list. Iterating it
    directly yields the string keys, which is a silent `'str' has no attribute
    'get'` if a caller assumes a sequence.
    """
    comps = Q.load_all(REPO)
    assert comps, "manifest graph loaded empty; the fixture itself is wrong"
    assert isinstance(comps, dict), (
        f"load_all contract changed: expected a dict, got {type(comps).__name__}"
    )
    return comps


def _component(comps, cid):
    return comps.get(cid)


def declared_children(comps, skill_id) -> set[str]:
    c = _component(comps, skill_id)
    assert c is not None, f"no manifest component with id={skill_id!r}"
    return set(c.get("requires_skills") or [])


def skill_prose(skill_id: str) -> str:
    p = SKILLS / skill_id / "SKILL.md"
    assert p.is_file(), f"missing {p}"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# the contract exists and says what we think it says
# ---------------------------------------------------------------------------
def test_retro_manifest_declares_ship_as_a_child():
    """Pin the contract itself, so the tests below cannot silently pass.

    If `ship` is ever dropped from retro's requires_skills, the denial-check
    below would trivially succeed against an empty declaration -- a vacuous
    pass. Assert the premise.
    """
    children = declared_children(load_components(), "retro")
    assert "ship" in children, (
        "retro/manifest.yaml no longer declares `ship`; the orchestration "
        f"contract changed (children: {sorted(children)})"
    )


# ---------------------------------------------------------------------------
# M9a -- prose may not DENY an edge the manifest declares
# ---------------------------------------------------------------------------
#: Phrasings that assert an edge does not exist. Each is a real sentence shape
#: found in the corpus, not a hypothetical.
_DENIAL_TEMPLATES = (
    r"{parent}\s*>\s*{child}\b[^.\n]{{0,60}}?does not exist",
    r"`?/?{child}`?[^.\n]{{0,80}}?not auto-chained by[^.\n]{{0,40}}?`?/?{parent}`?",
)

#: A "chains A + B only" sentence is a CLOSED-SET claim: it affirms the children
#: it names and denies every other declared child. Handled separately from the
#: templates above because a naive `chains.*only` match flags all four of retro's
#: declared children, including the two the sentence actually affirms -- the
#: enumeration has to be parsed, not pattern-matched.
_CLOSED_SET_RE = re.compile(
    r"`?/?(?P<parent>[a-z][a-z0-9-]*)`?\s+skill\s+chains\s+(?P<body>[^.\n]{0,120}?)\bonly\b",
    re.IGNORECASE,
)


#: A denial that is being RETRACTED is not a live denial. Skills document
#: corrected errors on purpose (the repo's whole incident-recording practice
#: depends on it), and a retraction has to quote the false claim to name it. A
#: checker that cannot tell an assertion from its retraction would forbid
#: recording the fix -- which is worse than the drift it prevents. Detected on
#: the SENTENCE containing the hit, not the whole file, so a retraction in one
#: paragraph cannot excuse a live denial in another.
_RETRACTION_MARKERS = (
    "previous version",
    "were false",
    "was false",
    "superseded",
    "supersedes",
    "no longer accurate",
    "incorrectly",
    "retracted",
    "corrected",
)


def _in_retraction(text: str, span: tuple[int, int]) -> bool:
    """Is this hit inside a sentence that is retracting the claim?"""
    start = max(text.rfind("\n", 0, span[0]) + 1, 0)
    end = text.find("\n", span[1])
    sentence = text[start : end if end != -1 else len(text)].lower()
    return any(m in sentence for m in _RETRACTION_MARKERS)


def _denials(text: str, parent: str, child: str) -> list[str]:
    hits = []
    for tmpl in _DENIAL_TEMPLATES:
        pat = tmpl.format(parent=re.escape(parent), child=re.escape(child))
        for m in re.finditer(pat, text, re.IGNORECASE):
            if _in_retraction(text, m.span()):
                continue
            hits.append(m.group(0).strip())

    for m in _CLOSED_SET_RE.finditer(text):
        if m.group("parent").lower() != parent.lower():
            continue
        named = set(re.findall(r"`?/?([a-z][a-z0-9-]*)`?", m.group("body"), re.IGNORECASE))
        named = {n.lower() for n in named}
        if child.lower() not in named:
            if _in_retraction(text, m.span()):
                continue
            # The sentence closes the set without naming this declared child.
            hits.append(m.group(0).strip())
    return hits


def test_no_skill_denies_a_declared_orchestration_edge():
    """THE core regression test.

    Scans every skill's prose for a sentence denying an edge that some
    manifest declares. This is the check whose absence let three skills
    disagree about the live workflow.
    """
    comps = load_components()
    edges = [
        (cid, child)
        for cid, c in comps.items()
        if isinstance(c, dict) and c.get("type") == "skill"
        for child in (c.get("requires_skills") or [])
    ]
    assert edges, "no orchestration edges found in the manifest graph"

    offenders = []
    for skill_dir in sorted(SKILLS.iterdir()):
        md = skill_dir / "SKILL.md"
        if not md.is_file():
            continue
        text = md.read_text(encoding="utf-8")
        for parent, child in edges:
            for hit in _denials(text, parent, child):
                offenders.append(f"{skill_dir.name}/SKILL.md denies {parent}>{child}: {hit!r}")

    assert offenders == [], (
        "skill prose denies an orchestration edge the manifest declares:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# M9b -- a skill may not attribute a security gate to a skill that lacks it
# ---------------------------------------------------------------------------
#: The security-review skills a measurement pass might attribute to /ship.
_GATE_SKILLS = (
    "insecure-defaults",
    "differential-review",
    "agentic-actions-auditor",
    "semgrep",
)


def gates_implemented_by(skill_id: str) -> set[str]:
    """Which gate skills does this skill's own prose actually invoke?

    Reads the prose rather than the manifest because a CONDITIONAL gate is
    correctly absent from requires_skills (it is not a hard dependency), so the
    manifest cannot answer this question. The prose is the implementation of
    record for a gate step.
    """
    text = skill_prose(skill_id)
    return {g for g in _GATE_SKILLS if re.search(rf"/?{re.escape(g)}\b", text)}


def test_ship_gate_inventory_is_what_we_think_it_is():
    """Pin the measured ground truth so drift is visible.

    Live `/ship` has ONE security gate: the conditional differential-review at
    Step 4. If a gate is ever added, this fails and the retrospective's table
    gets updated in the same change -- which is the coupling M9 was missing.
    """
    assert gates_implemented_by("ship") == {"differential-review"}, (
        "the /ship security-gate inventory changed; update "
        "skills/retrospective/SKILL.md's gate table in the same PR "
        f"(found: {sorted(gates_implemented_by('ship'))})"
    )


def test_retrospective_does_not_attribute_unimplemented_gates_to_ship():
    """A gate attributed to /ship but not implemented there yields a false zero.

    Pre-fix, /retrospective told the reader to measure `insecure-defaults`,
    `agentic-actions-auditor` and `semgrep` fires "inside /ship". None is
    implemented there, so those denominators can never be non-zero -- and "0
    fires" reads as a coverage problem when the truth is "not implemented".
    """
    implemented = gates_implemented_by("ship")
    text = skill_prose("retrospective")

    # Only flag a gate that is claimed to run VIA/INSIDE ship. Merely naming a
    # gate skill elsewhere (e.g. a ToB inventory line) is legitimate.
    offenders = []
    for gate in _GATE_SKILLS:
        if gate in implemented:
            continue
        pat = rf"`?/?{re.escape(gate)}`?[^.\n|]{{0,80}}?\b(?:via|inside|within|in)\s+`?/?ship`?"
        for m in re.finditer(pat, text, re.IGNORECASE):
            offenders.append(f"{gate}: {m.group(0).strip()!r}")

    assert offenders == [], (
        "skills/retrospective/SKILL.md attributes gates to /ship that /ship "
        "does not implement (these produce false zeros):\n  " + "\n  ".join(offenders)
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
