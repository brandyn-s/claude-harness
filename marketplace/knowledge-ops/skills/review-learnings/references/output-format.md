# Review Learnings — Output Format & Lossy Compression Guidance

## Lossy Compression Assessment (Step 14)

> DO NOT recommend by default.

- **Never propose consolidation proactively.** Detailed entries contain exact error strings, root-cause narratives, stack traces, and PR numbers that power semantic search matching and variant issue recognition. Compressing them into summary bullets loses this value.
- **Cost-benefit gate**: If the user explicitly requests consolidation, compute before proposing:
  1. Token savings: `(lines to remove × ~15 tokens) / 1M context` as percentage
  2. Search terms lost: count unique error messages, API-specific terms, and stack trace fragments that would be removed
  3. Present: "Consolidating these N entries saves ~X tokens (Y% of context) but removes Z unique error strings from semantic search."
  4. **If savings < 5% of context, say "not worth it" and skip.**
- **If consolidation proceeds** (user insists after seeing the tradeoff):
  - Use `[consolidated]` tag on merged blocks — NEVER `[confirmed]`. Original entries may have been `[observed]` (single occurrence). Merging under `[confirmed]` silently inflates confidence.
  - Preserve evidence provenance in every consolidated bullet (PR numbers, session counts, error counts).
  - Keep exact error strings in the consolidated version even if the narrative is compressed.

## Output Format

```
### Agent Memory Audit — {date}

#### Knowledge Capture Health
- Transcripts saved: {count}
- Recent /distill invocations: {count from last retro}
- Recent /capture invocations: {count from last retro}
- Status: {healthy / WARNING: description}

#### Summary
| Topic File | Entries | [observed] | [confirmed] | [promoted] | PROMOTE-CANDIDATE | Last Modified | Issues |
|------------|---------|------------|-------------|------------|-------------------|---------------|--------|
| security.md | {N} | {N} | {N} | {N} | {N} | {date} | {count} |
| crowdstrike.md | {N} | {N} | {N} | {N} | {N} | {date} | {count} |
...

#### Legacy Artifact Check (P0)
| Directory | Contents | Status | Action |
|-----------|----------|--------|--------|
| {path} | {description} | {unique/duplicate/empty} | Delete / Migrate to topics/ |

#### Issues Found

**PROMOTE-CANDIDATE entries** (3+ observations, awaiting promotion to agent .md):
- [{topic}] {entry title} — {N} observations, action: promote to {agent}.md

**Promoted tombstones** (dead weight — remove immediately):
- [{topic}] {entry title} — already moved to {destination}

**Time staleness** ([observed] > 30 days):
- [{topic}] {entry title} — last seen {date}, age {N} days

**Write-only memory** (access_count=0 AND age > 30 days — never retrieved since creation):
- [{topic}] {entry title} — created {date}, age {N} days, access_count=0
  Cause: {poor discoverability / low value / covered elsewhere}
  Action: {reword title with specific keywords / prune / prune (covered at higher tier)}

**Version staleness** (workaround/until tags with satisfied constraints):
- [{topic}] {entry title} — tagged {tag}, current version {version}

**Contradictions** (memory vs topic/patterns file or CLAUDE.md):
- [{topic}] {entry title} — contradicts {source}

**Cross-agent duplicates** (same pattern in multiple agents):
- {entry title} — in [{topic1}] AND [{agent2}]
  Suggestion: keep in {recommended agent}, remove from other, or move to {topic}-patterns.md

**Global memory overlap** (duplicated between agent memory and global auto-memory):
- [{topic}] {entry title} — also in global MEMORY.md section {section}

**Format inconsistencies** (mixed header/bullet styles confuse pruning logic):
- [{topic}] Uses both `### [tag]` headers and `- [tag]` bullets — normalize to one style

**Auto-captured entries** (detected via analyzer):
- [{topic}] {entry title} — {N} auto-captured entries
  Assessment: {ready for promotion / needs review / low value}

**Most referenced** (highest operational value — promote candidates):
- [{topic}] {entry title} — accessed {N} times (decay_score: {score})

**Archive health**:
- [{topic}] {N} lines — {healthy / WARNING: {issue}}

#### Safe Cleanup (recommend "do all")
| # | Action | Topic | Entry | Priority |
|---|--------|-------|-------|----------|
| 1 | {prune/promote/correct/tag/delete/dedup} | {topic} | {entry} | {P0/P1} |

#### Lossy Compression (not recommended — mention only)
{N} entries across {M} topic files could theoretically be consolidated.
Token savings: ~{X} tokens ({Y}% of context). Error strings lost: {Z}.
**Recommendation: skip.** Only consolidate if hitting context limits on a specific file.
```
