"""CI gate for the supergoal prior-arc extraction-recall harness (harness/PROBLEM.md).

Pins parse_plan.extract_metric_names against an INDEPENDENT, hand-labeled fixture
(harness/fixture.json oracle_metric_names — never the extractor's own output). The
prior-arc guard (check_prior_arcs.py) keys ONLY on these names and silently no-ops
when the list is empty, so a miss == supergoal's "refuses re-litigation of prior
arcs" value-prop is undelivered for that plan.

CONTRACT (chosen 2026-05-31): metrics are declared via `METRIC <name>=` lines (any
case) or ALLCAPS identifiers. The case-insensitive METRIC= fix took micro-recall
52.4% -> 61.9% and FULLY delivers the guard for conforming plans (structured /
ALLCAPS, recall 1.0). The remaining gap is 3 prose-only plans (s4/s6/s7) that don't
declare metrics structurally; by the chosen contract they no-op WITH A VISIBLE
WARNING (check_prior_arcs.py directs the author to add METRIC= lines) rather than
risk the over-extraction a global prose regex would cause.
"""
from __future__ import annotations

import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "harness"

# Path-load this skill's harness measure.py under a UNIQUE module name. Several
# skills ship a harness/measure.py; a bare `from measure import ...` collides in
# sys.modules under `pytest skills/` (first import wins), binding the gate to the
# wrong skill's measurement.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("supergoal_prior_arc_measure", HARNESS / "measure.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
run_measurement = _mod.run_measurement


# Snippets that DECLARE metrics structurally (METRIC= lines or ALLCAPS) or via the
# hardcoded literals — the conforming path the case-insensitive METRIC= fix must
# now fully deliver (guard active + recall 1.0).
STRUCTURED_SNIPPETS = {
    "s1_allcaps_works",
    "s2_allcaps_only_works",
    "s3_metric_eq_upper_works",
    "s5_metric_eq_lower_silent_noop",  # now caught by the case-insensitive METRIC= fix
    "s8_prose_hardcoded_literals",
}
# Plans that do NOT declare metrics structurally -> guard no-ops WITH A WARNING by
# the chosen contract (check_prior_arcs directs the author to add METRIC= lines).
# Shrinking this (a further fix) or growing it (a regression) must update this pin.
KNOWN_SILENT_NOOP = {
    "s4_snake_case_silent_noop",
    "s6_mixed_case_metrics",
    "s7_metrics_in_prose",
}
FROZEN_RECALL_FLOOR = 0.60  # post-fix micro-recall is 0.619; floor blocks regression


def test_structured_declarations_fully_extracted():
    """The chosen contract, delivered: every plan that declares metrics structurally
    (METRIC= / ALLCAPS / hardcoded literal) has FULL extraction recall, so its
    prior-arc guard is active and complete."""
    m = run_measurement()
    by_id = {r["id"]: r for r in m["rows"]}
    for sid in STRUCTURED_SNIPPETS:
        r = by_id[sid]
        assert r["prior_arc_guard_active"] and r["recall"] == 1.0, (
            f"{sid}: structured-declaration plan not fully extracted "
            f"(recall {r['recall']:.0%}, missed {r['missed']}) — the METRIC=/ALLCAPS "
            f"contract path must deliver the guard (harness/PROBLEM.md)"
        )


def test_recall_does_not_regress_below_frozen_baseline():
    """Regression floor. The gap from here to target_recall (0.90) is the 3
    prose-only plans (s4/s6/s7) that don't follow the METRIC= contract."""
    m = run_measurement()
    assert m["recall"] >= FROZEN_RECALL_FLOOR, (
        f"extraction recall {m['recall']:.1%} regressed below the frozen baseline "
        f"{FROZEN_RECALL_FLOOR:.0%} (target {m['target_recall']:.0%}); see harness/PROBLEM.md"
    )


def test_silent_noop_set_is_the_documented_deficiency():
    """Pin the plans whose guard no-ops (prose-only, no METRIC= declaration). By the
    chosen contract these warn the author to declare metrics; the set must not grow
    (regression) without review, and shrinks only via a deliberate further fix."""
    m = run_measurement()
    noop = {r["id"] for r in m["rows"] if not r["prior_arc_guard_active"]}
    assert noop == KNOWN_SILENT_NOOP, (
        f"prior-arc no-op set changed: {noop} != documented {KNOWN_SILENT_NOOP} "
        f"(harness/PROBLEM.md)"
    )
