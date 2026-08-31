---
name: api-ingest
description: 'Ingest API documentation into the searchable doc library (probes OpenAPI/llms.txt, falls back to Firecrawl scraping).'
when_to_use: 'Use when API documentation needs to be ingested for future reference. Accepts URLs (HTML doc sites, OpenAPI spec URLs), local files (OpenAPI JSON/YAML, PDF, Postman collections), or GitHub raw URLs. Probes for OpenAPI/llms-full.txt first (10x cheaper than scraping), falls back to Firecrawl. Stores in ~/Documents/api-docs/{api-name}/, indexes with codebase-memory-mcp for semantic retrieval. Trigger phrases: "api-ingest", "ingest API docs", "add API docs", "index this API". Do NOT use for building MCP servers from specs or for pre-coding constraint checks (use /api-preflight).'
argument-hint: "[url-or-filepath] [--name api-name]"
compatibility:
  # Requires MCP servers: firecrawl, codebase-memory-mcp. Optional: context7-docs (falls back to ingesting regardless if unavailable).
  requires:
    - mcp: codebase-memory-mcp
      tools: [index_repository, index_status, search_code_semantic]
    - mcp: firecrawl
  optional:
    - mcp: context7-docs
      fallback: "falls back to ingesting regardless if unavailable"
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Agent AskUserQuestion Bash Glob Read Write mcp__codebase-memory-mcp__index_repository mcp__codebase-memory-mcp__index_status mcp__codebase-memory-mcp__search_code_semantic mcp__context7-docs__query-docs mcp__context7-docs__resolve-library-id mcp__firecrawl__*
effort: medium
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


# API Ingest — Add API Documentation to Searchable Library

Convert API documentation from any source into indexed, searchable markdown
that Claude can query during future sessions.

**Output**: `~/Documents/api-docs/{api-name}/`
**Index**: single `api-docs` project in codebase-memory-mcp (Voyage embeddings)

---

## Command Router

Parse ARGUMENTS for a source (URL or local file path) and optional `--name`.

If no arguments or `help`:
```
/api-ingest <url-or-filepath> [--name api-name]

Supported sources:
  - OpenAPI 3.x / Swagger 2.0 (JSON or YAML, local file or URL)
  - HTML doc site (probes for spec first, falls back to Firecrawl)
  - PDF (via pymupdf4llm)
  - Postman Collection v2.1 (JSON or documenter URL)
  - GitHub raw URL to spec file
```

---

## Phase 0: Pre-Probe (improvement 1 + 5)

**Run this before any scrape.** Two parallel checks that shape the whole run.

### 0a. Context7 overlap check

**Availability gate first:** the `context7-docs` MCP server is NOT registered on
the macOS host (verified 2026-08-22 against `~/.claude.json`; it was absent from
the 2026-08-06 backup too — these references predate the host). Probe with
ToolSearch (`select:mcp__context7-docs__resolve-library-id`); if empty, SKIP 0a
with a one-line note ("0a skipped: context7-docs not connected") and continue to
0b. Do not report the skip as an error, and do not install the server silently —
registering it is a user decision.

```
mcp__context7-docs__resolve-library-id(libraryName="<api-name>")
```

If a result exists with **snippets > 500 and benchmark > 70**, the API is well-covered by Context7 already. Tell the user:

> "Context7 has N snippets for {api-name} (score: X). You can query via
> `mcp__context7-docs__query-docs` without ingesting. Proceed with ingestion anyway? (y/N)"

Default to skipping if user doesn't confirm. This avoids re-doing work Context7 already did for free.

For domain-specific or internal APIs (unlikely to be in Context7), skip this check — no point probing.

### 0b. Canonical-source probe

For HTML doc URLs (not direct spec URLs), probe common paths **in parallel** before deciding to scrape. See `references/spec-probe-urls.md` for the full list. One 5-second parallel probe can replace 20 page scrapes.

Minimum probe set:
- `{origin}/llms-full.txt` — Mintlify / Anthropic / llmstxt.org standard
- `{origin}/openapi.json` + `.yaml`
- `{origin}/swagger.json`
- `{origin}/api/openapi.json`
- Any vendor-specific URL noted in the dispatch prompt

```bash
# Parallel probe (GET — we need the body to validate JSON/YAML structure below)
# ABSOLUTE binary paths are load-bearing: inside sandboxed subshell loops, PATH
# resolution for child binaries can fail mid-command (`command not found: curl`)
# while the same binary works at top level — measured 2026-08-22 on this exact
# probe shape. /usr/bin/curl etc., or run the loop from a written script file.
for path in /llms-full.txt /openapi.json /openapi.yaml /swagger.json /api/openapi.json; do
  (body=$(/usr/bin/curl -sL -m 5 -w "\n__HTTP_CODE__:%{http_code}" "${ORIGIN}${path}"); \
   code=$(echo "$body" | /usr/bin/tail -1 | /usr/bin/cut -d: -f2); \
   [ "$code" = "200" ] && echo "FOUND: ${ORIGIN}${path}" && \
   echo "$body" | /usr/bin/sed '$d' > "/tmp/probe-$(echo ${path} | /usr/bin/tr / _).body") &
done
wait
```

Validate found resources from the saved body files: JSON specs must parse + contain `openapi` or `swagger` key; llms-full.txt must be plain text > 10 KB. A 200 status alone isn't enough (many sites return HTML 200 for any path).

**If probe succeeds → jump to Phase 2a (spec ingestion).** Skip Firecrawl scraping of endpoint reference pages, but still run 0c.

### 0c. Concept-page probe

Even when 0b finds a spec, the prose-docs site usually carries cross-cutting concepts that aren't in OpenAPI: per-endpoint expansion values, pagination semantics, endpoint-naming conventions, error code shapes, webhook auth, idempotency keys, search/filter syntaxes. **Skipping the prose docs because OpenAPI was found gives a doc-set that looks complete but isn't.** This bit the Ashby ingestion (2026-04-26): the OpenAPI spec defined `expand: array<string>` with no per-endpoint enum, but the prose docs at `developers.ashbyhq.com/docs/expansions` listed the actual valid values per endpoint. mcp-forge built tool descriptions claiming `expand=['candidate'|'job']` worked when neither was valid; the model trusted the description, hit `invalid_input`, and incorrectly concluded the API didn't expose form responses.

When the source URL points to a docs site (not a direct spec URL), probe these standard concept paths in parallel **alongside 0b** — they flow into Phase 3, not Phase 2:

```bash
# Step 1 of 2 (HEAD): cheap status check — narrows the candidate set
# Step 2 of 2 (GET): inline body+heading validation — accepts only real
# concept pages and drops HTML 200 shells. Both run inline below.
for path in /docs/authentication /docs/auth \
            /docs/expansions /docs/expansion /docs/expanding-results \
            /docs/pagination /docs/pagination-and-incremental-sync \
            /docs/endpoint-naming \
            /docs/responses-and-errors /docs/errors /docs/error-codes \
            /docs/rate-limit /docs/rate-limits /docs/rate-limiting \
            /docs/idempotency /docs/idempotent-requests \
            /docs/webhooks /docs/setting-up-webhooks /docs/authenticating-webhooks \
            /docs/filtering /docs/sorting /docs/searching; do
  (url="${ORIGIN}${path}"; \
   # Step 1: HEAD status check
   code=$(curl -sIL -o /dev/null -w "%{http_code}" -m 5 "$url"); \
   [ "$code" != "200" ] && exit 0; \
   # Step 2: GET body + Content-Type + <h1>/<h2> heading match (>1KB body)
   tmp=$(mktemp); \
   ct=$(curl -sL -m 8 -D - -o "$tmp" "$url" | grep -i '^Content-Type:' | head -1); \
   echo "$ct" | grep -qi 'text/html' || { rm -f "$tmp"; exit 0; }; \
   [ "$(wc -c < "$tmp")" -lt 1024 ] && { rm -f "$tmp"; exit 0; }; \
   # Heading text must match the concept (case-insensitive substring)
   concept=$(echo "$path" | sed 's|/docs/||; s|-| |g'); \
   grep -iE "<h[12][^>]*>[^<]*${concept}" "$tmp" >/dev/null && \
     echo "FOUND: $url"; \
   rm -f "$tmp") &
done
wait
```

Per `references/concept-page-paths.md` (extend that list as new vendors surface different conventions). HEAD 200 is not sufficient — many sites return a 200 HTML shell for any path. The GET validation above is inline (no separate step required): each candidate must be `Content-Type: text/html`, body > 1 KB, AND contain an `<h1>`/`<h2>` whose text matches the concept name.

Concept pages found here are mandatory inputs to Phase 3 when the source is a docs site, even if a spec was also found. The two are complementary, not redundant.

---

## Phase 1: Detect Source Type

| Pattern | Source type | Phase |
|---------|-----------|-------|
| Ends with `.yaml`/`.yml`/`.json` | OpenAPI/Swagger/Postman file | 2a |
| Ends with `.pdf` | PDF | 2c |
| Contains `documenter.getpostman.com` | Postman | 2d |
| Phase 0b probe found a spec | Canonical source | 2a |
| Phase 0b probe found llms-full.txt | Full-docs text | 2b |
| Other URL | HTML docs | 2e (Firecrawl fallback) |

### Derive API name

- `--name` flag → use it (kebab-case, lowercase)
- OpenAPI spec → `info.title` (lowercase, hyphenated)
- URL → domain (e.g., `docs.hologram.io` → `hologram`)
- PDF → filename stem
- Ambiguous → ask user

### Create output directory

```bash
mkdir -p ~/Documents/api-docs/{api-name}
```

---

## Phase 2: Convert to Markdown

### 2a. OpenAPI/Swagger spec

**Set `TEMP` fallback before any `$TEMP` reference** (Linux/macOS do not export `TEMP`
by default; without this, `$TEMP/parse-foo.py` expands to `/parse-foo.py`):

```bash
TEMP="${TEMP:-/tmp}"
```

Write a Python parser to `$TEMP/parse-{name}.py` (NOT output dir — improvement 3).
Parse with `yaml.safe_load` / `json.load`. Detect: OpenAPI 3.x (`openapi` key) vs Swagger 2.0 (`swagger` key) vs Postman (`info.schema` contains `postman`).

**Always use `encoding='utf-8'`** in `open()` calls.

**If spec is large (>5 MB):** slice by `paths` prefix list. Keep the sliced YAML as `openapi.{json,yaml}` in the output dir for future re-parse but don't index it (wrong format for semantic search).

Generate `reference.md` with:
- API title, version, base URL
- Auth schemes from `securitySchemes`
- Endpoints grouped by tag/path prefix
- Per-endpoint: method, path, summary, parameters, request body schema, permissions/scopes from `security`

### 2b. llms-full.txt

Fetch with `curl`, split into `reference.md` (endpoint sections) + `constraints.md` (auth/rate limit sections). If > 10 MB, treat as too large and fall back to 2e.

### 2c. PDF

```python
import pymupdf4llm
md = pymupdf4llm.to_markdown("spec.pdf")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(md)
```

### 2d. Postman

Fetch from:
```
https://documenter.gw.postman.com/api/collections/{userId}/{collectionId}?segregateAuth=true&versionTag=latest
```
Header: `Origin: https://documenter.getpostman.com`. Parse `item` tree recursively.

### 2e. HTML scraping (Firecrawl fallback)

Only used when Phase 0b found no spec. See `references/firecrawl-rate-limits.md` for plan-specific limits.

1. `firecrawl_map` with `limit: 60`
2. Filter URLs: drop `/es/`, `/fr/`, `/pt-BR/`, `/ja/`, `/zh/`, `/de/`, `/discuss/`, PDFs
3. Scrape 8-12 highest-value pages, `formats: ["markdown"]`, `onlyMainContent: true`
4. **Standard plan** (current): 500 scrapes/min + 50 crawls/min — parallelism is free. If >12 pages needed, proceed without narrowing. For >50 pages, `/crawl` is fine.

---

## Phase 3: Extract Constraints

After `reference.md`, write `constraints.md` with:

- **Auth** — bearer / API key / OAuth / mTLS + creation URL
- **Base URL(s)** — prod, staging, regional variants
- **Rate limits** — per-plan table if published
- **Scopes / permissions** — exhaustive list, grouped by resource family
- **Webhook signatures** — HMAC algorithm + timing-safe compare requirement
- **Known gotchas** — from indexed sessions, agent memory, or the API's own warnings

For OpenAPI: parse `securitySchemes`, per-op `security` arrays, `x-ms-permissions` extensions.
For scraped: use `firecrawl_extract` with an auth/rate-limit schema.
For existing knowledge: read matching topic file at `~/.claude/agent-memory/topics/` and copy relevant gotchas.

**Concept pages from Phase 0c — mandatory ingestion when source is a docs site, even if a spec was found.** Scrape each found page with `firecrawl_scrape` (markdown format, `onlyMainContent: true`) and add corresponding sections to `constraints.md`:

| Concept page found in 0c | constraints.md section | Why mcp-forge needs it |
|---|---|---|
| `/docs/expansions` (or similar) | `## Expansions` — table of `\| Endpoint \| Valid expand values \|` | Without this, generated tools default to `expand: array<string>` with no enum constraint, and tool descriptions parrot generic placeholder text |
| `/docs/pagination` | `## Pagination` — cursor / limit / syncToken semantics, max page size | Generated list tools need accurate pagination guidance |
| `/docs/endpoint-naming` | `## Endpoint Naming` — `.list` vs `.info` vs `.search` semantics | Helps mcp-forge classify read vs write correctly |
| `/docs/responses-and-errors` | `## Error Shapes` — success/failure JSON shape, error code list | Generated `_check_response` helpers can produce better error messages |
| `/docs/rate-limit` | augment existing rate limit section | per-plan limits and burst behavior |
| `/docs/idempotency` | `## Idempotency` — header name, scope, retention | Write tools can advertise idempotency-key support |
| `/docs/webhooks` | augment existing webhook section with HMAC header name, signing algorithm, timestamp tolerance | Generated webhook handlers need exact header + algo |
| `/docs/filtering` / `/docs/sorting` / `/docs/searching` | `## Query Syntax` — filter/sort/search syntax | Better param descriptions for list tools |

**Spec ↔ prose divergence wins go to prose.** When the OpenAPI spec lacks an enum that prose docs enumerate (the Ashby `expand` case), or names a value that prose doesn't list, document the divergence in constraints.md so downstream consumers (mcp-forge) know which to trust:

```markdown
> NOTE: OpenAPI spec for /application.info has `expand: array<string>` with no items.enum.
> Per developers.ashbyhq.com/docs/expansions, valid values are
> `applicationFormSubmissions`, `openings`, `referrals`. Trust prose, not spec.
```

**Format hints for constraint-graph parse compatibility** — `~/Documents/api-docs/constraint_graph.py` reads `constraints.md` to build the queryable graph used by `/api-preflight` Phase 0. When the API's auth model fits, structure this file so the parser can extract nodes:

- `### {Resource Area}` headers above markdown permission tables with columns `| Operation | Delegated Permissions | Application Permissions | Admin Consent |`
- A `## Common Gotchas` section with `- bullet` entries

APIs without this structure (simple bearer-token REST, no scopes) won't populate operation → scope chains, but gotchas still parse. Do not force the Graph-style format on APIs it doesn't fit — just include what makes sense.

---

## Phase 3b: Emit llms-full.txt and skill.md

After `reference.md` and `constraints.md` exist, emit `llms-full.txt` (concatenation header + both files; skip if combined > 10 MB) and `skill.md` (condensed agent-framework summary; emit only when operation count ≤ 50). Full templates and field semantics in `references/output-templates.md`.

---

## Phase 4: Index with codebase-memory-mcp (improvement 4)

**Always index the parent directory `~/Documents/api-docs` with `force=true`.**
The project name is auto-derived from the path (`Users-<user>-Documents-api-docs`)
— there is one canonical api-docs project; per-subdir indexing fragments it.

```
mcp__codebase-memory-mcp__index_repository(
  repo_path="/Users/<user>/Documents/api-docs",
  force=true,
  skip_report=true
)
```

- **`force=true` is REQUIRED, not optional, for this skill** (verified 2026-06):
  an incremental run (omitting `force`) updates the GRAPH layer (node/edge counts
  grow) but does **NOT** regenerate the Voyage EMBEDDINGS for new files — so the
  new API's docs parse structurally yet are **silently unsearchable** by semantic
  query (`embeddings_indexed` stays flat; the test query returns only the old
  APIs). Because semantic prose retrieval is the entire point of this index,
  `force=true` (full re-embed of all api-docs) is mandatory on every ingest. The
  full re-embed of a handful of small markdown files is a few seconds — cheap.
- `skip_report=true` stops the tool writing `ARCHITECTURE_REPORT.md` into the
  docs dir (Phase 5 cleanup would otherwise have to remove it).
- Do **not** pass `mode="fast"` — fast mode skips docs/large files, the opposite
  of what we want; the default `full` mode embeds the markdown.
- Markdown files are embedded as `Module` nodes via Voyage `voyage-4-large`.

`index_repository` returns when indexing completes (synchronous) — no polling
loop needed.

**Do NOT verify by node/edge counts — that is a false-positive trap.** The graph
layer and the embedding layer update independently: node/edge counts can grow
while the Voyage embeddings stay stale, so a growing `nodes` count does **not**
prove the new docs are searchable. The ONLY trustworthy verification is the
semantic test query below returning the new API. (This is why `force=true` is
mandatory above — without it the graph grows but embeddings don't.)

**Test query (semantic — Voyage embeddings, NOT grep) — this IS the verification:**
```
mcp__codebase-memory-mcp__search_code_semantic(
  query="<api-name> authentication required scope",
  project="Users-<user>-Documents-api-docs"
)
```

Expected: a top result whose `file` starts with `{api-name}/` (e.g.
`{api-name}/reference.md`). If the new API does NOT appear (only previously-ingested
APIs return), the embeddings did not regenerate — re-run Phase 4 with `force=true`.
Confirm `embeddings_indexed` in the response rose by the new file count. Use
`search_code_semantic`, not `search_code` — the latter is grep-shaped and won't
rank prose by meaning.

**Degradation path — codebase-memory-mcp not connected this session (MANDATORY,
not an error).** Probe with ToolSearch (`select:mcp__codebase-memory-mcp__index_repository`);
if empty, the server is unregistered or failed to start. In order:

1. **CLI fallback (same engine, no MCP session needed):** run the index +
   verification through the binary directly. The Voyage key must be in env for
   embeddings to regenerate — mirror the launcher's Keychain pattern in a
   SCRIPT FILE (inline `$(security ...)` substitution is classifier-blocked;
   a written script that exports and never prints the value is the sanctioned
   shape, same as `~/.local/bin/codebase-memory-mcp-launch`):

   ```bash
   # in a written .zsh script: export VOYAGE_API_KEY from Keychain, then
   ~/.local/bin/codebase-memory-mcp cli index_repository \
     '{"repo_path": "/Users/<user>/Documents/api-docs", "force": true, "skip_report": true}'
   ~/.local/bin/codebase-memory-mcp cli search_code_semantic \
     '{"query": "<api-name> authentication required scope", "project": "Users-<user>-Documents-api-docs"}'
   ```

   The same verification contract applies: the new API's files must appear and
   `embeddings_indexed` must rise. NOTE: the binary's `--help` tool list is
   STALE — `search_code_semantic` and the `force`/`skip_report` params exist
   even though help omits them (verified 2026-08-22, v0.7.0-example.3).
2. **Neither MCP nor CLI available:** record `SEMANTIC-INDEX-DEFERRED` in the
   Phase 6 report with the reason. The ingested files remain fully valid and
   grep-able; only semantic retrieval is pending. Do NOT skip silently, and do
   NOT claim the index updated.

If the server is missing because it was DEREGISTERED (check `~/.claude.json`
`mcpServers` vs `~/.claude.json.backup`), restore with
`claude mcp add codebase-memory-mcp --scope user -- ~/.local/bin/codebase-memory-mcp-launch`
(2026-08-22 incident: the registration vanished from `~/.claude.json` between
Aug 6 and Aug 22 while the binary and launcher survived; restored the same day).

---

## Phase 4.5: Update Constraint Graph

`constraint_graph.py` (at `~/Documents/api-docs/constraint_graph.py`)
computes the graph on demand each time it is invoked (e.g. with `--dump`)
— it walks all `constraints.md` files under `api-docs/` and constructs
the queryable graph in-memory for `/api-preflight` Phase 0. There is no
persistent state file to update, but the new API must produce parseable
nodes or Phase 0 falls back to slower semantic search for it.

**If the script is absent on first ingest, this skill bootstraps a
minimal stub** (Step 4.5a-bootstrap below) so downstream consumers
(`/api-preflight` Phase 0) have a working utility. If bootstrap is
skipped or fails, Phase 4.5 degrades cleanly — Phase 4 (semantic index)
and Phase 1 of `/api-preflight` work fully without the graph.

### Step 4.5a: Bootstrap + parse verification

If `~/Documents/api-docs/constraint_graph.py` is absent, write it from the
stub in `references/constraint-graph-bootstrap.md`. Then invoke
`constraint_graph.py --dump` and count nodes for the new API.

### Step 4.5b–c: Classify outcome

The full classification table (0 nodes / stub-only / full parse / gotchas-only),
the exact subprocess wrapper, and the no-auto-repair rule live in
`references/phase-4-5-parse-verification.md`. If the script is still absent
after bootstrap, skip Phase 4.5 with a Note and proceed to Phase 5 — Phase 4
semantic index remains valid.

---

## Phase 5: Verify (improvement 6)

**Never trust a subagent's "success" report alone.** Agent return channels occasionally drop even when files are written.

```bash
OUT=~/Documents/api-docs/{api-name}
# Required — ingestion fails if missing or tiny
for f in reference.md constraints.md; do
  path="$OUT/$f"
  if [ ! -f "$path" ]; then
    echo "MISSING: $path — retry ingestion"
    exit 1
  fi
  size=$(wc -c < "$path")
  if [ "$size" -le 1000 ]; then
    echo "TOO SMALL: $path ($size bytes) — minimum is >1 KB (>1000 bytes), retry"
    exit 1
  fi
done
# Expected — warn but do not retry
for f in llms-full.txt; do
  path="$OUT/$f"
  if [ ! -f "$path" ]; then
    echo "NOTE: $f not emitted — check Phase 3b output (combined size > 10MB?)"
  fi
done
# Optional — only expected for ≤50 operations
if [ ! -f "$OUT/skill.md" ]; then
  echo "NOTE: skill.md not emitted — operation count > 50 or not attempted"
fi
```

**If files exist but agent reported failure** → accept (silent-success case, just indexing missing). Proceed to Phase 4.

**If agent reported success but files missing** → retry ingestion once. If second attempt also fails, ask user whether to:
- Switch source (try the spec URL instead of HTML)
- Skip this API
- Debug manually

Clean up any helper scripts that leaked into the output dir. The glob below
matches the documented writer naming (`parse-{name}.py`, hyphen — see Phase
2a). Use `find` with both hyphen and any other separator so future writer
variants are still caught:
```bash
find ~/Documents/api-docs/{api-name} -maxdepth 1 -type f \
     \( -name 'parse-*.py' -o -name 'parse[^a-z]*.py' -o -name '_*.py' \) \
     -delete
```

---

## Phase 5b: Persist newly-discovered constraints (re-ingest path)

If this invocation is a refresh of an already-ingested API and the caller
surfaced new constraints during downstream use, merge them into the existing
`constraints.md` before Phase 4 re-index. See `references/refresh-path.md`
for the merge + re-index procedure (uses parent-directory indexing with
canonical `api-docs` project name).

---

## Phase 6: Report

```
=== API Docs Ingested ===
API:          {api-name}
Source:       {url-or-filepath}
Method:       spec / llms-full.txt / scraped N pages
Files:        reference.md ({size}), constraints.md ({size})
                [+ llms-full.txt ({size})]
                [+ skill.md ({size}) if ≤50 operations]
                [+ openapi.json ({size}) if spec retained]
Index:        +{nodes_added} nodes (api-docs project, incremental)
Total index:  {total_nodes} nodes across all APIs
Graph:        +{N} nodes ({operations} ops, {scopes} scopes) — or warning if 0

Search:  mcp__codebase-memory-mcp__search_code_semantic(query="...", project="Users-<user>-Documents-api-docs")
Preflight: /api-preflight {api-name} "<use case>"
Refresh: /api-ingest {source} --name {api-name}
```

---

## Subagent dispatch

For parallel multi-API ingestion, dispatch the dedicated `api-ingest-worker`
agent (Firecrawl-only, ~15× lower MCP spawn overhead than `general-purpose`).
Cap at 5 parallel workers for MCP child-process memory safety. See
`references/subagent-dispatch.md` for dispatch template and per-plan limits.

**Worker prompt MUST include:** "Durable artifacts (`reference.md`,
`constraints.md`, anything under `~/Documents/api-docs/`) must never cite `/tmp`
or `$TEMP` paths as an evidence source — those paths vanish. Cite the retained
copy in the output directory (`llms.txt`, `openapi.json`) instead." (2026-08-22:
a worker's reference.md cited its /tmp scratch corpus as the line-number source
and needed a post-hoc repoint.)

## Examples

See `references/examples.md` for direct-spec, HTML-docs, and batch-parallel
invocation examples with expected timing.

---

## Success Criteria

- [ ] Phase 0 probes ran before any scrape (unless direct spec URL)
- [ ] Phase 0c concept-page probe ran when source was a docs site, EVEN IF a spec was found in 0b
- [ ] `reference.md` > 1 KB and contains endpoint definitions
- [ ] `constraints.md` > 1 KB and covers auth + rate limits
- [ ] When concept pages were found in 0c, each became a section in `constraints.md` (Expansions table, Pagination, Endpoint Naming, Error Shapes, Idempotency, etc.)
- [ ] Spec ↔ prose divergences explicitly noted in `constraints.md` so downstream consumers (mcp-forge) know which to trust
- [ ] `llms-full.txt` emitted (unless combined size > 10 MB — note if skipped)
- [ ] `skill.md` emitted when operation count ≤ 50 (note if skipped)
- [ ] Phase 4 ran with `force=true`, and the semantic test query returns the new API's files (node-count growth alone is NOT sufficient — embeddings must regenerate; confirm via `embeddings_indexed` rising and the new API appearing in search results)
- [ ] Phase 4.5 constraint graph parse-verification ran (constraint_graph.py --dump); node count reported (warn if 0)
- [ ] Test query returns results from the new API's files
- [ ] No helper scripts left in output dir
- [ ] If subagent was used, Phase 5 file verification passed

## Important Rules

- Always `encoding='utf-8'` on file writes (Windows cp1252 default)
- Never inline complex Python in bash — write to `$TEMP` first, then execute
- Helper scripts live in `$TEMP`, finals live in `~/Documents/api-docs/{name}/`
- Durable artifacts never cite `/tmp`/`$TEMP` paths as evidence sources — cite
  the retained `llms.txt`/`openapi.json` in the output directory
- For large specs (>5 MB), slice before indexing
- Firecrawl: `/map` before `/scrape`, prefer both over `/crawl` on Free
- The sliced spec file is retained as `openapi.json`/`openapi.yaml` in output; codebase-memory-mcp only embeds parseable source/markdown, so the large JSON spec is not semantically indexed (a GraphQL `schema.json` is likewise retained-but-not-indexed)
- `force=true` is REQUIRED on every api-docs index run — incremental updates the graph but NOT the Voyage embeddings, leaving new docs silently unsearchable; the full re-embed of a few small markdown files is only seconds
