---
name: search-axis-rotate
description: "Rotate the SEARCH AXIS to break a stuck search / red-team / optimization. Use when an approach plateaus and 'what next?' feels open-ended — trigger phrases: 'stuck', 'plateau', 'hit a wall', 'tried everything', 'not finding more', 'break the ceiling', 'different angle', 'exhausted this approach'. Enumerates the six search axes (representation, diversity, measurement, orchestration, mechanism-class, method-blindspot), rotates to the cheapest untried one, and enforces tested-refuted vs untested-uncharted before any 'wall' claim. Chains to /plateau-diagnose for the measurement axis and /red-team-axes for adversarial targets. Do NOT use for: fast-feedback loops moving with each fix, brand-new systems with no baseline, or trivial bugs with an obvious cause."
argument-hint: "<what plateaued> <what you've already tried>"
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Read, Grep, Glob, Bash, AskUserQuestion
effort: medium
---

# Search-Axis-Rotate

> When a search / red-team / optimization stops yielding, the move is to change the SEARCH AXIS — not to run the current lever harder or longer. A plateau is evidence about the current lever, never about the frontier. This skill names the axes, rotates to the cheapest untried one, and forces you to prove a wall TESTED before you call it one.

Pairs the standing directive "never assume a ceiling" (`[[feedback_no-ceiling-assumptions]]`) with a concrete next move (`[[break-plateau-by-axis-rotation]]`). Every gain in a hard search comes from a *different* axis; the plateau is the current lever's ceiling, not the search's.

## Arguments

- `what plateaued` — the metric / search / attack that stopped yielding.
- `what you've already tried` — the levers exhausted so far (used to classify the current axis in Step 2).

## The six search axes

| Axis | Vary… | Cheap instrument |
|------|-------|------------------|
| **Representation** | how the attempt is expressed (single→multi-turn, direct→encoded, raw→obfuscated) | reformulate + re-run a handful |
| **Diversity** | breadth of generation (one generator → decorrelated pool × modes; partition the space) | fan out N distinct generators |
| **Measurement** | what you score against — READ the scorer/oracle SOURCE (cell-key, per-lane, auth dims) instead of optimizing blind | read the scoring code (30–90s) |
| **Orchestration** | the search machinery (sequential → parallel subagents → dynamic workflow) | dispatch a small parallel batch |
| **Mechanism-class** | the KIND of attempt (when one class refuses, switch to a structurally different one) | one probe per new class |
| **Method-blindspot** | the search PROCEDURE's own blind side (a filter that never tested one branch) | audit what your method never evaluated |

## Steps

### Step 1 — Confirm the plateau is real
Two consecutive no-yield attempts on ONE lever = the stop signal. If the metric still moves with each fix, this skill is overhead — stop and keep iterating. (Mirrors `eval-shipping-discipline` "two consecutive same-class regressions is a stop signal".)

### Step 2 — Classify the CURRENT axis
Name which of the six axes your exhausted levers sat on. Almost always it is ONE axis worked repeatedly (e.g. "I kept varying the prompt wording" = representation, worked to death).

### Step 3 — Enumerate the UNTRIED axes
List the axes you have NOT yet varied. This is the load-bearing step: the frontier is an axis you haven't tried, and naming the untried set makes it visible. Use `AskUserQuestion` if the choice of next axis is non-obvious and user context would decide it.

### Step 4 — Rotate to the cheapest untried axis
Pick the lowest-cost untried axis and run its cheap instrument (table above). **Default first pick: the MEASUREMENT axis — read the scorer/oracle source.** Across real campaigns it is the highest-yield rotation every time: it converts blind optimization into targeted search (it surfaces per-lane scoring, hidden key dimensions, collapse rules you were fighting blind).
- If the plateau is a **metric** (F1/recall/precision/latency) → chain to **/plateau-diagnose** (the measurement axis done as a full contingency-cell recipe).
- If the target is **adversarial / hardened** (attacks refusing) → chain to **/red-team-axes** (the axes instantiated as harness generators + oracles).

### Step 5 — TESTED-refuted vs UNTESTED-uncharted (the honesty gate)
Before claiming any axis is a "wall", classify it:
- **TESTED-REFUTED** — measured to refusal across the class (e.g. 8 distinct mechanisms all refused + a direct probe). A real wall; document it as a finding and stop rotating on it.
- **UNTESTED-UNCHARTED** — an axis/lever not yet exercised. NOT a wall. Rotate to it. Absence of a result in your search is a property of the search, not the world (`[[symmetric-evidentiary-burden]]`).

FORBIDDEN: declaring a ceiling/frontier from a plateau. Enumerate the untried axes instead (`[[feedback_no-ceiling-assumptions]]`).

## Output
- The current axis (what was worked to death).
- The untried-axis list.
- The axis rotated to + its cheap-probe result.
- Per exhausted axis: TESTED-REFUTED (with the evidence) or UNTESTED (rotate target).
- Any chain invoked (/plateau-diagnose, /red-team-axes).

## Examples

**Example 1 — red-team plateau (the JED campaign, 2026-07).** Attacks stuck at N known cells; representation (prompt wording) worked to death. Rotated axes in turn: representation→multi-turn (broke EXFIL), diversity→decorrelated swarm (+1 cell), **measurement→read the scorer source** (revealed per-lane scoring + an auth dimension — the highest-yield rotation), orchestration→dynamic workflow, mechanism-class→8 novel injection classes. shell.run/http.post-int came back TESTED-REFUTED (8 mechanisms + a direct private-IP probe all refused) — a real wall, documented, not assumed.

**Example 2 — skip it.** A single-tool latency regression that moved AT a deploy: the axis is `commit_sha`, the cell is "the deploy" — just bisect. No rotation needed.

## Success Criteria
- The current (exhausted) axis is named.
- At least one untried axis is rotated to and probed before any "wall" claim.
- Every "wall" is classified TESTED-REFUTED (with evidence) or UNTESTED — no assumed ceilings.
- Metric plateaus chain to /plateau-diagnose; adversarial targets chain to /red-team-axes.

## When NOT to use
- Fast-feedback metric still moving with each fix (iterate, don't rotate).
- Brand-new system with no baseline (nothing to plateau against).
- Trivial bug with an obvious cause.

## References
- `[[break-plateau-by-axis-rotation]]` (memory) — the axis taxonomy + discipline this skill operationalizes.
- The measurement-axis rule cluster: `verify-effectiveness.md`, `diagnose-before-fix.md`, `reproduce-before-optimize.md`, `symmetric-evidentiary-burden.md`, `verify-before-assuming.md`.
- `/plateau-diagnose` — the measurement axis as a full metric-cell recipe.
- `/red-team-axes` — the axes instantiated for adversarial targets via the harness.
