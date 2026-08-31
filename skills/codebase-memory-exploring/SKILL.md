---

name: codebase-memory-exploring
description: "Explore codebase structure — modules, functions, classes, routes — via the code graph."
when_to_use: 'Use when asked to explore codebase structure, list functions or classes, show API endpoints, or understand how code is organized. Queries the code-graph knowledge graph for modules, routes, and relationships. Trigger phrases: "explore the codebase", "understand the architecture", "what functions exist", "show me the structure", "how is the code organized", "find functions matching", "search for classes", "list all routes", "show API endpoints". Do NOT use for semantic text search (use /code-explore or search_code_semantic), code quality analysis (use /codebase-memory-quality), or indexing (use /index-repo).'
effort: low
model: sonnet
argument-hint: '[query, e.g. "list all API endpoints", "show module structure"]'
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires the codebase-memory-mcp server for querying the knowledge graph.
  requires:
    - mcp: codebase-memory-mcp
allowed-tools: mcp__codebase-memory-mcp__list_projects mcp__codebase-memory-mcp__index_repository mcp__codebase-memory-mcp__search_graph mcp__codebase-memory-mcp__query_graph mcp__codebase-memory-mcp__get_code_snippet mcp__codebase-memory-mcp__get_architecture mcp__codebase-memory-mcp__service_map
---

## codebase-memory-exploring

# Codebase Exploration via Knowledge Graph

Use graph tools for structural code questions. They return precise results in ~500 tokens vs ~80K for grep-based exploration.

## Workflow

### Step 1: Check if project is indexed

```
list_projects
```

If the project is missing from the list:

```
index_repository(repo_path="/path/to/project")
```

If already indexed, skip — auto-sync keeps the graph fresh.

### Step 2: Get a structural overview

**For "what services exist" / service-map queries, start with `service_map`** — it returns a structured enumeration of services grouped by domain, with `depends_on` lists and route/security counts in one call:

```
service_map(project="<name>")
```

For package boundaries, hotspots, entry points, and HTTP cross-service edges, use `get_architecture` (below).

Start with the high-level architecture summary:

```
get_architecture(project="<name>")
```

Returns a service/module-level architecture map: top-level packages, their relationships, and the principal entry points. Use this first when the user asks "how is X organized" or "what does this codebase do" — it answers the structural question in one call without needing to compose `search_graph` queries.

For raw node/edge counts when `get_architecture` doesn't surface the needed granularity, prefer targeted `search_graph` calls (e.g., `search_graph(label="Route")` then count, or `search_graph(label="Function", name_pattern=".*_test$")` for test functions). For aggregate counts across labels, run `search_graph` per label and sum the totals — see `references/code-graph-reference.md`.

**HTTP_CALLS caveat**: The `services` aspect of `get_architecture` undercounts inter-service communication — zenoh/MCAP/pub-sub/CLI subprocess paths produce no HTTP_CALLS edges. Cross-reference architecture docs and `service_map`'s `depends_on` lists. See `code-explore`'s service/module identification anti-patterns for measurement evidence (PSM 2026-05-07: 3 HTTP_CALLS edges total, 2/3 FP).

### Step 3: Find specific code elements

Find functions by name pattern:
```
search_graph(label="Function", name_pattern=".*Handler.*")
```

Find classes:
```
search_graph(label="Class", name_pattern=".*Service.*")
```

Find all REST routes:
```
search_graph(label="Route")
```

Find modules/packages:
```
search_graph(label="Module")
```

Scope to a specific directory:
```
search_graph(label="Function", qn_pattern=".*services\\.order\\..*")
```

### Step 4: Read source code

After finding a function via search, read its source:
```
get_code_snippet(qualified_name="project.path.to.FunctionName")
```

### Step 5: Understand structure

For file/directory exploration within the indexed project, use Glob or search by structural node labels:
```
glob("/path/to/project/src/services/**/*.{ts,js}")
```

Alternatively, search for structural nodes within a scope:
```
search_graph(label="Module", qn_pattern=".*\\.services\\..*")
```

## When to Use Grep Instead

- Searching for **string literals** or error messages → `search_code` (grep-shaped) or Grep
- Finding a file by exact name → Glob
- For regex-scanned content (TODO/FIXME markers, secrets, patterns) → `search_code` with `regex=true` (NOT `search_code_semantic` — that tool is meaning-based and takes no regex; a regex passed to it is embedded as prose and returns cosine neighbors, not matches)
- The graph indexes structural elements (nodes, relationships); for text-pattern searches within code, use `search_code` (`regex=true`); for meaning-based search use `search_code_semantic`

## Key Tips

- Page sizes are tool-specific — confirm `has_more`/`offset` semantics per call rather than assuming a fixed default. Pass an explicit `limit=` when you need a known cap; use `offset` with the returned `has_more` to paginate.
- Use `project` parameter when multiple repos are indexed.
- Route nodes have a `properties.handler` field with the actual handler function name.
- `exclude_labels` removes noise (e.g., `exclude_labels=["Route"]` when searching by name pattern).

> **Related:** code-explore (routing), codebase-memory-quality, codebase-memory-tracing. Reference docs: `references/code-graph-reference.md`

## Examples

**Explore repo structure:**
User asks "how is mcp-servers organized?" Per Step 2, start with `get_architecture(project="mcp-servers")` for the service/module-level summary; fall back to label-scoped `search_graph` calls (e.g., `search_graph(label="Function")`, `search_graph(label="Module")`) if the user wants raw counts. Then `search_graph(label="Module")` to list top-level modules. Present the directory tree with function counts per module.

**Find API endpoints:**
User asks "what endpoints does this service expose?" Run `search_graph(label="Route")` to list all routes with HTTP methods, then `get_code_snippet` on each handler to show the implementation.


**Example 2: Finding module dependencies**
User says: "What modules does the alerting service depend on?"
Actions: Run `search_graph(label="Module", name_pattern="alerting")` to locate the alerting module(s), then `query_graph(query="MATCH (m:Module)-[:IMPORTS]->(n:Module) WHERE m.name = 'alerting' RETURN n.name LIMIT 50")` to enumerate import relationships. Follow up with `get_architecture(project="<name>")` if cross-package context is needed.
Result: Dependency tree showing 4 direct imports (redis_client, opa_client, crowdstrike_api, slack_notifier) and their transitive chains.

## Success Criteria

- Codebase structure presented with module/package hierarchy and function counts
- Functions and classes listed with file paths and qualified names
- Relationships between components identified (imports, containment, call edges)
- Output is actionable — user can navigate directly to the relevant code
