---
name: review-depth-by-risk
description: "Companion to superpowers:subagent-driven-development: size each task's review to its risk tier, allow one repair batch and one re-review then stop, keep concurrent implementers on disjoint scope, and halt every queued mutation when the user changes scope."
when_to_use: 'Use when dispatching implementer and reviewer subagents under superpowers:subagent-driven-development, at the moment you choose how much review a completed task gets. Trigger phrases: "how much review", "security boundary change", "risk tier", "one more review round", "scope changed mid-run". Do NOT use to replace subagent-driven-development''s dispatch, ledger, or fix-loop mechanics.'
allowed-tools: Read Grep Glob Agent AskUserQuestion
---

# Review depth by risk

Companion to `superpowers:subagent-driven-development`, which owns dispatch,
task briefs, the workspace ledger, and the fix loop. This skill adds four
decision rules that plugin leaves to judgment. Extracted on 2026-09-03 from
this repository's fork of superpowers v4.3.1.

## 1. Freeze the acceptance matrix and risk tier before dispatch

Write the task-wide acceptance matrix once, before any implementer runs. Each
reviewer inspects the bounded task surface and returns one complete issue set,
not one adjacent defect per cycle. Review a vertical slice, not each
micro-commit, and wait for completion notifications rather than polling.

## 2. Size review to the risk tier

Classify the completed slice, then apply the matching path:

- **Source, documentation, or test-only:** implementer self-review plus the
  relevant focused check.
- **Normal product code:** one combined spec-and-quality reviewer.
- **Production mutation or security boundary:** separate spec reviewer and
  quality reviewer, in that order. Two reviewers because the two failure modes
  differ: one checks that the change does what the plan said, the other that
  it does not do anything else.

Do not dispatch a final whole-implementation reviewer when the same final diff
already passed the selected path and the integration gate. Later observations
become backlog unless they expose data loss, unauthorized mutation, a security
boundary bypass, or a false terminal claim.

## 3. One repair batch, one re-review, then stop

Collect one complete issue set, make one repair batch, and re-review once. A
second rejection stops the task with the remaining blockers and returns
control to the user. It must not start another repair agent and must not widen
the acceptance matrix; expanding the matrix during re-review is how review
loops run for hours.

## 4. Disjoint scope and the scope-change barrier

Two implementers may run concurrently only on disjoint paths, for example
tests and implementation in separate directories. Never on overlapping files.

When the user narrows, replaces, or cancels work, interrupt active agents and
inventory every queued file, external, and live action. Reclassify each
against the new scope, cancel what fell outside it, and do not resume
mutations until the scope ledger is reconciled.

Return to `superpowers:subagent-driven-development` for the mechanics, and to
`superpowers:finishing-a-development-branch` once the integration gate passes.

## Examples

**Example 1: a typo fix routed to the wrong depth**
User says: "Review this one-word docs change."
Actions:
1. Freeze the acceptance matrix and risk tier before dispatch (step 1): docs
   only, no runtime surface, lowest tier.
2. Size the review to the tier (step 2): one reviewer, no adversarial pass.
Result: one review, minutes. The matrix was frozen first, so the low tier was
a recorded decision rather than an in-flight judgment call.

**Example 2: an auth-path change**
User says: "Review the change to the token-refresh branch."
Actions:
1. Risk tier is highest — a privilege boundary (step 1). Matrix names the
   allow, deny, malformed, and expired cases up front.
2. Size accordingly (step 2): a security-focused reviewer plus an adversarial
   second pass on the verdict, because a wrong "safe" gets acted on.
3. One repair batch, one re-review (step 3).
Result: the deny path was untested. Found on the first pass because the matrix
was frozen before anyone read the diff.

**Example 3: a review loop that will not converge**
Situation: the second re-review returns new blockers.
Actions:
1. Stop rather than starting a third repair agent (step 3).
2. Do not widen the acceptance matrix to absorb the new findings.
3. Return the remaining blockers and control to the user.
Result: the task stops with an honest blocker list after two passes, instead
of running review cycles until a reviewer happens to find nothing.

## Success Criteria

- The acceptance matrix and risk tier are written down before any reviewer is
  dispatched, and neither is widened afterward.
- Review depth is a function of the recorded risk tier, not of how the diff
  looks on inspection.
- At most one repair batch and one re-review run; a second rejection stops the
  task and returns the remaining blockers to the user.
- Concurrent implementers operate only on disjoint paths, never on overlapping
  files.
- On a scope change, active agents are interrupted and every queued file,
  external, and live action is reclassified before mutations resume.
- Control returns to `superpowers:subagent-driven-development` for mechanics
  and to `superpowers:finishing-a-development-branch` once the gate passes.
