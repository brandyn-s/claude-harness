# Phase 2c: Knowledge Base Context Loading

After domain-specific context and semantic memory search (Phase 2b), check the
digital garden for prior decisions and lessons relevant to this task.

## Search

Call `mcp__memory-search__memory_search` with the task description as query,
`scope="all"`, `limit=10`. Filter results to entries sourced from
`knowledge-base/topics/` **AND `knowledge-base/plans/*-flaws.md`** files — the
flaw-logs are the highest-recall hits for "what went wrong last time on work
like this" (validated 2026-06-20: natural task queries returned the relevant
prior flaw as the #1 hit at cosine 0.69/0.50). Excluding them was the gap that
made this a retrieve-WRITE-only system; including them closes the
retrieve-before-acting loop. Surface any matched flaw entry as a "⚠ past flaws
relevant to this work" block the plan must read before its first risky step.

**Index-freshness caveat (load-bearing):** if this session WROTE flaw-logs or
KB entries earlier, the search index may predate them (it is not auto-refreshed
mid-session). Check `memory_stats` `last_reindex`; if it is older than the most
recent flaw-log mtime, run `memory_reindex` BEFORE relying on a negative result
— a stale index silently returns "no prior flaws" (2026-06-20: the index was
~9h stale; the validation only worked after a reindex).

If no KB results appear, also fall back to direct filesystem search:
`Glob ~/Documents/knowledge-base/{topics,plans}/*.md` then `Grep <domain keywords>`
across the matched files.

## Relevance filter

Only include entries with cosine similarity > 0.65 or metadata score >= 4.
Discard weak matches.

## Two-pass loading (prevents context bloat)

- **Pass 1**: For each matched topic (max 3), read the H2 entry titles and
  dates from the file. Present as a compact index to the user.
- **Pass 2**: For topics with cosine > 0.7, read the **full topic page** and
  include the last 3-5 H2 entries as planning context (not just snippets).
  These entries contain prior decisions, failed approaches, and architectural
  constraints that directly inform the plan. For topics with cosine 0.65-0.7,
  read only the single most relevant entry. Skip entries that overlap with
  information already loaded from agent memory or topic patterns.
  Max total: 3 full topic pages or 5 individual entries, whichever is smaller.

## Date caveat

Flag any loaded entry older than 30 days with a note:
"This entry is from [date] — verify it still reflects current state."

## Deduplication

If a KB entry covers the same ground as an agent memory entry or topic
pattern, prefer the agent memory / topic pattern (they are more actively
maintained). Only include the KB entry if it adds context not available
elsewhere (e.g., *why* a decision was made, alternatives that were rejected,
failed approaches).

## Skip conditions

Skip Phase 2c entirely if:
- The task is simple enough that Phase 2a-2b already provided sufficient context
- No KB results meet the relevance threshold
- The task is about building something new where past **solution-patterns** might
  anchor thinking — BUT this skip applies ONLY to the topics/ pattern retrieval, NEVER
  to the `plans/*-flaws.md` flaw retrieval. Past FAILURES are most valuable exactly on
  novel/risky work (anchoring risk is for "how others solved it", not "what blew up last
  time"). Always run the flaw-log search even when skipping pattern retrieval.
