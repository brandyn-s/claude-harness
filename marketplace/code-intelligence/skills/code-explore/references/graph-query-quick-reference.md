# Graph Query Quick Reference and Deep Architecture Review

Relocated verbatim from `skills/code-explore/SKILL.md` on 2026-09-04 (docs/skill-cap-decisions.md).

## Graph Query Quick Reference

### Structure Exploration

Get an overview of what's in the graph:
```
get_graph_schema          # Node/edge counts, relationship patterns
search_graph(label="Module")  # List top-level modules
search_graph(label="Route")   # List all REST routes
search_graph(label="Function", name_pattern=".*Handler.*")  # Find by name
get_code_snippet(qualified_name="project.path.FunctionName")  # Read source
```

Scope to a directory with `qn_pattern=".*services\\.order\\..*"`.

### Dead Code & Quality Analysis

```
# Dead code: functions with zero inbound calls (excluding entry points)
search_graph(label="Function", relationship="CALLS", direction="inbound", max_degree=0, exclude_entry_points=true)

# High fan-out (calling 10+ others — refactor candidates)
search_graph(label="Function", relationship="CALLS", direction="outbound", min_degree=10)

# High fan-in (called by 10+ others — critical functions)
search_graph(label="Function", relationship="CALLS", direction="inbound", min_degree=10)

# Files that change together (hidden coupling)
query_graph(query="MATCH (a)-[r:FILE_CHANGES_WITH]->(b) WHERE r.coupling_score >= 0.5 RETURN a.name, b.name, r.coupling_score ORDER BY r.coupling_score DESC LIMIT 20")
```

Before deleting dead code candidates, verify with `trace_call_path(direction="inbound", depth=1)` and check for USAGE edges.

### Call Chain Tracing

`trace_call_path` requires an **exact** name. Discover it first:
```
search_graph(name_pattern=".*Order.*", label="Function")
```

Then trace:
```
trace_call_path(function_name="ProcessOrder", direction="both", depth=3)
# Always use direction="both" — "outbound" misses cross-service callers

# Risk-classified impact analysis
trace_call_path(function_name="ProcessOrder", direction="inbound", depth=3, risk_labels=true)
# Returns CRITICAL (hop 1), HIGH (hop 2), MEDIUM (hop 3), LOW (hop 4+)

# Git diff blast radius
detect_changes()                    # All uncommitted changes
detect_changes(scope="branch", base_branch="main")  # Branch delta
```

### Cross-Service & Async

```
# HTTP calls between services
query_graph(query="MATCH (a)-[r:HTTP_CALLS]->(b) RETURN a.name, b.name, r.url_path, r.confidence LIMIT 20")

# Interface implementations
query_graph(query="MATCH (s)-[r:OVERRIDE]->(i) WHERE i.name = 'Read' RETURN s.name, i.name LIMIT 20")

# Read references (callbacks, variable assignments)
query_graph(query="MATCH (a)-[r:USAGE]->(b) WHERE b.name = 'ProcessOrder' RETURN a.name, a.file_path LIMIT 20")
```

### Key Pitfalls

1. `search_graph(relationship="HTTP_CALLS")` filters nodes by degree — does NOT return edges. Use `query_graph` with Cypher to see actual edges.
2. `query_graph` caps at 200 rows — COUNT queries silently undercount. Use `search_graph` with degree filters for counting.
3. `trace_call_path` needs exact names — use `search_graph(name_pattern=...)` first.
4. `search_graph` with degree filters has no row cap (unlike `query_graph`).
5. **`WITH ... COUNT(*)` aggregation may silently return raw un-aggregated rows** up to the 200-row cap on older code-graph versions (verified 2026-05-07 against PSM). The query parses but the GROUP BY semantics don't apply — you get 200 raw matches that look like an answer but aren't. To detect: compare returned row count to the source MATCH cardinality; if equal, aggregation didn't engage. Workaround: use `search_graph` with `min_degree`/`max_degree` filters for counting, or post-process raw rows in the caller.
6. **`IN [list]`, `IS NULL`, `IS NOT NULL` are supported** (B1: 2026-05-07; IS NULL/IS NOT NULL: Plan 3 Phase A 2026-05-06). `WHERE n.name IN ['a', 'b']`, `WHERE n.docstring IS NOT NULL`, and `WHERE n.start_line IS NULL` all work. `IN` lists must be string or number literals; empty lists are rejected at parse time.

> For full Cypher syntax reference, edge types, and node labels: see `${CLAUDE_PLUGIN_ROOT}/skills/codebase-memory-exploring/references/code-graph-reference.md`

## Deep Architecture Review

For "understand this codebase" queries that need a comprehensive structured
output (not just a quick answer), load the architecture review template at
`${CLAUDE_PLUGIN_ROOT}/skills/evaluate-repos/references/architecture-review-template.md`.

It provides a Staff Engineer Guide format covering: executive summary, core
architectural insight, decision log, dependency rationale, tech debt, security
model, testing strategy, and recommended source file reading order.

Use when: the user asks for a full architecture review, codebase onboarding
doc, or "explain this entire system to me." Skip for targeted queries.
(Pattern source: microsoft/skills wiki-onboarding — Context7 registry 2026-04-06)

