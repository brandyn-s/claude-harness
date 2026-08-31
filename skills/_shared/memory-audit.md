# Shared Memory Audit Reference

Canonical list of memory locations and health checks. Used by `review-learnings`,
`healthcheck`, `audit-architecture`, and `garden` to avoid divergent logic.

## Memory locations

| Path | Purpose | Tracked in git? |
|---|---|---|
| `~/.claude/agent-memory/topics/*.md` | Per-topic operational knowledge (API gotchas, platform notes, tool patterns) | Yes (except `recent-sessions.md`) |
| `~/.claude/agent-memory/sentinel/baselines.md` | Audit baseline snapshots | Yes |
| `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/MEMORY.md` | Global auto-memory index (<150 lines) | Yes |
| `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/*.md` | User/project/feedback/reference auto-memory entries | Yes |
| `~/Documents/knowledge-base/topics/*.md` | Digital garden — multi-session strategic knowledge | Yes (separate repo) |
| `~/.claude/session-transcripts/*.jsonl` | Session transcripts | No (local only) |

## Legacy directories (known non-legacy — don't flag)

- `agent-memory/sentinel/` — audit baselines, active state. NOT legacy.
- Any directory not listed above under `agent-memory/` IS legacy from the pre-2026-03-25
  per-agent architecture — flag for migration or deletion.

## Gitignored files

- `agent-memory/topics/recent-sessions.md` — transient cross-session history, never committed.

## Shared audit checks

Any skill auditing memory health should run these in order:

1. **Directory inventory** — ls topics/, flag non-`topics/` subdirs under `agent-memory/` as legacy
2. **Git-tracked check** — `git ls-files agent-memory/topics/` to confirm which are committed
3. **Tag hygiene** — count `[promoted]` tombstones (0 expected), `PROMOTE-CANDIDATE` (0 expected),
   `[FIXED]` (should be 0 — fixes live in git history)
4. **Stale observed** — `[observed]` entries older than 30 days → candidate for `[confirmed]` or prune
5. **Version staleness** — entries with version tags older than `claude --version` → prune
6. **MEMORY.md sync** — every MEMORY.md link resolves; every memory/*.md is linked

## Shared health thresholds

| Metric | Threshold | Action |
|---|---|---|
| MEMORY.md line count | >150 | WARN — approaching 200-line truncation |
| Session transcripts | 0 | FAIL — knowledge capture broken |
| `[promoted]` tombstones | >0 | Always prune |
| `PROMOTE-CANDIDATE` entries | >0 | Always surface for user action |
| Stale `[observed]` (>60 days) | >5 | Bulk confirm-or-prune sweep |
| Topic file line count | >500 | Consider splitting |

## Not in scope here

- **Rule compliance** (violation rates, defense layers) — owned by `audit-rules`
- **File path staleness across skills/hooks/config** — owned by `healthcheck` Check 5
- **Architecture count drift** (ARCHITECTURE.md vs disk) — owned by `healthcheck` Check 6
