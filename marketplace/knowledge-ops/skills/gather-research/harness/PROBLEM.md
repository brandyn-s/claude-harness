# Measurement harness — gather-research grounding efficacy (LIVE ARM)

A `build-measurement-harness` instance answering recommendation #1 ("measure the
heavy skills") for the **prose-only** skills whose value is open-ended LLM +
web judgment. It answers: **does `gather-research`'s citation-domain-freshness +
PRIMARY-source verdict framework actually raise grounding precision and
refutation recall over a fair baseline (a strong single Opus pass with no
framework) — by enough to justify its ~3-6x cost?**

This is the **live arm** the cloud session could not run (it needs keys + web).
Unlike the deterministic harnesses (`roundtable`, `variant-analysis`, `persona`,
`supergoal`) whose value-prop is a pure function, `gather-research` has **no
deterministic value-prop surface** — the only way to measure it is to *run it on
a labeled task and score the outcome against an independent oracle*. The A/B
runner (`run_live.py`) is keyed + manual; CI asserts only on the committed
`results.json`.

## 1. Classify the measurement (Phase 0)
- **Unit:** one research claim → `(verdict, cited_urls, confidence)`.
- **Decision under test:** the skill's `references/citation-domain-freshness.md`
  framework — PRIMARY/ADJACENT/OFF-DOMAIN classification, freshness windows, and
  verdict bars (SUPPORTED ≥2 PRIMARY, REFUTED ≥3 PRIMARY, CONTESTED, UNCHARTED) —
  plus the `symmetric-evidentiary-burden` discipline.
- **Success:** per-claim correctness vs the hand-label, AND grounding (a
  SUPPORTED claim's *own cited URL* must actually contain the claim's specifics).
- **Cost asymmetry:** **ASYMMETRIC** — a false SUPPORTED on a fabricated / refuted /
  outdated claim (over-claiming, the exact failure the framework exists to
  prevent) is far worse than a cautious UNCHARTED on a true claim. The primary
  metric (`grounding_precision`) is therefore precision-sensitive.
- **Measurement class:** agent-benchmark, **Mode C** (custom labeled corpus),
  n=15. Mode C / n<50 is small → results are **directional**, reported with
  spread (the `oracle-agent-benchmark.md` subset-gate caveat; the plan mandates
  small fixtures because live calls cost money).

## 2. The oracle — independent ground truth (Phase 1, CARDINAL RULE)
Two independent sources, neither of which is the producer model judging itself:
1. **Hand-curated verdict labels** (oracle type a) — each claim's true disposition
   (`supported` / `not_supported`) was established by the author against a REAL
   primary source, verified 2026-05-31 via Exa/Tavily (see `fixture.json`
   `ground_truth` per claim). `verdict_accuracy`, `refutation_recall`,
   `fabrication_resistance`, `true_recall` are computed against these.
2. **Deterministic term-overlap grounding** (oracle type c) — for every SUPPORTED
   verdict, `run_live.py` fetches the arm's *own* cited URL over plain HTTP (no
   key) and `grade.grounding_passes` checks whether ≥60% of the claim's
   discriminating `grounding_terms` appear. No model judges the producer.

**Anti-circularity guards actually enforced here:**
- The producer (Opus 4.8) never grades its own output; scoring is hand-labels +
  deterministic fetch.
- The fixture claims are **disjoint from the skill's own worked examples**
  (`citation-domain-freshness.md` Ex1-4: hyperpolation / abduction / distance-lever
  / Dada). Reusing those would let the WITH-skill arm read the answers from its
  own framework text — teaching-to-the-test. Verified disjoint.
- Both arms use the **same best model + same hosted web_search tool**; the ONLY
  difference is the system prompt (framework ON vs OFF), so the delta isolates
  the framework, not the model or the search tool.

## 3. Fixture (`fixture.json`) — 15 hand-labeled claims, 4 categories
| Category | n | Expected disposition | What it tests |
|---|---|---|---|
| `true_primary` | 5 | supported | true_recall (no over-correction) + grounding |
| `refuted` | 4 | not_supported | refutation_recall on plausible-but-false claims |
| `outdated` | 3 | not_supported | refutation_recall on was-true-now-false claims |
| `fabricated` | 3 | not_supported | fabrication_resistance (no source exists; adjacent real papers are traps) |

The 3 `fabricated` claims each have a real **adjacent** paper (ReCAP vs fake
"Recursive Context Distillation"; real Constitutional AI vs fake "Constitutional
Scaling Laws"; Google Melodi vs fake "Holographic Memory for Transformers") — so
"confirming" one by citing the adjacent paper is a grounding failure the
deterministic check catches.

## 4. Metrics, A/B, and two operating points (Phase 7)
- **`grounding_precision`** (PRIMARY, precision-sensitive operating point): of all
  claims an arm marked SUPPORTED, the fraction whose cited URL grounds.
- **`refutation_recall`** (recall-sensitive operating point): of `refuted` +
  `outdated` claims (n=7), the fraction correctly NOT marked SUPPORTED.
- **`fabrication_resistance`**: of `fabricated` claims (n=3), fraction NOT marked
  SUPPORTED (inverse hallucination rate).
- **`true_recall`**: of `true_primary` (n=5), fraction marked SUPPORTED (guards
  against the framework over-correcting into refusing true claims).
- **`verdict_accuracy`**: overall agreement with the hand-label disposition.

**A/B:** `with_skill` (framework system prompt) vs `baseline` (strong plain
fact-checker, same model + web_search). N=3 runs, mean+spread.
**Verdict rule** (`grade.decide_verdict`): **keep** if Δgrounding_precision ≥ 0.05;
**fix** if a sub-metric regresses below baseline; **trim** otherwise (framework
not worth its ~5x cost).

## 5. Frozen baseline — the measured answer
<!-- RESULTS_TABLE_START : transcribed from results.json (N=3, model claude-opus-4-8, 2026-05-31). Refresh via run_live.py. -->
Measured 2026-05-31, N=3, `claude-opus-4-8`, n=15 claims, both arms with hosted web_search:

| Metric | baseline (mean) | with_skill (mean) | Δ | spread (both) |
|---|---|---|---|---|
| **grounding_precision** (primary) | 1.00 | 1.00 | **0.00** | 0.0 |
| refutation_recall | 1.00 | 1.00 | 0.00 | 0.0 |
| fabrication_resistance | 1.00 | 1.00 | 0.00 | 0.0 |
| true_recall | 1.00 | 1.00 | 0.00 | 0.0 |
| verdict_accuracy | 1.00 | 1.00 | 0.00 | 0.0 |

**Verdict: `trim` (ceiling-bound).** The freshness/PRIMARY framework produced **no
measurable lift** over a fair baseline because the baseline — a strong frontier
model (Opus 4.8) with web search — **already hits ceiling (1.0)** on every metric,
including the fabricated-claim traps. Δ=0.00 on the primary metric is below the
0.05 ship bar → by the cost rule, the framework's ~5× ceremony is not paid for by
a measurable accuracy gain *on this corpus*.

**The arms DID behave differently** (verified in `runs/` transcripts), the binary
metric just can't reward it: on the 3 fabricated claims the **baseline** answered
`FALSE` while citing real *adjacent* material (e.g. it surfaced the real Lawfare
"Scaling Laws & Claude's Constitution" piece for the fabricated "Constitutional
Scaling Laws" claim — yet still rejected it); the **with_skill** arm answered
`UNCHARTED` with **empty citations** (the framework's "don't manufacture support"
discipline). Both normalize to `not_supported`, so both score 1.0. Notably the
baseline's `FALSE` ("no such paper exists") is arguably a *stronger* verdict than
the framework's `UNCHARTED` for a non-existent paper — a small point AGAINST the
framework's uncharted-first rule on fabricated-source claims.

**Honest caveats (do not over-read this as "the framework is worthless"):**
- **Ceiling / saturation** (the `oracle-agent-benchmark.md` HumanEval caveat): a
  metric saturated at 1.0 for both arms cannot discriminate. A *discriminating*
  fixture would need claims engineered so a strong searching model over-claims
  WITHOUT the freshness/multi-source discipline (subtle CONTESTED cases requiring
  the ≥3-PRIMARY bar; near-current claims inside the 12-month frontier window) —
  much harder to construct and not what this plan's fixture targets.
- **Small n (=15)** → directional only; the per-metric 95% CI on this size is wide.
- What the binary metric does NOT capture and the framework DOES deliver: a
  precise verdict taxonomy (UNCHARTED/CONTESTED/OUTDATED vs a flat TRUE/FALSE) and
  an explicit no-citation-on-unsupported discipline. Those are real qualitative
  differences; they are simply not accuracy gains on this corpus.
<!-- RESULTS_TABLE_END -->

## 6. REAL vs INSTRUMENT (Phase-9 check) — PERFORMED, result is REAL
A perfect 1.0/1.0 tie demands the Phase-9 check (verify-effectiveness's instrument-first gate):
is the tie a real ceiling, or a grader that trivially returns 1.0? Both ruled in:
1. **Scorer proven non-trivial:** `tests/test_gather_research_efficacy.py`
   (`test_grader_instrument_fp_fn_zero`) drives `grade.py` on a tiny synthetic
   fixture with hand-computed expected metrics — it returns grounding_precision
   **0.5** and fabrication_resistance **0.0** on a mixed input, i.e. it CAN and
   does produce non-1.0 values and counts over-claims. The grounding/normalize/
   aggregate functions are pure (no network), so a live delta cannot be a scorer
   artifact.
2. **Tie verified REAL in transcripts:** I read `runs/` for both arms on the
   hard claims. The baseline genuinely rejected every refuted/outdated/fabricated
   claim (`FALSE`/`FALSE (OUTDATED)`) with real citations, and genuinely confirmed
   every true claim (`TRUE` + a grounding-passing arXiv/docs URL). It is not being
   mis-scored — it actually got them right. The tie is a **ceiling effect**, not
   an instrument bug. (Sampled all 10 hard claims × 2 arms; 0 mis-scores.)

Raw per-run transcripts are saved under `runs/` so anyone can re-grade the sample
and reach the same verdict (Phase-9 auditability).

## 7. Truncation audit (Phase 5) + freshness gate (Phase 6)
- **web_search** (hosted, both arms): `max_uses=5` — identical for both arms, so
  any cap is symmetric and does not bias the A/B.
- **grounding fetch**: plain HTTP GET, 25s timeout; a non-200 / JS-only page →
  `grounded=False` (a citation we cannot verify does not count as grounded —
  conservative, never inflates precision).
- **Anthropic API**: `max_tokens=2000` per call (ample for the per-claim JSON).
  `claude-opus-4-8` rejects `temperature`; omitted (residual variance captured by N≥3).
- **Freshness:** `results.json` pins `model`, `fixture_sha`, `run_date`, `n_runs`.
  The CI test warns if the committed `fixture_sha` ≠ the current `fixture.json`
  hash (results stale → rerun `run_live.py`).

## 8. Live arm provenance
- **Keys:** only `ANTHROPIC_API_KEY` (hosted web_search runs on the Anthropic key;
  grounding fetch is keyless). Tavily/Exa keys were unavailable in-env, which is
  why the design uses first-party web_search + plain HTTP — making `run_live.py`
  reproducible for anyone with just an Anthropic key.
- **Cost:** ~`n_claims × 2 arms × n_runs` Opus calls with web_search (~90 at N=3).

## 9. Retired at this fixture (2026-09-04)

This A/B is retired at the current fixture. `run_live.py` prints a notice and refuses a
real run without `--acknowledge-retired-fixture`; `--plan-only` keeps working and the
receipt carries `fixture_status: retired`.

Reason (`docs/research-skills-root-cause.md` §6): both arms score 180/180 on Opus 4.8
(2026-05-31) and on Fable 5.1 (2026-09-03) — 45/45 verdicts correct per run, 5/5
supported records grounded, 0 issues. The arms differ only in vocabulary (UNCHARTED with no
citations vs FALSE with citations on the 3 fabricated claims), which the binary metric does
not score. Two full runs (~180 web-search calls) produced zero bits about the framework:
the fixture has no discriminating power for a searching frontier model of either
generation.

Unchanged: the frozen 2026-05-31 baseline, its committed sample, and the CI gate. Reopen
only with a fixture on which the baseline is below 1.0 (subtle CONTESTED cases, claims
inside the 12-month window) and a label-level accuracy metric so the taxonomy is graded.
