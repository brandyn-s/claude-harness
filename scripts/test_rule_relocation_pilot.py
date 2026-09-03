"""Contracts for bin/rule_relocation_pilot.py — the instrument that AUTHORISES a
relocation out of the ambient rule tier.

Why this file exists: the pilot's `skill_scoped` property was DECLARED, not proven.
`activity()` returns owner-invocation for such a candidate, so
`exposed = activity - owner` is empty BY CONSTRUCTION, coverage is 100%, and the
verdict is SAFE. Nothing checked that the rule's scope actually equalled its owner
skills.

Measured 2026-08-26: twelve NO-DETECTOR rules are named by some skill's
`requires_rules`. That reads like the link that legitimately made `output-grounding`
SAFE. It is not — `requires_rules` means "this skill needs this rule", not "this
rule's scope IS this skill". Declaring those twelve as skill_scoped candidates would
have minted **five false SAFE verdicts covering 24,952 bytes** (uncharted-vs-refuted
8,255; best-in-class-for-cross-model 6,838; red-team-rubric-discipline 4,099;
symmetric-evidentiary-burden 3,644; api-doc-lookup 2,116), with the remaining six
refused only by `n < MIN_ACTIVITY_SESSIONS` — a shield that a busier corpus removes.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _pilot():
    spec = importlib.util.spec_from_file_location(
        "rule_relocation_pilot_probe", REPO / "bin" / "rule_relocation_pilot.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


PILOT = _pilot()


def _by_rule(rule: str):
    for c in PILOT.CANDIDATES:
        if c.rule == rule:
            return c
    raise AssertionError(f"{rule} is not a pilot candidate")


def test_known_positive_output_grounding_scope_names_its_owner_skills():
    """The one legitimate skill_scoped candidate must still pass.

    A guard that refused everything would be useless, so this is the positive
    control: output-grounding's @scope literally enumerates its four owner skills.
    """
    c = _by_rule("output-grounding")
    assert c.skill_scoped, "output-grounding is the skill-scoped reference candidate"
    assert PILOT.scope_is_bound_to_owner_skills(c) is True
    scope = PILOT.rule_scope_text("output-grounding")
    assert scope, "rule body must be locatable after its relocation to skills/_shared/"
    for sk in c.owner_skills:
        assert sk in scope.lower(), sk


@pytest.mark.parametrize("rule", [
    "uncharted-vs-refuted",
    "best-in-class-for-cross-model",
    "eval-shipping-discipline",
    "security-critical-search-verification",
    "verify-instrument-before-fix",
    "red-team-rubric-discipline",
    "symmetric-evidentiary-burden",
    "compare-by-need",
    "reproduce-before-optimize",
    "api-doc-lookup",
])
def test_known_negative_task_type_scoped_rules_are_refused(rule: str):
    """Each of these is named by a skill's requires_rules but scoped to a TASK TYPE.

    If one of these ever returns True, either its @scope was deliberately narrowed to
    its owner skills (check the diff) or the guard regressed. Do NOT relocate on the
    strength of a flipped verdict here without re-reading the rule's @scope.
    """
    c = _by_rule(rule)
    assert c.skill_scoped, f"{rule} is declared with owner skills and no signals"
    assert PILOT.scope_is_bound_to_owner_skills(c) is False, (
        f"{rule} would mint a false SAFE: exposed==0 by construction"
    )


def test_missing_rule_body_is_a_refusal_not_a_pass():
    """A candidate whose rule cannot be located must return None, which the verdict
    ladder maps to RULE-BODY-NOT-FOUND. Returning True here would let a deleted rule
    authorise its own relocation."""
    fake = PILOT.Candidate(rule="no-such-rule-zzz-41773", owner_skills={"whatever"})
    assert PILOT.rule_scope_text("no-such-rule-zzz-41773") is None
    assert PILOT.scope_is_bound_to_owner_skills(fake) is None


def test_a_scope_unbound_candidate_can_never_reach_safe():
    """BEHAVIOURAL, not textual.

    The first version of this test compared source positions -- it asserted the scope
    branch appeared before the SAFE branch in the file. That proxy PASSED while a
    mutation moving the check to the END of the ladder produced 6 SAFE verdicts
    instead of 1 (rules/tdd-mutation-testing.md item 26: pinning a proxy rather than
    the property). The ladder was extracted into `decide_verdict` so the property
    itself can be asserted.

    A wrongly-declared skill_scoped candidate has exposed == 0 and cov == 1.0 BY
    CONSTRUCTION, which is the SAFE signature. Sweep the whole input space that could
    otherwise reach SAFE and require refusal every time.
    """
    for n in (0, 1, 4, 5, 20, 500):
        for cov in (None, 0.0, 0.70, 0.95, 1.0):
            for has_owner in (True, False):
                verdict = PILOT.decide_verdict(
                    skill_scoped=True, scope_bound=False, has_owner=has_owner,
                    recall=None, doc_share=None, n=n, cov=cov,
                )
                assert verdict == "SCOPE-NOT-SKILL-BOUND", (n, cov, has_owner, verdict)
                assert verdict != "SAFE"


def test_an_unlocatable_rule_body_can_never_reach_safe():
    for n in (5, 500):
        for cov in (0.95, 1.0):
            assert PILOT.decide_verdict(
                skill_scoped=True, scope_bound=None, has_owner=True,
                recall=None, doc_share=None, n=n, cov=cov,
            ) == "RULE-BODY-NOT-FOUND"


def test_a_scope_bound_candidate_still_reaches_safe_when_it_should():
    """Positive control on the ladder: the guard must not have become a blanket
    refusal. A properly scope-bound candidate with full coverage still passes."""
    assert PILOT.decide_verdict(
        skill_scoped=True, scope_bound=True, has_owner=True,
        recall=None, doc_share=None, n=20, cov=1.0,
    ) == "SAFE"
    # and the other gates still bite
    assert PILOT.decide_verdict(
        skill_scoped=True, scope_bound=True, has_owner=True,
        recall=None, doc_share=None, n=4, cov=1.0,
    ) == "INSUFFICIENT-N"
    assert PILOT.decide_verdict(
        skill_scoped=False, scope_bound=True, has_owner=True,
        recall=0.10, doc_share=None, n=20, cov=1.0,
    ) == "LOW-RECALL"
    assert PILOT.decide_verdict(
        skill_scoped=False, scope_bound=True, has_owner=True,
        recall=None, doc_share=0.90, n=20, cov=1.0,
    ) == "DETECTOR-READS-DOCS"
    assert PILOT.decide_verdict(
        skill_scoped=False, scope_bound=True, has_owner=False,
        recall=None, doc_share=None, n=20, cov=1.0,
    ) == "NO-GROUND-TRUTH"


def test_every_skill_scoped_candidate_is_scope_verified_or_refused():
    """The corpus-wide invariant: no candidate may be treated as skill_scoped on the
    strength of its declaration alone. Either its scope names its owners, or the
    guard refuses it. This is what closes the 24,952-byte false-SAFE path."""
    unverified = []
    for c in PILOT.CANDIDATES:
        if not c.skill_scoped:
            continue
        if PILOT.scope_is_bound_to_owner_skills(c) is not True:
            continue
        scope = (PILOT.rule_scope_text(c.rule) or "").lower()
        missing = [sk for sk in c.owner_skills if sk.lower() not in scope]
        if missing:
            unverified.append((c.rule, missing))
    assert unverified == [], unverified
