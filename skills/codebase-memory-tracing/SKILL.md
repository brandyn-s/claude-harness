---

name: codebase-memory-tracing
description: "Trace call chains, callers/callees, and change impact via the code graph."
when_to_use: 'Use when asked to trace function call chains, find callers or callees, analyze change impact, or understand dependency relationships. Queries the code-graph knowledge graph for call paths and risk classification. Trigger phrases: "who calls this function", "what does X call", "trace the call chain", "find callers of", "show dependencies", "what depends on", "trace call path", "impact analysis". Do NOT use for module-level exploration (use /codebase-memory-exploring), quality metrics (use /codebase-memory-quality), or simple symbol-reference lookups not tied to call-graph analysis (see codebase-memory-exploring/references/code-graph-reference.md).'
effort: low
model: sonnet
argument-hint: "[function or call path to trace]"
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires the codebase-memory-mcp server for call chain traversal.
  requires:
    - mcp: codebase-memory-mcp
allowed-tools: Grep mcp__codebase-memory-mcp__detect_changes mcp__codebase-memory-mcp__get_code_snippet mcp__codebase-memory-mcp__query_graph mcp__codebase-memory-mcp__search_graph mcp__codebase-memory-mcp__trace_call_path
---

## codebase-memory-tracing

# Call Chain Tracing via Knowledge Graph

Use graph tools to trace function call relationships. One `trace_call_path` call replaces dozens of grep searches across files.

## Workflow

### Step 1: Discover the exact function name

`trace_call_path` requires an **exact** name match. If you don't know the exact name, discover it first with regex:

```
search_graph(name_pattern=".*Order.*", label="Function")
```

Use full regex for precise discovery — no full-text search needed:
- `(?i)order` — case-insensitive
- `^(Get|Set|Delete)Order` — CRUD variants
- `.*Order.*Handler$` — handlers only
- `qn_pattern=".*services\\.order\\..*"` — scope to order service directory

This returns matching functions with their qualified names and file locations.

### Step 2: Trace callers (who calls this function?)

```
trace_call_path(function_name="ProcessOrder", direction="inbound", depth=3)
```

Returns a hop-by-hop list of all functions that call `ProcessOrder`, up to 3 levels deep.

### Step 3: Trace callees (what does this function call?)

```
trace_call_path(function_name="ProcessOrder", direction="outbound", depth=3)
```

### Step 4: Full context (both callers and callees)

```
trace_call_path(function_name="ProcessOrder", direction="both", depth=3)
```

**Always use `direction="both"` for complete context.** Cross-service HTTP_CALLS edges from other services appear as inbound edges — `direction="outbound"` alone misses them.

### Step 5: Read suspicious code

After finding interesting callers/callees, read their source:

```
get_code_snippet(qualified_name="project.path.module.FunctionName")
```

### Step 6: Cross-check on low confidence

If `trace_call_path` returns `_metadata.confidence.band == "low"` OR `unresolved_call_count > resolved × 10`, the resolver missed most callees. Known recurrent failure modes: Rust struct constructors, method-on-type dispatch, and external-crate paths (Rust scope-aligned F1 0.82-0.91 per `bench/accuracy/baselines/` in the code-graph repo; verified 2026-05-13: `create_gps1_pos` returned 1/344 calls resolved while grep found ≥5 callable references in the same 44-line body).

Supplement with Grep on the source range:

```
get_code_snippet(qualified_name="...", include_neighbors=true)  # get file_path + line range
Grep(pattern="<function_name>", path="<file>", -A=20, -B=2)     # read surrounding context
```

Then enumerate calls in the source body manually. Treat anything in the source but not in the graph trace as a graph-coverage gap (not real absence) and report it accordingly to the user.

## Cross-Service HTTP Calls

To see all HTTP links between services with URLs and confidence scores:

```
query_graph(query="MATCH (a)-[r:HTTP_CALLS]->(b) RETURN a.name, b.name, r.url_path, r.confidence ORDER BY r.confidence DESC LIMIT 20")
```

Filter by URL path:
```
query_graph(query="MATCH (a)-[r:HTTP_CALLS]->(b) WHERE r.url_path CONTAINS '/orders' RETURN a.name, b.name, r.url_path")
```

## Async Dispatch (Cloud Tasks, Pub/Sub, etc.)

Find dispatch functions by name pattern, then trace:
```
search_graph(name_pattern=".*CreateTask.*|.*send_to_pubsub.*")
trace_call_path(function_name="CreateMultidataTask", direction="both")
```

## Interface Implementations

Find which structs implement an interface method:
```
query_graph(query="MATCH (s)-[r:OVERRIDE]->(i) WHERE i.name = 'Read' RETURN s.name, i.name LIMIT 20")
```

## Read References (callbacks, variable assignments)

```
query_graph(query="MATCH (a)-[r:USAGE]->(b) WHERE b.name = 'ProcessOrder' RETURN a.name, a.file_path LIMIT 20")
```

## Risk-Classified Impact Analysis

Add `risk_labels=true` to get risk classification on each node. For inbound-only impact (who depends on this?):

```
trace_call_path(function_name="ProcessOrder", direction="inbound", depth=3, risk_labels=true)
```

For full cross-service impact, prefer `direction="both"` per Step 4 — `direction="outbound"` alone misses HTTP_CALLS edges from other services (which appear as inbound edges to the traced function):

```
trace_call_path(function_name="ProcessOrder", direction="both", depth=3, risk_labels=true)
```

Returns nodes with `risk` (CRITICAL/HIGH/MEDIUM/LOW) based on hop depth, plus an `impact_summary` with counts. Risk mapping: hop 1=CRITICAL, 2=HIGH, 3=MEDIUM, 4+=LOW.

## Detect Changes (Git Diff Impact)

Map uncommitted changes to affected symbols and their blast radius:

```
detect_changes()
detect_changes(scope="staged")
detect_changes(scope="branch", base_branch="main")
```

Returns changed files, changed symbols, and impacted callers with risk classification. Scopes: `unstaged`, `staged`, `all` (default), `branch`.

## Key Tips

- Start with `depth=1` for quick answers, increase only if needed (max 5).
- Edge types in trace results: `CALLS` (direct), `HTTP_CALLS` (cross-service), `ASYNC_CALLS` (async dispatch), `USAGE` (read reference), `OVERRIDE` (interface implementation).
- `search_graph(relationship="HTTP_CALLS")` filters nodes by degree — it does NOT return edges. Use `query_graph` with Cypher to see actual edges with properties.
- Results are capped at 200 nodes per trace.
- `detect_changes` requires git in PATH.

> **Related:** code-explore (routing), codebase-memory-exploring, codebase-memory-quality

## Examples

**Trace callers of a function:**
User asks "who calls ProcessOrder?" Run `search_graph(name_pattern="ProcessOrder", label="Function")` to confirm the exact name, then `trace_call_path(function_name="ProcessOrder", direction="inbound", depth=3)`. Present the caller chain with file paths at each hop.

**Impact analysis for a change:**
User asks "what breaks if I change the ValidateToken function?" Run `trace_call_path(function_name="ValidateToken", direction="both", depth=3, risk_labels=true)` to get risk-classified callers AND callees. (Step 4 mandates `direction="both"` for impact analysis on cross-service codebases — `direction="outbound"` alone misses HTTP_CALLS edges from other services, which appear as inbound edges to the traced function.) Supplement with `detect_changes()` if the change is already in the working tree. Present a risk summary: CRITICAL/HIGH/MEDIUM/LOW counts.


**Example 2: Tracing error propagation**
User says: "If Redis connection fails in the shared client, what breaks?"
Actions: Traces all callers of redis_client.get/set/delete through the call graph. Maps failure propagation to affected endpoints and services.
Result: "Redis failure affects 8 endpoints across 3 services: rate-limiter (hard failure), session-cache (graceful degradation), audit-log (async, queued)."

## Success Criteria

- Complete caller/callee chain identified with file paths and hop depth
- Cross-file and cross-service references found (HTTP_CALLS, ASYNC_CALLS edges included)
- Risk assessment provided for impact analysis queries (CRITICAL/HIGH/MEDIUM/LOW classification)
- Edge types distinguished in output (direct CALLS vs HTTP_CALLS vs USAGE references)
