---
paths:
  - "**/rules/complete-the-whole-instruction.md"
  - "**/rules/incidents/complete-the-whole-instruction.md"
---

# complete-the-whole-instruction: Incident Narratives

Extracted from `rules/complete-the-whole-instruction.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## a-pr-is-a-unit-of-shipping-not-a

```
WHY: a PR is a unit of SHIPPING, not a unit of DONE. An instruction is
     complete when the USER'S whole ask is satisfied end to end — which may
     be several PRs. "I merged a green PR" answers "did I ship something,"
     NOT "did I do what was asked." Never let the PR boundary truncate the
     instruction.
```

## the-failure-is-silent-because-the-hard-part-is

```
WHY: the failure is silent BECAUSE the hard part is never named out loud —
     it just quietly becomes "next" after the easy part ships. Naming it
     up front makes deferring it a visible choice, not a default drift.
```

## tests-pass-it-builds-the-pr-merged-is-component

```
WHY: "tests pass / it builds / the PR merged" is component-green. The user
     experiences the SEAM (a live call, a visible screen, the whole multi-
     part behavior). A claim of "done" that never crossed the seam the user
     will hit is a claim about the component, not the deliverable.
     (Pairs with verify-effectiveness.md multi-seam invariant.)
```

## if-evidence-a-design-doc-a-measurement-the-code

```
WHY: if evidence (a design doc, a measurement, the code) says the thing
     you're about to build ON may be the wrong foundation, building anyway
     is the most expensive form of half-assing — it ships polished work on
     a premise the user would have re-decided. Surface it the moment you
     see it, BEFORE the next build, even when it threatens work in flight.
```

## what-the-code-does-is-not-what-it-was

```
WHY: what the code DOES is not what it was SUPPOSED to do. Inferring the
     goal from the current code's behavior re-implements the bug — you build
     toward the broken present, not the intended design. When the repo HAS
     source-of-truth docs (SPEC.md, a design doc, the original brief, a
     tarball of intent), READ THEM to learn the goal BEFORE forming the plan;
     the code is evidence of the current state, the docs are evidence of the
     target. INCIDENT 2026-06-29 Claudinator: the Experiments tab rendered
     findings, so I concluded "Experiments = findings" and RENAMED the tab —
     moving AWAY from the SPEC's actual intent (a runnable battery catalog).
     User: "you are wrong... going off on misguided tangents... review the
     initial .md files for the original intent. This is a non-functional app."
     The rename treated the symptom (wrong data shown) and missed the disease
     (the battery run-flow was never built). Reading SPEC §10 FIRST would have
     given the real scope; reading the code gave a confident wrong answer.
```

## many-prs-many-tests-many-worktrees-read-as-thoroughness

```
WHY: many PRs / many tests / many worktrees read as thoroughness and HIDE
     a half-met instruction. The honest completeness check is "is the
     USER'S ask fully satisfied," never "how much did I produce."
```

## the-2026-06-29-judge-incident-canonical-technique-shipped

```
WHY: the 2026-06-29 judge incident — "canonical technique" shipped without
     one live call; the smoke harness that would have caught it was not run;
     it failed every call in production.
```

## 2026-06-29-inferred-experiments-findings-from-the-rendered

```
WHY: 2026-06-29 — inferred "Experiments = findings" from the rendered code,
     renamed the tab, moved away from the SPEC's real intent (a runnable
     battery catalog). User: "you are wrong... review the initial .md files."
```

## 2026-07-31-cloudtrail-athena-bandwidth-the-user-s

```
INCIDENT 2026-07-31 CloudTrail/Athena bandwidth: the user's literal, REPEATED ask was
"reduce the bandwidth". Ten PRs of diagnosis, correctness fixes and safety-gating shipped
first -- every one of them genuinely real work -- while the plan's OWN text already marked
two bandwidth levers as touching no judge input and shippable independently. The design was
in hand roughly an hour before the user's pushback: "I made one simple request and you keep
failing to act on it. This is unacceptable."
The trap is that each prerequisite was defensible ON ITS OWN, which made the deferral
SELF-SUSTAINING: there was always a real next thing, so nothing ever presented as a choice
to skip the deliverable. Distinct from shipping a tractable HALF (the failure above) -- here
nothing of the ask shipped at all, and the plan itself said it did not have to wait.
```
