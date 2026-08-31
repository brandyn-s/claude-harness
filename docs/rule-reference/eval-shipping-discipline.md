---
paths:
  - "**/harness/**"
  - "**/eval/**"
  - "**/evals/**"
  - "**/evaluation/**"
  - "**/evaluations/**"
  - "**/tests/**"
  - "**/fixtures/**"
  - "**/metrics/**"
  - "**/*eval*.py"
  - "**/*eval*.yaml"
  - "**/*eval*.yml"
  - "**/*baseline*.json"
---

@rule eval_shipping_discipline
@version 2026-05-06
@scope every decision to ship a default change driven by an eval metric (MRR, HR@1, recall, precision, F1, latency, accuracy); every "this beats current by X" claim that affects production behavior

# ─── INVARIANTS (always-true) ───

INVARIANT policy_threshold_is_not_a_significance_test
  # WHY: thresholds like "ship if Δ MRR > +0.005" are operational rules of
  #   Full: incidents#thresholds-like-ship-if-mrr-0-005-are-operational

INVARIANT ship_decisions_on_metric_deltas_require_significance_evidence
  # WHY: "metric A > metric B by ε" without per-query data is an
  #   Full: incidents#metric-a-metric-b-by-without-per-query-data

INVARIANT both_off_mode_and_production_mode_must_validate
  # WHY: rerank-off shows fusion-stage behavior; rerank-on shows the
  #   Full: incidents#rerank-off-shows-fusion-stage-behavior-rerank-on-shows

INVARIANT default_flips_must_measure_every_affected_fixture
  # WHY: a change to a resolver/extractor/scoring default that affects
  #   Full: incidents#a-change-to-a-resolver-extractor-scoring-default-that
  # INCIDENT 2026-05-14 Phase A regression (PR #315 → recovery PR #320,
  #   Full: incidents#2026-05-14-phase-a-regression-pr-315-recovery

# ─── PROCEDURE: before shipping any eval-driven default change ───

STEP_1 verify per-query data is saved alongside aggregate metrics:
  - eval script must output {query, expected, rank, rr/hit, score?} per query
  - if not: fix the eval script first; do not ship from aggregate-only data

STEP_2 compute paired bootstrap CI on the metric delta:
  - resample queries with replacement (n_bootstraps ≥ 10000)
  - compute Δ metric per resample
  - report 95% CI [lo, hi]
  - cite the script that produced the CI in the PR description

STEP_3 ship gate — BINARY: ship default-on OR retire. NO opt-in / canary
        intermediate state.
  - CI excludes zero in the favorable direction → SHIP DEFAULT-ON
    (pending production-stack verification)
  - CI includes zero AND mean delta is unfavorable → RETIRE
  - CI includes zero AND mean delta is favorable on the primary
    metric → SHIP DEFAULT-ON. The point-estimate signal is the
    operative information; sub-clean CI on n=99-100 corpora reflects
    sample-size limits, not absence of signal. Document the CI
    explicitly in the PR; future sessions can re-tighten with a larger
    golden if the lift turns out to be noise.
  # WHY NO OPT-IN: opt-in defaults are a non-decision. The user does
  #   Full: incidents#no-opt-in-opt-in-defaults-are-a-non

STEP_4 production-stack verification (when applicable):
  - if eval was at rerank=off but production is rerank=on: re-run eval
    at rerank=on and verify the ordering preserves
  - if production-stack verification is environmentally blocked (API
    latency, rate limit), DOCUMENT the block; do not ship without it

STEP_5 PR description must include:
  - point estimate, 95% CI bounds, n_bootstraps
  - "CI excludes zero" verdict line
  - which production-stack mode was tested (or noted as blocked)

# ─── USER OVERRIDE POLICY ───

GUARD pattern="we already cleared the policy threshold, ship it":
  REFUSE. Policy threshold is not a significance test. Run the bootstrap
  CI on existing per-query data (free) before shipping. NO EXCEPTIONS.

GUARD pattern="bootstrap is overkill, the delta is large":
  REFUSE for production-default changes. The harness is already built
  (10K resamples, ~10 sec on a 200-query holdout). The cost of computing
  it is trivial; the cost of shipping a default that turns out to be
  noise is not. NO EXCEPTIONS for ship decisions.

GUARD pattern="just trust the rerank=off result, sonnet won't matter":
  REFUSE. Sonnet reranks the top-15 hybrid candidates; the set of
  candidates differs between weight settings. Sonnet may equalize OR
  amplify the off-mode delta. The only way to know is to test it.
  EXCEPTIONS: only if rerank=off is the actual production mode (e.g.,
  when sonnet is disabled by env or by policy).

GUARD pattern="API throughput blocks production-stack test, ship anyway":
  REFUSE. Document the block. Defer the ship until the production-stack
  test runs cleanly. The off-mode result is captured for next session;
  no urgency justifies shipping past the gate.
  EXCEPTIONS: a separate explicit user authorization that names the
  specific risk being taken on.

GUARD pattern="significance test costs API tokens, skip it":
  REFUSE. Bootstrap CI is computed locally on per-query data (no API
  calls). Per-query data should already be saved by the eval script
  (see eval-shipping-discipline procedure step 1). NO EXCEPTIONS.

GUARD pattern="ship as opt-in canary, let users enable when they want":
  REFUSE. Opt-in is a non-decision; the user does not enable it; the
  lever's value is never realized. The decision is binary: flip the
  default ON or RETIRE. Sub-clean CI on n=99-100 is a sample-size
  limit, not a signal-absence proof — favorable point estimates on
  the primary metric are sufficient to flip the default with the CI
  documented in the PR. Add the deferred-default-flip pattern to the
  worst-offender list during /retro and recover by flipping the
  default. NO EXCEPTIONS.
  # WHY: Documented 2026-05-18 after Sonnet listwise PR #408 + #410 +
  #   Full: incidents#documented-2026-05-18-after-sonnet-listwise-pr-408

# ─── FAILURE MODES to recognise ───

FAILURE shipped_default_on_policy_threshold_alone:
  RECOVERY: revert. Re-run eval with per-query data dump. Compute
  bootstrap CI. If CI includes zero, the original ship was a noise-driven
  decision. If CI excludes zero, restore the ship and document the
  bootstrap evidence retroactively.

FAILURE shipped_at_rerank_off_then_rerank_on_inverted:
  RECOVERY: revert. The rerank-off delta was real but rerank-on
  consumed it (or inverted it). Production rank-quality didn't move as
  predicted. Document the inversion as a finding for future fusion
  retunes.

FAILURE bootstrap_CI_run_on_aggregate_data_no_per_query:
  SYMPTOM: bootstrap CI script fails with "no per-query data available";
  forces a fresh API re-run.
  RECOVERY: this is the Pattern 3 gap from 2026-05-06. Future eval
  scripts must save per-query JSON by default — see code-search PR #131.
  Backfill any older eval scripts on next touch.

# ─── EXAMPLES ───

GOOD: "(0.60, 0.40) wins (0.65, 0.35) by Δ=+0.0144 MRR. Bootstrap CI
[+0.0033, +0.0278] excludes zero. Pass 2 (rerank=on) confirms ordering
preserves. Shipping default flip in PR #N."

BAD: "(0.60, 0.40) wins (0.65, 0.35) by Δ=+0.0144 MRR which clears the
+0.005 ship threshold. Shipping."  ← clears threshold but no significance
test, no rerank-on verification.

BAD: "Eval shows X beats Y by 3pp on average."  ← no CI, no per-query
data cited, no falsifier.

# ─── INTEGRATION ───

This rule pairs with:
  - `verify-effectiveness.md` (validate-to-improve checklist; bootstrap CI
    is the rigor under "thresholds/heuristics" question)
  - `verify-instrument-before-fix.md` (verify the harness produces correct
    per-query data before trusting its CI)
  - `compare-by-need.md` (recommendation step requires evidence; bootstrap
    CI is the form that evidence takes for ranking metrics)

# ─── PROCEDURE: before retiring an experiment pre-implementation ───

INVARIANT pre_implementation_retirement_on_extrapolation_requires_axis_audit
  # WHY: "retire X because analog Y lost" is an EXTRAPOLATION. If
  #   Full: incidents#retire-x-because-analog-y-lost-is-an-extrapolation

STEP_1 identify the candidate retirement and the cited analog evidence
        - "We should retire X because Y showed Z."

STEP_2 enumerate the axes on which X and Y differ:
        - Model / version (e.g., rerank-2 vs Sonnet 4.6)
        - Mechanism (pointwise vs listwise; cross-encoder vs LLM-judge)
        - Input substrate (truncated content vs metadata-rich prompt)
        - Corpus (this codebase vs another)
        - Metric definition (MRR vs Acc@10 vs F1)
        - Prompt / interaction format
        - Source of labels (hand-curated vs behavioral vs LLM-judged)

STEP_3 IF ≥2 axes differ AND the empirical run cost is bounded
        (< 1 hr wall + < $20 API + no destructive side effects)
        → run the experiment. The retirement is not authorized by
        the analog evidence alone.

STEP_4 IF only 1 axis differs (e.g., same model, same mechanism,
        only metric changed) → extrapolation has a stronger anchor.
        Retirement may be authorized; document the axis explicitly.

STEP_5 IF retirement is authorized, the retirement memo MUST name the
        single axis that anchors the extrapolation. "Substrate" without
        decomposition into model/mechanism/input is NOT sufficient.

STEP_6 BEFORE finalizing retirement, run a 5-minute audit for adjacent
        / analog work in sibling repos or topic files:
          grep / memory_search for "<mechanism name> reranker"
          grep / memory_search for "<lever class> A/B"
        If a sibling repo or prior session has shipped the candidate
        mechanism on a different substrate, the substrate-extrapolation
        retirement is invalid and the empirical run is required.

GUARD pattern="we already tested the analog, the substrate is the same":
  REFUSE substrate identity claim without an explicit axis enumeration.
  Decompose substrate into model + mechanism + input + corpus + metric +
  prompt. If ≥2 components differ, the substrate isn't the same.
  NO EXCEPTIONS for pre-implementation retirement decisions.

GUARD pattern="the experiment is expensive, retire without running":
  EVALUATE the actual cost. < 1 hr wall + < $20 API + no destructive
  side effects is NOT expensive in any production-grade engineering
  workflow. "Expensive" claims must cite the measured cost; estimates
  inflated to justify retirement are the documented failure mode.

GUARD pattern="needs <external input> we don't have":
  RUN a 5-minute audit for whether the input is available from a
  different source (session JSONLs / git history / existing logs /
  behavioral traces / sibling-repo data / prior captures). Many
  "needs user input" framings collapse on inspection.

FAILURE pre_implementation_retirement_reversed_by_pushback:
  # 2 instances in one session arc, 2026-05-17/18 — full narrative:
  # rules/incidents/eval-shipping-discipline.md.
  RECOVERY: when adversarial pushback ("you're taking the easy way
  out", "have you considered X?") prompts an experiment that ships,
  document the retirement-memo failure as evidence the extrapolation
  was unanchored. Add the missed axis decomposition or missed
  alternative source to the rule's example list.

# ─── PROCEDURE: LLM-judge oracle candidate pool must be independent of the engine being graded ───

INVARIANT llm_judge_candidate_pool_must_not_come_from_engine_under_test
  # WHY: when the LLM-judge sees only the engine's pre-filtered top-K
  #   Full: incidents#when-the-llm-judge-sees-only-the-engine-s
  # INCIDENT 2026-05-18 memory-search PR #423: contaminated pool gave
  #   Full: incidents#2026-05-18-memory-search-pr-423-contaminated-pool

STEP_1 identify the candidate source for LLM-judge labeling:
  - If candidates come from the engine being graded (its top-K, its
    reranker output, its boosted fusion) → STOP. Switch candidate pool.

STEP_2 build a candidate pool that does NOT come from the engine:
  - BM25-only top-50 from the corpus (different retrieval primitive)
  - Random in-corpus samples (forces negative examples)
  - Separate retrieval stack (different embedding model, different
    reranker)
  - Human-validated seed labels

STEP_3 shuffle the pool to remove any incidental rank ordering before
       presenting to the LLM-judge.

STEP_4 strip provenance fields (rank, score, source attribution) from
       the candidates shown to the LLM-judge. Show only title +
       content. The LLM-judge must reason from content alone.

STEP_5 before publishing labels, run a blinded re-adjudication on a
       30-50 query sample to estimate the bias floor. A drop rate <30%
       indicates the labels are valid. >30% means the LLM-judge was
       rubber-stamping and the labels are artifact.

GUARD pattern="just LLM-judge the engine's outputs, that's the cheapest
  candidate source":
  REFUSE. The candidates the engine surfaces are exactly the candidates
  the metric is supposed to evaluate the engine's ability to surface.
  Using them as the oracle's input is structurally tautological.
  NO EXCEPTIONS for grade-bearing measurements.

GUARD pattern="the LLM-judge has a strict prompt, it won't rubber-stamp":
  REFUSE that argument as evidence. Sonnet's strict prompt in PR #423
  rejected 11% of queries (Sonnet found no good candidate). Under
  blinding, the SAME prompt rejected 98% of the originally-confirmed
  labels — the strict prompt's strictness was relative to the engine's
  pre-filtered pool, not absolute. Strict prompts on contaminated pools
  produce confidently-wrong labels at scale. NO EXCEPTIONS.

GUARD pattern="we have to use the engine's output because building a
  disjoint pool is expensive":
  EVALUATE: BM25-only top-50 is one SQL query per labeling. Random
  samples are one query. Both cost essentially zero. "Expensive" claims
  must cite actual measurement. NO EXCEPTIONS for grade-bearing
  measurements.

# ─── PROCEDURE: LLM-as-rater COUNT is provider-dependent — gate on ratio/set, not count ───

INVARIANT llm_rater_absolute_count_is_not_a_stable_metric
  # WHY: when an LLM applies a subjective extraction/grading rubric (count
  #   Full: incidents#when-an-llm-applies-a-subjective-extraction-grading-rubric
  # INCIDENT 2026-06-21 distill-vs-mega-distill head-to-head: a 5-compaction
  #   Full: incidents#2026-06-21-distill-vs-mega-distill-head-to

STEP_1 never publish "X found N lessons/findings" as a comparative headline.
       The count is rater-dependent. Publish the RATIO (A/B by the same rater)
       and the DIRECTION.

STEP_2 for a load-bearing comparison, confirm the result with a SECOND rater
       from a DIFFERENT PROVIDER (not just a different model of the same
       family — same-vendor models share training and correlate). If the
       direction/ratio reproduces cross-provider, it is real; if only the
       absolute count moves, that is expected granularity variance.

STEP_3 ground the FINDING SET mechanically (grep the cited evidence against
       source), not by trusting either rater's enumeration — the set is the
       durable artifact; the count is not.

GUARD pattern="rater found N vs M, that's the result" or "the count went up,
  ship it":
  REFUSE a bare count comparison from one rater. Counts swing ~2.5x by
  provider on the same input. Report the same-rater RATIO + a cross-PROVIDER
  confirmation + the grep-verified finding SET. NO EXCEPTIONS for a
  comparative claim that informs a decision.

GUARD pattern="use a different model as the second rater" (reaching for a
  same-family model like Sonnet for an Opus run):
  EVALUATE: a different PROVIDER (OpenAI/GPT, etc.) is the real independence
  control — same-vendor models correlate. Also confirm the second rater can
  hold the input: large condensed slices (>~9K lines) context-exhaust Sonnet;
  route to a large-context model (Opus / GPT-5.5-pro). NO EXCEPTIONS for
  load-bearing comparative measurements.

# ─── PROCEDURE: a CARRIED-FORWARD artifact is not an oracle until proven self-consistent ───

INVARIANT an_artifact_assembled_over_TIME_can_disagree_with_ITSELF
  # WHY: the two oracle failures below are about WHERE the candidates came from
  #   Full: incidents#the-two-oracle-failures-below-are-about-where-the

STEP_1 before treating any carried-forward artifact as an oracle, TEST IT AGAINST
        ITSELF. Pick two fields that must co-vary (events vs sessions, cost vs
        requests, count vs distinct-count) and compute their RATIO per row. A ratio
        that should be roughly stable and instead spans orders of magnitude means the
        fields were not written at the same time or from the same source.
STEP_2 separate the COPIED rows from the COMPUTED ones before scoring anything. A
        producer that copies a row when it has no input data creates rows that CANNOT
        disagree, so an aggregate "N of M fields agree" is scored against a
        pre-agreed denominator. Score against the COMPUTED subset.
STEP_3 look for the FLOOR. A field whose agreement count equals the copied-row count
        exactly is not slightly wrong -- EVERY row it computed is wrong. Cross-check
        with a field you KNOW is never computed (an always-null one): if both sit at
        the same number, that number is the never-correct floor, not a coincidence.
STEP_4 IF the artifact fails STEP_1, STOP validating against it. Build a
        known-ground-truth fixture instead (3-5 units, each field hand-verified by a
        direct query against the real source) and score against that. Keep the
        artifact comparison, RELABELLED as a DRIFT measure between editions -- which
        is genuinely useful -- but never as a correctness gate.

FORBIDDEN: reporting "field X agrees Y%" as a correctness measure when the artifact
            has not passed STEP_1. The number cannot distinguish "my formula is
            wrong" from "the artifact's value is stale."

GUARD pattern="the existing file IS the spec, so reproducing it proves correctness"
  (a carried-forward data artifact with no committed producer):
  REFUSE the oracle framing until STEP_1's self-consistency test passes. "Nothing
  regenerates it" is exactly the condition that lets its fields drift apart, and it
  is ALSO why it looks authoritative -- it is the file production actually reads. A
  low agreement number on such a target may mean YOUR OUTPUT IS MORE CORRECT.
  NO EXCEPTIONS before publishing an agreement percentage as a correctness claim.
  # WHY: 2026-07-31 mcp-servers #935, users_v2.json -- 8 readers, ZERO writers, so
  #   Full: incidents#2026-07-31-mcp-servers-935-users-v2-json

# ─── PROCEDURE: behavioral-oracle selection bias check ───

INVARIANT behavioral_signals_can_still_be_selection_biased
  # WHY: signals like "user navigated to file F after searching Q"
  #   Full: incidents#signals-like-user-navigated-to-file-f-after-searching
  # INCIDENT 2026-05-18 memory-search: n=114 navigation oracle showed
  #   Full: incidents#2026-05-18-memory-search-n-114-navigation-oracle

STEP_1 when grading from behavioral signals, also include:
  - Queries with NO follow-through (the user gave up after search)
  - Queries with non-navigation follow-through (asked the LLM
    directly, browsed via something other than file open)
  - LLM-judge labels on these UNLABELED queries — but with a candidate
    pool independent of the engine (per the LLM-judge rule above)

STEP_2 report the grade on BOTH the easy-skewed subset and the
  expanded subset. They answer different questions:
  - Easy-skewed: "how does the engine perform on queries the user
    actually navigated on?"
  - Expanded: "how does the engine perform on a representative
    production-query distribution?"

STEP_3 the publishable grade is the EXPANDED measurement. Easy-skewed
  is fine as a context number but the headline grade must use the
  unbiased substrate.

GUARD pattern="behavioral signals are unbiased by definition":
  REFUSE. Behavioral signals are absence-of-evidence biased — they only
  exist when the user found something. Absence of behavioral signal is
  silent and dominates the production distribution. NO EXCEPTIONS for
  grade claims.

# ─── PROCEDURE: lever-class exhaustion stop signal ───

INVARIANT three_consecutive_regressions_in_same_lever_class_is_a_stop_signal
  # WHY: if a lever class (reranking-stage modifications, candidate-
  #   Full: incidents#if-a-lever-class-reranking-stage-modifications-candidate
  # INCIDENT 2026-05-18 memory-search path-to-A push: MMR diversity
  #   Full: incidents#2026-05-18-memory-search-path-to-a-push

STEP_1 when two consecutive lever attempts in the same class regress:
  - Stop attempting MORE levers of the same class.
  - Document the regression pattern with the specific mechanism (e.g.
    "diversity penalty demotes correct neighbors because top-K has
    high intra-relevance similarity").

STEP_2 propose structural alternatives (NOT same-class refinements):
  - Different reranker model class (cohere-rerank-3, bge-reranker, ...)
  - Different retrieval primitive (multi-vector / ColBERT, two-stage)
  - Different substrate (full-document context, query rewriting)
  - These are multi-day investigations, NOT single-session tweaks.

STEP_3 publish the honest grade ceiling and recommend stopping further
  same-class tuning until structural change is investigated.

GUARD pattern="one more lever in the same class might work, let me try":
  EVALUATE: two consecutive regressions in the same class is the stop
  signal. Trying lever #3 of same class is noise-fitting. STOP. Propose
  structural alternatives or accept the current ceiling. NO EXCEPTIONS
  after two consecutive same-class regressions on metric-bearing A/Bs.

GUARD pattern="MMR / candidate-tuning / threshold-tweaking is industry
  standard, it should work":
  EVALUATE: "industry standard" is not evidence. The lever's effect on
  THIS engine state is what matters. If two attempts in the class fail
  on this engine, the engine is at the lever-class ceiling — industry
  standard doesn't override empirical regression on the specific corpus
  + reranker + ranking-stage state.

# ─── PROCEDURE: multi-arm paired comparison design (set BEFORE launching arms) ───

INVARIANT scoring_substrate_depth_must_match_across_arms
  # WHY: a hit metric scored by substring/containment is mechanically a
  #   Full: incidents#a-hit-metric-scored-by-substring-containment-is-mechanically
  # INCIDENT 2026-06-11 SweRank pilot: func Δ(C−A) +30.8pp CI [+7.7,+53.8]
  #   Full: incidents#2026-06-11-swerank-pilot-func-c-a-30

INVARIANT budget_gated_arms_must_share_instance_order_or_pre_pinned_subset
  # WHY: budget/ceiling gates truncate runs. Two arms that process the
  #   Full: incidents#budget-ceiling-gates-truncate-runs-two-arms-that-process
  # INCIDENT 2026-06-11 SweRank pilot: A (22 attempts, flat order) ∩
  #   Full: incidents#2026-06-11-swerank-pilot-a-22-attempts-flat

# ─── WHAT DOES NOT REQUIRE THIS CHECK ───

- Hotfix reverts (no metric improvement claim)
- Bug fixes that restore a previously-validated baseline
- Operational changes (latency, throughput, cost) where the metric is
  observed not estimated (latency p99 from production logs is not a
  metric-delta-driven default change; bootstrap doesn't apply)
- Security or correctness fixes (policy threshold isn't the bar at all)
- Retirements driven by genuinely-prohibitive cost (>1 hr wall AND
  >$50 API spend) where the analog evidence is single-axis-differing.
  Cost claims require measurement, not estimation.

# ─── PROCEDURE: commit the INSTRUMENT, not just the number ───

INVARIANT an_eval_that_produces_a_cited_number_commits_its_harness_in_the_same_pr
  # WHY: a report records what a measurement FOUND; nothing records what PRODUCED it.
  #   Full: incidents#a-report-records-what-a-measurement-found-nothing-records
  # INCIDENT 2026-07-30 — four artifacts, one measurement family, three permanently lost:
  #   Full: incidents#2026-07-30-four-artifacts-one-measurement-family-three

STEP_1 the PR citing a measurement contains: the harness, the exact prompt/config arms
        compared, and a dated results file. A results file alone is a claim.
STEP_2 the results file names the ENGINE and CORPUS measured on, so an engine migration
        visibly voids it instead of silently voiding it.
STEP_3 record REJECTED decisions with their evidence somewhere greppable (a DECISIONS.md
        scoped to the domain) — a rejection whose reasoning is unrecorded gets
        re-derived and re-retracted.

GUARD pattern="the eval is done, write up the result" (harness in /tmp, a scratch dir, or
  an untracked reports folder):
  REFUSE shipping the number without the instrument. Absent the harness, the number has a
  half-life of weeks and no way to detect its own expiry. Cost of committing: one
  `git add`. Cost of not: unrepeatable the moment the engine moves. NO EXCEPTIONS for a
  number cited in a grade or a decision.
