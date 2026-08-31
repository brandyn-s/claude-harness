<!--
DESTINATION: example-org/claude-knowledge-base repo,
~/Documents/knowledge-base/topics/audit-skill-three-phase-oracle.md

This is a /capture-format wiki draft. The canonical wiki repo isn't
cloned in the remote execution environment that produced this file,
so it lives here in claude-config under docs/wiki-drafts/ until
someone copies it across on a machine with the wiki repo checkout.

Copy everything below this HTML comment, then remove this file
from claude-config in the same commit.
-->
---
title: audit-skill — three-phase oracle design
stage: budding
tags: [audit, dev-tooling, oracle, verification, retrospective]
aliases: [audit-skill-oracle, three-phase-audit, oracle-verification-layer]
created: 2026-05-25
updated: 2026-05-25
---

# audit-skill — three-phase oracle design

> The audit-skill became a **three-phase contract** in May 2026:
> mechanical lint (Phase 1) → agent scenario audit (Phase 2) → oracle
> gating (Phase 3). Each phase closes a failure mode the prior phase
> structurally can't catch. This page captures the architectural
> decisions and the empirical numbers behind them.

---

## Decision: a verification layer (the "oracle") gates Phase 2 findings (2026-05-25)

**Problem.** Phase 2 agents produce findings; downstream batches act on
them. In the May 2026 fix campaign, 38% of attempted fixes were against
findings that had already been resolved by parallel work. The agent
notification path proved unreliable for "is this batch done?" because
notifications can be lost in long sessions. The static-tracker model
proved unreliable because the tree moved between discovery and action.

**Alternatives considered.**

1. *Better agent notifications.* Rejected — fixes the symptom (lost
   messages), not the root cause (using agent reports as truth).
2. *Re-run Phase 2 before every fix-batch.* Rejected — re-dispatching
   89 agents costs ~$10-30 and 30+ minutes per cycle. The cost
   asymmetry is wrong (verification more expensive than acting).
3. *Manual review gate.* Rejected — doesn't scale to ≥30 findings;
   becomes a bottleneck.
4. *Build a verification layer (decided).* Mechanical reproducer
   replays against the live tree; runs in ~ms-seconds per finding;
   produces a structured verdict whose semantic content is explicit.

The decided path satisfies the [[oracle-construction]] principles:
externally grounded (different mechanism than the LLM proposer),
verification procedure not entity (invokable, repeatable, traceable),
semantic content explicit (positive verdict means "the deterministic
predicate returned True against the working tree today" — NOT "bug
confirmed").

## Pattern: paired calibration fixtures stress-test reproducer specificity (2026-05-25)

**The pattern.** When labeling known-good and known-bad findings for
TPR/TNR measurement, deliberately construct **paired fixtures** that
exhibit *the same textual surface pattern* but differ in whether
the underlying bug is real.

Example from `tests/golden-findings/calibration/`:
- `true_fixture/SKILL.md`: contains `{baseDir}` outside backticks (real
  P1 bug — placeholder rendered literally to the agent).
- `false_fixture/SKILL.md`: contains `{baseDir}` **inside backticks** as
  an inert example mentioning the placeholder syntax (no rendering).

A too-narrow reproducer (`grep -q '{baseDir}'`) would correctly find the
true case AND incorrectly fire on the benign sibling. The pair forces
the reproducer to encode the *meaningful* difference (fence-aware
parsing), not just match the surface text.

This is the test-design analog of [[counterfactual-grounding]]: the
calibration is only as strong as the hardest near-miss it includes.

**Where this came from.** First-run TPR on the calibration set was
0.6 — Layer A's bash reproducer semantics were inverted (`fires = rc
!= expected_exit` instead of `rc == expected_exit`). The pair caught
it within 30 seconds of running. Without the pairs, individual
findings would have passed in isolation but the bug would have shipped.

## Decision: rename "consensus" → "ensemble" (honest framing about decorrelation limits) (2026-05-25)

**Problem.** The Phase 2 oracle has a layer that dispatches N agents
against the same skill and retains only findings ≥M of them report.
Original name: "consensus." Implied a guarantee the mechanism does not
provide.

**The honest bound.** Kim et al. ICML 2025: cross-vendor LLM judges
agree 60% of the time when both err. Ensembling buys *modest*
decorrelation against single-agent hallucination, NOT categorical
decorrelation against systematic misjudgment.

**Decision.** Rename "consensus" → "ensemble." Update the docstring +
SPEC.md to state explicitly: Tier 3 (soft evaluator), same mechanism
as the proposer, **use only as a pre-filter for high-stakes
behavior-fix findings, composed with Layer A's mechanical reproducer,
never as the sole verdict.** Tests pin the honest-framing markers in
the docstring ("NOT a decorrelated oracle", "Kim et al", "same
mechanism") so future maintainers can't quietly remove them.

The lesson generalizes: **naming an LLM-ensemble step "consensus"
launders epistemic strength the mechanism doesn't have.** Use the
weakest-honest term.

## Pattern: structural fixes vs mitigations (2026-05-25)

The May 2026 retro identified six root causes for the 38% stale rate.
Each got both a **mitigation** (handles the failure at runtime) AND a
**structural fix** (makes the failure mode impossible).

| Cause | Mitigation | Structural fix |
|---|---|---|
| Static tracker / live-tree mismatch | `act_on` re-verifies before action | `discover` one-shot replaces the tracker entirely |
| Parallel batch overlap | `act_on` catches side effects | Per-skill atomic `O_CREAT|O_EXCL` claim locks |
| Skippable gate | SKILL.md mandates Phase 3.5 | `validate.py` REJECT_PROSE_INPUT (raw trackers rejected at boundary) |
| Long-session state churn | `act_on` returns fresh verdict | `validate.py` REJECT_STALE_RECORD (30-min TTL on worklists) |
| Phase 2 LLM false positives | Layer B ensemble (modest) | `templates/phase2-prompt.md` requires self-verified reproducer at emission time |
| Prose findings (no predicate) | best-effort converter | `validate.py` REJECT_NO_REPRODUCER (manual findings can't enter dispatch) |

The distinction matters because **mitigations live inside a single
workflow; structural fixes change the API contract.** Mitigation alone
relies on every future workflow remembering to invoke the gate. The
structural fix makes "forgot to invoke the gate" impossible because
the API rejects unverified input.

This pattern generalizes to any LLM-orchestrated workflow: **don't
trust the orchestrator to call the verifier.** Make the verifier the
input shape.

## Lesson: the calibration set is the spec's audit trail (2026-05-25)

The `SPEC.md` for the oracle was written first — verdict semantics,
tier classification, decorrelation analysis, cost asymmetry per layer.
But spec text alone is performative. The N=30 labeled calibration set
(`tests/golden-findings/calibration/findings.yaml`) is what makes the
spec falsifiable:

- The spec claims Layer A's positive verdict means "the predicate
  returned True against the tree at the trace timestamp." The
  calibration set is paired examples where that statement is the
  ONLY thing the predicate proves — everything else (whether the bug
  is "real" in the broader sense) requires human judgment.
- The spec floors are documented (TPR ≥ 0.95, TNR ≥ 0.80). The
  calibration test fails the build below either floor. Future
  maintainers can't silently degrade the layer.

**Without the calibration set, the spec is folklore. With it, the
spec is enforceable.**

## Bridge to /distill

The operational lessons (don't use agent notifications as truth, pair
fixtures to stress specificity, schema-enforcement at the API boundary
beats prose discipline, calibration before deployment) live in
`agent-memory/topics/engineering-philosophy.md` "Audit + dev-tooling
discipline" — applied where they bite.

This page is the strategic-narrative side; agent-memory carries the
operational do-this / don't-do-this lessons.
