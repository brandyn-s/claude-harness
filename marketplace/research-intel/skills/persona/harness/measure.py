#!/usr/bin/env python3
"""Cohen's-kappa arithmetic measurement for persona's analyze.cohens_kappa.

A `build-measurement-harness` instance (see harness/PROBLEM.md). Drives the real
`scripts/analyze.cohens_kappa` across a labeled fixture of (rater_a, rater_b)
pairs and checks each computed kappa against an INDEPENDENT, hand-computed oracle
value (textbook binary-kappa formula, exact rational arithmetic, pinned in
fixture.json). It never trusts persona's code to define the right answer.

Why: persona's headline value-prop is a Cohen's-kappa agreement gate between its
two scorers. The Wave-1 audit found the kappa MATH is correct, BUT persona's
tests only use kappa in {-1, +1, ~0} -- regimes where kappa ~= raw agreement. A
non-trivially-wrong kappa (raw-agreement substituted, or the (1-pa)(1-pb) term
dropped) would pass every existing test: a wrong kappa would ship green. This
harness pins intermediate kappa values (0.3-0.75, where kappa clearly != raw
agreement) plus the degenerate cases, and includes a discriminator case proving
raw-agreement-substitution would mis-gate.

Deterministic + offline (cohens_kappa is a pure function; no network/keys).

Comparison note: persona's cohens_kappa returns round(.., 3). The fixture's
oracle_kappa values are the corresponding 3-decimal targets, so tol=1e-6 checks
the rounded result exactly. NaN oracles (pe==1, or length mismatch) are matched
by "both NaN".

Usage:
    python3 skills/persona/harness/measure.py [--json]
Exit code: 0 iff every case matches its hand-computed oracle within tol.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
SCRIPTS = HARNESS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from analyze import cohens_kappa  # noqa: E402  (persona's REAL implementation)

FIXTURE = HARNESS_DIR / "fixture.json"


def _is_nan_oracle(v) -> bool:
    return isinstance(v, str) and v.strip().lower() == "nan"


def run_measurement(fixture_path: Path = FIXTURE) -> dict:
    """Run persona's cohens_kappa over every fixture case; compare to the
    independent hand-computed oracle. Return measured metrics + per-case rows."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    tol = float(fixture.get("tol", 1e-6))
    floor = float(fixture.get("kappa_floor", 0.6))
    rows = []
    for c in fixture["cases"]:
        a = [bool(x) for x in c["rater_a"]]
        b = [bool(x) for x in c["rater_b"]]
        got = cohens_kappa(a, b)  # persona's REAL value (may be NaN)
        oracle = c["oracle_kappa"]
        got_nan = isinstance(got, float) and math.isnan(got)

        if _is_nan_oracle(oracle):
            ok = got_nan
            abs_err = 0.0 if ok else float("inf")
            oracle_disp = "NaN"
        else:
            oracle_f = float(oracle)
            abs_err = float("inf") if got_nan else abs(got - oracle_f)
            ok = (not got_nan) and abs_err <= tol
            oracle_disp = f"{oracle_f:.3f}"

        rows.append({
            "id": c["id"],
            "class": c["class"],
            "raw_agreement": c.get("raw_agreement"),
            "got": ("NaN" if got_nan else round(got, 6)),
            "oracle": oracle_disp,
            "abs_err": abs_err,
            "ok": bool(ok),
        })

    finite_errs = [r["abs_err"] for r in rows if math.isfinite(r["abs_err"])]
    max_abs_err = max(finite_errs) if finite_errs else 0.0
    mismatches = [r["id"] for r in rows if not r["ok"]]

    # Discriminator audit: prove raw-agreement-substitution would flip the gate.
    # The gate (analyze --strict) fires when an in-band kappa < floor. For the
    # discriminator case, real kappa < floor (gate fires) but raw_agreement >=
    # floor (an agreement-floor gate would NOT fire) -> substitution mis-gates.
    disc = next((c for c in fixture["cases"] if c["class"] == "discriminator"), None)
    discriminator = None
    if disc is not None:
        ra = float(disc["raw_agreement"])
        ok = float(disc["oracle_kappa"])
        discriminator = {
            "id": disc["id"],
            "raw_agreement": ra,
            "oracle_kappa": ok,
            "floor": floor,
            "real_kappa_gates": ok < floor,             # real kappa -> gate FIRES
            "raw_agreement_gates": ra < floor,          # raw-agree -> gate would NOT fire
            # Valid iff the two disagree: substituting raw-agreement flips the gate.
            "substitution_flips_gate": (ok < floor) and not (ra < floor),
        }

    return {
        "tol": tol,
        "kappa_floor": floor,
        "n_cases": len(rows),
        "max_abs_err": max_abs_err,
        "n_mismatch": len(mismatches),
        "mismatches": mismatches,
        "all_match": len(mismatches) == 0,
        "discriminator": discriminator,
        "rows": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="persona Cohen's-kappa arithmetic measurement")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)
    m = run_measurement()
    if args.json:
        print(json.dumps(m, indent=2))
    else:
        print("persona Cohen's-kappa measurement (analyze.cohens_kappa vs hand-computed oracle)")
        print(f"  {'case':<30} {'class':<14} {'raw':>5} {'kappa':>8} {'oracle':>8} {'abs_err':>10} {'ok':>4}")
        for r in m["rows"]:
            raw = "-" if r["raw_agreement"] is None else f"{r['raw_agreement']:.2f}"
            got = r["got"] if r["got"] == "NaN" else f"{r['got']:.6f}"
            err = "inf" if not math.isfinite(r["abs_err"]) else f"{r['abs_err']:.2e}"
            print(f"  {r['id']:<30} {r['class']:<14} {raw:>5} {str(got):>8} "
                  f"{r['oracle']:>8} {err:>10} {('ok' if r['ok'] else 'X'):>4}")
        d = m["discriminator"]
        print()
        if d is not None:
            print(f"  discriminator ({d['id']}): raw_agreement={d['raw_agreement']:.2f}, "
                  f"oracle_kappa={d['oracle_kappa']:.3f}, floor={d['floor']}")
            print(f"    real kappa gates (fires)        : {d['real_kappa_gates']}")
            print(f"    raw-agreement gates (would fire): {d['raw_agreement_gates']}")
            print(f"    => substituting raw-agreement for kappa FLIPS the gate: "
                  f"{d['substitution_flips_gate']}")
            print()
        print(f"  cases          : {m['n_cases']}")
        print(f"  max_abs_err    : {m['max_abs_err']:.2e}  (tol {m['tol']:.0e})")
        print(f"  mismatches     : {m['n_mismatch']}  {m['mismatches'] if m['mismatches'] else ''}")
        print(f"  RESULT         : {'PASS' if m['all_match'] else 'FAIL'} "
              f"(kappa arithmetic {'matches' if m['all_match'] else 'DIVERGES FROM'} hand-computed oracle)")
    return 0 if m["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
