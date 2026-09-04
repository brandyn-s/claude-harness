# Plan-Type: MEASUREMENT RUN (the deliverable is a number + a trustworthiness verdict)

**Fires when** the user's request is "measure / validate / assess the accuracy (precision /
recall / F1 / κ / agreement / coverage) of X" and the OUTPUT is *numbers with confidence
intervals + a verdict on whether to trust them* — NOT a feature build or a metric-lift ship.
Signal phrases: "this is a measurement run", "validate the accuracy of", "to a scientific
standard", "oracle", "ground truth", "untrusting of our own judgement".

**Why this plan-type exists.** superplan's default template is built for SHIP decisions —
Phase 3.5 baseline → fix → prove-it-lifted-M → terminal-doc-on-undershoot. That machinery
assumes the deliverable is a *change* whose effect you measure. A measurement run inverts it:
the measurement IS the deliverable, and the hard problems are *oracle design, contamination,
pre-registration, and instrument soundness* — none of which the default template requires.
The 2026-06-20 accuracy-measurement run had to hand-roll all of these; this plan-type makes
them structural. (It also operationalizes the user's verbatim rigor demand: "data, data fields,
data structure, assumptions, gotchas, AWS architecture, throttling, rate limiting, oracles,
harnesses, precision, recall, models, sequencing, judgement, methodology … checkpoints,
verification, validation, testing … untrusting of our own judgement.")

## Required sections (a measurement-run plan MUST contain all of these)

A measurement-run plan REPLACES the size-of-effect template's "Phase 3.5 Baseline → lift"
spine with this spine. Each section maps to a demand the user's rigor prompt made explicit.

### 0. Objectives + PRE-REGISTERED hypotheses + expected results
State the optimization target, the H1..Hn hypotheses, and their FALSIFIER BANDS **before
looking at any result** (anti-post-hoc-rationalization). Pre-registration is committed to git
BEFORE the expensive labeling/measurement phase runs. "We need to be untrusting of our own
judgement" = this section is locked first and the grading bands cannot move after results land.

### 1. Beliefs / constraints / assumptions — each TAGGED "test, don't trust"
Every prior number, prior dataset, and prior conclusion is RE-DERIVED or DISCARDED, never
imported (the run's B2/B3 discipline). List each load-bearing assumption with its verification
step. Distrust-our-own-judgement is a section, not a sentiment.

### 2. DATA — sources, fields, structures, gotchas
Every source view/table, its key fields, its known gotchas (empty fields, reserved words,
caps, truncation). The user asked for "data, data fields, data structure" explicitly.

### 3. ORACLE design (the hard problem — its own section, MANDATORY)
The oracle is what assigns ground truth. It MUST be:
- **INDEPENDENT of the engine under test** (contamination rule). If the engine is model M,
  the oracle must not be M or M's lineage (shared training → correlated error). An LLM-judge
  oracle's candidate pool must NOT come from the engine being graded (selection-on-the-DV).
- **Honest about what it can claim.** Inter-model AGREEMENT (κ) is RELIABILITY, not VALIDITY.
  Only ground truth (human labels, OR an external labeled corpus) yields validity. State which
  you have. If zero human labels → the run measures reliability; say so in every number's tag.
- **n_eff-aware.** A model panel has ~2 effective voters regardless of size (Kish n_eff); never
  claim N-model independence, never use naive majority vote. Report n_eff.
- **externally anchored where possible.** A labeled external corpus (e.g. a published benchmark)
  gives a real validity number with no manual labeling — with the DISTRIBUTION-SHIFT caveat
  stated (their corpus ≠ ours; it's a transfer test, not proof-on-our-traffic).

### 3a. RESEARCH RED-TEAM the load-bearing assumptions (MANDATORY before execution)
A measurement/oracle plan's design rests on assumptions that FEEL self-evident and are routinely
WRONG against current literature. This is the DESIGN-layer catcher of the six-catcher model
(phase-0-preflight) — the ONLY gate that catches a false design assumption, and empirically the
one that saved the 2026-06-20 run (it refuted "an independent-family panel + majority vote =
trustworthy oracle" → panels have ~2 effective voters; agreement≠validation; κ-deflation 33-41pp,
all from frontier papers — BEFORE any expensive labeling ran). It is NOT optional for oracle plans.

Method (do this at AUTHORING time, not as an add-on):
1. **DECOMPOSE** the plan into its load-bearing assumptions — especially the oracle's
   independence / validity claims, the metric's chance-correction choice, and the aggregation
   rule (majority vote? weighted? family-collapsed?).
2. **RESEARCH each assumption** against dated literature — `/gather-research` or a multi-provider
   search — FRESHNESS-CONSTRAINED: **≤6 months, frontier-systems prioritized**. An LLM-behavior
   assumption about a 2026 model class CANNOT be validated by pre-LLM citations
   (`gather-research/references/citation-domain-freshness.md`).
3. **TAG each** SUPPORTED / REFUTED / CONTESTED / UNCHARTED (`rules/symmetric-evidentiary-burden.md` — a refutation needs the same source bar as the claim).
   REFUTED → REDESIGN before execution. UNCHARTED → proceed but flag it; absence of a test is not
   refutation.
4. The surviving design carries a **`## Research basis`** section citing the sources (this run's
   §7), so the next author sees what the design was validated against and can re-check freshness.
5. **FEASIBILITY-check the red-team's OWN fixes (the fix needs red-teaming too).** When the
   red-team recommends an external resource to fix a flaw — a corpus, dataset, tool, model, or API
   — verify its ACCESSIBILITY in the SAME breath: access gate, license, DPA / signed-agreement
   requirement, download path, in-session reachability. "A labeled corpus exists" ≠ "we can use it
   in-session" (e.g. SecretBench requires a Google Cloud account + a signed DPA + email-gated
   access). An approval / calendar-gated dependency is a CONSTITUTION VIOLATION
   (self-contained-session), not an improvement — a red-team fix that introduces an external gate is
   a WORSE defect than the one it fixed. (`verify-before-assuming.md` reachability-vs-capability,
   applied to the red-team's own recommendations.)

This is distinct from the `/interview` stress-test (phase-4-construction): `/interview` probes
internal consistency by argument; this probes design assumptions against EXTERNAL current
evidence. An oracle plan needs both, but THIS one is the catcher for the most expensive flaw class.

### 4. HARNESS + instrument soundness
- **Audit every reused production component's CONTRACT** before trusting it as an instrument
  (see phase-0-preflight "Invocability + instrument-soundness"): does it EMIT the field you
  measure? what is the denominator? does its error path SWALLOW (production never-block) when a
  census needs HARD-FAIL? Read the decision function from source; don't infer from output shape.
- **Census the input POPULATION** + state the inclusion threshold (degenerate/empty units exist
  and LLM panels hallucinate on them).
- **Per-model invocation contract** (params differ across models — temperature, max-tokens).
- **Transient-vs-deterministic error handling**: retry + circuit-break the transient
  (network/throttle/timeout), fail-fast the deterministic (parse/validation), capture drops for
  a retry pass, compute the coverage checkpoint POST-retry. (See `verify-effectiveness.md`.)

### 5. AWS / infra interaction + throttling + rate limiting
Every service touched (Athena/Glue, S3+KMS, Bedrock TPS), its quotas, and the bounded-retry
posture. The user asked for "AWS architecture and interaction, throttling, rate limiting."

### 6. Metrics + sequencing + checkpoints
Precision / recall / F1 / κ definitions; chance-correction (κ headline, never raw agreement —
exact-match overstates 33-41pp); bootstrap 95% CI (n≥10k); per-phase CHECKPOINT that must pass
before the next; the SIX-catcher gate model (phase-0-preflight) applied across phases.

### 7. METHODOLOGY GUARDS — untrusting of our own judgement (MANDATORY)
Pre-registration before results · every prior number re-derived · oracle independent of engine ·
chance-correct everything · report n_eff · two reported tiers (validity-anchored vs
agreement-extrapolated) with the gap = honest uncertainty · asymmetric cost stated · instrument
proven before use · any invoke error hard-drops (deterministic) or retries (transient), never a
silent default. A REAL-TIME PLAN-FLAW LOG runs alongside execution (execution-discipline.md).

## Falsifiers + terminal doc
Same Step 5c contract as size-of-effect plans, plus: if the oracle's reliability anchor is weak
(e.g. n_eff < 1.5, or panel-vs-anchor κ < 0.6), DOWNGRADE every extrapolated number to
"indicative only" and say so in the headline — do not publish an agreement number as a validity
number.

## What this plan-type does NOT need
- Phase 3.5 "currently N → expected M" lift framing (there is no change being shipped).
- Production-stack default-flip verification (nothing is being flipped).
- The size-of-effect Demo ("user sees X improve") — the Demo is "operator runs the metric
  command and sees the numbers + CIs + the trustworthiness verdict, each scope-tagged."

## Reference implementation
The 2026-06-20 detection-pipeline accuracy run is the worked example: plan +
pre-registration (`bench/accuracy/P3_preregistration.md`) + oracle cascade harness +
compute_metrics (textbook-anchored tests) + the real-time flaw log
(`plans/2026-06-20-…-flaws.md`, 6 flaws / 5 catchers). Read it before authoring a new
measurement run.
