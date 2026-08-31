---
paths:
  - "**/rules/compare-by-need.md"
  - "**/rules/incidents/compare-by-need.md"
---

# compare-by-need: Incident Narratives

Extracted from `rules/compare-by-need.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## asymmetric-bar-no-incident-defer-documented-friction-implement

```
WHY: asymmetric bar ("no incident = defer, documented friction = implement")
     biases toward inaction. absorb batch (2026-04-05): 3/3 deferrals
     flipped to IMPLEMENT when challenged.
```

## additive-changes-have-trivial-adoption-cost-full-red-team

```
WHY: additive changes have trivial adoption cost; full red-team costs
     more than the change. Context7 session (2026-04-05): 7 IMPLEMENT
     → 0 survivors = evaluation bias, not rigor.
```

## 2026-07-26-claude-config-m9-a-report-prescribed

```
WHY: 2026-07-26 claude-config M9 — a report prescribed "describe
orchestration edges in one machine-readable workflow contract, then generate
or validate the prose." `retro/manifest.yaml` ALREADY declared
`requires_skills: [distill, capture, ship, mega-distill]` correctly, and
`ship/manifest.yaml` correctly declared `[]` (its gate is conditional, not a
hard dep). The actual defect: no check compared skill PROSE to the manifest
graph, so one skill's prose asserted `retro>ship` "does not exist" while
another made it mandatory. Fix was ~4 tests, not a subsystem — and because
the check enumerated EVERY declared edge instead of the one already known,
it found a second denied edge (`retro>mega-distill`) no report mentioned.
```

## 2026-03-26-tob-config-recommended-fix-issue-multi

```
INCIDENT 2026-03-26 ToB config: recommended /fix-issue, multi-model PR
review, dependabot graph analysis. All 3 collapsed on actual analysis:
- /fix-issue: Example already covers via /superplan + /ship
- multi-model PR: Example has 0 required approvals; solves non-problem
- dependabot graph: conditional on PR volume never checked
```

## 2026-04-05-absorb-batch-14-recs-6-deferred

```
INCIDENT 2026-04-05 absorb batch: 14 recs → 6 deferred by investigation
agents. User challenged 3; all 3 flipped to IMPLEMENT (strawman
alternatives, mislabeled incidents, inflated implementation costs).
```

## 2026-08-06 — an upstream security fix was not proof of a local defect

Claude Code 2.1.221/223 fixed a zsh `[[ ]]` permission bypass and invisible
approval-dialog padding. An analogous local guard fix looked justified from
that changelog alone. Direct probes instead showed the local raw-command regex
already blocked both shapes, while the one allowed zero-width-space form was
not executable by zsh. The probes then found a different real bypass—ANSI-C
quoting—which the vendor note did not mention. The upstream defect was real;
the unsupported inference was that our implementation shared it.
