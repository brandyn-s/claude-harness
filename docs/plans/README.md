# docs/plans/

Working directory for plan documents. This is a **convention, not an archive**.

`/superplan` and `/superpowers:brainstorming` write plan files here, and
`tests/superplan/` asserts on the path. Keeping plans on disk
is what lets a later session pick up an earlier one's intent instead of
reconstructing it.

## Convention

```
docs/plans/YYYY-MM-DD-short-slug.md
```

A useful plan states the objective, the falsifiers (what would prove the approach
wrong), and a demo line — the observable outcome that means it is done. `/supergoal`
reads those fields to decide when to stop.

## Why this directory shipped empty

The 37 historical plans from the private original were removed from this export.
They documented work on systems that are not here, so to an outside reader they were
residue rather than reasoning. The convention is the transferable part; the same
choice was made for `agent-memory/` and `skills/_shared/repo-map.md`.

The plans here now are the ones about this repository itself:

- `2026-09-06-lean-core-ab.md` — the pre-registered A/B for the lean ambient rule
  core; `bin/lean-core-ab.py` implements its arms and its fixed decision rule.
