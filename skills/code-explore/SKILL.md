---

name: code-explore
description: "Find and understand code by meaning, combining semantic search with structural graph context."
when_to_use: 'Use when asked to find code by meaning, understand how something works, or explore code needing both semantic search and structural analysis. Routes to text/semantic search for conceptual queries and auto-chains with graph tools for context. Trigger phrases: "find code", "where is", "how does", "show me the", "find the implementation", "understand this codebase". Do NOT use for structural-only queries — use /codebase-memory-tracing for call chains and callers, /codebase-memory-quality for dead code and fan-out, /codebase-memory-exploring for codebase structure. Also not for file reading (use Read), simple grep (use Grep), or non-code questions.'
argument-hint: "[natural language code query]"
effort: low
model: sonnet
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires the codebase-memory-mcp server (unified text/semantic search + graph).
  requires:
    - mcp: codebase-memory-mcp
allowed-tools: Read mcp__codebase-memory-mcp__detect_changes mcp__codebase-memory-mcp__get_architecture mcp__codebase-memory-mcp__get_code_snippet mcp__codebase-memory-mcp__get_graph_schema mcp__codebase-memory-mcp__list_projects mcp__codebase-memory-mcp__query_graph mcp__codebase-memory-mcp__query_security_surfaces mcp__codebase-memory-mcp__rank_by_query mcp__codebase-memory-mcp__search_code_semantic mcp__codebase-memory-mcp__search_graph mcp__codebase-memory-mcp__trace_call_path mcp__codebase-memory-mcp__find_similar_functions mcp__codebase-memory-mcp__index_status mcp__codebase-memory-mcp__search_code
---

## code-explore

# Code Explore

Route code exploration queries to the right tool and chain automatically.

## Tool Inventory

All tools below live on the single `codebase-memory-mcp` server — text/semantic
search and the graph share one backend, one registry, one `project` parameter
(no separate "active project" switch; pass `project` per call, or omit to use
the session-detected default).

### Text / semantic search
| Tool | Use for |
|------|---------|
| `mcp__codebase-memory-mcp__search_code` | Literal / regex TEXT search over indexed files (grep-shaped) — string literals, error messages, config values, imports. Set `regex=true` for pattern matching. NOT semantic — use `search_code_semantic` for meaning-based queries. |
| `mcp__codebase-memory-mcp__search_code_semantic` | Voyage-embedding semantic search by meaning ("authentication middleware", "GPS parsing"), with `file_pattern`/`label` filters. No regex — this is meaning-based, not pattern-based. |
| `mcp__codebase-memory-mcp__find_similar_functions` | Find functions similar to an already-indexed function BY NAME (refactor/duplicate-candidate search) — NOT a free-text search; needs an existing function name as the seed |
| `mcp__codebase-memory-mcp__index_status` | Check if repo is indexed |

### Graph
| Tool | Use for |
|------|---------|
| `mcp__codebase-memory-mcp__search_graph` | Find nodes by name/pattern |
| `mcp__codebase-memory-mcp__query_graph` | Cypher relationship queries |
| `mcp__codebase-memory-mcp__trace_call_path` | Trace call chains between functions |
| `mcp__codebase-memory-mcp__get_code_snippet` | Get source + caller/callee metadata |
| `mcp__codebase-memory-mcp__get_architecture` | Codebase overview (routes, hotspots, layers) |
| `mcp__codebase-memory-mcp__detect_changes` | Blast radius of uncommitted changes |
| `mcp__codebase-memory-mcp__query_security_surfaces` | Security audit (auth, sinks, crypto) |
| `mcp__codebase-memory-mcp__rank_by_query` | PageRank top-K nodes for a symbol-list or short-keyword query. **Prefer `search_code_semantic` for natural-language queries** — `rank_by_query` collapses on common-token noise (verified 2026-05-13: "GPS data parsing reception" returned `reception` parameter in an unrelated camera-replay file as top hit). |

**Metadata:** the unified `codebase-memory-mcp` tools return a `_metadata` envelope with `freshness` (index-vs-disk state) and `provenance` (data_source, and `model` on semantic search). The `_metadata.reranker.{applied,reason}` fields and their reason vocabulary belonged to the RETIRED Python `code-search` server and are not emitted by this server — do not key behavior on them. `search_code_semantic` errors clearly ("No embeddings available…") when `VOYAGE_API_KEY` was unset at index time; that message, not a reranker flag, is the signal to reindex.

## When to Use This Skill vs codebase-memory-*

This skill handles **conceptual** and **mixed** queries that need text/semantic search or both search + structural tools chained together. For **structural-only** queries that only need the graph, use the specialized skill directly:

- Call chains, callers, callees, impact analysis → `/codebase-memory-tracing`
- Dead code, fan-out, fan-in, coupling analysis → `/codebase-memory-quality`
- Codebase structure, function inventory, route listing → `/codebase-memory-exploring`

The specialized skills provide deeper workflows (verification steps, risk classification, pagination) that this router's one-liner routing table cannot match.

## Routing Decision Tree

## Step 0: Discover Declaration Patterns (for broad searches)

For codebase-wide queries ("find all X", "audit Y", "inventory Z"), discover HOW the codebase declares the concept before searching for values:

1. **Identify the language/framework stack** — check file extensions, build files (`Cargo.toml`, `flake.nix`, `package.json`), or run `get_architecture`
2. **Find declaration idioms** — sample a few files to discover macros, config DSLs, and env-var patterns:
   - **Rust**: `defvar!` macros, `const` declarations, `env::var().unwrap_or()` fallbacks
   - **Nix**: `mkOption { default = ...; }` blocks, inline `password =` / `environment =` assignments
   - **Python**: `os.getenv()` / `os.environ` with defaults, class-level constants
   - **TypeScript**: `process.env.X || 'default'` patterns
   - **Go**: `os.Getenv` with fallbacks, const blocks
   - **Config files**: embedded PEM keys, base64 tokens, JSON credentials
3. **Search those patterns first** — grep for the codebase's own idioms before generic value patterns
4. **Then run generic value-pattern greps** as a second pass for universal patterns (`password = "..."`, `BEGIN PRIVATE KEY`)

Skip this step for targeted queries ("what calls function X?", "where is file Y?") — it's only for broad sweeps.

### Step 1: Classify the query

| Query pattern | Type | Primary tool |
|--------------|------|-------------|
| "Where is the X code?" | Conceptual | search_code_semantic (meaning); search_code for a known literal/symbol |
| "Find the X implementation" | Conceptual | search_code_semantic (meaning); search_code for a known literal/symbol |
| "Find all definitions of `<exact symbol>`" | Exact-symbol | **Grep** with regex (e.g., `^(pub )?(struct\|enum\|type)\s+<Name>\b`) — cheaper and more precise than graph for known identifiers; fall back to `search_graph(name_pattern="^<Name>$")` if Grep returns ambiguous results |
| "Find all Rust `fn new` / constructors / `impl X { fn new(...)`" | Rust idiom | **graph** `search_graph(label="Method", name_pattern="^new$")` OR **Grep** `^\s*(pub\s+)?(async\s+)?fn\s+new\s*[(<]`. **NOT semantic search** — embedding anchors on TypeScript "constructor" vocab and misses Rust `fn new` entirely (verified 2026-05-13: top-5 hits were all TS constructors). |
| "Find `todo!()` / `unimplemented!()` / `panic!("not impl")` stubs" | Rust idiom | **Grep** `(todo!\|unimplemented!)\s*\(` — precise. **NOT semantic search** — semantic for "todo unimplemented stub" returns unrelated semantic neighbors (NMEA file headers in PSM eval, no actual stub call sites). |
| "Find `#[derive(<Trait>)]` types" | Rust idiom | **Grep** `#\[derive\([^)]*<Trait>` — precise. **NOT graph** — `decorator_tags CONTAINS 'derive'` returns 0 even with 47+ derive blocks present (extraction gap, see knowledge-base/plans/2026-05-13-test-battery-n2-n4 N2). |
| "Find `macro_rules!` definitions" | Rust idiom | **Grep** `^macro_rules!\s+\w+` — precise. `search_code` also works (found `defcan/message_builder`, `libio/sync_macros`, etc.) but slower; Grep returns counts + file list directly. |
| "How does X work?" | Conceptual | search_code_semantic (meaning) |
| "Show me X patterns" | Conceptual | search_code_semantic (meaning); search_code regex for a literal pattern |
| "Find all X" / "audit Y" | **Broad** | search_code (multi-phrasing) |
| "What is X?" / "What does X do?" / "Tell me about X" | **Identification** | graph: search_graph + paginate + edge queries — see Step 1.6 |
| "What calls X?" | Structural | graph: query_graph CALLS inbound |
| "Who uses X?" | Structural | graph: search_graph + trace |
| "Blast radius of changing X" | Structural | graph: detect_changes |
| "Find dead code" | Structural | graph: search_graph max_degree=0 |
| "Show all routes/endpoints" | Structural | graph: get_architecture routes |
| "Trace from X to Y" | Structural | graph: trace_call_path |
| "What depends on X?" | Structural | graph: query_graph IMPORTS inbound |
| "Understand this codebase" | Overview | graph: get_architecture, then search_code for details |

### Step 1.5: Multi-Phrasing Expansion (broad queries only)

When Step 1 classifies a query as **Broad** — "find all X", "audit Y", "inventory Z",
or any security audit query — expand the single query into 4 search passes (3 parallel
+ mandatory self-seed D) before executing. This catches results that natural language
alone misses.

> Reference: `references/search-strategies.md` for the full strategy catalog and
> quantitative evidence (22% model overlap, 2x HyDE confidence scores).

**Detect broad queries by keyword**: "find all", "audit", "inventory", "every",
"scan for", "list all", or security terms ("credentials", "secrets", "firewall",
"unsafe", "permissions", "hardcoded").

**Generate 3 phrasings:**

1. **A — Natural language** (the original query, as-is)
2. **B — Hypothetical code** (what the answer would look like as code)
   - Identify the primary language from Step 0 or the project's `top_tags`
   - Generate a 1-2 line code snippet that represents a *specific instance* of what you're searching for
   - Example: for "find hardcoded credentials" in a Nix repo → `password = "admin123"; apiKey = "sk-secret-key-hardcoded"; environment.AWS_SECRET_ACCESS_KEY = "AKIA"`
3. **C — Framework idiom** (the codebase's own declaration syntax for the concept)
   - Use Step 0's discovered declaration patterns
   - Example: for "find hardcoded credentials" in Nix → `mkOption type str default secret token oidc_client_secret environment`

**Always run all 3 phrasings** for broad queries — do not skip based on score. Each phrasing
surfaces different results regardless of NL score quality (tested: even when NL scored 0.03,
the framework idiom phrasing found 3 unique files at 0.07).

**Self-seeding (mandatory 4th phrasing):** After phrasings A, B, C return results,
examine the top result's `name` and `snippet` fields from EACH phrasing. Extract the
structural vocabulary the codebase uses for this domain — field names, function patterns,
module conventions. Generate phrasing D using that vocabulary as a new query.

Examples from testing (2026-04-11, 4 queries, +9 unique files):
- Phrasing A top result `credentials = {` → Phrasing D: `credentials = { accessKeyId secretAccessKey sessionToken region endpoint`
  → Found: `reloadd/update_handler.rs:download_from_s3`, `hitlman-apid/main.rs`
- Phrasing B top result `create_raw_image_message` → Phrasing D: `from_raw_parts as_ptr &[u8] Vec<u8> buffer bytes raw pixel frame`
  → Found: `apid/compression.rs:encode_zstd_frame_raw`, `torchyd2/util.rs:compute_checksum`
- Phrasing B top result `register_compass_device` → Phrasing D: `fn register_device serialport::new TTYPort CanSocket socketcan baud_rate`
  → Found: `libdevice/device_info.rs:send_pgn_request`, `libdb/example/device.rs:register_device`, `device-setup/main.rs:register_device`

The key insight: top results reveal the codebase's own vocabulary for the domain.
Using that vocabulary as a query digs deeper into the same semantic neighborhood,
finding related functions the original phrasings missed. This produced a 20-30%
recall improvement on top of the 3-phrasing pipeline.

**Iterative self-seeding:** If phrasing D surfaces new vocabulary not present in A/B/C
results (new function names, new module patterns, new declaration idioms), generate
phrasing E using D's top results the same way D used A/B/C's. Cap at 2 self-seed cycles
(D and E). The first cycle discovers the codebase's domain vocabulary; the second cycle
digs deeper into that vocabulary's neighborhood.
(Pattern source: affaan-m/everything-claude-code iterative-retrieval — Context7 registry 2026-04-11)

**Execute phrasings A, B, C in parallel** via `search_code` (they're independent).
Then generate and execute phrasing D (sequential — needs A/B/C results as input).
If D reveals new vocabulary, generate and execute phrasing E (sequential — needs D's results).
Use `k=10` per phrasing to cast a wider net.

**Merge results:**
- Union all results by file path
- Deduplicate — same file from multiple phrasings = one entry
- Annotate each result with which phrasings found it: `[A,B,C]`, `[B,C]`, `[A]`, etc.
- Sort by: appearance count (desc), then max score across phrasings (desc)

**Present with confidence tiers:**
- **High confidence** (3+ of 4 phrasings): report directly
- **Medium** (2/4): report, note which phrasings agreed
- **Medium-Low** (1/4 idiom, signature, or self-seed): report, flag for manual verification
- **Low** (1/4 natural-language-only): include but note single-source
- Self-seeded results (phrasing D only) that don't overlap with A/B/C are **Medium-Low** — they're
  deeper in the semantic neighborhood but unconfirmed by independent phrasings

**Anti-patterns:**
- Do NOT generate generic language constructs as HyDE queries (`Result<T, Error>`, `async fn`, `impl Trait`). These match thousands of chunks. Be specific to the *security-relevant pattern*.
- Do NOT multi-phrase targeted queries ("where is function X"). Single pass is sufficient.

**Dual-model consensus — mechanism unverified on the consolidated server.**

The original mechanism here (`switch_project(project_path=..., provider=...)`
to swap between a `voyage` and `voyage-context` index for the same path, run
the query on each, merge) relied on the old code-search server's per-provider
registry entries and its `switch_project` tool. Neither exists on
`codebase-memory-mcp`: `list_projects` and `search_code_semantic`'s schemas
don't advertise a provider field or parameter, so whether dual-model
consensus survives in some other form is **unverified** — check the actual
`list_projects` response for this project (it may carry more fields than the
terse tool description implies) before assuming the capability is gone
entirely. Until re-verified, treat dual-model consensus as unavailable and
rely on multi-phrasing (Step 1.5) for recall diversity on a single model —
it doesn't need re-verification and already provides most of the same value
(catching results a single query phrasing misses).

Use `voyage` + `voyage-context` (both >0.79 MRR on Nix). Avoid Voyage + Jina for Nix
(Jina MRR 0.638 adds noise). Check `references/search-strategies.md` for model pairing guidance.

### Step 1.6: Service/Module Identification Pattern

When Step 1 classifies a query as **Identification** ("what is X", "what does X do", "tell me
about X"), run the fixed, completeness-biased recipe in
`references/service-module-identification.md` (Step A paginated `search_graph` surface → B
architecture docs → C cross-service edges → D canonical source files → E verify before claiming,
plus its anti-patterns) before any free-form exploration.

### Step 2: Execute primary tool

Run the tool identified in Step 1 (or the multi-phrasing pipeline from Step 1.5 for broad queries).

### Step 3: Auto-chain if the answer needs the other tool

| After this result... | Follow up with... |
|---------------------|-------------------|
| `search_code`/`search_code_semantic` found a function | Graph: `query_graph` CALLS inbound to see who calls it |
| `search_code`/`search_code_semantic` found a function | Graph: `get_code_snippet` with include_neighbors=true for callers/callees |
| `search_code` result is truncated | Graph: `get_code_snippet` by qualified name for full source |
| Graph found callers/callees by name | `search_code` to understand what a caller does |
| Graph found a node | Read tool with file:line for the exact implementation |
| "How does X work?" partially answered | `find_similar_functions(name=<the function already found>)` for related/refactor-adjacent code |

### Step 4: Present combined answer

1. Direct answer to the question
2. Primary result (file, function, line numbers)
3. Chained context (callers, dependencies, similar code)

## Pre-flight Check

Before routing, verify the target repo is indexed.

**No active-project / switch step anymore.** The consolidated server has no
`switch_project` tool and `list_projects` reports no `current_project` field —
every query tool takes `project` as a per-call parameter (name, not path),
defaulting to "session project" (server-resolved) when omitted. The historical
hang (`switch_project` skipped → CWD auto-registered as a project → endless
reindex of `~/`) was specific to the old server's CWD-auto-registration
behavior; whether an equivalent risk exists in the session-project default is
**unverified** — as a defensive practice, always pass `project` explicitly
when the target repo is inferable from the query (CWD signal, mentioned
crate/service, explicit repo reference), and never pass `~`, `/`, `$HOME`, or
a bare drive root as a `project`/`repo_path` value anywhere in this skill.

1. **Resolve the target project name**: `mcp__codebase-memory-mcp__list_projects`
   — find the entry matching the query's target repo by `root_path`. If the
   target repo isn't obvious from the query and no entry obviously matches,
   ASK the user rather than guess.
2. **Check the index exists and is healthy**:
   - `mcp__codebase-memory-mcp__index_status(project=<name>)` — if the project
     isn't found or `status != "ready"`, stop and tell the user "the index for
     `<path>` is missing or not ready. Run `/index-repo <path>` first." Do NOT
     attempt to call `index_repository` from this skill — indexing is the
     `/index-repo` skill's job.
3. **Pass `project` explicitly on every call** in this skill (search and
   graph tools alike) once resolved in Step 1 — don't rely on the session
   default once a specific target is known.

If the project can't be resolved, ask the user rather than falling back to
an unscoped search.

## Examples

**"Where's the rate limiting code?"**
1. Conceptual -> semantic: `search_code_semantic(query="rate limiting")` -> finds `check_rate_limit` at claude-proxy:902
2. Chain -> graph: `query_graph("MATCH (f)-[:CALLS]->(g) WHERE g.name = 'check_rate_limit' RETURN f.name LIMIT 10")` -> shows callers
3. Answer: "Rate limiting is in `check_rate_limit()` at claude-proxy/claude_proxy.py:902. Called by `proxy_messages()` during request handling."

**"What calls _build_oauth?"**
1. Structural -> graph: `query_graph("MATCH (f)-[:CALLS]->(g) WHERE g.name = '_build_oauth' RETURN f.name, f.file LIMIT 10")`
2. Chain -> search: `search_code(pattern="_build_oauth")` -> shows the implementation
3. Answer: "`_build_oauth` is defined at shared/mcp_http.py:130. Called by `configure_http_transport` at line 377."

**"Understand the authentication system"**
1. Overview -> graph: `get_architecture(aspects=["routes", "services"])` -> service map
2. Conceptual -> semantic: `search_code_semantic(query="authentication logic")` -> finds `_build_oauth`, `_authorize_tool_call`
3. Structural -> graph: `trace_call_path(function_name="_authorize_tool_call")` -> auth call chain
4. Answer: combined narrative

## Graph Query Quick Reference

Copy-ready `search_graph` / `query_graph` / `trace_call_path` / `detect_changes` recipes for structure
exploration, dead-code and fan-in/fan-out analysis, call-chain tracing, cross-service edges, plus the
six known code-graph pitfalls, and the Deep Architecture Review template pointer: see
`references/graph-query-quick-reference.md`.

## Success Criteria

- Pre-flight Check completed: target project resolved via `list_projects`, index status verified `ready`; `project` passed explicitly on every subsequent call
- Query routed to the correct tool (search_code/search_code_semantic for conceptual, graph tools for structural)
- Results include file paths and line numbers for navigation
- Auto-chaining applied when the primary result needs context from the other tool
- For structural queries: caller/callee chains, risk classification, or degree metrics provided
- For dead code: false positives filtered by checking USAGE edges and entry points
- For broad/audit queries: multi-phrasing applied — phrasings A (natural language), B (hypothetical code), C (framework idiom) MANDATORY, plus mandatory self-seed phrasing D, and conditional phrasing E when D surfaces new vocabulary (4-5 total passes); results annotated with confidence tiers
- For broad queries: union of results is larger than any single phrasing (the whole point — catch what NL misses)
