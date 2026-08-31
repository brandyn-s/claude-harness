"""Rubric scorer for /scout-frontier paradigm-distance fixtures.

Reads a fixture JSON and validates the paradigm-distance rubric against the
hand-scored ground truth on TWO contracts (SKILL.md Step 8):

  TPR = 1.0  — every expected_paradigm_distinct finding computes distance >= 1
  FPR = 0    — every negative_control computes distance == 0

Both the expected findings and the negative controls must carry per-axis
values so the scorer can RECOMPUTE distance from the 4 axes and compare it to
the hand-assigned `distance`. A control with no axis values cannot be verified
and blocks a clean pass (it would otherwise let "FPR = 0" be asserted without
ever being measured).

Feature-parity "traps" (a better-implemented same-paradigm system that should
score 0) belong in `negative_controls` WITH full axes — not in the expected
set. Putting a distance-0 entry in `expected_paradigm_distinct` violates the
TPR contract and is reported as a TPR failure.

Exit codes:
  0 = fixture passes (no FP/FN, TPR = 1.0, FPR = 0, nothing unverifiable)
  1 = mismatch detected (rubric disagrees with ground truth)
  2 = malformed input (bad JSON / missing required fields)

Usage:
  python score_rubric.py <fixture.json>
  python score_rubric.py ~/.claude/skills/scout-frontier/test-fixtures/code-intel-paradigms.json
  python score_rubric.py ~/.claude/skills/scout-frontier/test-fixtures/observability-paradigms.json
"""
import json
import sys
from pathlib import Path

AXES = ("data_structure", "computation_model", "abstraction_level", "time_dynamics")


def distance(incumbent: dict, finding: dict) -> tuple[int, list[str]]:
    """Return (distance, axes-that-differ) by comparing finding to incumbent on the 4 axes."""
    differs = [a for a in AXES if finding.get(a) != incumbent.get(a)]
    return len(differs), differs


REQUIRED_TOP_LEVEL = ("incumbent", "fixture_name", "version")


def score(fixture_path: Path) -> int:
    """Score a fixture; return exit code (0 = pass, 1 = mismatch, 2 = malformed input)."""
    raw = fixture_path.read_text(encoding="utf-8")
    try:
        fixture = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"FAIL: fixture is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(fixture, dict):
        print(
            f"FAIL: fixture must be a JSON object at top level, got {type(fixture).__name__}",
            file=sys.stderr,
        )
        return 2
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in fixture]
    if missing:
        print(
            f"FAIL: missing required field(s): {', '.join(missing)} "
            f"(fixture must contain: {', '.join(REQUIRED_TOP_LEVEL)})",
            file=sys.stderr,
        )
        return 2
    incumbent = fixture["incumbent"]
    if not isinstance(incumbent, dict):
        print(
            f"FAIL: 'incumbent' must be a JSON object, got {type(incumbent).__name__}",
            file=sys.stderr,
        )
        return 2
    missing_incumbent_fields = [k for k in ("name", *AXES) if k not in incumbent]
    if missing_incumbent_fields:
        print(
            f"FAIL: 'incumbent' missing required field(s): {', '.join(missing_incumbent_fields)} "
            f"(incumbent must contain: name, {', '.join(AXES)})",
            file=sys.stderr,
        )
        return 2
    distinct = fixture.get("expected_paradigm_distinct", [])
    controls = fixture.get("negative_controls", [])
    for label, entries in (
        ("expected_paradigm_distinct", distinct),
        ("negative_controls", controls),
    ):
        if not isinstance(entries, list):
            print(
                f"FAIL: '{label}' must be a JSON array, got {type(entries).__name__}",
                file=sys.stderr,
            )
            return 2
        if not entries:
            print(
                f"FAIL: '{label}' is missing or empty — TPR/FPR cannot be measured, "
                "so a pass would be vacuous "
                "(SKILL.md Step 8 requires 5+ entries, each with all 4 axis values)",
                file=sys.stderr,
            )
            return 2
        non_objects = sorted({type(e).__name__ for e in entries if not isinstance(e, dict)})
        if non_objects:
            print(
                f"FAIL: every '{label}' entry must be a JSON object, "
                f"got: {', '.join(non_objects)} "
                "(each entry needs name, distance, and the 4 axis values)",
                file=sys.stderr,
            )
            return 2
        if len(entries) < 5:
            print(
                f"WARN: '{label}' has only {len(entries)} entr(y/ies); "
                "SKILL.md Step 8 requires 5+ for a publishable fixture",
                file=sys.stderr,
            )

    print(f"Fixture: {fixture['fixture_name']} (v{fixture['version']})")
    print(f"Incumbent: {incumbent['name']}")
    print(f"  axes: {tuple(incumbent[a] for a in AXES)}")
    print()
    print(f"{'Finding':50s} {'Computed':>9s} {'Declared':>9s} {'Differs on':38s} {'Status':>9s}")
    print("-" * 128)

    fp_count = 0       # computed > declared (rubric credits too much distance)
    fn_count = 0       # computed < declared (rubric credits too little)
    tpr_fail = 0       # expected finding that computes distance 0 (rubric calls it same-paradigm)
    unverifiable = 0   # entry with no axis values — distance cannot be recomputed

    # --- TPR: every expected finding must recompute to distance >= 1 -----------
    for f in distinct:
        name = f.get("name", "<unnamed>")[:48]
        declared = f.get("distance")
        if not all(a in f for a in AXES):
            print(f"{name:50s} {'-':>9s} {str(declared):>9s} {'(no axis values)':38s} {'SKIP':>9s}")
            unverifiable += 1
            continue
        computed, differs = distance(incumbent, f)
        differs_str = ",".join(differs) if differs else "(none)"
        if computed == 0:
            status = "TPR-FAIL"
            tpr_fail += 1
        elif declared is not None and computed > declared:
            status = "FP"
            fp_count += 1
        elif declared is not None and computed < declared:
            status = "FN"
            fn_count += 1
        else:
            status = "OK"
        print(f"{name:50s} {computed:>9d} {str(declared):>9s} {differs_str[:38]:38s} {status:>9s}")

    # --- FPR: every negative control must recompute to distance 0 --------------
    print()
    print(f"Negative controls (must recompute to distance 0): {len(controls)} entries")
    fpr_miss = 0
    for c in controls:
        name = c.get("name", "<unnamed>")[:48]
        if not all(a in c for a in AXES):
            print(f"  SKIP  {name:48s} (no axis values — cannot verify distance == 0)")
            unverifiable += 1
            continue
        computed, differs = distance(incumbent, c)
        if computed != 0:
            differs_str = ",".join(differs)
            print(f"  FPR-FAIL  {name:44s} computed {computed} (differs on {differs_str})")
            fpr_miss += 1
        else:
            print(f"  OK    {name:48s} computed 0")
        if c.get("distance", 0) != 0:
            print(f"  WARN: {name} declared distance != 0 (negative controls must declare 0)")
            fp_count += 1

    # --- Verdict ---------------------------------------------------------------
    n_distinct = len(distinct)
    n_controls = len(controls)
    tpr = (n_distinct - tpr_fail - sum(1 for f in distinct if not all(a in f for a in AXES))) / n_distinct if n_distinct else 1.0
    fpr = fpr_miss / n_controls if n_controls else 0.0

    print()
    print(f"TPR (expected scoring distance >= 1): {tpr:.2f}  [{tpr_fail} scored 0]")
    print(f"FPR (controls scoring distance > 0):  {fpr:.2f}  [{fpr_miss} scored > 0]")
    print(f"Arithmetic consistency: {fp_count} FP, {fn_count} FN, {unverifiable} unverifiable")

    ok = (
        fp_count == 0
        and fn_count == 0
        and tpr_fail == 0
        and fpr_miss == 0
        and unverifiable == 0
    )
    print()
    if ok:
        print("PASS: rubric reproduces hand-scored ground truth "
              "(TPR = 1.0, FPR = 0, no arithmetic drift, all entries verifiable)")
        return 0
    reasons = []
    if tpr_fail:
        reasons.append(f"{tpr_fail} expected finding(s) scored distance 0 (TPR < 1.0)")
    if fpr_miss:
        reasons.append(f"{fpr_miss} negative control(s) scored distance > 0 (FPR > 0)")
    if fp_count:
        reasons.append(f"{fp_count} finding(s) over-credited (computed > declared)")
    if fn_count:
        reasons.append(f"{fn_count} finding(s) under-credited (computed < declared)")
    if unverifiable:
        reasons.append(f"{unverifiable} entr(y/ies) have no axis values (cannot verify)")
    print("FAIL: " + "; ".join(reasons))
    print("Investigate before publishing measurements (see ~/.claude/rules/validate-to-improve.md).")
    return 1


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    p = Path(sys.argv[1]).expanduser()
    if not p.exists():
        print(f"Fixture not found: {p}", file=sys.stderr)
        sys.exit(2)
    sys.exit(score(p))


if __name__ == "__main__":
    main()
