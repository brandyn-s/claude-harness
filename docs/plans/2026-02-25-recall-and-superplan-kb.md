# Knowledge Base as Memory — /recall Skill + Superplan Phase 2c

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the digital garden knowledge base a readable memory source via an on-demand `/recall` skill and automatic superplan context loading.

**Architecture:** `/recall` uses memory-search MCP (which already indexes KB topics) for semantic search, then selectively reads matched topic pages. Superplan gets a new Phase 2c that does the same search automatically during planning. A `--search` flag on `sync-knowledge.py` provides a fast metadata-only fallback.

**Tech Stack:** memory-search MCP (BGE-small embeddings, SQLite), sync-knowledge.py (Python), SKILL.md (markdown)

---

### Task 1: Add `--search` flag to sync-knowledge.py

Reusable metadata search over topic frontmatter + H2 titles. Used as fallback when memory-search MCP is unavailable, and for structured output (filenames, tags, entry counts).

**Files:**
- Modify: `~/.claude/hooks/sync-knowledge.py`

**Step 1: Read the current file**

Read `~/.claude/hooks/sync-knowledge.py` to understand existing structure.

**Step 2: Add `cmd_search` function**

Add after the existing `cmd_list` function. The search logic:
1. Accept 1+ keyword arguments
2. For each topic file in `~/Documents/knowledge-base/topics/*.md`:
   - Parse frontmatter (title, tags, aliases)
   - Extract all H2 entry titles
   - Score: +3 for filename match, +3 for title match, +2 for tag match, +2 for alias match, +1 for H2-title match
   - Keywords match as case-insensitive substrings
3. Sort by score descending, return top 10
4. Output format: one line per match with score, filename, title, matching fields

```python
def cmd_search(keywords):
    """Search topic pages by keyword matching against metadata and entry titles."""
    topics_dir = KB_DIR / "topics"
    topics = sorted(topics_dir.glob("*.md")) if topics_dir.exists() else []

    if not topics:
        print("No topic pages to search.")
        return

    results = []
    kw_lower = [k.lower() for k in keywords]

    for topic in topics:
        fm = parse_frontmatter(topic)
        title = fm.get("title", topic.stem.replace("-", " ").title())
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        aliases = fm.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]

        # Extract H2 titles
        h2_titles = []
        try:
            with open(topic, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("## "):
                        h2_titles.append(line[3:].strip())
        except Exception:
            pass

        score = 0
        matched_fields = []

        for kw in kw_lower:
            # Filename match (+3)
            if kw in topic.stem.lower():
                score += 3
                if "filename" not in matched_fields:
                    matched_fields.append("filename")

            # Title match (+3)
            if kw in title.lower():
                score += 3
                if "title" not in matched_fields:
                    matched_fields.append("title")

            # Tag match (+2)
            if any(kw in t.lower() for t in tags):
                score += 2
                if "tags" not in matched_fields:
                    matched_fields.append("tags")

            # Alias match (+2)
            if any(kw in a.lower() for a in aliases):
                score += 2
                if "aliases" not in matched_fields:
                    matched_fields.append("aliases")

            # H2 title match (+1)
            if any(kw in h.lower() for h in h2_titles):
                score += 1
                if "entries" not in matched_fields:
                    matched_fields.append("entries")

        if score > 0:
            results.append((score, topic, title, matched_fields))

    results.sort(key=lambda x: -x[0])
    results = results[:10]

    if not results:
        print(f"No matches for: {' '.join(keywords)}")
        return

    print(f"Search results for: {' '.join(keywords)}")
    for score, topic, title, fields in results:
        entries = count_entries(topic)
        last = get_last_date(topic)
        print(f"  [{score:2d}] {topic.name}  ({entries} entries, {last})  {title}  matched: {', '.join(fields)}")
```

**Step 3: Wire up argparse**

Add `--search` to the mutually exclusive group and wire it to `cmd_search`:

```python
group.add_argument("--search", nargs="+", metavar="KEYWORD", help="Search topics by keyword")

# In the dispatch block:
elif args.search:
    cmd_search(args.search)
```

**Step 4: Test the search**

Run: `python ~/.claude/hooks/sync-knowledge.py --search hook windows`
Expected: `hook-design-patterns.md` appears at top with high score (filename + tags match).

Run: `python ~/.claude/hooks/sync-knowledge.py --search OBO`
Expected: `obo-authentication.md` appears at top.

Run: `python ~/.claude/hooks/sync-knowledge.py --search nonexistent`
Expected: "No matches for: nonexistent"

**Step 5: Commit**

```bash
cd ~/.claude && git add hooks/sync-knowledge.py
git commit -m "feat(sync-knowledge): add --search flag for keyword metadata search"
```

---

### Task 2: Reindex memory-search to include KB topics

The memory-search server already has `~/Documents/knowledge-base/topics/` in its hardcoded index paths, but the current index (666 chunks) may not include them if it was built before the knowledge base existed.

**Files:**
- No code changes — just trigger reindex

**Step 1: Trigger reindex**

Call `mcp__memory-search__memory_reindex()`.

**Step 2: Verify KB topics are indexed**

Call `mcp__memory-search__memory_search(query="hook design windows subprocess", scope="all", limit=5)`.
Expected: Results include entries from `knowledge-base/topics/hook-design-patterns.md`.

Call `mcp__memory-search__memory_stats()` to verify chunk count increased.
Expected: `files_indexed` count includes KB topic files. Chunk count > 666.

**Step 3: Verify scope filtering**

Call `mcp__memory-search__memory_search(query="OBO authentication", scope="patterns", limit=3)`.
Note whether KB topics appear (they should if scope="all" but may not under "patterns").
This tells us whether we need a new scope value for the recall skill.

---

### Task 3: Create the /recall skill

**Files:**
- Create: `~/.claude/skills/recall/SKILL.md`

**Step 1: Create the skill directory**

```bash
mkdir -p ~/.claude/skills/recall
```

**Step 2: Write SKILL.md**

```markdown
---
name: recall
description: >
  Search and load knowledge from the digital garden. Finds topic pages by
  semantic search, then selectively reads matching entries into context.
  Use when you need to recall prior decisions, lessons, patterns, or failed
  approaches from past sessions. Trigger phrases: "recall", "what did we
  learn about", "what do we know about", "prior decisions on",
  "knowledge base search".
  Do NOT use for capturing new knowledge (use /capture), operational tool
  gotchas (check agent memory directly), or API reference patterns
  (use topic files).
argument-hint: "<search terms>"
---

# Recall — Knowledge Base Search

Search the digital garden for prior decisions, lessons, patterns, and
failed approaches. Returns relevant topic entries loaded into context so
you can reason over past knowledge.

---

## How It Works

This skill uses two search mechanisms in sequence:

1. **Semantic search** via memory-search MCP (primary) — finds entries by
   meaning, not just keywords
2. **Metadata search** via sync-knowledge.py --search (fallback) — matches
   against filenames, tags, aliases, and H2 entry titles

---

## Process

**Step 1: Parse the query**

Extract search terms from `$ARGUMENTS`. If no arguments provided, ask the
user what they want to recall.

**Step 2: Semantic search**

Call `mcp__memory-search__memory_search` with:
- `query`: the user's search terms
- `scope`: "all"
- `limit`: 10

Filter results to only those from `knowledge-base/topics/` source files.
If no KB results appear in the top 10, note this — the topic may not be
indexed yet.

**Step 3: Metadata search (parallel)**

Run: `python ~/.claude/hooks/sync-knowledge.py --search <terms>`

This catches metadata matches that semantic search might miss (exact tag
matches, filename matches).

**Step 4: Merge and deduplicate**

Combine results from both searches. Deduplicate by filename. Rank by:
1. Semantic match score (cosine similarity > 0.7 = strong)
2. Metadata match score
3. Recency (prefer recently updated topics)

Select the top 3-5 unique topic files.

**Step 5: Two-pass read**

**Pass 1 — Index scan**: For each matched topic, read ONLY the frontmatter
and H2 entry titles (not full bodies). Present this as a summary:

```
Found 3 relevant topics:

1. **Hook Design Patterns** (hook-design-patterns.md, budding, 2 entries)
   - Consolidate hooks per event to eliminate Windows console flashes (2026-02-23)
   - CREATE_NO_WINDOW alone is insufficient — add STARTUPINFO SW_HIDE (2026-02-25)

2. **OBO Authentication** (obo-authentication.md, budding, 2 entries)
   - OBO token flow and MSAL integration (2026-02-22)
   - FastMCP 3.0 logger override workaround (2026-02-24)

3. **Skill Design Patterns** (skill-design-patterns.md, budding, 5 entries)
   - [5 entry titles listed]
```

**Pass 2 — Selective deep read**: Read the full content of the top 1-2
most relevant topics (highest combined score). For topics ranked 3+,
only show the index from Pass 1 unless the user asks for more.

**Step 6: Present findings**

Present the loaded knowledge with a brief caveat:

> These are historical entries from the knowledge base. Entries older than
> 30 days may reflect superseded decisions — check dates and verify
> against current state if using as constraints.

If no results were found, say so and suggest:
- Check spelling / try different keywords
- Run `/capture list` to browse all topics
- The knowledge may not have been captured yet

---

## Examples

**Example 1: Specific topic recall**
User says: `/recall OBO authentication`
Actions:
1. Semantic search finds obo-authentication.md entries
2. Metadata search confirms match (filename + tags)
3. Full read of obo-authentication.md
Result: OBO decision history loaded into context

**Example 2: Cross-topic recall**
User says: `/recall windows subprocess`
Actions:
1. Semantic search finds hook-design-patterns entries about subprocess
2. Metadata search finds hook-design-patterns via tags [windows]
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

## Success Criteria

- Semantic search returns relevant KB entries (not just agent memory)
- Metadata fallback catches exact matches semantic search misses
- Two-pass read prevents context bloat (index first, deep read selectively)
- Stale entries flagged with date caveat
- No results case handled gracefully with actionable suggestions
```

**Step 3: Verify skill is discoverable**

Check that the skill appears in the skills list by reading the directory.

**Step 4: Commit**

```bash
cd ~/.claude && git add skills/recall/SKILL.md
git commit -m "feat: add /recall skill for knowledge base search"
```

---

### Task 4: Add Phase 2c to superplan SKILL.md

**Files:**
- Modify: `~/.claude/skills/superplan/SKILL.md`

**Step 1: Read current superplan SKILL.md**

Already read above. The insertion point is after Phase 2b (Semantic Memory Search) and before Phase 3 (Capability Assessment).

**Step 2: Add Phase 2c block**

Insert after the "For unknown domains" section (line 61) and before "## Phase 3":

```markdown
### Phase 2c: Knowledge Base Context

After domain-specific context and semantic memory search, check the digital
garden for prior decisions and lessons relevant to this task.

**Search**: Call `mcp__memory-search__memory_search` with the task
description as query, `scope="all"`, `limit=10`. Filter results to entries
sourced from `knowledge-base/topics/` files.

If no KB results appear, also run:
`python ~/.claude/hooks/sync-knowledge.py --search <domain keywords>`

**Relevance filter**: Only include entries with cosine similarity > 0.65
or metadata score >= 4. Discard weak matches.

**Two-pass loading** (prevents context bloat):
- **Pass 1**: For each matched topic (max 3), extract only the H2 entry
  titles and dates. Present as a compact index.
- **Pass 2**: Read the full content of entries that directly relate to the
  current task (max 2 full entries total). Skip entries that overlap with
  information already loaded from agent memory or topic patterns.

**Date caveat**: Flag any loaded entry older than 30 days with a note:
"⚠ This entry is from [date] — verify it still reflects current state."

**Deduplication**: If a KB entry covers the same ground as an agent memory
entry or topic pattern, prefer the agent memory / topic pattern (they are
more actively maintained). Only include the KB entry if it adds context
not available elsewhere (e.g., *why* a decision was made, alternatives
that were rejected, failed approaches).

**Skip conditions**: Skip Phase 2c entirely if:
- The task is simple enough that Phase 2a-2b already provided sufficient context
- No KB results meet the relevance threshold
- The task is about building something new where past patterns might anchor thinking
```

**Step 3: Update the plan quality checks**

In `references/planning-framework.md`, add one line to the Plan Quality Checks section:

```markdown
- Knowledge base entries older than 30 days are flagged, not treated as constraints
```

**Step 4: Commit**

```bash
cd ~/.claude && git add skills/superplan/SKILL.md skills/superplan/references/planning-framework.md
git commit -m "feat(superplan): add Phase 2c knowledge base context loading"
```

---

### Task 5: Update MEMORY.md and verify end-to-end

**Files:**
- Modify: `~/.claude/projects/<your-claude-project>/memory/MEMORY.md`

**Step 1: Add recall skill to the Skills section in MEMORY.md**

Add to the skills list:
```
- **recall**: Knowledge base search — semantic + metadata search, two-pass read (index then selective deep read), date-caveat for stale entries
```

**Step 2: End-to-end test of /recall**

Invoke `/recall hook windows` and verify:
1. Semantic search returns hook-design-patterns entries
2. Metadata search confirms match
3. Two-pass read works (index first, then full content)
4. Date caveat appears for older entries

**Step 3: End-to-end test of superplan KB loading**

Invoke `/superplan Plan how to add a new hook for X` and verify:
1. Phase 2c fires and searches KB
2. hook-design-patterns entries appear in context
3. Plan references prior hook lessons

**Step 4: Commit MEMORY.md update**

```bash
cd ~/.claude && git add projects/<your-claude-project>/memory/MEMORY.md
git commit -m "docs: add recall skill to MEMORY.md skills list"
```
