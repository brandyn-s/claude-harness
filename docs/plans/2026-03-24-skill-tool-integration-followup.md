# Skill-Tool Integration Followup Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the remaining items from the 43-skill audit — two borderline skill integrations and a shared patterns reference file.

**Architecture:** Additive edits to 2 existing skills + 1 new shared reference file. All edits use the Python batch script approach (Edit tool reverted by PostToolUse hooks on `~/.claude/` files). Ship as a single PR.

**Tech Stack:** Python (apply script), Markdown (skill edits + reference file)

---

### Task 1: Create shared tool integration patterns reference

**Files:**
- Create: `~/.claude/skills/_shared/tool-integration-patterns.md`

**Step 1: Write the reference file**

Create `~/.claude/skills/_shared/tool-integration-patterns.md` with the 7 reusable patterns identified from the audit, plus the mandatory index guard pattern. Each pattern should have: name, source skill, when to use, example tool calls, and the "when to skip" guard.

Content:

```markdown
# Tool Integration Patterns

Reusable patterns for integrating code-search, code-graph, and memory-search
into skills. Extracted from the 43-skill audit (2026-03-23, PRs #342-#345).

---

## Pattern 0: Pre-flight Index Check (MANDATORY)

**Source:** code-explore, stig-verify, preflight
**When:** Before ANY code-search or code-graph call in a skill.

```
mcp__code-search__get_index_status()   # Returns chunk count, last index time
mcp__code-graph__list_projects()       # Returns indexed project names
```

If the target repo isn't indexed, offer `/index-repo <path>` and skip the
codebase analysis step. Do NOT call search tools on unindexed repos — they
silently return empty results.

For memory-search: always available (auto-indexed). Check staleness with
`mcp__memory-search__memory_stats()` if accuracy matters.

---

## Pattern 1: Routing Decision Tree

**Source:** code-explore
**When:** A skill needs to choose between code-search and code-graph.

Classify the query:
- **Conceptual** ("find code that handles authentication") → `search_code`
- **Structural** ("what calls this function", "show API routes") → `search_graph`, `trace_call_path`
- **Overview** ("show the architecture") → `get_architecture`

Auto-chain: if code-search finds a function, follow up with `trace_call_path`
to show callers. If code-graph finds a node, follow up with `get_code_snippet`
to read the source.

---

## Pattern 2: Discovery + Trace + Risk Classification

**Source:** codebase-memory-tracing
**When:** Need to find a function, trace its callers/callees, and classify risk.

1. `search_graph(name_pattern=".*Order.*", label="Function")` — find exact name
2. `trace_call_path(function_name="ProcessOrder", direction="both", depth=3)` — BFS traversal
3. Risk labels: CRITICAL (hop 1), HIGH (hop 2), MEDIUM (hop 3), LOW (hop 4+)

CRITICAL: always use `direction="both"` to catch HTTP_CALLS from other services.

---

## Pattern 3: Degree Filtering

**Source:** codebase-memory-quality
**When:** Finding dead code, high fan-out, or high fan-in functions.

- Dead code: `search_graph(relationship="CALLS", direction="inbound", max_degree=0, exclude_entry_points=true)`
- High fan-out: `search_graph(direction="outbound", min_degree=10)`
- High fan-in: `search_graph(direction="inbound", min_degree=10)`

Verify dead code with `trace_call_path(direction="inbound", depth=1)` +
`query_graph` for USAGE edges (functions may be read but not called).

---

## Pattern 4: Dual Indexing

**Source:** index-repo
**When:** Setting up a repo for both semantic and structural search.

```
mcp__code-search__index_directory(directory_path=<path>)   # Voyage AI embeddings (60-90 min)
mcp__code-graph__index_repository(path=<path>)             # Tree-sitter graph (30-60s)
```

Both support incremental indexing but only check file content hashes,
not embedding model upgrades. After model changes, rebuild with `incremental=false`.

---

## Pattern 5: Dedup Before Write

**Source:** capture, distill
**When:** Persisting knowledge to any memory tier.

```
mcp__memory-search__memory_check_duplicate(text="<proposed entry summary>")
```

- similarity >= 0.85 → skip (already exists)
- similarity 0.55-0.85 → merge (update existing entry)
- similarity < 0.55 → append (genuinely new)

Also run `mcp__memory-search__memory_search(query="<entry title>", limit=5)`
for broader semantic matching across all indexed files.

---

## Pattern 6: Staleness Audit

**Source:** review-learnings
**When:** Auditing memory health or checking if knowledge is current.

```
mcp__memory-search__memory_stale()          # Decay scoring for all chunks
mcp__memory-search__memory_stats()          # Access frequency, chunk counts
mcp__memory-search__memory_search(query=X)  # Cross-agent dedup matching
```

14+ day staleness threshold. Write-only detection: access_count=0, 30+ days.

---

## Pattern 7: Semantic Search for Convention Discovery

**Source:** mcp-forge-build (Step 3b), mcp-forge-audit (Step 5b)
**When:** Need to find established patterns or conventions in an indexed codebase.

```
mcp__code-search__search_code(query="<conceptual description>", directory=<repo>)
mcp__code-search__find_similar_code(code="<example code>", directory=<repo>, limit=10)
```

Use for: description conventions, parameter naming patterns, duplicate detection,
cross-server consistency checking. Combine with `memory_search` for prior
decision discovery.
```

**Step 2: Verify the file was created**

Run: `ls -la ~/.claude/skills/_shared/tool-integration-patterns.md`
Expected: file exists

**Step 3: Commit (batched with Task 2 and 3)**

Hold — commit with all tasks together.

---

### Task 2: Add memory-search + code-search to cost-analyze

**Files:**
- Modify: `~/.claude/skills/cost-analyze/SKILL.md`

**Step 1: Write a Python apply script**

The script adds memory-search correlation to the `optimize` mode (Step 2) and
adds an index guard. Insert after the `optimize` bullet in Step 2:

```python
# In the optimize bullet, after "could run on Sonnet":
old = '- **optimize**: Flag sessions with >100K output tokens, subagent fan-out >5,\n  repeated tool calls (>10 of same tool), and skills running on Opus that\n  could run on Sonnet.'
new = old + '\n  Use `mcp__memory-search__memory_search(query="expensive session patterns", limit=5)` to correlate expensive sessions with known inefficiencies from prior analysis. If code-search is indexed (`get_index_status`), use `search_code(query="<expensive skill name>")` to find the skill\'s implementation and identify wasteful tool call patterns.'
```

**Step 2: Run the apply script**

Run: `python3 apply-cost-mcp.py`
Expected: "OK cost-analyze/SKILL.md"

---

### Task 3: Add code-search adapter pattern detection to mcp-create Phase 1

**Files:**
- Modify: `~/.claude/a separate skill (not included in this export)

**Step 1: Write a Python apply script**

The script adds a code-search step after the AST analysis (Phase 1, after step 4
"Detect already-adapted servers"). Insert a new step 4b:

```python
old = '4. **Detect already-adapted servers**:'
new = '4. **Detect already-adapted servers**:'
# After step 4, insert step 4b for adapter pattern discovery
```

The new step 4b:
```
4b. **Search for similar adapters** (requires index — check `get_index_status()` first,
    skip if not indexed): Use `mcp__code-search__search_code(query="<source API name> adapter",
    directory="$HOME/Documents/GitHub/mcp-servers")` to find existing
    servers that wrap similar APIs. If matches found, read their adaptation patterns
    (lifespan setup, auth handling, error mapping) to inform Phase 2 scaffolding.
```

**Step 2: Run the apply script**

Run: `python3 apply-mcp-create.py`
Expected: "OK mcp-create/SKILL.md"

---

### Task 4: Ship all changes

**Step 1: Verify all 3 files changed**

Run: `git -C ~/.claude diff --stat skills/`
Expected: 3 files changed (1 new, 2 modified)

**Step 2: Stage, branch, commit, push, PR, merge**

Use the Python batch approach to stage + commit atomically, then push and PR via
the standard `/ship` workflow. Single PR with all 3 changes.

Branch: `feat/tool-integration-followup`
Commit message: `feat: add shared tool integration patterns reference + cost-analyze and mcp-create integrations`
