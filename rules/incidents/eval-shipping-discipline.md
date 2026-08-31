---
paths:
  - "**/rules/eval-shipping-discipline.md"
  - "**/rules/incidents/eval-shipping-discipline.md"
---

# Eval Shipping Discipline: Incident Narratives

Extracted from `rules/eval-shipping-discipline.md`. The parent rule
keeps invariants, procedures, guards, and recovery lines as-is; full
incident narratives that calibrate each one live here.

---

## 2026-05-14 Phase A regression — default-flip without re-baselining sibling fixtures
**Anchors:** `default_flips_must_measure_every_affected_fixture`

Shipped `RESOLVER_DROP_FUZZY_JANUSIAN_CHAINS` default-on globally based
on flask-adversarial evidence (0/11 precision in the ambiguous-fuzzy
bucket → pure-win). Did not re-measure PSM Rust before merging
PR #315.

Re-baseline during Phase E surfaced **-2.2pp F1 on assetman** (29
legit Rust trait dispatches killed by the gate). Required Phase E
(PR #320) to recover by scoping the default to Python only.

**Cost.** ~30 turns of diagnosis + an extra recovery PR. A 5-minute
re-baseline of PSM Rust before merging PR #315 would have caught it.

**Lesson encoded in the parent rule.** When shipping a default-flip
PR that touches a resolver, extractor, scoring rule, or any other
knob that applies across languages/fixtures, re-baseline every
documented adversarial + production fixture (per `fixtures.json`
scope) on a build with the change applied. Include the per-fixture
deltas in the PR description. If a fixture regresses, scope the
change to the language/condition where it wins.

---

## 2026-05-17/18 memory-search arc — pre-implementation retirement on extrapolation
**Anchors:** `pre_implementation_retirement_on_extrapolation_requires_axis_audit`,
`pre_implementation_retirement_reversed_by_pushback`

Two retirements in one session arc, both reversed by adversarial
user pushback that prompted the empirical run:

### Phase E (Sonnet listwise reranking)
Retired pre-implementation citing *"Sonnet would inherit the
content-only substrate headwind from Phase D's rerank-2 loss
(ΔMRR -0.045)."* That argument conflated 3 changed axes:

| Axis      | Phase D (rerank-2) | Phase E (Sonnet listwise) |
|-----------|--------------------|---------------------------|
| Model     | Voyage rerank-2    | Sonnet 4.6 (orders of magnitude more capable) |
| Mechanism | pointwise          | listwise (one comparative call vs 15 isolated) |
| Substrate | 500-char content only | title + path + date + 15-line content |

User pushback prompted the actual experiment (PR #408): listwise
shipped at **HR@5 +0.040 CI [+0.010, +0.081]**, reversing the
retirement. Empirical cost was **$4 + 10 min**.

### Phase A4-lite (user labeling)
Retired claiming "needs user labels." The "needs" framing excluded
the behavioral-label path — session JSONLs already record what file
the user read after each `memory_search`. User pushback ("you are
taking the easy way out") surfaced the alternative; PR #404 shipped
with **n=41 from session JSONLs, zero user input**.

**Lesson encoded.** When ≥2 axes differ between candidate X and
analog Y, and the empirical run cost is bounded (< 1 hr wall + < $20
API + no destructive side effects), running the experiment is
required. The retirement is not authorized by the analog evidence
alone.

---

## 2026-05-18 memory-search PR #423 — LLM-judge candidate pool contamination
**Anchors:** `llm_judge_candidate_pool_must_not_come_from_engine_under_test`

127 unlabeled queries were Sonnet-relabeled using each query's engine
top-15 candidates. 112/127 (88%) got ≥1 confirmed label.

Blinded re-adjudication on BM25 top-50 + 30 random pool (PR #426)
showed **49/50 (98%) drop rate** — Sonnet rejected almost all
original picks when shown a pool independent of the engine. The
"A-" grade was retracted.

**Mechanism.** When the LLM-judge sees only the engine's pre-filtered
top-K as candidates, it rubber-stamps the engine's existing ranking
rather than making an independent quality judgment. This is
selection-on-the-dependent-variable: the oracle is the engine's
output filtered through "is this plausible?" — not "is this
correct?" The resulting labels biased the n=233 grade by ~50pp.

**Lesson encoded.** Candidate pool for LLM-judge labeling must come
from a different retrieval primitive (BM25-only top-50, random
samples, separate retrieval stack, or human-validated seeds). Strip
provenance fields. Shuffle to remove rank ordering. Run a blinded
re-adjudication on 30-50 queries to estimate the bias floor — drop
rate <30% indicates valid labels, >30% indicates rubber-stamping.

---

## 2026-05-18 memory-search — behavioral oracle selection bias
**Anchors:** `behavioral_signals_can_still_be_selection_biased`

n=114 oracle from Read/Edit/Write/Bash navigation showed
**HR@5=0.956 (A)**. Expanding via clean Sonnet relabel (independent
pool) + Grep/Glob signals + widened window/threshold to n=171 showed
**HR@5=0.854 (B+)** — a -0.10 drop on the same engine.

**Mechanism.** Signals like "user navigated to file F after searching
Q" look behavioral (not LLM-judged), but they're still selection-
biased: users only follow through when the engine surfaced something
plausible. Queries where the engine returned nothing useful produce
NO follow-through, so they don't enter the oracle. The "harder"
queries (no behavioral follow-through because user gave up) are real
production load that the n=114 oracle never captured.

**Lesson encoded.** Report grades on BOTH easy-skewed and expanded
subsets. The publishable grade is the expanded measurement. Easy-
skewed is fine as a context number but the headline grade must use
the unbiased substrate.

---

## 2026-05-18 memory-search path-to-A push — lever-class exhaustion
**Anchors:** `three_consecutive_regressions_in_same_lever_class_is_a_stop_signal`

After Phase E shipped Sonnet listwise (+0.040 HR@5), two consecutive
attempts to push further within the same lever class regressed:

| Attempt | Mechanism | Result |
|---------|-----------|--------|
| PR #428 | MMR diversity over listwise output | **-0.029 HR@5** |
| PR #429 | candidate_k=100 (broader pool) | **-0.012 HR@5** |

Both were "incremental tuning of post-listwise output." Two
consecutive failures in the same class signaled the remaining levers
in that class (query expansion via embeddings, per-query model swap)
would likely also regress. **Tasks #37 and #38 were retired
un-attempted with documented rationale.**

**Lesson encoded.** Two consecutive same-class regressions is a stop
signal. Propose structural alternatives (different reranker model
class, different retrieval primitive, different substrate) — these
are multi-day investigations, NOT single-session tweaks. Publish the
honest grade ceiling and recommend stopping further same-class
tuning until structural change is investigated.

---

## 2026-06-11 SweRank pre-filter pilot — depth-confounded delta + order-mismatched truncation
**Anchors:** `scoring_substrate_depth_must_match_across_arms`,
`budget_gated_arms_must_share_instance_order_or_pre_pinned_subset`

Three-arm Loc-Bench pilot (code-graph `experiment/swerank-prefilter-pilot`,
finding doc `bench/accuracy/baselines/2026-06-11-swerank-prefilter-pilot.md`):
A = `code_localize_agent` baseline, B = agent + retrieval candidates,
C = code-search retrieval only.

**Depth confound.** Arm C's class/func hits were scored against the
parent.name blob of all k=50 retrieved chunks; arms A/B were scored
against the agent's top-10 entity output. func Δ(C−A) measured **+30.8pp
with 95% CI [+7.7, +53.8] excluding zero** — a result that would have
been a landmark DONE — but a 50-name substrate mechanically contains
ground-truth function names more often than a 10-entity one, so the
delta conflates retrieval quality with scoring depth. Per-rank names
were NOT persisted, so matched-depth re-scoring required a fresh ~$8
run; verdict forced to BLOCKED ON MEASUREMENT. file_hit (C capped at
top-15 unique files) stayed depth-comparable and is the clean signal
(13/13).

**Order-mismatched truncation.** Both arms were gated (A: $4.50
token-metered; C: $8 Voyage ceiling) and both truncated as designed —
but A processed the 50-instance pin in flat parquet order while C
processed it grouped by repo (a per-repo index-sharing optimization).
The truncated prefixes barely overlapped: 22 ∩ 16 = **9 paired** of a
50-instance design. A $1, 4-instance arm-A extension onto C's indexed
set recovered paired n=13.

**Also encoded:** budget gates must meter the units they cap. The
harness's flat $0.05/query estimate underbooked a 989K-input-token
instance ~20× (actual ~$1.02); the gate was blind until switched to
token-metered cost (Haiku 4.5 $1/$5 per MTok).

**Cost.** The confound cost the pilot its primary verdict (~$8
follow-up to resolve); the order mismatch cost ~44% of designed paired
power (recovered for $1). Both are zero-cost to prevent at design time:
matched scoring K + persisted per-rank results + shared processing
order (or a pre-pinned subset every arm completes).


<!-- extracted 2026-08-01: ambient-context reduction -->

## thresholds-like-ship-if-mrr-0-005-are-operational

```
WHY: thresholds like "ship if Δ MRR > +0.005" are operational rules of
     thumb. They assume the noise floor is below the threshold; they
     don't measure it. A +0.0144 delta might exceed +0.005 but have a
     95% CI that includes zero (in which case the +0.0144 could be
     noise across query draws). 2026-05-06 D1: +0.0144 cleared the
     +0.005 threshold AND the bootstrap CI [+0.0033, +0.0278] excluded
     zero — but the second test is what made the verdict trustworthy.
```

## metric-a-metric-b-by-without-per-query-data

```
WHY: "metric A > metric B by ε" without per-query data is an
     observation, not a finding. Bootstrap CI on per-query data is
     the cheapest way to convert observation → finding. Free if the
     eval script already saves per-query output; ~10 seconds CPU
     otherwise.
```

## rerank-off-shows-fusion-stage-behavior-rerank-on-shows

```
WHY: rerank-off shows fusion-stage behavior; rerank-on shows the
     production stack. A delta that exists at rerank-off can be
     equalized OR amplified by rerank — the only way to know is to
     test under both. Shipping on rerank-off evidence alone risks
     production rank-quality not moving as predicted (or moving in
     the opposite direction).
```

## a-change-to-a-resolver-extractor-scoring-default-that

```
WHY: a change to a resolver/extractor/scoring default that affects
     multiple fixtures needs evidence from ALL of them. A default
     that wins on fixture A can regress fixture B.
```

## 2026-05-14-phase-a-regression-pr-315-recovery

```
INCIDENT 2026-05-14 Phase A regression (PR #315 → recovery PR #320,
     -2.2pp F1 on assetman from a flask-validated default-flip).
     Full narrative: rules/incidents/eval-shipping-discipline.md.
PROCEDURE: when shipping a default-flip PR that touches a knob
     applying across languages/fixtures, re-baseline every
     documented adversarial + production fixture (per
     fixtures.json scope). Include per-fixture deltas in the PR.
     If a fixture regresses, scope the change to the
     language/condition where it wins.
```

## no-opt-in-opt-in-defaults-are-a-non

```
WHY NO OPT-IN: opt-in defaults are a non-decision. The user does
not remember to enable them; the lever's value is never realized;
the experimental result becomes shelfware. User feedback
2026-05-18: "I hate opt-in, stop doing all of this work just to
flip flop and say opt-in. I'll never remember to do that. We need
to either flip it on or not. This needs to be the approach for any
of the work that we do."
```

## documented-2026-05-18-after-sonnet-listwise-pr-408

```
WHY: Documented 2026-05-18 after Sonnet listwise PR #408 + #410 +
corpus-expansion PR #409 shipped as opt-in canary
(MEMORY_SEARCH_RERANKER=sonnet_listwise) on favorable mean lift
but sub-clean CI. User feedback: opt-in defaults are not used;
the experimental work is wasted unless the default flips.
```

## retire-x-because-analog-y-lost-is-an-extrapolation

```
WHY: "retire X because analog Y lost" is an EXTRAPOLATION. If
     candidate and analog differ on multiple axes (model, mechanism,
     input substrate, corpus, prompt format, metric), the
     extrapolation has no anchor and the retirement is likely wrong.
INCIDENTS 2026-05-17/18 memory-search arc: Phase E Sonnet listwise
     and Phase A4-lite labeling — both retired pre-implementation
     then reversed by user pushback. PR #408 (+0.040 HR@5) and
     PR #404 (n=41 from session JSONLs). Full narrative with axis
     decomposition: rules/incidents/eval-shipping-discipline.md.
```

## when-the-llm-judge-sees-only-the-engine-s

```
WHY: when the LLM-judge sees only the engine's pre-filtered top-K
     as candidates, it rubber-stamps the engine's ranking instead
     of making an independent quality judgment. Selection-on-the-
     dependent-variable: the oracle is the engine's output filtered
     through "is this plausible?" not "is this correct?"
```

## 2026-05-18-memory-search-pr-423-contaminated-pool

```
INCIDENT 2026-05-18 memory-search PR #423: contaminated pool gave
     88% confirmed-label rate; blinded re-adjudication on BM25 +
     random pool (PR #426) dropped 98% of those labels, retracting
     the "A-" grade. ~50pp bias on n=233. Full narrative:
     rules/incidents/eval-shipping-discipline.md.
```

## when-an-llm-applies-a-subjective-extraction-grading-rubric

```
WHY: when an LLM applies a subjective extraction/grading rubric (count
     the load-bearing lessons, count the findings, rate the items), the
     ABSOLUTE COUNT is a function of the rater's granularity, not just
     the artifact. The same input yields ~2.5x different counts across
     providers because each splits "one finding" into a different number
     of lessons. A single-rater count is therefore noise-dominated as a
     headline metric. What IS stable across raters/providers: (a) the
     DIRECTION of a comparison (A>B), (b) the RATIO between two arms
     scored by the SAME rater, and (c) the FINDING SET (which distinct
     items were surfaced, verified against source).
```

## 2026-06-21-distill-vs-mega-distill-head-to

```
INCIDENT 2026-06-21 distill-vs-mega-distill head-to-head: a 5-compaction
     session scored 6 lessons (Opus, Arm A) vs 17 (GPT-5.5-pro, same Arm A)
     — a 2.8x rater spread on IDENTICAL input. But the C/A ratio held
     across providers (Opus 2.8x, GPT 2.4x). The early single-rater
     "multiplier" was inflated by a low-balled denominator; only the
     cross-provider ratio + the grep-verified head-only finding SET were
     trustworthy. A Sonnet rater could not even be used — it context-
     exhausted at 2000/9551 lines (see platform-changelog model-read-budget).
```

## the-two-oracle-failures-below-are-about-where-the

```
WHY: the two oracle failures below are about WHERE the candidates came from
     (contamination) and WHICH ones entered (selection bias). This third one is
     about WHEN each FIELD was written. An artifact that gets CARRIED FORWARD
     edition to edition -- because nothing regenerates it -- accumulates fields
     populated at different times from different sources. It then disagrees with
     ITSELF, and reproducing it becomes an UNACHIEVABLE target: for some fields,
     matching it would mean reproducing an error.
THE TRAP: it looks like a perfect oracle. It is the real artifact the real
     consumers really read, so "reproduce it" feels like the obvious bar. Every
     field disagreement then reads as YOUR formula being wrong, and you go
     hunting N formulas when the target itself is the defect.
```

## 2026-07-31-mcp-servers-935-users-v2-json

```
WHY: 2026-07-31 mcp-servers #935, users_v2.json -- 8 readers, ZERO writers, so
every edition carried the last one forward. Validating a rebuild against it gave
15 of 42 fields >=95% and sent me hunting 27 formulas. Measured instead:
  * 221 of 892 rows were COPIED and could not disagree (the denominator was 25%
    pre-agreed). Re-scored on the 671 computed rows: 4 correct, 24 partial, 3
    never right.
  * `ot_reqs` agreed on EXACTLY 221 -- the copied count -- so every computed row
    was wrong. `arch_score`, always-null by design, sat at the same 221, proving
    221 was the floor.
  * `terminals` for one user read {'Apple_Terminal': 13} while the lake held
    iTerm.app at 903,857 events / 940 sessions and NO Apple_Terminal at all.
    Across the 98 users with >1,000 requests, terminal_events/ot_reqs spanned
    60,611x (0.000091 to 5.5) -- a ratio that cannot vary that much from one
    source at one time.
I ALSO overgeneralized twice from single confirmed probes: "31 formulas are
UNCHARTED" (largely one wrong table), then "ONE wrong table, not 31 formulas"
(the swap fixed 4 of 30: 11 improved, 12 worsened, 19 unchanged). Confirming a
mechanism on ONE field is not confirming it explains the SET.
```

## signals-like-user-navigated-to-file-f-after-searching

```
WHY: signals like "user navigated to file F after searching Q"
     look behavioral (not LLM-judged) but are still selection-
     biased: users only follow through when the engine surfaced
     something plausible. Queries where the engine returned nothing
     useful produce NO follow-through, so they don't enter the
     oracle. Systematically biased toward "easy" queries.
```

## 2026-05-18-memory-search-n-114-navigation-oracle

```
INCIDENT 2026-05-18 memory-search: n=114 navigation oracle showed
     HR@5=0.956 (A); n=171 expanded oracle (clean Sonnet relabel +
     Grep/Glob signals) showed HR@5=0.854 (B+). -0.10 drop on the
     same engine. Full narrative: rules/incidents/eval-shipping-
     discipline.md.
```

## if-a-lever-class-reranking-stage-modifications-candidate

```
WHY: if a lever class (reranking-stage modifications, candidate-
     pool tweaks, dispatch-threshold tuning) yields regressions on
     multiple sequential attempts, the lever class is structurally
     saturated on the current engine state. Continuing to tune is
     noise-fitting.
```

## 2026-05-18-memory-search-path-to-a-push

```
INCIDENT 2026-05-18 memory-search path-to-A push: MMR diversity
     (PR #428, -0.029 HR@5) and candidate_k=100 (PR #429, -0.012
     HR@5) both regressed. Tasks #37, #38 retired un-attempted with
     documented rationale. Full narrative: rules/incidents/eval-
     shipping-discipline.md.
```

## a-hit-metric-scored-by-substring-containment-is-mechanically

```
WHY: a hit metric scored by substring/containment is mechanically a
     function of how MUCH text each arm exposes to the scorer. Scoring
     arm A on its top-10 entities while scoring arm C on a 50-name
     retrieval blob hands C ~5x the chances to contain a ground-truth
     name — the delta measures depth, not quality.
```

## 2026-06-11-swerank-pilot-func-c-a-30

```
INCIDENT 2026-06-11 SweRank pilot: func Δ(C−A) +30.8pp CI [+7.7,+53.8]
     EXCLUDED zero but was depth-confounded → verdict forced to
     BLOCKED instead of DONE; per-rank names weren't persisted, so
     matched-depth re-scoring required a fresh ~$8 run. Full:
     rules/incidents/eval-shipping-discipline.md.
FIX: cap every arm's scoring substrate at the SAME K before launch,
     and persist per-rank results so any depth can be re-scored
     offline. Persist-at-full-K, score-at-matched-K.
```

## budget-ceiling-gates-truncate-runs-two-arms-that-process

```
WHY: budget/ceiling gates truncate runs. Two arms that process the
     same pin in DIFFERENT orders (flat corpus order vs grouped-by-repo
     order) truncate to different prefixes — the paired intersection
     collapses far below either arm's n.
```

## 2026-06-11-swerank-pilot-a-22-attempts-flat

```
INCIDENT 2026-06-11 SweRank pilot: A (22 attempts, flat order) ∩
     C (16, repo-grouped) = 9 paired of a 50-instance design; a $1
     4-instance extension recovered n=13. Full narrative:
     rules/incidents/eval-shipping-discipline.md.
FIX: either identical processing order across arms, or pre-pin a
     subset small enough that every arm completes it under its gate.
     Also meter gates in the SAME UNITS they cap (token-metered, not
     flat per-query estimates — the flat $0.05 estimate underbooked a
     989K-token instance 20x and would have let spend run blind).
```

## a-report-records-what-a-measurement-found-nothing-records

```
WHY: a report records what a measurement FOUND; nothing records what PRODUCED it.
     The number is then un-reproducible, un-re-runnable, and — worst —
     un-INVALIDATABLE: a later engine/prompt/corpus change silently voids it while
     the report still reads as current.
```

## 2026-07-30-four-artifacts-one-measurement-family-three

```
INCIDENT 2026-07-30 — four artifacts, one measurement family, three permanently lost:
  SYS_SESSION_V2 prompt (certified recall 0.640 / FPR 0.352, n=1,278) — LOST; only a
    report section HEADING survives. Moot regardless: the cert is a `sonnet-4-6`
    artifact and production moved to Sonnet 5, so the instrument changed under it.
  the FIX2 clause (measured 0.907 / 0.023) — LOST; results JSON survives, treatment
    does not. Void regardless: that harness hand-built a judge header diverging from
    the deployed construction.
  the paired A/B harness — RECOVERED from a session TRANSCRIPT and committed
    (mcp-servers #916). Recovery was luck, not a retention policy.
  the methodology finding that INVALIDATED FIX2 — existed only in a transcript.
COST: two recommendations shipped then retracted in one session, both re-deriving
     decisions the org had already made three weeks earlier.
```
