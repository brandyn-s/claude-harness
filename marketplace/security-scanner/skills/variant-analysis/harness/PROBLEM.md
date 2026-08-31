# Measurement harness — variant-analysis FP-gate delivery

A `build-measurement-harness` instance: does `variant-analysis` actually
**deliver** its one quality bound — the documented **50% false-positive cap** —
or does that gate sit **inert** by default, rubber-stamping any pattern that
ships without an FP sample?

This measures the *mechanism's delivery of its value-prop*, deterministically and
offline. It does NOT measure "does variant-analysis find more real bug variants
than a single grep" — that needs a labeled multi-variant corpus + live model
(the **live arm**, sketched at the end).

## 1. Classify the measurement
- **Unit:** one gate decision.
  - FP gate: `(n_matches, fp_rate_cap, sampled_fp)` → pass/fail.
  - Baseline gate: `(seed_file, seed_line, matches)` → pass/fail.
- **Decision under test:**
  - `scripts/verify_variants.check_fp_gate(n_matches, fp_rate_cap, sampled_fp, ndjson)` — the only enforcement of variant-analysis's "stop when FP rate exceeds ~50%" principle. A `passed=True` is an implicit claim "this pattern's FP rate is within the documented cap."
  - `scripts/verify_variants.check_baseline(seed_file, seed_line, matches, ndjson)` — the Level-0-must-match-the-seed kernel gate (measured as the control that Wave 1 said IS sound).

## 2. The oracle (independent hand-derived ground truth)
For each scenario the oracle label is set **by hand from the documented
contract**, NEVER from `verify_variants.py`'s output:

- **Documented contract (FP cap):** SKILL.md Key Principle #4 — "Know when to
  stop: 50%+ FP rate means you've gone too generic"; METHODOLOGY.md "Security
  audit triage" row — acceptable FP rate `<50%`; `verify_variants.main` defaults
  `fp_rate_cap=0.5`. The gate's job is to **block** a pattern whose FP rate
  exceeds the cap.
- **FP-cap oracle rule:**
  - FP rate **> cap** ⇒ **FAIL** (pattern generalized too far).
  - FP rate **≤ cap** (with a sample, or trivially when `n_matches == 0`) ⇒ **PASS**.
  - **No sample** on a real match set ⇒ **UNVERIFIED / non-PASS**. The gate has
    *zero evidence* the FP rate is under cap. harness-pattern.md §2 states the
    oracle "never launders verdicts up the stack: skipped checks report skipped
    + reason and don't masquerade as passes." A **bare `passed=True`** here is a
    **contract violation**; an `UNVERIFIED`/non-PASS verdict satisfies it.
- **Baseline oracle rule:** Level-0 pattern must match `seed_file:seed_line`.
  Match present ⇒ **PASS**; file/line mismatch or no match ⇒ **FAIL**.

The Wave-1 finding this addresses: `check_fp_gate` returns `passed=True`
("gate informational only") whenever `sampled_fp` is absent — so by default the
FP cap is **INERT**: a pattern matching thousands of lines passes `--strict`
with no sample. The `fp_no_sample_large_matchset` scenario is the witness.

## 3. Fixture (`fixture.json`)
9 hand-labeled scenarios across two gates.

**FP gate (5):**
- `fp_above_cap` — 150/200 = 75% > 50% → oracle **FAIL** (gate delivering value).
- `fp_at_cap_boundary` — 50/100 = 50% (≤ cap) → oracle **PASS** (boundary).
- `fp_below_cap` — 10/100 = 10% < 50% → oracle **PASS**.
- `fp_no_sample_large_matchset` — 5000 matches, `sampled_fp=null` → oracle
  **UNVERIFIED** (the bug surface: current code returns a bare PASS).
- `fp_no_matches` — 0 matches, no sample → oracle **PASS** (vacuously within
  cap; guards against over-correction breaking the empty case).

**Baseline gate (4):**
- `baseline_seed_hit` — seed `api/users.py:42` in matches → oracle **PASS**.
- `baseline_wrong_line` — right file, line 99≠42 → oracle **FAIL** (Wave 1's "sound" case).
- `baseline_wrong_file` — right line, wrong file → oracle **FAIL**.
- `baseline_no_matches` — empty match set → oracle **FAIL**.

## 4. Metric + gate
- **inert_fp_gate** — does `fp_no_sample_large_matchset` (oracle UNVERIFIED)
  wrongly come back PASS? **The headline flag.** True = the FP cap is inert by default.
- **contract_violations / n_contract_violations** — scenarios where the real
  gate's verdict diverges from the documented contract. **Exit gate: must be 0.**
- **fp_gate_contract_compliance** — FP scenarios matching the contract.
- **baseline_gate_contract_compliance** — baseline scenarios matching the contract
  (expected 100% before *and* after — the control).
- **overall_contract_compliance** — all scenarios.

To recover whether a `True` is an *evidence-backed* pass or a *bare* pass, the
harness inspects the emitted NDJSON record: a pass with no `fp_rate` field and
reason "informational only" is classified `PASS(bare)`. Against an `UNVERIFIED`
oracle, any PASS (bare or not) is the violation.

Run: `python3 skills/variant-analysis/harness/measure.py` (exit 1 if any
contract violation, incl. an inert FP gate).

## 5. Frozen baseline (the measured answer)

| | inert_fp_gate | fp_gate_compliance | baseline_compliance | violations |
|---|---|---|---|---|
| **Before** (gate informational-only on missing sample) | **True** | 80% (4/5) | 100% (4/4) | 1 (`fp_no_sample_large_matchset`) |
| **After** (proposed: missing sample ⇒ UNVERIFIED/non-PASS) | False | 100% (5/5) | 100% (4/4) | 0 |

**Before-state read:** the FP gate enforces the cap correctly *only when a
sample is present* (`fp_above_cap` FAILs, `fp_below_cap`/boundary PASS). But its
default-path behavior — the overwhelmingly common case where a hunter ships a
pattern without sampling FPs — is a **bare PASS regardless of match count**: a
5000-line match set sails through `--strict`. The cap is therefore **inert by
default**. The **baseline gate is sound** in every scenario (wrong line/file/no
match all FAIL), confirming Wave 1's split assessment: the seed-baseline half
works; the FP-cap half is the unfixed deficiency.

## 6. Proposed minimal fix (for the orchestrator — NOT applied here)
In `check_fp_gate`, replace the bare informational PASS on a missing sample with
a non-PASS `UNVERIFIED` verdict **only when there is something to verify**
(`n_matches > 0`); keep the legitimate pass for `n_matches == 0`:

```python
def check_fp_gate(n_matches, fp_rate_cap, sampled_fp, ndjson):
    record = {"run_id": _now(), "check": "fp_rate_gate", "n_matches": n_matches, "cap": fp_rate_cap}
    if n_matches == 0:
        record["passed"] = True
        record["reason"] = "no matches; FP rate vacuously 0"
        emit(record, ndjson); return True
    if sampled_fp is None:                      # <-- was: bare passed=True
        record["passed"] = False
        record["verdict"] = "UNVERIFIED"
        record["reason"] = f"{n_matches} matches but no FP sample; cap UNVERIFIED — sample required"
        emit(record, ndjson); return False
    fp_rate = sampled_fp / n_matches
    record["fp_rate"] = fp_rate
    record["passed"] = fp_rate <= fp_rate_cap
    if not record["passed"]:
        record["reason"] = f"FP rate {fp_rate:.0%} > cap {fp_rate_cap:.0%} — generalized too far"
    emit(record, ndjson); return record["passed"]
```

Under `--strict` this makes an unsampled, non-empty pattern fail loudly ("sample
required") instead of silently passing. The harness re-run should then show
`inert_fp_gate=False` and `n_contract_violations=0`. (Doc follow-on: the
informational-only language in SKILL.md / harness-pattern.md §2/§7 should be
updated to "missing sample ⇒ UNVERIFIED under --strict," not "informational.")

## 7. REAL vs INSTRUMENT (Phase-9 check)
The "before" violation is REAL, not an instrument artifact:
- `check_fp_gate` / `check_baseline` are pure functions; the harness calls them
  directly with args of the exact shape `main()` passes (`len(matches)`,
  `spec["fp_rate_cap"]`, `pat["sampled_fp"]`; `seed_file`, `seed_line`, `matches`).
- The oracle labels are hand-set per scenario from the documented contract and
  are independent of the functions' output (CARDINAL RULE).
- The inert-gate verdict is read from the function's *own emitted record*
  (reason "informational only", no `fp_rate`) — the bug is in the code path, not
  in the measurement.
- Applying the §6 fix flips `fp_no_sample_large_matchset` to non-PASS and drives
  violations to 0; reverting it turns the gate red again. The metric tracks the
  code, not noise.

## 8. Live arm (requires a labeled corpus + model — not run here)
The downstream efficacy question — *does climbing the abstraction ladder surface
real variants at an acceptable FP rate?* — needs a corpus of repos with
**planted, labeled variants of a seed bug** and a model to drive generalization.
Protocol: run the five-step loop per seed; at each level record true/false
positives against the labels; verify the FP gate trips exactly when the measured
FP rate crosses the cap, and that recall does not collapse. Corpus + runner are
future work; this harness is the template (independent oracle + labeled fixture +
metric + frozen baseline + CI gate).

## Not-yet-fixed deficiencies this harness documents (follow-on)
- **The §6 fix is proposed, not applied** (HARD RULE: no edits to
  `verify_variants.py` from this harness). Until applied, `--strict` runs
  without an FP sample pass vacuously.
- **No FP-sampling helper.** Nothing in the skill helps a hunter *produce*
  `sampled_fp` (it must hand-classify a sample of matches). With the §6 fix the
  gate will demand a sample it gives no tooling to compute — a sibling lift
  (sample-N-matches-for-triage) is the next increment.
- **`fp_rate_cap` is a single global** — METHODOLOGY.md defines four context caps
  (CI <5%, dev <20%, audit <50%, research <80%) but the spec only carries one.
  Per-context caps are unmeasured here.
