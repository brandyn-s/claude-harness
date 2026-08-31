---
name: plateau-diagnose
description: "Find the contingency-table cell holding a stuck metric's failure mass before fixing."
when_to_use: Use when an aggregate metric (F1, recall, precision, accuracy, latency) sits on a plateau and "what to fix next?" feels open-ended. Six-step recipe finds the cell of the contingency table holding the failure mass and verifies it represents real failure before designing a fix. Trigger phrases - "plateau diagnose", "stuck metric", "F1 plateau", "what to fix next", "metric not moving", "diagnose plateau". Do NOT use for fast-feedback metrics already moving with each fix, well-mapped hypothesis spaces, brand-new systems with no instrumentation, or trivial bugs with obvious causes.
argument-hint: "<metric_name> <measurement_artifact>"
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Read, Grep, Glob, Write, Edit
effort: medium
---

# Plateau Diagnose

> Six-step recipe for moving a stuck metric off a plateau. Pairs persona-driven hypothesis breadth with disciplined per-cell measurement, then verifies the failure cell represents real system error (not measurement artifact) before designing a fix.

## Arguments

Both arguments are required:

- `metric_name` (string) — the plateau-ed metric being diagnosed (e.g., `F1`, `recall@10`, `p95_latency_ms`, `precision`).
- `measurement_artifact` (path) — path to the per-query / per-edge / per-row output that constructs the metric. The recipe needs row-level data (not just the aggregate scalar) so Steps 3-5 can compute per-cell statistics.

If `measurement_artifact` is not row-level (e.g., only a summary table), the recipe does not fit — re-emit the harness with per-row outputs first.

## When to invoke

The metric must be:
1. **Plateaued** — multiple recent fixes haven't moved it meaningfully
2. **Multi-dimensional** — failures can plausibly be grouped by ≥2 categorical axes (caller_kind × resolver_rule, request_type × payload_size, error_class × user_segment)
3. **Cheaply re-measurable** — a single harness run is feasible (not a 24-hour experiment)

If any of those is false, this recipe doesn't fit.

## The six steps

### Step 1: Persona discovery (hypothesis breadth) — OPTIONAL

Run `/persona "<problem statement>" --mode discovery` against the problem (the problem statement is positional; `--mode discovery` selects the discovery mode per `skills/persona/SKILL.md`'s argument-hint). The output is 14-15 framings of varying quality — most will be wrong, but the breadth is the point. The recipe doesn't need the persona to be RIGHT; it needs enough alternatives that the measurement instrument (Steps 3-5) can pick the right one.

**This step is OPTIONAL.** If you have ANY of: a well-mapped hypothesis space, no API budget for persona dispatch, or a strong prior on what the failure modes are — skip Step 1 and start with Step 2's cheap reality check. Steps 2-6 stand alone; Step 1 is breadth-of-hypothesis insurance for cases where you don't have a working theory.

**Skip Step 1 when**: the hypothesis space is genuinely well-mapped — the team has named all reasonable causes, and instrumentation is just confirming which is biggest.

**Carry forward to Step 2**: each persona framing's `[novel]`/`[default]` tag and measurable axis (per the persona discovery calibration gates added 2026-05-02). `[default]` framings get tested but get less attention; `[novel]` framings are where the persona system actually adds value.

### Step 2: Cheap reality check (refute hypotheses fast)

Pick the leading 2-3 hypotheses from Step 1 (if run) or from your own enumerated hypotheses (if Step 1 was skipped). Test each with the lowest-cost instrument that can refute it: a `grep` on real edges, a sample-mode LLM-Judge, a one-off Python script measuring delta.

**WARNING — PARTIAL-vs-FULL sample bias**. Sample-mode results that name specific shares (e.g., "20% of FPs are X") are HYPOTHESIS-grade only. The harness's sampling logic IS part of the instrument. Common bias: alphabetical-prefix sampling biases toward whatever pattern dominates that prefix. Re-confirm with full data before treating PARTIAL findings as evidence.

The point of Step 2 is to refute fast before committing to instrumentation work in Step 3.

### Step 3: Instrumentation pass (emit dimensions)

For each error edge / failed prediction / slow request, emit the categorical fields that might explain it. These become the columns of the contingency table.

Examples (code-graph CALLS):
- `caller_node_kind` (function-body, method-body, test-body, package-init-block)
- `resolver_rule` (exact-qn-match, same-package-shadow, cross-package-heuristic, ...)
- `candidate_set_size` (1, 2, 3, ≥4)

The dimensions should match the framings from Step 1's `[novel]` framings if Step 1 was run, or your own enumerated hypotheses' categorical axes if Step 1 was skipped — those are what the recipe is testing.

### Step 4: Re-baseline with the new fields populated

Run the measurement harness on real data with the Step 3 fields emitted. Compute per-cell statistics: precision/recall/error-rate by `(dim_A × dim_B)`, sometimes `(dim_A × dim_B × dim_C)`.

**Watch for**: per-aggregate metric hiding per-cell collapse. Aggregate F1=0.89 is meaningless when one project has F1=0.54 and another has F1=0.99. Always look at per-project AND per-cell breakdowns.

### Step 5: Read the cell

Find the one combination carrying the failure mass. Per-cell precision is more actionable than per-project F1.

In the worked example: `(method-body × cross-package-heuristic) = 416/428 FPs (97.2%)`. That's the cell.

### Step 6: Verify cell edges are real failures (Step 5b)

**Before designing any fix, sample 3-5 of the cell's failure edges and verify by source inspection that they represent real failures, NOT measurement artifacts.**

Three sessions in a row, the cell surfaced by Step 5 turned out to be an instrument bug:
- Cell looked like "cross-package-heuristic threshold too loose" → confidence labels were uncalibrated; threshold killed 1063 TPs
- Cell looked like "same-package-shadow miss" → CBM definition-time QN format bug
- Cell looked like "runIncrementalPasses single-site explosion" → oracle drops `recv.method` calls

A 5-minute source inspection of 3-5 edges is dramatically cheaper than:
- Designing a system fix that doesn't fix anything
- Spinning up a follow-up investigation when the system fix doesn't move the metric
- Debugging the wrong layer for an hour before realizing the cause is upstream

If the edges look correct in source but the instrument doesn't see them, **the fix lives in the harness, not in the system**.

## Output

After running the steps that applied (Steps 2-6 always; Step 1 only if the hypothesis space wasn't already well-mapped), produce a brief report covering:

- **Step 1** (if run): how many persona framings; how many `[novel]` vs `[default]`. Note "skipped — hypothesis space well-mapped" if Step 1 was bypassed.
- **Step 2**: which hypotheses were refuted; any PARTIAL-mode findings flagged for FULL-data verification
- **Step 3**: which dimensions added; rationale tied to Step 1 framings
- **Step 4**: per-cell metric table; aggregate vs per-project distribution
- **Step 5**: the dominant cell; its share of total failures
- **Step 6**: 3-5 cell edges sampled; verdict on each (real failure or instrument artifact); recommended fix layer

If a majority of sampled edges are "instrument artifact", the fix is in the harness. If a majority are "real failure", design a fix targeting the cell. If verdicts are mixed, expand the sample to 5 edges and re-evaluate the split.

## Examples

**Example 1: Stuck F1 on Go fixture**

Used on 2026-05-02 to diagnose code-graph's CALLS edge F1=0.890 plateau. Full arc:

- Step 1: 14 framings, 4 pursued. Janusian framing was the only `[novel]` one that shipped (+0.5pp F1).
- Step 2: PARTIAL LLM-Judge claimed 20% ghost-package-block; FULL data showed 0% (sampling artifact).
- Steps 3-5: Identified `(method-body × cross-package-heuristic)` cell holding 416/428 FPs.
- Step 6: NOT YET DEFINED at the time. Without it, Y.1's "tighten threshold" approach was attempted; measurement showed -31pp F1; reverted.
- Eventually: Step 6's discipline was retroactively applied via per-site investigation, revealing the cell was an oracle drop bug. PR #140 fixed the instrument: F1 0.890 → 0.980 (+8.7pp).

**Example 2: Skip the recipe entirely**

For a single-tool single-call latency regression where the metric moved AT a deploy, skip the recipe. The dimension is `commit_sha`; the cell is "the deploy"; just bisect.

## Success Criteria

- Step 6 verdicts are produced for the dominant cell
- Recommended fix layer (system vs harness) is named
- If a fix is shipped, F1 measurement before/after is captured per-cell, not just aggregate
- Outcome is logged for future calibration (knowledge-base persona-outcomes-log.md)

## When NOT to use this skill

- The metric is fast-feedback (moves with each fix). Recipe is overhead for tight loops.
- Hypothesis space is genuinely well-mapped (skip Step 1, run Steps 2-6).
- Instrumentation cost exceeds fix value (2-week refactor for a quarterly grumble).
- Brand-new system with no baseline — there's nothing to plateau against.
- Trivial bug with an obvious cause that doesn't need cell-level analysis.

## References

- `verify-effectiveness.md` rule — "prove the instrument before publishing the measurement" applied at the recipe's Step 6.

Optional user-local context (may not be present in every environment):

- `~/Documents/knowledge-base/topics/plateau-diagnosis-pattern.md` — topic-file version of this recipe with full motivation, failure modes, and the 3-instance recurrence table that justifies Step 6.
- `~/Documents/knowledge-base/research/persona-outcomes-log.md` — per-run log of persona discovery's actual contribution; informs hypothesis weighting.
