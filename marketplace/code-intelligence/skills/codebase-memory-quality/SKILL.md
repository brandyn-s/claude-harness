---

name: codebase-memory-quality
description: "Find dead code, unused functions, and high-fan-out refactor candidates via the code graph."
when_to_use: 'Use when asked to find dead code, unused functions, high fan-out nodes, refactor candidates, or run a code quality audit. Queries the code-graph knowledge graph for degree filtering and structural analysis. Also for co-change coupling: files that always change together across folders, hidden dependencies, or which unused functions are safe to delete. Trigger phrases: "dead code", "unused functions", "unreachable code", "high fan-out", "complex functions", "code quality audit", "functions nobody calls", "reduce codebase size", "files that change together", "hidden dependency", "safe to delete", "refactor candidates", "cleanup candidates". Do NOT use for structural exploration (use /codebase-memory-exploring), reference lookups (see codebase-memory-exploring/references/code-graph-reference.md), or indexing (use /index-repo).'
effort: low
model: sonnet
argument-hint: '[query, e.g. "find dead code", "high fan-out functions"]'
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires the codebase-memory-mcp server for degree filtering and quality metrics.
  requires:
    - mcp: codebase-memory-mcp
allowed-tools: mcp__codebase-memory-mcp__search_graph mcp__codebase-memory-mcp__query_graph mcp__codebase-memory-mcp__trace_call_path mcp__codebase-memory-mcp__list_projects
---

## codebase-memory-quality

# Code Quality Analysis via Knowledge Graph

Use graph degree filtering to find dead code, high-complexity functions, and refactor candidates — all in single tool calls.

## Workflow

### Dead Code Detection

Find functions with zero inbound CALLS edges, excluding entry points:

```
search_graph(
  label="Function",
  relationship="CALLS",
  direction="inbound",
  max_degree=0,
  exclude_entry_points=true
)
```

`exclude_entry_points=true` removes route handlers, `main()`, and framework-registered functions that have zero callers by design.

### Verify Dead Code Candidates

Before deleting, verify each candidate truly has no callers:

```
trace_call_path(function_name="SuspectFunction", direction="inbound", depth=1)
```

Also check for read references (callbacks, stored in variables):

```
query_graph(query="MATCH (a)-[r:USAGE]->(b) WHERE b.name = 'SuspectFunction' RETURN a.name, a.file_path LIMIT 10")
```

### High Fan-Out Functions (calling 10+ others)

These are often doing too much and are refactor candidates:

```
search_graph(
  label="Function",
  relationship="CALLS",
  direction="outbound",
  min_degree=10
)
```

### High Fan-In Functions (called by 10+ others)

These are critical functions — changes have wide impact:

```
search_graph(
  label="Function",
  relationship="CALLS",
  direction="inbound",
  min_degree=10
)
```

### Files That Change Together (Hidden Coupling)

Find files with high git change coupling:

```
query_graph(query="MATCH (a)-[r:FILE_CHANGES_WITH]->(b) WHERE r.coupling_score >= 0.5 RETURN a.name, b.name, r.coupling_score ORDER BY r.coupling_score DESC LIMIT 20")
```

> The `0.5` coupling threshold and the `LIMIT 20` budget are inherited
> defaults — see `references/tuning-notes.md` for rationale and how to
> log evidence when adjusting them. Per-repo overrides may be appropriate
> for repos with shared-utility files that change with everything.


High coupling between unrelated files suggests hidden dependencies.

### Modules Nobody Imports

```
search_graph(
  relationship="IMPORTS",
  direction="inbound",
  max_degree=0,
  label="Module"
)
```

## Classifying Findings

After identifying hotspots, classify each into an action category. Classification turns
a list of findings into a prioritized action plan.

### Complexity Classification

| Category | Criteria | Action |
|----------|----------|--------|
| **Split** | High fan-out + long function body | Break into smaller functions |
| **Simplify** | High fan-out + short body | Reduce branching (early returns, guard clauses) |
| **Parameterize** | Too many arguments (6+) | Group into config/options struct |
| **Monitor** | Moderate fan-out (5-9), not growing | Note it, revisit if it worsens |
| **Split file** | File over 500 lines or 10+ functions | Break into focused modules |

### Duplication Classification

| Category | Criteria | Action |
|----------|----------|--------|
| **Extract** | Identical logic in 3+ places | Create shared helper in utils/ |
| **Parameterize** | Same structure, different values | Common function with parameters |
| **Acceptable** | Similar code serving different domains | Note it, no action needed |
| **Boilerplate** | Framework convention patterns | Skip — intentional repetition |
| **Test-only** | Repeated test setup/fixtures | Shared test fixture (low priority) |

Present findings with classification in the output table:

```
| Function | Fan-out | Lines | Classification | Action |
|----------|---------|-------|---------------|--------|
| process_all() | 14 | 120 | Split | Break into process_a() + process_b() |
| validate() | 11 | 25 | Simplify | Early returns for 3 guard clauses |
| configure() | 6 args | 40 | Parameterize | ConfigOptions struct |
| handle_event() | 7 | 35 | Monitor | Stable, revisit if grows |
```

(Pattern source: openshift/lightspeed-operator `find-complexity` + `find-duplication` — Context7 registry 2026-04-16)

## Precondition: project indexed

This skill assumes the target project is indexed. Before any quality query:

1. Call `mcp__codebase-memory-mcp__list_projects` and confirm the target project appears with a recent timestamp.
2. If the project is **missing**: stop and tell the user "Project `<name>` is not indexed. Run `/index-repo <path>` first." Do NOT attempt to call `index_repository` from this skill — indexing is the `/index-repo` skill's job.
3. If the project is **stale** (last indexed before recent code changes the user is asking about): warn the user and recommend re-running `/index-repo`. Proceed only if the user explicitly chooses to use the stale index.
4. If `mcp__codebase-memory-mcp__list_projects` itself errors: report the MCP-server error verbatim and stop; the server is unavailable.

## Key Tips

- `search_graph` with degree filters has no row cap (unlike `query_graph` which caps at 200 by default — raise with `max_rows` up to 10000; check `capped` in the response).
- Use `file_pattern` to scope analysis to specific directories: `file_pattern="**/services/**"`.
- Dead code detection works best after a full index — re-run `/index-repo` if the project was recently set up or has many uncommitted changes.
- Paginate results with `limit` and `offset` — check `has_more` in the response.

> **Related:** code-explore (routing), codebase-memory-exploring, codebase-memory-tracing

## Examples

**Find dead code in a repo:**
User asks "what functions are never called in mcp-servers?" Run `search_graph(label="Function", relationship="CALLS", direction="inbound", max_degree=0, exclude_entry_points=true)`. Verify candidates with `trace_call_path(direction="inbound", depth=1)` and `query_graph` for USAGE edges before reporting.

**Identify high fan-out functions:**
User asks "which functions are doing too much?" Run `search_graph(label="Function", relationship="CALLS", direction="outbound", min_degree=10)`. Present each function with its outbound call count and suggest refactor candidates.


**Example 2: Surfacing hidden file coupling**
User says: "Which files in mcp-servers change together most often?"
Actions: Run `query_graph(query="MATCH (a)-[r:FILE_CHANGES_WITH]->(b) WHERE r.coupling_score >= 0.5 RETURN a.name, b.name, r.coupling_score ORDER BY r.coupling_score DESC LIMIT 20")`. Classify high-coupling pairs in unrelated directories as hidden coupling candidates.
Result: "3 high-coupling pairs across unrelated modules — guardrail/rules.py and netcloud/router.py (coupling 0.82) suggests an undocumented dependency worth investigating."

## Success Criteria

- Dead code candidates listed with file paths and function names
- False positives filtered by checking for USAGE edges, entry points, and framework registrations
- Quality metrics presented with counts (e.g., "12 dead functions, 3 high fan-out nodes")
- Actionable recommendations provided (delete, refactor, or investigate further)
