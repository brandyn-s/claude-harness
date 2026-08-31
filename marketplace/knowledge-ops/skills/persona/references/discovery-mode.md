# Discovery mode workflow

**Goal**: surface framings the team hasn't considered. Optimized for
finding-unknowns, NOT for verifying-knowns.

**Aligns with**: the original 2026-04-29 dispatch (Go precision = 0.515
that surfaced edge-type partitioning as a frame).

**F6 finding that shapes this mode**: casual scoring (B1) measures
plausibility, not correctness (kappa=0 with rubric scoring). Therefore
discovery mode does NOT use automated scoring. The synthesis layer is
manual review by the user.

## Workflow

### 1. Problem statement preparation

Skill receives the problem from the CLI. If the problem is:
- A multi-paragraph engineering description with explicit symptoms,
  constraints, and known facts — STRIP DOWN to symptoms + question
  only. Verbose problem statements telegraph answers (F6 finding).
- A one-line metric plateau — keep as-is.
- A measurement-design inversion (`--inversion` flag) — replace the
  persona prompt's "diagnose & prescribe" framing with "what would
  your framework measure here?"

The loose problem is intentional. Don't add structure.

### 2. Cohort selection

- Default N: **15** (per dispatch template Article I)
- Default sampling: **bucket-coverage** (≥1 per bucket, then
  round-robin)
- Default seed: deterministic hash of slug only (same slug across
  different problems/dates/modes reproduces the same cohort)
- Default inventory: canonical-2026-04-29

CLI overrides: `--n N`, `--sampling random|bucket|curated`, `--seed N`,
`--inventory PATH`.

The default produces 15 personas spanning all 11 buckets, with 4
extra personas filling the most-relevant buckets.

### 3. Persona dispatch

Each persona receives:
- Detailed framework prompt (≥800w from inventory body) — M5 finding:
  detailed prompts produce slightly less noise
- Loose problem statement (no structured ground truth)
- Standard recommendation request: 3-5 specific recommendations with
  framework-coherent rationale per recommendation
- **Calibration gates (added 2026-05-02 per [[persona-outcomes-log]] row 1)**:
  each recommendation must include a `[novel]`/`[default]` calibration
  tag and a measurable axis (the categorical property to GROUP BY for
  validation). See `templates/dispatch-prompt.md` for the exact format.

#### Why the calibration gates exist

The 2026-05-02 code-graph plateau-fixes session (n=1 baseline run):

- 14 framings surfaced. 4 became concrete work. 1 shipped directly
  (Janusian → Y.3, +0.5pp F1).
- One of the pursued framings (Y.1 "tighten the threshold") was a
  `[default]` engineering hypothesis — would have been generated
  without persona discovery. Its measurable axis was `confidence_band`,
  but the axis was uncalibrated, leading to a -31pp F1 disaster
  averted only by the recipe's stop-and-ask gate.
- Two pursued framings had no measurable axis at all and got refuted
  on inspection.

The two gates surface this distinction in the persona output BEFORE
the team commits engineering effort:

- **`[novel]` vs `[default]` tag**: distinguishes recommendations that
  required the persona's specific lens from default engineering
  hypotheses that would arise without it. Tracks what the persona
  system actually adds versus what's just noise.
- **Measurable axis**: forces each framing to name the categorical edge
  property (or row attribute, or request dimension) that the team
  would `GROUP BY` to validate the recommendation. A framing without
  a measurable axis is `[SPECULATIVE]` and goes to a separate bucket;
  it can still be discussed but does not count as actionable.

Dispatched via the Anthropic SDK. The current Haiku 4.5 API identifier remains
the economical producer default. `--model` and optional `--effort` select a
different lane; `PERSONA_MODEL` and `PERSONA_MODEL_EFFORT` provide run-level
defaults. Every result records requested and provider-observed runtime
provenance. M4's Sonnet 4.6 and Opus 4.7 comparisons are frozen historical
evidence: they found that capability tier reduced noise more than signal, but
they do not define today's operational model choices.

If a dispatch is refused, truncated, empty, rejected by the provider, or
returned by a model other than the one requested, the run fails closed. Partial
typed results remain in `results-by-persona/` for diagnosis, but the run is not
indexed and the command does not claim completion.

### 4. Synthesis layer (non-interactive)

> **Status: not yet implemented in `scripts/analyze.py`.** The
> automated clustering / convergence detection / divergent-insight
> flagging below describes the designed behavior. Today, discovery
> mode produces per-persona outputs and the user does the synthesis
> by hand. Until the synthesis layer ships, treat the steps below as
> a manual checklist for human review rather than an automated pass.

Personas dispatch in parallel (or sequentially if SDK rate-limits).
After all complete, the (eventual) synthesis script will run WITHOUT
any human interaction:

1. **Convergence detection**: cluster recommendations by sentence-
   embedding cosine. Any cluster with ≥3 personas across ≥2 buckets
   is a "convergent theme" — the dispatch template's positive
   convergence signal.
2. **Divergent insights**: recommendations that don't cluster (single-
   persona, no cosine neighbor) are flagged as "potential novel
   framings — manual review needed."
3. **Bucket coverage report**: which buckets contributed which
   convergent themes. Mode-collapse within one bucket = sampling
   artifact, not signal.

Output written to `analysis.md` in the run dir.

### 5. Output structure

The discovery-mode `analysis.md` has these sections:
- **Convergent themes** — clusters of ≥3 personas across ≥2 buckets,
  ranked by convergence size. **Each theme inherits the most-common
  calibration tag from its member recommendations** (e.g.
  "Convergent theme: tighten cross-package threshold `[default]`,
  measurable axis: confidence_band"). When tags disagree across the
  cluster, list both.
- **Single-persona insights** — flagged for manual review. Calibration
  tags are surfaced inline.
- **Bucket-coverage map** — which buckets contributed
- **Calibration summary (added 2026-05-02)**: counts of `[novel]` vs
  `[default]` recommendations across the run, plus the count of
  `[SPECULATIVE]` (no-measurable-axis) recommendations. This is the
  per-run row that gets logged to `persona-outcomes-log.md` after the
  user investigates outcomes.
- **Per-persona recommendations** — full output, one section per
  persona, in dispatch order. Calibration tags appear inline per
  recommendation.
- **No automated grading** — explicit note that the synthesis is
  algorithmic clustering, not correctness-judging

### 6. Manual review (after skill completes)

The user reads `analysis.md` and:
- Marks convergent themes as "actionable" / "diligence" / "off-target"
- Investigates single-persona insights manually
- Records lessons-learned in
  `~/Documents/knowledge-base/research/dispatch-runs/INDEX.md`

The skill does NOT do this review automatically. F6 confirmed casual
scoring (Haiku rater with neutral prompt) approves nearly everything
as plausible — useless as evidence.

## What discovery mode does NOT do

- Score recommendations programmatically (would be plausibility-detection)
- Compute precision/recall (no ground truth)
- Pre-register a rubric (would be premature when the goal is finding
  unknowns)
- Apply LLM-as-judge scoring (different mode for that — rubric)

## When to switch to rubric mode

Switch to rubric mode if:
- You have a known-answer fixture (e.g., a real problem you've already
  solved and want to verify dispatch reproduces the answer)
- You want to compare dispatch performance across models, sampling
  rules, or N values — a controlled experiment
- You want measurement that's comparable across runs

## Reproducibility

Same slug → same cohort (deterministic seed). Same slug with same
inventory and same model → personas with same inputs produce
mostly-deterministic outputs (model temperature aside).

Caveat: model temperature is non-zero. Reruns may produce slightly
different output even with fixed seed. The synthesis layer's
convergence-detection is robust to small variations.

## Cost (Haiku 4.5)

- 15 personas × ~$0.005 = ~$0.075 per dispatch
- No scoring layer cost in discovery mode
- Total typical run: <$0.10

## When the synthesis layer fails

If the convergence detector finds zero clusters of size ≥3 across ≥2
buckets, the personas didn't converge. Either:
1. The problem is too vague (consider adding minimal structure)
2. The personas aren't engaging with the problem (review per-persona
   output for refusals or generic responses)
3. The N=15 cohort happened to be all noise (rare; rerun with different
   seed)

The skill outputs a "no convergence detected" warning to `analysis.md`
and recommends manual review of all 15 outputs before drawing
conclusions.
