# Weekly Update Skill Design

**Date**: 2026-03-09
**Status**: Approved
**Approach**: Pure skill (Approach A) - all data collection and synthesis in model context

## Skill Identity

- **Name**: `weekly-update`
- **Default window**: 7 days, configurable (`/weekly-update 3d`, `/weekly-update 14d`)
- **Default channel**: `#alerts` (C0AAL6V10JX)
- **Output format**: Slack mrkdwn (not GitHub markdown)
- **Target length**: 3,000-4,000 characters

## Data Collection (4 parallel streams)

### Stream 1: Merged PRs (primary unit for protected repos)

```
gh pr list -R example-org/<repo> --state merged --json number,title,body,mergedAt
```

Repos: mcp-servers, mcp-infra, claude-config, example-compliance-repo, example-sbom-tool

PR body contains the "why" context. Title gives conventional-commit prefix for thematic clustering.

### Stream 2: Git commits (unprotected repos only)

```
git -C <path> log --oneline --since="<window>"
```

Repos: knowledge-base, obsidian-infra

### Stream 3: Session learning reports

Read .md files from ~/.claude/session-transcripts/ matching date range. Dedup by hex session ID suffix (last 8 chars), keep latest per session.

### Stream 4: Knowledge base diffs

```
git -C <kb-path> log --oneline --name-only --since="<window>"
```

Track research/ and topics/ files specifically.

## Thematic Grouping

Cluster by theme, not repo or date:
1. Group PRs by conventional-commit scope (e.g., feat(claude-proxy) across repos)
2. Group by capability area when scope missing
3. Research/knowledge gets own section if 3+ topics updated
4. Session-only work folded into relevant themes
5. Empty themes omitted entirely

## Slack Formatting

- *bold* for section headers (not **bold** or #)
- Bullet points with plain -
- Emoji sparingly for visual anchors
- Code/repo names in backticks
- No markdown headers

## Review + Post Flow

1. Generate narrative
2. Present draft for review
3. On approval, post via conversations_add_message to C0AAL6V10JX
4. Report permalink

## Murderboard Mitigations

| Problem | Fix |
|---------|-----|
| No lived context | Use PR descriptions (body), not just titles |
| Research invisible | Scan knowledge-base research/ and topics/ commits |
| Slack mrkdwn | Explicit formatting rules in skill |
| Double-counting | PRs as primary unit for protected repos, commits for unprotected |
| Message length | Target 3,000-4,000 chars |
| Thematic grouping | Cluster by conventional-commit scope + capability area |
| Transcript dedup | Dedup by hex session ID suffix, keep latest |
