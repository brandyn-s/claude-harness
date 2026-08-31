# Terminal doc — what gets written when supergoal exits

## When it fires

Step 7 always runs when `/goal` exits, regardless of exit reason:

- `success` — demo achieved
- `falsifier-<name>-triggered` — a falsifier observation evaluated true
- `budget-exhausted` — turn or token cap reached
- `plan-tampered` — plan SHA-256 changed mid-loop
- `scorer-broken` — verifier itself crashed mid-run (exit code in `scorer_broken_codes`); requires human review before re-attempting
- `stuck-no-progress` — `consecutive_no_progress` hit `max_stuck` (default 3) without demo-achieved or metric improvement

Skipped silently only if `~/Documents/knowledge-base/plans/` does not exist (no substrate to persist into).

## Path

`~/Documents/knowledge-base/plans/<plan-slug>-terminal.md` — sibling of the original plan file. Same naming convention as superplan Step 5a's `<slug>-baseline.md`.

## Required sections

### Header

```
# Terminal doc: <slug>

**Date**: YYYY-MM-DD
**Plan**: `<plan-path>`
**Exit reason**: <reason>
**Turns**: <used>/<total>
**Tokens**: <used>/<total>
```

### Per-phase freshness verdict

Re-measured baselines at exit. For each baseline metric:
- value at plan start (from `baseline.currently_N`)
- value at exit (re-measured by the hook just before exit)
- delta + interpretation (improved / regressed / unchanged)

If the hook hadn't re-measured recently, run the metric_commands one final time before writing.

### Re-diagnosis

Fires when exit reason is not `success`. Captures:
- What the failure observation was (falsifier text + measurement)
- What this means for the plan's hypothesis (rewrite in light of the observation)
- What substrate / layer / mechanism is now suspected as the actual lever

### Retired hypothesis

The plan's proposed mechanism, marked as "did not move <metric>." This is what the prior-arc check in the next session will read.

Format: `<mechanism>: did not move <metric> (currently_N=<x> → expected_M=<y>, exit measurement=<z>)`

### Named next-plan target

If exit reason is not `success`: what should a successor plan investigate? Be concrete — name the substrate, layer, mechanism, or measurement. Avoid "investigate further" / "look into" / vague verbs.

Example: `Next: instrument the resolver's fanout step before patching; current measurements conflate fanout and dedup. Lift candidate: dedup pass.`

### Lineage

The chain of prior terminal docs for the same metric (from state.lineage when `--force-rerun` was set). Includes the current attempt's plan path as the latest entry.

If there were no prior arcs, the section reads "First attempt on these metrics. No prior arcs."

## Why these sections

Each section serves a downstream consumer:

| Section | Read by | What they need |
|---------|---------|---------------|
| Header | future plan authors | Quick context: when, what, what happened |
| Freshness verdict | future plan authors | "Was the baseline still valid when this ended?" |
| Re-diagnosis | future plan authors | "What's the new hypothesis?" |
| Retired hypothesis | prior-arc check script | grep-able list of failed mechanisms |
| Next-plan target | future plan authors | "Where do I start?" |
| Lineage | prior-arc check script | Chain detection across many sessions |

The format is markdown so humans can read it; the structure is regex-stable so `check_prior_arcs.py` can mine it.

## Git+PR flow

After writing the file, `write_terminal.py`:

1. `git checkout -b terminal/<slug>` in the KB repo
2. `git add <terminal-path>` + `git commit -m "terminal(<slug>): <exit-reason>"`
3. `git push -u origin terminal/<slug>`
4. `gh pr create --title ... --body ...`
5. `gh pr merge --auto --squash --delete-branch`

Failures (no .git, no gh, push denied) are surfaced but non-fatal: the file is written locally even if the commit/PR flow fails. The user can recover manually.

## Composition with future runs

Next-session superplan, Phase 2d:
1. Globs `~/Documents/knowledge-base/plans/*-terminal.md`
2. Greps for the new plan's metric names
3. Hits surface in the prior-arc ledger that Phase 2d emits
4. The new plan must position its mechanism against the retired hypotheses

Next-session supergoal, Step 2 (prior-arc check):
1. Globs the same terminal docs
2. Refuses re-litigation by default
3. With `--force-rerun`, attaches the lineage chain to the next terminal doc

Both checks read the same terminal docs. The structure-stable sections (Retired hypothesis, Lineage) make this composition robust.
