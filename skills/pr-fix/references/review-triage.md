# Review Triage — Phase 3-review

For `[PR-REVIEW]` items: PRs authored by someone else where I am on
`reviewRequests` or otherwise on the hook for the review. The skill
never auto-approves or auto-merges these — the point is the review
itself.

## Critical Gotchas

- **Never auto-merge a `[PR-REVIEW]` item.** Even if CI is green and the
  diff looks small, the user explicitly needs to review it. Automating
  the merge defeats the purpose.
- **Never push a review approval from the skill.** The approval is the
  reviewer's judgment call. The skill surfaces context; the reviewer
  decides.
- **Do not summarize sensitive diffs verbatim in the output.** If the PR
  touches credentials, security configuration, or anything flagged as
  `.env` / `.pem` / `credentials.json`, redact the values in the summary.

## Per-PR summary format

```
[PR-REVIEW] <org/repo> #<n>  <title>
  Author:     <login>  (opened <N>d ago, last updated <M>d ago)
  Branch:     <headRefName>
  Size:       +<additions> / -<deletions> across <file count> files
  CI state:   <green|red|pending>  — list any failing required checks
  Mergeable:  <MERGEABLE|DIRTY|BLOCKED>
  Top files:  (up to 5, ranked by churn)
              - path/to/file.py  (+40 -10)
              - ...
  Category:   (feat | fix | chore | docs | ci | refactor | security)
  Scope hint: 1-2 sentences inferred from title + top files
  Blockers:   list any (failing CI, conflicts, draft, unresolved threads)
```

## Query to produce the summary

```bash
gh pr view <n> --repo <org/repo> \
  --json title,author,createdAt,updatedAt,headRefName,additions,deletions,changedFiles,mergeable,mergeStateStatus,reviewRequests,reviews,statusCheckRollup,files \
  --jq '{
    t: .title,
    a: .author.login,
    created: .createdAt,
    updated: .updatedAt,
    branch: .headRefName,
    adds: .additions,
    dels: .deletions,
    files: .changedFiles,
    top5: [.files[] | {path, churn: (.additions + .deletions)}] | sort_by(-.churn) | .[0:5],
    ms: .mergeStateStatus,
    ci: ([.statusCheckRollup[] | select(.conclusion=="FAILURE") | .name])
  }'
```

## Output

Present all `[PR-REVIEW]` items as a bulleted list with the per-PR
summary. End with:

```
Review queue: N PRs awaiting your review.
Open each one in order of blocking-criticality (failing CI first,
then oldest, then largest-scope).
```

Do NOT proceed to merge. Stop after presenting.

## When the PR is clearly unblocked and trivial

For PRs that are obviously low-risk (tiny dependabot-adjacent changes
authored by others, green CI, single-line config tweaks), you MAY
suggest the user queue `--auto`, but always with explicit "want me to
queue auto-merge?" confirmation. Never proceed silently.

## Example — real case from 2026-04-23 session

Two of the 16 digest PRs belonged in `[PR-REVIEW]`:
- `mcp-servers #259` (dylan-example, 18d) — `Add example-falcon MCP
  server`. Substantive: new MCP service with auth flow. Blockers: 1
  `dependency-audit` failure. Flagged to user — new-server review is
  architectural, not mergeable without inspection.
- `mcp-infra #286` (dylan-example, 18d) — `Add example-falcon to
  mcp_services`. Pairs with #259 (Terraform registration). Same
  decision: flag, do not merge.

Both were summarized with size + CI state and handed back to the user.
