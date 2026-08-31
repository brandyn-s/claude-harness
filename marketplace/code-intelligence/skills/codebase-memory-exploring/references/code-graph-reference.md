# code-graph MCP — Tool Reference

## Tools

| Tool | Purpose |
|------|---------|
| `index_repository` | Parse and ingest repo into graph (only once — auto-sync keeps it fresh) |
| `list_projects` | List all indexed projects with timestamps and counts |
| `delete_project` | Remove a project from the graph |
| `search_graph` | Structured search with filters (name, label, degree, file pattern) |
| `search_code_semantic` | Voyage-embedding semantic search by MEANING (no regex). Use for intent queries like "authentication middleware". |
| `search_code` | Literal / regex TEXT search over indexed files (grep-shaped; set `regex=true` for patterns). This is the pattern-matching tool. |
| `rank_by_query` | PageRank top-K nodes for a symbol-list or short-keyword query. Prefer `search_code_semantic` for natural-language queries — `rank_by_query` collapses on common-token noise. |
| `trace_call_path` | BFS call chain traversal (exact name match required). Supports `risk_labels=true` for impact classification. |
| `detect_changes` | Map git diff to affected symbols + blast radius with risk scoring |
| `query_graph` | Cypher-like graph queries. Default 200-row cap, raisable via `max_rows` (up to 10000); response includes `effective_cap` always and `capped: true` when truncated. |
| `query_security_surfaces` | Security-focused query for auth, sinks, crypto, and trust boundaries |
| `get_architecture` | High-level service/module architecture map — call before any structural fallback for "how is this organized" questions |
| `get_graph_schema` | Returns schema and aggregate node/edge counts across the graph |
| `index_status` | Returns current indexing status and statistics for a project |
| `index_health` | Checks indexing health and data consistency |
| `service_map` | Structured enumeration of services grouped by domain, with `depends_on` lists plus route/security counts in one call |
| `get_code_snippet` | Read source code by qualified name |
| `code_localize` | Localize code to a specific scope via agentic LLM-driven exploration |
| `code_localize_agent` | Agentic code localization variant with multi-step reasoning |

Note: To check indexing status, use `index_status` or `get_architecture` (returns empty if the project is not indexed). To get aggregate node/edge counts and schema information, use `get_graph_schema` or run `search_graph` per label and sum the totals.

## Edge Types

| Type | Meaning |
|------|---------|
| `CALLS` | Direct function call within same service |
| `HTTP_CALLS` | Synchronous cross-service HTTP request |
| `ASYNC_CALLS` | Async dispatch (Cloud Tasks, Pub/Sub, SQS, Kafka) |
| `IMPORTS` | Module/package import |
| `DEFINES` / `DEFINES_METHOD` | Module/class defines a function/method |
| `HANDLES` | Route node handled by a function |
| `IMPLEMENTS` | Type implements an interface |
| `OVERRIDE` | Struct method overrides an interface method |
| `USAGE` | Read reference (callback, variable assignment) |
| `FILE_CHANGES_WITH` | Git history change coupling |
| `CONTAINS_FILE` / `CONTAINS_FOLDER` / `CONTAINS_PACKAGE` | Structural containment |

## Node Labels

`Project`, `Package`, `Folder`, `File`, `Module`, `Class`, `Function`, `Method`, `Interface`, `Enum`, `Type`, `Route`

## Qualified Name Format

`<project>.<path_parts>.<name>` — file path with `/` replaced by `.`, extension removed.

Examples:
- `myproject.cmd.server.main.HandleRequest` (Go)
- `myproject.services.orders.ProcessOrder` (Python)
- `myproject.src.components.App.App` (TypeScript)

Use `search_graph` to discover qualified names, then pass them to `get_code_snippet`.

## Cypher Subset (for query_graph)

**Supported:**
- `MATCH` with node labels and relationship types
- Variable-length paths: `-[:CALLS*1..3]->`
- `WHERE` with `=`, `<>`, `>`, `<`, `>=`, `<=`, `=~` (regex), `CONTAINS`, `STARTS WITH`
- `WHERE` with `AND`, `OR`, `NOT`
- `RETURN` with property access, `COUNT(x)`, `DISTINCT`
- `ORDER BY` with `ASC`/`DESC`
- `LIMIT`
- Edge property access: `r.confidence`, `r.url_path`, `r.coupling_score`

**Not supported:** `WITH`, `COLLECT`, `SUM`, `CREATE/DELETE/SET`, `OPTIONAL MATCH`, `UNION`

## Common Cypher Patterns

```
# Cross-service HTTP calls with confidence
MATCH (a)-[r:HTTP_CALLS]->(b) RETURN a.name, b.name, r.url_path, r.confidence LIMIT 20

# Filter by URL path
MATCH (a)-[r:HTTP_CALLS]->(b) WHERE r.url_path CONTAINS '/orders' RETURN a.name, b.name

# Interface implementations
MATCH (s)-[r:OVERRIDE]->(i) RETURN s.name, i.name LIMIT 20

# Change coupling
MATCH (a)-[r:FILE_CHANGES_WITH]->(b) WHERE r.coupling_score >= 0.5 RETURN a.name, b.name, r.coupling_score

# Functions calling a specific function
MATCH (f:Function)-[:CALLS]->(g:Function) WHERE g.name = 'ProcessOrder' RETURN f.name LIMIT 20

# Module import dependencies (used by Example 2 in SKILL.md)
MATCH (m:Module)-[:IMPORTS]->(n:Module) WHERE m.name = 'alerting' RETURN n.name LIMIT 50
```

## Regex-Powered Search (No Full-Text Index Needed)

`search_graph` (name/qn patterns) and `search_code` (`regex=true`) support full Go regex, making full-text search indexes unnecessary. `search_code_semantic` is meaning-based and takes NO regex. Regex patterns provide precise, composable queries that cover all common discovery scenarios:

### search_graph — name_pattern / qn_pattern

| Pattern | Matches | Use case |
|---------|---------|----------|
| `.*Handler$` | names ending in Handler | Find all handlers |
| `(?i)auth` | case-insensitive "auth" | Find auth-related symbols |
| `get\|fetch\|load` | any of three words | Find data-loading functions |
| `^on[A-Z]` | names starting with on + uppercase | Find event handlers |
| `.*Service.*Impl` | Service...Impl pattern | Find service implementations |
| `^(Get\|Set\|Delete)` | CRUD prefixes | Find CRUD operations |
| `.*_test$` | names ending in _test | Find test functions |
| `.*\\.controllers\\..*` | qn_pattern for directory scoping | Scope to controllers dir |

### search_code — regex=true

| Pattern | Matches | Use case |
|---------|---------|----------|
| `TODO\|FIXME\|HACK` | multi-pattern scan | Find tech debt markers |
| `(?i)password\|secret\|token` | case-insensitive secrets | Security scan |
| `func\\s+Test` | Go test functions | Find test entry points |
| `api[._/]v[0-9]` | API version references | Find versioned API usage |
| `import.*from ['"]@` | scoped npm imports | Find package imports |

### Combining Filters for Surgical Queries

```
# Find unused auth handlers
search_graph(name_pattern="(?i).*auth.*handler.*", max_degree=0, exclude_entry_points=true)

# Find high fan-out functions in the services directory
search_graph(qn_pattern=".*\\.services\\..*", min_degree=10, relationship="CALLS", direction="outbound")

# Find all route handlers matching a URL pattern
search_code(pattern="(?i)(POST|PUT).*\\/api\\/v[0-9]\\/orders", regex=true)
```

## Critical Pitfalls

1. **`search_graph(relationship="HTTP_CALLS")` does NOT return edges** — it filters nodes by degree. Use `query_graph` with Cypher to see actual edges.
2. **`query_graph` defaults to a 200-row cap** — raise it with `max_rows` (up to 10000); the response sets `capped: true` and `effective_cap` when truncated, so undercounts are NOT silent. `search_graph` with `min_degree`/`max_degree` is still cheaper for pure counting.
3. **`trace_call_path` needs exact names** — use `search_graph(name_pattern=".*Partial.*")` first to discover names.
4. **`direction="outbound"` misses cross-service callers** — use `direction="both"` for full context.
5. **Page sizes are tool-specific** — confirm `has_more`/`offset` semantics per call rather than assuming a fixed default. Some tools return ~10 rows by default, others (e.g. `search_graph` with `limit=`) return whatever you ask for; do not rely on a server-wide default.

## Decision Matrix

| Question | Use |
|----------|-----|
| Who calls X? | `trace_call_path(direction="inbound")` |
| What does X call? | `trace_call_path(direction="outbound")` |
| Full call context | `trace_call_path(direction="both")` |
| Find by name pattern | `search_graph(name_pattern="...")` |
| Dead code | `search_graph(max_degree=0, exclude_entry_points=true)` |
| Cross-service edges | `query_graph` with Cypher |
| Impact of local changes | `detect_changes()` |
| Risk-classified trace | `trace_call_path(risk_labels=true)` |
| Service inventory | `service_map(project="...")` |
| Security surfaces | `query_security_surfaces` |
| PageRank by query | `rank_by_query` (symbols/keywords; not natural language) |
| Text / regex search | `search_code` (`regex=true`) or Grep |
| Meaning-based search | `search_code_semantic` |

> **Related:** code-explore (routing), codebase-memory-exploring, codebase-memory-quality, codebase-memory-tracing

## Examples

**Look up Cypher syntax for a call chain query:**
User asks "how do I query for all functions that call ProcessOrder?" Refer to the Cypher Subset and Common Cypher Patterns sections. Provide: `query_graph(query="MATCH (f:Function)-[:CALLS]->(g:Function) WHERE g.name = 'ProcessOrder' RETURN f.name LIMIT 20")`.

**Find the right tool for a structural question:**
User asks "I want to find unused imports." Consult the Decision Matrix — this maps to `search_graph(relationship="IMPORTS", direction="inbound", max_degree=0, label="Module")`. Explain why `search_graph` is preferred over `query_graph` for degree-filtered searches. (Note: inbound = modules with no incoming IMPORTS, i.e., unused.)

## Success Criteria

- Correct tool selected from the 15-tool inventory based on the question type
- Query syntax is valid against the supported Cypher subset (no unsupported clauses)
- Results are actionable — includes qualified names, file paths, or edge properties the user needs
