# Preconditions, Missing Baselines, and Graceful Degradation

Consult from Step 0 (gh precondition rationale), Step 1 (missing baseline files), and any
mid-run source failure (degradation table).

## Step 0: why a missing `gh` aborts the run

If `gh` is missing, abort the skill with the exit-2 message. Do NOT fall
back to "Web Track only" — the architecture audit and CHANGELOG parse both
require `gh api` calls. The original precondition note ("gh CLI
authenticated") covered auth but not installation; an unauthenticated `gh`
fails fast with a clear error, but a missing `gh` produces a confusing
`command not found` mid-run.

**Auditing note (verification environments):** This abort path is the
intended behavior — it means the documented `gh ...`, `tavily_*`, and
`web_*_exa` commands are only exercisable on a host with `gh` installed
+ authenticated and the Tavily/Exa MCP servers attached. Auditors
re-running the literal commands from this skill must do so on such a
host; sandbox environments without `gh` will (correctly) terminate at
Step 0 before any command is exercised. `claude --version` is the only
command verifiable in every environment.

## Step 1: missing baseline files

Any of Step 1 items 1, 2, 3, or 5 may be absent on fresh deployments,
worktrees, or first-run sessions. For each file: if Read returns ENOENT,
log the missing path in the Sources Log (`baseline: ARCHITECTURE.md absent`)
and continue with the remaining reads. Do NOT abort the skill — the audit
still produces value from whichever baseline files are present. The only
required baseline is item 4 (rules); if those are missing the deployment
itself is broken and the user should be told.

## Graceful degradation table

| Failure | Action |
|---------|--------|
| Tavily empty | Retry with `site:` prefix or broader keywords |
| `gh` missing at Step 0 | Abort with exit 2 (per Step 0 precondition). Do NOT continue with web track only — the architecture audit and CHANGELOG parse both require `gh api` calls. |
| `gh` authenticated but a single command errors mid-run | Note the failed query in the report's Sources Log, skip that one query, continue with remaining `gh` and web-track queries |
| Step 1 baseline file (ARCHITECTURE.md, MEMORY.md, CLAUDE.md, prior report) absent | Log the missing path in Sources Log (`baseline: <path> absent`) and continue with remaining baselines. Phase A workaround scan operates on whatever loaded successfully; if every baseline is absent, surface "no prior architecture state — Phase A skipped" and run Phase B only. |
| URL 404 | Note in report, skip |
