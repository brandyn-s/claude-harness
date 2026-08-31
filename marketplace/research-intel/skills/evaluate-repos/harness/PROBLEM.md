# Measurement harness — evaluate-repos de-bias efficacy (LIVE ARM)

A `build-measurement-harness` instance (recommendation #1, live arm) for
`evaluate-repos`. The skill exists to fix self-evaluation **dismissal bias**: a
single agent evaluating an external pattern against its own architecture
pattern-matches it to "we already have that" and SKIPs. The fix is two agents with
opposite mandates — ADVOCATE (argue FOR) + SKEPTIC (argue AGAINST) → synthesis.

**This harness tests the de-bias CLAIM directly and falsifiably:** does the
advocate/skeptic harness LOWER false-dismissal vs a single self-eval pass — without
inflating over-adoption?

## 1. Classify the measurement (Phase 0)
- **Unit:** one adopt/defer/reject decision on a neutrally-described external pattern.
- **Decision under test:** advocate+skeptic+synthesis (3 calls) vs single self-eval (1 call).
- **Primary metric:** `false_dismissal_rate` = of should_adopt patterns, fraction the arm
  did NOT adopt (REJECT or DEFER). The de-bias claim is harness < baseline.
- **Guard metric:** `over_adoption_rate` (de-biasing must not over-correct into adopting
  bad patterns).
- **Class:** agent-benchmark, Mode C, n=14 (7 should_adopt / 7 should_reject). Directional.

## 2. Oracle — independent ground truth (Phase 1)
HUMAN-CURATED historical dispositions (oracle type b) drawn from this architecture's
documented adoption history (rules/ + rules/incidents/). The KEY subset is 4
**`look_dismissable: true` should_adopt** patterns — ones that proved right to adopt in
hindsight but a single self-eval tends to dismiss (3 are real **wrongly-dismissed-then-
adopted** cases: listwise-rerank, behavioral-labels, blinded-judge-pool). Anti-
circularity: the arms see ONLY the neutral `pattern` text (no outcome/incident); the
producer never sets the labels — history does. Patterns described to avoid teaching-to-
the-test (no "we adopted/rejected this" leakage).

## 3. Fixture (`fixture.json`) — 14 patterns
| Disposition | n | of which look_dismissable |
|---|---|---|
| should_adopt | 7 | 4 (the de-bias-critical cases) |
| should_reject | 7 | 0 |

## 4. Metrics, A/B (Phase 7)
- **`false_dismissal_rate`** (primary): of should_adopt, fraction not adopted. Lower=better.
- **`dismissable_dismissal_rate`**: same, over the look_dismissable subset (the cases the
  bias most affects).
- **`over_adoption_rate`** (guard): of should_reject, fraction adopted.
- **`decision_accuracy`**: overall (adopt↔should_adopt, reject↔should_reject; defer=incorrect).
A/B: `with_skill` (advocate+skeptic+synthesis) vs `baseline` (single self-eval), both
claude-opus-4-8, NO web_search (pure reasoning vs a shared architecture-context blurb).
N=3. Verdict (`grade.decide_verdict`, noise-aware): **keep** if harness lowers
false-dismissal beyond noise without inflating over-adoption; **fix** if it over-adopts;
**trim** if no measurable de-bias.

## 5. Frozen baseline — the measured answer (over-dismissal guard added + re-measured 2026-05-31)

### 5a. PRE-guard measurement — the `fix` finding (the de-bias mechanism BACKFIRES)
| Metric | baseline (single self-eval) | with_skill (UNGUARDED auto-synthesis) | Δ |
|---|---|---|---|
| decision_accuracy | 0.786 | 0.310 | −0.476 |
| false_dismissal_rate (lower=better) | 0.286 | 0.857 | +0.571 WORSE |
| over_adoption_rate (guard) | 0.000 | 0.000 | 0.000 |

The single self-eval baseline was DECISIVE and mostly right (adopted 5/7 should-adopt). The
unguarded advocate/skeptic→auto-synthesis arm, after the mandatory SKEPTIC case, **over-hedged**:
it DEFERred most should-adopt patterns (false_dismissal 0.857) — over-DISMISSAL, the exact
opposite of the skill's intent.

### 5b. THE FIX (commit `5ee9111`) — over-dismissal guard
Added to the harness synthesis arm AND the deployed SKILL.md: *"a skeptic case EXISTING is not a
blocker; DEFER/REJECT only on a NAMED concrete blocker; absent one, the advocate case stands."*
Plus a Rule forbidding LLM auto-synthesis of the decision (the human is decider).

### 5c. POST-guard re-measurement (N=3, same harness) — guard HALVES the backfire but does NOT rescue it
<!-- RESULTS_TABLE_START : N=3, claude-opus-4-8, 2026-05-31, guarded synthesis. -->
| Metric | baseline | with_skill (GUARDED auto-synthesis) | Δ |
|---|---|---|---|
| decision_accuracy | 0.786 | 0.310 | −0.476 |
| false_dismissal_rate (lower=better) | 0.286 | 0.524 | +0.238 still WORSE |
| hard_reject_rate | 0.238 | 0.000 | guard stopped hard-rejects of good patterns |
| over_adoption_rate (guard) | 0.000 | 0.048 | +0.048 (negligible) |

**Verdict: `fix` (still).** The over-dismissal guard substantially helped — false_dismissal
0.857 → 0.524, and hard-rejects of good patterns went to ZERO — but the guarded synthesizer STILL
over-hedges to DEFER more than a decisive single pass (0.524 > 0.286). An LLM that just read a
mandatory adversarial skeptic case hedges toward caution even when explicitly told not to. So the
auto-synthesis mechanism is improved-but-still-flawed.

**CRITICAL VALIDITY CAVEAT + actionable conclusion (now empirically grounded):** the REAL skill
presents both arguments **to the HUMAN, who decides** — this harness substitutes an LLM synthesis
(necessary to automate the A/B), so it measures *auto-synthesis*, NOT the skill-as-designed
(un-measurable here). The post-guard result STRENGTHENS the design conclusion: even a GUARDED
auto-synthesizer over-hedges, so **keep the human as decider; never auto-synthesize the decision**
(codified as a Rule). The over-dismissal guard still ships — it halves the over-hedging AND protects
the human-presentation step (Step 4) from the same skeptic-driven dismissal bias. n=14 directional;
baseline stdev 0 while with_skill false_dismissal stdev 0.067.
<!-- RESULTS_TABLE_END -->

## 6. REAL vs INSTRUMENT + measurement-validity (Phase-9) — PERFORMED
1. **Not a parse artifact:** the prime suspect for a backfire result is the synthesis
   JSON failing to parse → defaulting to DEFER (inflating false-dismissal). Checked:
   **0/42 decisions** in BOTH arms were parse-fallbacks — every decision is a clean
   ADOPT/DEFER/REJECT token. The harness genuinely DEFERs (it is case (b) below, not an
   instrument bug). De-bias grader itself proven FP=FN=0 (`test_debias_grader_fp_fn_zero`);
   committed `runs/sample-records` re-grades to `results.json`.
2. **Which of the three cases?** (a) harness reduces a real baseline bias [keep],
   (b) harness ADDS hedging the baseline lacked [fix], (c) neither arm biased [trim].
   Transcript shows **(b)**: baseline ADOPTs 5/7 should-adopt decisively; harness DEFERs
   most after the skeptic's case. So the advocate/skeptic→auto-synthesis pipeline
   INCREASES dismissal → `fix`.
3. **Validity boundary (decisive):** the measured arm is a PROXY — an LLM synthesis
   stands in for the skill's actual human decider. The finding is valid for "auto-
   synthesize the advocate/skeptic decision"; it does NOT measure the skill-as-designed
   (human decides on both arguments). See §5 verdict for the actionable framing.
4. **Post-guard re-measurement (REAL, not instrument):** after adding the over-dismissal guard
   (§5b), false_dismissal dropped 0.857→0.524 with **0/84 decisions** parse-fallbacks (all genuine
   ADOPT/DEFER/REJECT tokens) — the partial improvement is real model behavior, not a scorer
   artifact. The guarded synthesizer still DEFERs more than the single pass (0.524 > 0.286),
   confirming case (b) persists even guarded. The committed `runs/sample-records-2026-05-31.json`
   re-grades to the guarded `results.json` (`test_results_reproducible_from_committed_sample`).

## 7. Truncation / freshness
No web_search (pure reasoning); `max_tokens` 700/call; `claude-opus-4-8` (no temperature).
`results.json` pins model, fixture_sha, run_date, n_runs.

## 8. Provenance
Keys: `ANTHROPIC_API_KEY` only. Cost: n_patterns × (1 + 3) × n_runs calls (~168 at N=3).
