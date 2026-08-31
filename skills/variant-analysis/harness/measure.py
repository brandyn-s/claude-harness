#!/usr/bin/env python3
"""FP-gate / baseline-gate delivery measurement for variant-analysis.

A `build-measurement-harness` instance (see harness/PROBLEM.md). Drives the real
`scripts/verify_variants.check_fp_gate` and `check_baseline` across a labeled
scenario fixture and measures whether variant-analysis's only quality bound — the
documented 50% false-positive cap — is actually DELIVERED, or whether it is INERT
by default (returns a bare PASS when no FP sample is supplied).

Deterministic + offline: both gates are pure functions of their args plus an
NDJSON emit handle; no network, no rg/semgrep, no LLM in the loop.

The oracle is INDEPENDENT hand-derived ground truth (fixture.json `oracle_verdict`
per scenario), derived from the documented contract (SKILL.md "50%+ FP rate means
you've gone too generic"; METHODOLOGY.md audit-triage <50%; harness-pattern.md
"skipped checks ... don't masquerade as passes"). It is NEVER derived from
verify_variants.py's own output.

Usage:
    python3 skills/variant-analysis/harness/measure.py [--json]
Exit code: 0 iff the measured gate behavior matches the documented contract on
every scenario (i.e. no contract violations, including no inert FP gate).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
SCRIPTS = HARNESS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from verify_variants import check_fp_gate, check_baseline  # noqa: E402

FIXTURE = HARNESS_DIR / "fixture.json"


def _last_record(buf: io.StringIO) -> dict:
    """Parse the NDJSON the gate emitted so we can inspect verdict + reason."""
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    return json.loads(lines[-1]) if lines else {}


def _classify_fp(passed: bool, record: dict, oracle: str) -> dict:
    """Map the real gate's (passed, emitted-record) to a verdict + contract check.

    The current gate can only return a bool. We recover whether a True was an
    EVIDENCE-BACKED pass (fp_rate computed and <= cap) or a BARE pass (no sample;
    reason 'informational only') by inspecting the emitted NDJSON record.
    """
    has_fp_rate = "fp_rate" in record
    if passed and not has_fp_rate:
        verdict = "PASS(bare)"  # passed with no FP evidence
    elif passed:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    # Contract evaluation against the independent oracle:
    if oracle == "FAIL":
        ok = verdict == "FAIL"
    elif oracle == "PASS":
        # An evidence-backed PASS is correct. A bare PASS is only acceptable
        # when there is genuinely nothing to verify (n_matches == 0), which the
        # fixture encodes as oracle PASS for fp_no_matches.
        ok = verdict in ("PASS", "PASS(bare)")
    elif oracle == "UNVERIFIED":
        # The gate has no evidence; a bare PASS here LAUNDERS an unverified
        # verdict into a pass -> contract violation (inert gate). Any non-PASS
        # verdict (UNVERIFIED / FAIL) would satisfy the contract.
        ok = verdict not in ("PASS", "PASS(bare)")
    else:
        ok = False
    return {"verdict": verdict, "ok": ok}


def run_measurement(fixture_path: Path = FIXTURE) -> dict:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    rows = []

    # ---- FP-gate scenarios -------------------------------------------------
    for sc in fixture["fp_gate_scenarios"]:
        buf = io.StringIO()
        passed = check_fp_gate(sc["n_matches"], sc["fp_rate_cap"], sc["sampled_fp"], buf)
        rec = _last_record(buf)
        c = _classify_fp(bool(passed), rec, sc["oracle_verdict"])
        rows.append({
            "id": sc["id"], "gate": "fp", "oracle": sc["oracle_verdict"],
            "verdict": c["verdict"], "ok": c["ok"],
            "detail": f"n_matches={sc['n_matches']} sampled_fp={sc['sampled_fp']} cap={sc['fp_rate_cap']}",
            "reason": rec.get("reason", ""),
        })

    # ---- Baseline-gate scenarios ------------------------------------------
    for sc in fixture["baseline_scenarios"]:
        buf = io.StringIO()
        hit = check_baseline(sc["seed_file"], sc["seed_line"], sc["matches"], buf)
        verdict = "PASS" if hit else "FAIL"
        ok = verdict == sc["oracle_verdict"]
        rows.append({
            "id": sc["id"], "gate": "baseline", "oracle": sc["oracle_verdict"],
            "verdict": verdict, "ok": ok,
            "detail": f"seed={sc['seed_file']}:{sc['seed_line']} matches={len(sc['matches'])}",
            "reason": _last_record(buf).get("reason", ""),
        })

    fp_rows = [r for r in rows if r["gate"] == "fp"]
    bl_rows = [r for r in rows if r["gate"] == "baseline"]

    # The inert-FP-gate flag: did the no-sample-but-real-matches case (oracle
    # UNVERIFIED) wrongly come back as a PASS? This is the Wave-1 deficiency.
    inert_row = next(r for r in fp_rows if r["id"] == "fp_no_sample_large_matchset")
    inert_fp_gate = inert_row["verdict"] in ("PASS", "PASS(bare)")

    violations = [r["id"] for r in rows if not r["ok"]]

    def rate(num, denom):
        return (num / denom) if denom else 0.0

    return {
        "fp_rate_cap": fixture["fp_rate_cap"],
        "n_scenarios": len(rows),
        "contract_violations": violations,
        "n_contract_violations": len(violations),
        "inert_fp_gate": inert_fp_gate,
        "fp_gate_contract_compliance": rate(sum(r["ok"] for r in fp_rows), len(fp_rows)),
        "baseline_gate_contract_compliance": rate(sum(r["ok"] for r in bl_rows), len(bl_rows)),
        "overall_contract_compliance": rate(sum(r["ok"] for r in rows), len(rows)),
        "rows": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="variant-analysis FP/baseline gate delivery measurement")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)
    m = run_measurement()
    if args.json:
        print(json.dumps(m, indent=2))
    else:
        print("variant-analysis gate-delivery measurement (real gates vs independent oracle)")
        print(f"  {'scenario':<28} {'gate':<9} {'oracle':<11} {'verdict':<11} {'ok':>3}")
        for r in m["rows"]:
            flag = "" if r["ok"] else "  <-- CONTRACT VIOLATION"
            print(f"  {r['id']:<28} {r['gate']:<9} {r['oracle']:<11} {r['verdict']:<11} "
                  f"{('ok' if r['ok'] else 'X'):>3}{flag}")
        print()
        print(f"  inert_fp_gate                      : {m['inert_fp_gate']}   "
              f"(True = no-sample/large-matchset case wrongly PASSES; the gate is inert by default)")
        print(f"  fp_gate_contract_compliance        : {m['fp_gate_contract_compliance']:.0%}")
        print(f"  baseline_gate_contract_compliance  : {m['baseline_gate_contract_compliance']:.0%}")
        print(f"  overall_contract_compliance        : {m['overall_contract_compliance']:.0%}")
        print(f"  contract_violations                : {m['n_contract_violations']}  {m['contract_violations']}")
    return 0 if m["n_contract_violations"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
