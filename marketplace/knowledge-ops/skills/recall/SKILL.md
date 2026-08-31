---

name: recall
description: "Search the knowledge base (digital garden) for prior decisions, lessons, and patterns."
when_to_use: 'Use when prior decisions, lessons, patterns, or failed approaches from past sessions need to be recalled. Searches the digital garden by semantic match and selectively reads matching entries into context. Trigger phrases: "recall", "what did we learn about", "what do we know about", "prior decisions on", "knowledge base search". Do NOT use for capturing new knowledge (use /capture), operational tool gotchas (check agent memory directly), or API reference patterns (use topic files).'
argument-hint: "[search terms]  (e.g., \"dependency audit\", \"prior decisions on retry logic\", \"workaround for vendor-router\")"
effort: low
model: sonnet
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires memory-search MCP for semantic search across the digital garden.
  requires:
    - mcp: memory-search
allowed-tools: Read Glob Grep Bash mcp__memory-search__memory_search AskUserQuestion
---

## recall

# Recall — Knowledge Base Search

Search the digital garden for prior decisions, lessons, patterns, and
failed approaches. Returns relevant topic entries loaded into context so
you can reason over past knowledge.

**Knowledge base:** `~/Documents/knowledge-base/topics/` (primary), `~/Documents/knowledge-base/research/`, `~/.claude/agent-memory/topics/`
**Search index:** memory-search MCP — Voyage 4 asymmetric (voyage-4-large index + voyage-4-lite query) over SQLite + sqlite-vec, with BM25 fusion and RRF

---

## Process

**Step 1: Parse the query**

Extract search terms from `$ARGUMENTS`. If no arguments provided, ask the
user what they want to recall.

**Step 2: File-first search (PRIMARY - fast, reliable)**

Search `~/Documents/knowledge-base/topics/` using Glob and Grep:
1. `Glob("*.md", path="~/Documents/knowledge-base/topics/")` to list all topic files
2. `Grep(pattern=<search terms>, path="~/Documents/knowledge-base/topics/")` to find matches
3. Read the matched files directly

This is the primary search path - it's fast, reliable, and doesn't timeout.

**Step 3: Semantic search (FALLBACK - if file search misses)**

Only if Step 2 returns no matches, try `mcp__memory-search__memory_search` with:
- `query`: the user's search terms
- `scope`: "all"
- `limit`: 10

Filter results by source AND confidence:

1. Look at the top-1 result whose `source_file` is under `knowledge-base/topics/`.
2. **IF that top-1 has cosine ≥ 0.7** → use the `knowledge-base/topics/` matches only (current behavior; topic pages are the curated layer).
3. **ELSE (top-1 topics/ match has cosine < 0.7)** → ALSO include the best matches from `knowledge-base/research/` and `agent-memory/topics/` whose cosine ≥ 0.65. Rationale: Phase 9 review in PR #559 showed `dependency-audit.md` (research) was strictly more relevant than `topics/security.md` for STIG queries; the strict topics/-only filter was hiding strictly-better matches.
4. Skip any result with cosine < 0.65.

Note: semantic search can timeout on multi-term queries (378s observed). If it times out, rely on Step 2 results.

**Step 4: Merge, deduplicate, and tag confidence**

Combine results from file search (Step 2) and semantic search (Step 3).
Deduplicate by filename. Rank by:
1. Direct file match (Grep hit = strongest signal)
2. Semantic match score (cosine similarity ≥ 0.7 = strong match)
3. Recency (prefer recently updated topics)

Then classify each surviving result by its memory-search cosine score
(per Phase B4):

- `[HIGH conf]` — cosine ≥ 0.8 (engine is confident the content matches the query)
- `[MED conf]`  — 0.65 ≤ cosine < 0.8 (relevant but discount before quoting as load-bearing)
- `[FILE match]` — direct Grep/Glob hit with no engine score

Note: Step 3's `< 0.65` filter is the floor — anything below that band is dropped, so no `[LOW conf]` tier exists at this point.

Select the top 3-5 unique files (mix of confidence bands allowed; prefer HIGH and FILE first).

**Step 5: Two-pass read**

**Pass 1 — Index scan**: For each matched topic, read ONLY the frontmatter
and H2 entry titles (not full bodies). Present this as a summary, with
the Step 4 confidence-band tag in front of each title:

```
Found 3 relevant topics:

1. [HIGH conf] **Hook Design Patterns** (hook-design-patterns.md, budding, 2 entries)
   - Consolidate hooks per event to eliminate Windows console flashes (2026-02-23)
   - CREATE_NO_WINDOW alone is insufficient — add STARTUPINFO SW_HIDE (2026-02-25)

2. [MED conf] **OBO Authentication** (obo-authentication.md, budding, 2 entries)
   - OBO token flow and MSAL integration (2026-02-22)
   - FastMCP 3.0 logger override workaround (2026-02-24)

3. [FILE match] **Dependency Audit** (dependency-audit.md, evergreen, 14 entries)
```

**Pass 2 — Selective deep read**: Read the full content of the top 1-2
most relevant topics (highest combined score, prefer HIGH and FILE
matches). For topics ranked 3+, only show the index from Pass 1 unless
the user asks for more.

**Step 6: Present findings**

Present the loaded knowledge with a brief caveat:

> These are historical entries from the knowledge base. Entries older than
> 30 days may reflect superseded decisions — check dates and verify
> against current state if using as constraints. Treat `[MED conf]`
> matches as suggestive only — quote with hedging.

If no results were found, say so and suggest:
- Check spelling / try different keywords
- Run `/capture list` to browse all topics
- The knowledge may not have been captured yet

**Step 7: Log telemetry (always; one record per /recall invocation)**

Append one JSONL record to `~/.claude/recall-telemetry.jsonl` so we can
measure how often file-first satisfies the query, how often the engine
fallback fires, and **which top-K slots the consumer actually deep-read
in Pass 2**. Use the helper script (avoids JSON-quoting bugs in inline
`echo`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/recall/scripts/log_telemetry.py" \
    --query "<the query from Step 1>" \
    --file-first-hit "<true|false>" \
    --file-first-path "<path or empty>" \
    --fallback-used "<true|false>" \
    --top1-cosine "<float or 0.0>" \
    --slots-used "<comma-separated 1-indexed slots or empty>" \
    --num-results <int>
```

Field rules:
- `--file-first-hit` — true whenever Step 2 returned ≥1 match.
- `--fallback-used` — true whenever Step 3 was actually invoked.
- `--top1-cosine` — cosine of the top-1 memory-search result if Step 3
  ran; else `0.0`.
- `--slots-used` — comma-separated 1-indexed slot numbers from the Step
  4 ranked list that you actually deep-read in Step 5 Pass 2. Example:
  if you presented 4 ranked matches in Pass 1 and deep-read slots 1 and
  3, pass `"1,3"`. Pass `""` if no slots were deep-read (no-results case
  or user-aborted). Critical: count **deep reads** only — Pass 1's
  title/frontmatter scan doesn't count.
- `--num-results` — total ranked items the Step 4 merge produced
  (1..K). Pass `0` if no engine call ran and no file-first matches
  existed.

The telemetry file is local-only and append-only; nothing reads it
automatically. After ~100-200 records, the slot-use distribution
resolves the open question from `/roundtable improving memory-search`
META_SYNTHESIS D2 (whether pooled-judged P@5 is worth instrumenting or
whether top-1/2 usage dominates and retired raw P@5 stays retired).

Run `${CLAUDE_PLUGIN_ROOT}/skills/recall/scripts/analyze_telemetry.py` to summarize
the accumulated records (file-first-hit / fallback-used rates, top-1
cosine percentiles p10/p50/p90, and slot-use distribution). The script
reports the empirical answer once enough records have accumulated.

---

## Examples

The example topic filenames below (`obo-authentication.md`,
`hook-design-patterns.md`, `terraform-ci-patterns.md`, etc.) are
illustrative — what your knowledge base contains depends on what's been
captured. Substitute real topic names from your own
`knowledge-base/topics/` directory.

**Example 1: Specific topic recall**
User says: `/recall OBO authentication`
Actions:
1. File-first search (Glob+Grep) finds obo-authentication.md
2. Two-pass read: index scan, then deep read of obo-authentication.md
Result: OBO decision history loaded into context

**Example 2: Cross-topic recall**
User says: `/recall windows subprocess`
Actions:
1. File-first search misses (no filename match for "windows subprocess")
2. Semantic search returns hook-design-patterns.md (cosine ≥ 0.7)
3. Full read of hook-design-patterns.md
Result: Both subprocess suppression entries loaded

**Example 3: Broad concept recall**
User says: `/recall CI CD pipeline`
Actions:
1. Semantic search finds terraform-ci-patterns, github-actions-discipline,
   supply-chain-security entries
2. Index scan of all 3 topics (titles only)
3. Deep read of terraform-ci-patterns (highest score, most entries)
Result: CI patterns loaded, other topics indexed for follow-up

---

## Success Criteria

- File-first search (Glob+Grep) catches direct filename/content matches reliably and fast
- Semantic search fallback returns relevant KB entries when file-first misses
- Two-pass read prevents context bloat (index first, deep read selectively)
- Stale entries flagged with date caveat
- No results case handled gracefully with actionable suggestions
