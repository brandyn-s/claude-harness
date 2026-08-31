# Tuning Notes — Shared Convention

Skills with load-bearing numeric thresholds (cosine cutoffs, percentage
gates, day-window heuristics, etc.) should keep a local
`references/tuning-notes.md` that tracks empirical evidence for each
threshold. This makes future tuning decisions defensible — and makes
it obvious when a threshold has *no* evidence and is just an inherited
guess.

## Format

```markdown
# Tuning Notes

## Threshold: <name> (current value: <value>)

**Used by**: <SKILL.md location, e.g., "Step 3 dedup gate">
**Effect**: <what changes if you raise or lower it>

### Evidence
- YYYY-MM-DD — <PR/commit/incident> — <observed outcome>
- YYYY-MM-DD — <PR/commit/incident> — <observed outcome>

### Open questions
- <unresolved tradeoff, missing measurement, etc.>
```

## Discipline

1. **One entry per change.** When you adjust a threshold, append a
   dated row citing the PR/commit and the observed outcome. Do not
   silently change numeric constants without logging here.
2. **Evidence is concrete.** "Worked in my testing" is not evidence —
   cite a PR number, an incident date, a precision/recall count, or a
   measurable behavior change.
3. **No evidence = honest gap.** If a threshold has zero entries, that
   is itself useful information: future maintainers know the number is
   inherited and the gap should be closed before tightening it.
4. **Open questions are first-class.** Surface what you don't know
   (e.g., "no precision/recall data exists for this gate") alongside
   what you do.

## Reference exemplar

`skills/recall/SKILL.md` cites PR #559's Phase 9 review as evidence for
its 0.7 / 0.65 thresholds — that is the standard to match.
