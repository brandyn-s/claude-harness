"""CI gate for the persona Cohen's-kappa arithmetic harness (harness/PROBLEM.md).

Pins persona's headline value-prop -- the Cohen's-kappa agreement gate between
its keyword and LLM-judge scorers -- to INDEPENDENT, hand-computed ground truth.

Wave-1 finding this closes: the kappa math is correct, but persona's existing
tests (test_persona_kappa_gate.py) only use kappa in {-1, +1, ~0}, regimes where
kappa ~= raw agreement. A non-trivially-wrong kappa -- raw-agreement substituted,
or the (1-pa)(1-pb) chance-correction term dropped -- would pass every existing
test and ship green. These tests assert the intermediate kappa values (0.3-0.75,
where kappa clearly != raw agreement) plus the degenerate cases, and assert the
discriminator: a case where substituting raw-agreement for kappa would flip the
--strict gate decision.

The oracle is hand-derived from the textbook binary-kappa formula
(pe = pa*pb + (1-pa)*(1-pb); kappa = (po-pe)/(1-pe)) and pinned in fixture.json --
it is NEVER computed by calling persona's cohens_kappa.
"""
from __future__ import annotations

from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "harness"

# Path-load this skill's harness measure.py under a UNIQUE module name. Several
# skills ship a harness/measure.py; a bare `from measure import ...` collides in
# sys.modules under `pytest skills/` (first import wins), binding the gate to the
# wrong skill's measurement.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("persona_kappa_measure", HARNESS / "measure.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
run_measurement = _mod.run_measurement


def test_kappa_matches_hand_computed_oracle_every_case():
    """persona's cohens_kappa must equal the hand-computed oracle (tol 1e-6)
    for every fixture case, including the intermediate kappas where kappa
    differs sharply from raw agreement."""
    m = run_measurement()
    assert m["all_match"], (
        f"cohens_kappa diverged from the hand-computed oracle on {m['mismatches']} "
        f"(max_abs_err={m['max_abs_err']:.2e}, tol={m['tol']:.0e}). This means "
        f"persona's chance-corrected agreement is wrong -- its headline kappa "
        f"value-prop is no longer trustworthy (see harness/PROBLEM.md)."
    )
    assert m["max_abs_err"] <= m["tol"], (
        f"max_abs_err={m['max_abs_err']:.2e} exceeds tol={m['tol']:.0e}"
    )


def test_intermediate_kappas_pinned():
    """Guard specifically the intermediate regime the old tests never covered:
    every non-edge case must be a strictly-interior kappa (not in {-1,0,+1}) and
    must match its oracle. A raw-agreement substitution would break these."""
    m = run_measurement()
    interior = [r for r in m["rows"] if r["class"] in ("intermediate", "discriminator")]
    assert len(interior) >= 3, "harness must pin at least 3 intermediate kappa cases"
    for r in interior:
        assert r["ok"], f"intermediate case {r['id']} did not match oracle {r['oracle']}"


def test_discriminator_raw_agreement_substitution_would_fail_gate():
    """The crux of the Wave-1 hole: prove the harness distinguishes real kappa
    from raw agreement at the gate boundary. For the discriminator case the
    real (in-band) kappa is < floor (the --strict gate FIRES), while raw
    agreement is >= floor (an agreement-floor gate would NOT fire). So
    substituting raw-agreement for kappa flips the gate -- exactly the
    non-trivial wrongness the old {-1,+1,~0} tests could not catch."""
    m = run_measurement()
    d = m["discriminator"]
    assert d is not None, "fixture must contain a discriminator case"
    assert d["real_kappa_gates"], (
        f"discriminator {d['id']}: real kappa {d['oracle_kappa']} should be "
        f"< floor {d['floor']} (gate fires)"
    )
    assert not d["raw_agreement_gates"], (
        f"discriminator {d['id']}: raw_agreement {d['raw_agreement']} should be "
        f">= floor {d['floor']} (an agreement-floor gate would NOT fire)"
    )
    assert d["substitution_flips_gate"], (
        f"discriminator {d['id']} must prove raw-agreement-substitution flips the "
        f"gate: real kappa={d['oracle_kappa']} (gates) vs raw_agreement="
        f"{d['raw_agreement']} (does not gate), floor={d['floor']}"
    )
