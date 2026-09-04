# Measurement harness — deep-dive confidence-calibration efficacy (LIVE ARM)

A `build-measurement-harness` instance (recommendation #1, live arm) for
`deep-dive`. Its value-prop is DIFFERENT from the gather-* fact-check family: the
three-layer defense — **HIGH/MEDIUM/LOW confidence + provenance + per-finding
counterfactual** (`skills/_shared/output-grounding.md`). So this harness asks:
**does deep-dive's mandatory confidence actually CALIBRATE (do HIGH-confidence
answers come true more often than LOW?), are its counterfactuals substantive (not
boilerplate), and does it match baseline correctness — by enough to justify ~4× cost?**

## 1. Classify the measurement (Phase 0)
- **Unit:** one factual question → `(answer, confidence, counterfactual)`.
- **Decision under test:** the confidence-grading + counterfactual discipline.
- **Primary metric:** `calibration_discrimination` = accuracy@HIGH − accuracy@non-HIGH
  (the skill's confidence is only useful if it discriminates correctness). Correctness
  (vs baseline) is secondary — a strong model + search ceilings it.
- **Cost asymmetry:** a confidently-wrong answer (HIGH + incorrect) is the worst case;
  the calibration metric directly penalizes it.
- **Class:** agent-benchmark, Mode C, n=15. Directional.

## 2. Oracle — independent ground truth (Phase 1)
- **Deterministic correctness** vs HUMAN-CURATED answer keys (`fixture.json`
  expected_terms / wrong_terms; false-premise → must REJECT). No model judges the
  producer. Verified 2026-05-31.
- **Calibration** is computed from the arm's OWN confidence labels vs its own
  correctness — a within-arm property, fully deterministic given the keys.

## 3. Fixture (`fixture.json`) — 15 questions, spread so confidence has signal
| Bucket | n | Tests |
|---|---|---|
| stable easy/medium facts | 4 | should be HIGH + correct (well-calibrated) |
| stable hard facts | 3 | MAST=14, TruthfulQA inverse, Turpin unfaithfulness, Constitutional-AI origin |
| currency-twist (answer changed) | 4 | current Opus/GPT-5/MCP-date/1M-context — correct = CURRENT not stale |
| false-premise | 4 | nonexistent paper/benchmark/stat — a calibrated arm REJECTS or goes LOW |

## 4. Metrics, A/B (Phase 7)
- **`calibration_discrimination`** (primary): acc@HIGH − acc@non-HIGH for each arm.
- **`accuracy`**: overall correctness (WITH vs baseline).
- **`currency_accuracy`** / **`false_premise_reject_rate`**: sub-slices.
- **`counterfactual_substantive_rate`** (WITH only): fraction of counterfactuals that
  carry a SURVIVES/COLLAPSES/AMBIGUOUS verdict, are non-trivial, and aren't boilerplate
  reused verbatim across questions.
A/B: `with_skill` (3-layer framework) vs `baseline` (plain pass that still emits a
confidence label, so calibration is comparable). N=3, mean+spread. Verdict
(`grade.decide_verdict`): **keep** if confidence meaningfully discriminates (disc >
noise) + counterfactuals substantive + correctness not worse; **fix** if confidence
is anti-calibrated or counterfactuals boilerplate; **trim** if discrimination ~0.

## 5. Frozen baseline — the measured answer
<!-- RESULTS_TABLE_START : N=3, claude-opus-4-8, 2026-05-31 (re-graded against corrected fixture). -->
Measured 2026-05-31, N=3, `claude-opus-4-8`, n=15:

| Metric | baseline | with_skill |
|---|---|---|
| accuracy | 1.000 | 1.000 |
| **calibration_discrimination** (primary) | n/a (no non-HIGH bin) | **0.000** (uniformly HIGH → no spread) |
| currency_accuracy | 1.000 | 1.000 |
| false_premise_reject_rate | 1.000 | 1.000 |
| counterfactual_substantive_rate | n/a (baseline emits none) | 1.000 |

**Verdict: `trim`.** Both arms hit **ceiling accuracy (1.00)** — Opus 4.8 + search
aces this fixture, including correctly REJECTING all 4 false-premise questions
(no hallucinated papers). The framework's mandatory confidence is **uninformative**:
the model marked **43 of 45** answers HIGH and got ~all of them right, so HIGH-vs-
non-HIGH accuracy is identical (discrimination 0.0) — the labels have no spread to
calibrate. The counterfactual layer IS delivered (1.00 substantive) but is **inert**
when accuracy is already ceiling. So the three-layer ceremony buys no measurable
value here → trim.

**Caveat (ceiling/saturation):** the fixture is too easy for a frontier model to
exercise calibration — there are essentially no wrong answers to assign LOW to. A
discriminating calibration measurement needs a HARDER fixture where the model
genuinely errs (then HIGH-vs-LOW accuracy could diverge). The confidence-layer
value-prop is therefore *unfalsified-on-the-upside* by this fixture, not disproven.
<!-- RESULTS_TABLE_END -->

## 6. REAL vs INSTRUMENT (Phase-9 check) — a grader bug was caught and corrected
This harness's most instructive Phase-9 moment. The FIRST grading produced a
striking verdict: `fix` — "framework ANTI-calibrated, accuracy 0.867 < baseline 1.0".
Per verify-effectiveness's instrument-first gate, I read the transcript before trusting it. BOTH
framework "misses" were **grader artifacts**, not real failures:
- `mast-modes`: framework correctly said "14 modes… clustered into **3 categories**",
  but the v1 fixture listed `"three categories"` as a wrong_term → false-fail.
- `mcp-date`: framework correctly said "November 2024", but its verbose dated "Note:"
  tripped a bare-year wrong_term (2025/2026).
Root cause: the `wrong_terms` mechanism was **brittle against the WITH arm's
verbosity** (it mentions history/alternatives/dates; the terser baseline doesn't), so
bare-number/name wrong_terms penalized *correct* verbose answers. The "anti-
calibration" was a knock-on (those correct-but-grader-failed answers were HIGH-conf).

Fix: rewrote `fixture.json` to rely on EXPECTED-term presence with empty/specific-
phrase wrong_terms, then **re-graded the SAME captured answers** (no live re-run).
Corrected result: accuracy 1.00 = 1.00 (tie), discrimination 0.0 → `trim`. The
calibration grader itself is proven FP=FN=0 by `test_calibration_grader_fp_fn_zero`
(synthetic A=HIGH+correct, B=LOW+wrong, C=LOW+rejected → acc 0.667, disc 0.5).
Committed `runs/sample-records-2026-05-31.json` re-grades to `results.json`
(`test_results_reproducible_from_committed_sample`). Lesson: a brittle key can
manufacture a confident-but-false "the framework is broken" verdict; reading source
before trusting the cell is mandatory.

## 7. Truncation / freshness
hosted web_search `max_uses=4` (symmetric); `max_tokens=1500`; `claude-opus-4-8`
(no temperature). `results.json` pins model, fixture_sha, run_date, n_runs.

## 8. Provenance
Keys: `ANTHROPIC_API_KEY` only (hosted web_search; no grounding fetch needed —
correctness is key-matched, not URL-grounded).

## 9. Paused at this fixture (2026-09-04) — pending run-time keys

Status: **paused, not retired.** `run_live.py` prints a notice and refuses a real run
without `--acknowledge-retired-fixture`; `--plan-only` keeps working and the receipt
carries `fixture_status: paused-pending-runtime-keys`.

Reason (`docs/research-skills-root-cause.md` §4, §9 item 1, §12.1): the `current-*`
questions encode a dated answer key, and the 2026-09-03 `fix` verdict was entirely the
instrument — a stale currency key plus a rejection-cue miss. Under the corrected grader
both arms score 180/180 on both dates and the verdict is BLOCKED ON MEASUREMENT: the
fixture is at ceiling and no calibration signal is left to measure. The currency keys are
being made run-time-resolved on another branch; until that lands, a run against this
fixture re-grades the same ceiling.

Unchanged: the frozen 2026-05-31 baseline (`results.json`), its committed sample and
lineage, and the CI gate in `tests/test_deep_dive_efficacy.py`. Reopen when the run-time
keys land, together with a harder fixture (questions a searching frontier model gets
wrong) so calibration has something to discriminate.
