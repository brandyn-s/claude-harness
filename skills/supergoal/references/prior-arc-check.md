# Prior-arc check — refusing re-litigation

## Why this exists

`autoresearch`'s lineage docs track a single session's history. superplan's Phase 2d builds a prior-arc ledger from prior plan files. **Neither catches the case where supergoal is invoked on a fresh plan that targets a metric a previous terminal doc already retired.**

The 2026-05-08 multi-plan arc (HTTP_CALLS / IMPLEMENTS) shipped 4 consecutive PRs each proposing a different mechanism for the same metric; none moved it. Each plan author had full confidence; none had checked the prior terminal docs first. This is the failure mode prior-arc-check prevents.

## What it does

1. Read `metric_names[]` from the state file.
2. Glob `~/Documents/knowledge-base/plans/*-terminal.md`.
3. For each, grep for any metric name (whole-word match).
4. If any hits (1-2 arcs), emit a ledger sorted by date and exit 0 (soft warn + proceed). If 3+ arcs, emit a ledger and exit 21 (refuse).
5. If `--force-rerun` was set on a refuse, attach the matched paths as `lineage[]` in the state file and exit 0.

## Ledger format

```
PRIOR-ARC LEDGER — 3 prior terminal doc(s) targeted these metrics:

Date         Exit reason                    Metrics                       Retired hypothesis
--------------------------------------------------------------------------------------------------------------
2026-05-07   falsifier-corpus-drift-trig    HTTP_CALLS                    reqwest URL extraction
2026-05-08   budget-exhausted               HTTP_CALLS,IMPLEMENTS         handler resolution rework
2026-05-09   falsifier-extractor-regressed  HTTP_CALLS                    callsite normalization

REFUSED: prior arcs exist. Re-invoke with --force-rerun to proceed.
        Doing so attaches the lineage chain to the eventual terminal doc.
```

## When to set `--force-rerun`

You should set it when:
- The new plan's proposed mechanism is structurally distinct from every prior retired hypothesis
- You have new evidence (new measurement, new code, new failure mode) the prior plans didn't have
- You're explicitly running a new attempt with different priors and want the lineage attached

You should **not** set it when:
- You haven't read the prior terminal docs (the ledger printed by this script is a teaser; click through and read them)
- The new plan's mechanism is the same as a retired one under a different name
- The metric has only been measured once and isn't worth a re-run

## Lineage propagation

When `--force-rerun` is set, the matched terminal doc paths are added to `state.lineage[]`. `write_terminal.py` emits these in the new terminal doc's `## Lineage` section, so the next session sees the full chain. Arc N+1 will see arcs 1..N when its own prior-arc check runs.

This makes the chain visible across many sessions — exactly the "3 consecutive PRs targeting the same metric" failure mode becomes detectable on the 2nd attempt (would require explicit opt-in to retry).

## Substrate-aware skips

`~/Documents/knowledge-base/plans/` missing → exit 0 with one-line note "no plans dir." No ledger emitted. The user is on a fresh / non-Example system; there are no prior arcs to check.

`metric_names[]` empty → exit 0 with one-line note "no metric_names in plan." Either the plan's metrics are lowercase / non-standard (the regex didn't catch them — fix the plan's metric naming), or the plan is structural (no measurable metric — supergoal might be the wrong tool).
