# pr-fix Examples

Worked examples showing how the skill behaves across its three item types (PR, CI, BR), direct invocation, iterate mode, and combined multi-fix sessions.

## Example 1: Discovery finds two stale PRs

User says: `/pr-fix`

Discovery runs the involvement searches (author/review-requested across orgs, full sweep of example-org) plus local-clone axes (branch hygiene, dirty trees), and finds:
- claude-config #290: `validate` check failing (JSON syntax error)
- code-graph #15: `Build` check failing (Go compilation error)

User picks #1. Skill reads `gh run view --log-failed`, sees JSON parse error at line 86. Reads `settings.json`, finds missing comma. Fixes it. Pushes to branch. Reports. Asks if user wants to fix #2.

## Example 2: Direct fix for a known PR

User says: `/pr-fix mcp-servers#201`

Skips discovery. Fetches PR #201 details, reads failing check logs, sees Python import error in `hologram/server.py`. Checks out branch, fixes import, pushes. Reports.

## Example 3: Infrastructure failure

User says: `/pr-fix`

Discovery finds mcp-infra #259 with failing `plan` check. Reads logs: runner timed out after 10 minutes. Reports: "Infrastructure failure - runner timeout, not a code issue." Offers `gh run rerun 23456 --failed`. User approves, skill triggers rerun.

## Example 4: Commit CI failure on main

User says: `/pr-fix`

Discovery finds no failing PRs, but commit CI shows mcp-servers main@b942dd3 with `Catalog Drift Detection` failing (scheduled workflow). Reads logs: drift script can't find `AWS_REGION` env var. Creates `fix/catalog-drift-env` branch, adds the env var to the workflow file, pushes, creates PR #305 with auto-merge queued. Reports.

## Example 5: Branch cleanup

User says: `/pr-fix`

Discovery finds no failing CI but 3 repos with stale branches: claude-config (55 branches, 52 merged), mcp-infra (45, 41 merged), mcp-servers (25, 22 merged). User picks 'branches'. Skill lists all merged branches per repo, confirms with user, then batch-deletes via `git push origin --delete`. Reports: "Cleaned 115 merged branches across 3 repos."

## Example 6: Iterate until green

User says: `/pr-fix mcp-servers#201 --iterate`

Skips discovery. Diagnoses: ruff format failure. Fixes formatting, pushes. Waits 90s, polls CI. Cycle 1 passes ruff but now errcheck fails (new issue exposed). Reads logs, fixes missing error check, pushes. Waits 90s, polls CI. All checks green. Reports: "Fixed in 2 cycles: ruff format (cycle 1), errcheck (cycle 2). All checks passing."

## Example 7: Mixed PR and commit failures

User says: `/pr-fix`

Discovery finds 1 failing PR (code-search #23, `analyze` check) and 2 commit CI failures (mcp-servers main — gitleaks, mcp-infra main — Secret Scanning). User picks 'all'. Skill processes the PR fix first (push to existing branch), then each commit CI fix (create fix/ branch + PR for each). Reports combined summary table.
