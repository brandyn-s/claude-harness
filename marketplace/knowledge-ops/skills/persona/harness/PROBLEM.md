# Measurement harness — persona Cohen's-kappa agreement gate

A `build-measurement-harness` instance answering recommendation #1 ("measure the
heavy skills"): is persona's headline value-prop — a **Cohen's-κ agreement gate**
between its two scorers (keyword vs LLM-judge) — actually *trustworthy*? Does
`cohens_kappa` truly compute chance-corrected agreement, and does the
`--strict` / `--kappa-floor` gate fire at the right threshold?

This measures the *mechanism's arithmetic*, deterministically and offline. It does
NOT measure "do the two scorers agree on real personas" — that needs live runs +
labeled outputs (the **live arm**, sketched at the end).

## Wave-1 finding this closes
The κ MATH is correct, BUT persona's only κ tests (`tests/test_persona_kappa_gate.py`)
use κ ∈ {−1 (total disagreement), +1 (identical), ~0.1 (out-of-band)} — exactly the
regimes where **κ ≈ raw agreement**. A *non-trivially-wrong* κ — raw-agreement
substituted for κ, or the `(1−pa)(1−pb)` chance term dropped — reproduces those
extremes and would **pass every existing test**: a wrong κ ships green. This harness
pins the **intermediate** regime (κ ≈ 0.3–0.75, where κ clearly ≠ raw agreement) plus
the degenerate ±1 / chance / NaN cases, and adds a discriminator that flips the gate.

## 1. Classify the measurement
- **Unit:** one κ computation = a labeled `(rater_a, rater_b)` pair of binary
  endorse(1)/reject(0) judgments, with a hand-computed `oracle_kappa`.
- **Decision under test:** `scripts/analyze.cohens_kappa(a, b)` — the function whose
  output drives the in-band ambiguity flag and (under `--strict`) the gate exit code.
  Signature: `cohens_kappa(a: list[bool], b: list[bool]) -> float`, returns
  `round((p_o − p_e)/(1 − p_e), 3)`, or `float('nan')` when `n==0`, `len(a)!=len(b)`,
  or `p_e == 1`.
- **Gate under test:** `analyze.py --strict --kappa-floor F` (default F=0.6) exits 1
  iff some RC has κ **< F** while **in-band** — both scorers' base rates in `[0.2, 0.8]`
  (the kappa-paradox guard, Feinstein & Cicchetti 1990). Out-of-band low κ never gates.

## 2. The oracle (INDEPENDENT, hand-computed ground truth)
**Cardinal rule:** the oracle is computed by the textbook formula by hand, **NEVER**
by calling persona's `cohens_kappa`. Binary Cohen's κ:
- `po` = fraction of items where the two raters agree (== raw agreement),
- `pa`, `pb` = each rater's fraction of positives,
- `pe = pa·pb + (1−pa)(1−pb)`,
- `κ = (po − pe) / (1 − pe)`.

Each fixture case carries an `oracle_kappa` (and a one-line derivation) computed this
way via exact rational arithmetic (`fractions.Fraction`), then written as the
3-decimal value persona's `round(.., 3)` returns. The harness compares persona's
output to that pinned constant within `tol = 1e-6` (NaN oracles matched by "both NaN").

**ANCHOR** (verifies the formula): `a=[1,1,0,0,1]`, `b=[1,0,0,0,1]` → po=0.8, pa=0.6,
pb=0.4, pe=0.48, **κ=0.615**. Reproduced exactly (case `anchor_kappa_0p615`).

## 3. Fixture (`fixture.json`) — 10 hand-labeled cases
**Intermediate (κ ≈ 0.3–0.75, κ clearly ≠ raw agreement):**
- `anchor_kappa_0p615` — κ=0.615, raw=0.80 (the spec anchor).
- `substantial_kappa_0p583` — κ=0.583, raw=0.80.
- `half_base_kappa_0p600` — κ=0.600, raw=0.80 (sits exactly on the floor: gate fires only on κ **<** floor).
- `strong_kappa_0p737` — κ=0.737, raw=0.90.
- `moderate_kappa_0p348_DISCRIM` — see discriminator below.

**Discriminator (proves κ ≠ raw agreement at the gate):**
- `moderate_kappa_0p348_DISCRIM` — `a=[0×7,1,1,1]`, `b=[0×5,1,1,0,1,1]`: po=0.70,
  pa=0.3, pb=0.4, pe=0.54, **κ=0.348**. Both base rates **in-band** ([0.2,0.8]).
  Raw agreement 0.70 ≥ 0.6 would **PASS** an agreement-floor gate, but the real κ=0.348
  **< 0.6 FIRES** the gate. ⇒ substituting raw-agreement for κ **flips the gate** — the
  exact non-trivial wrongness the old {−1,+1,~0} tests cannot catch.

**Edge / degenerate:**
- `perfect_agreement` — identical raters → κ=**+1.0** (po=1, pe=0.52).
- `perfect_disagreement` — never agree, equal base rates → κ=**−1.0** (po=0, pe=0.5).
- `chance_level_zero` — agreement exactly at chance → κ=**0.0** (po=pe=0.5). Pins the
  `(1−pa)(1−pb)` term: dropping it gives pe=0.25, κ=0.333, not 0.
- `degenerate_all_endorse` — both endorse everything, pe=1 → κ=**NaN** (out-of-band, never gates).
- `length_mismatch` — `len(a)≠len(b)` → κ=**NaN** (guard).

## 4. Metric + gate
- **max_abs_err** — max |persona_κ − oracle_κ| over the finite cases. **Gate: ≤ 1e-6.**
- **all_match / n_mismatch** — every case must match its hand-computed oracle.
- **substitution_flips_gate** — discriminator: real κ gates (κ<floor) while raw
  agreement does not (raw≥floor). **Gate: must be true.**

Run: `python3 skills/persona/harness/measure.py` (exit 1 on any mismatch).
CI gate: `skills/persona/tests/test_kappa_measurement.py` — asserts every oracle match
(tol 1e-6) AND the discriminator. This is the regression protection Wave 1 said was missing.

## 5. Frozen baseline (the measured answer)
| | max_abs_err | n_mismatch (of 10) | discriminator flips gate |
|---|---|---|---|
| **persona current** (`analyze.cohens_kappa`) | **0.0** (≤ 1e-6) | **0** | **true** |

persona's κ arithmetic reproduces the hand-computed oracle on every case — including
all five intermediate κ values and both NaN edges — so the math is **CORRECT**. The
deliverable is therefore the now-present **arithmetic-pinning gate**, not a behavior
fix: the harness converts "κ happens to be right" into "κ is *proven* right and a
regression turns CI red." A mutation that substitutes raw-agreement, drops the
`(1−pa)(1−pb)` term, or otherwise perturbs κ flips `chance_level_zero` and every
intermediate case, failing the gate.

## 6. REAL vs INSTRUMENT (Phase-9 check)
The measurement is REAL, not an instrument artifact: `cohens_kappa` is a pure function
fed the exact `list[bool]` shape `analyze.py` constructs; the oracle is hand-derived
by the textbook formula (exact `Fraction` arithmetic) and pinned as a constant,
wholly independent of persona's output; the comparison tolerance (1e-6) is far tighter
than any rounding slack since the oracle targets persona's own 3-decimal rounding.
The anchor (κ=0.615) cross-checks the oracle formula itself. If the harness ever
*passed* a known-wrong κ it would be an instrument failure — guarded by the
discriminator (proves the metric separates κ from raw agreement) and `chance_level_zero`
(proves the chance term is exercised).

## 7. Live arm (requires keys + labeled outputs — not run here)
The downstream question — *do persona's two scorers actually agree on real persona
outputs, and is a low in-band κ a true rubric-ambiguity signal?* — needs an
`ANTHROPIC_API_KEY` (for the LLM-judge) and a corpus of persona outputs with
**human-adjudicated** endorse/reject labels per RC. Protocol: score the corpus with
both scorers, compute κ per RC, and check (a) κ tracks human-rated rubric clarity and
(b) `--strict` gates the RCs humans flag as ambiguous. That validates κ as a *construct*;
this harness validates κ as *arithmetic*. Fixture + runner are future work; this harness
is the template (independent oracle + labeled fixture + metric + frozen baseline + gate).

## Not-covered-here (follow-on)
- This pins `cohens_kappa` arithmetic. The **gate plumbing** (in-band guard + exit code)
  is covered by the existing `tests/test_persona_kappa_gate.py`; a future increment could
  fold an intermediate-κ in-band case (e.g. the discriminator) into that subprocess gate
  test to pin the *threshold behavior* at κ=0.348/0.6, not just the arithmetic.
- κ here is binary (endorse/reject). If persona ever scores >2 categories, a weighted /
  multi-category κ oracle would be the next harness.
