# audit-architecture — run history

Dated measurements behind the rules in SKILL.md. The rule lives in SKILL.md; the
evidence lives here.

## Phase 0 — checkout currency (stale-base guard)

- 2026-06-16: a 29-behind checkout produced two D3 findings — topic count,
  hook-manifest count — already fixed on main; both would have been "re-fixed" to
  wrong values.
- 2026-07-24: a 34-behind tree surfaced 5 undocumented doc items when the true
  `origin/main` set was 8; the 3 extra (a skill + 2 topics) were structurally
  invisible against the stale tree. Auditing the stale tree yields an INCOMPLETE
  finding SET, not just uncertain counts.
- 2026-08-22: `origin/main` carried a newer Phase 0 executable-collision guard
  step that the deployed SKILL.md copy lacked; it was nearly skipped. The redirect
  now covers the skill's own definition.

## Phase 0 — performance probes (2026-08-22)

- A generic `mcp` `pgrep` pattern swept in Claude Helper, SkyComputerUseClient,
  and Palantir browser processes, inflating the "MCP footprint" to a meaningless
  15 GB. Derive the substring per server from its exec'd form.
- System `pip show fastmcp` reported NOT INSTALLED on a venv-launched fleet while
  every server ran fine; the version must be read through each server's own
  launch interpreter.

## Phase 1 — discovery script (2026-08-22)

Hand-rolled coverage matchers produced two false gaps; `discovery.py` with the
maintained alias map replaced them.

## Phase 7A — meta-reference false positives (2026-05-26)

The scanner's "broken refs" check flagged three meta-references as broken files:

- `` `references/X.md` `` inside prose like "For each `references/X.md`, identify
  ..." (X is a placeholder, not a filename)
- `path: skills/<skill>/references/missing-ref.md` inside a YAML schema EXAMPLE
  (the file is intentionally absent — a synthetic fixture for the audit pattern
  itself)
- `references/search-waves.md` cited inside a `reason: invoked via X` example
  (describing what the audit looks for, not citing X)

## Phase 7A — findings file deleted mid-run (2026-07-24)

On this contended host a parallel session deleted the canonical
`audit-architecture-findings.yaml` mid-run, silently destroying delta history.
Dated snapshots are the durable per-run record the delta step reads.

## Phase 7C — repo-fix mechanics (2026-08-22, 5-PR fix batch)

The marketplace-regeneration and worktree-cleanup rules in Phase 7C were measured
on a five-PR fix batch: every merge invalidated every other open branch's
generated `marketplace/` files, and two audit worktrees were left behind.
