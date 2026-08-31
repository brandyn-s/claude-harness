---
name: api-preflight
description: "Map an API's auth, scopes, token types, and prerequisite chain before writing code against it."
when_to_use: 'Use before writing code that calls an API to extract all authentication requirements, permission scopes, token types, and constraint chains. Searches indexed API docs (code-search), topic files, and optionally live docs via Firecrawl. Produces a constraint map showing the full dependency chain of prerequisites. Trigger phrases: "api-preflight", "what permissions do I need", "check API constraints", "preflight API", "before I code against this API". Do NOT use for ingesting new API docs (use /api-ingest) or for building MCP servers (use /mcp-forge-build).'
argument-hint: "[api-name] \"[use-case description]\""
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: AskUserQuestion Bash Read mcp__codebase-memory-mcp__search_code mcp__firecrawl__firecrawl_agent mcp__firecrawl__firecrawl_agent_status mcp__firecrawl__firecrawl_extract mcp__memory-search__memory_search
effort: low
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


# API Preflight — Constraint Extraction Before Coding

Surface all authentication requirements, permission scopes, token types,
rate limits, and constraint chains BEFORE writing any code against an API.
Prevents the pattern of discovering prerequisites through sequential
trial-and-error.

---

## Command Router

Parse ARGUMENTS for an API name and a use-case description in quotes.

If no arguments or `help`:
```
API Preflight — Extract constraints before coding

Usage:
  /api-preflight <api-name> "<use-case description>"

Examples:
  /api-preflight microsoft-graph "manage conditional access policies in GCC High"
  /api-preflight slack "delete private channels in Enterprise Grid"
  /api-preflight hologram "bulk activate SIM cards and update data plans"

What it does:
  1. Searches indexed API docs for auth/permission requirements
  2. Checks agent-memory topic files for known gotchas
  3. Optionally scrapes live docs for missing constraint data
  4. Produces a constraint map showing the full prerequisite chain
```

---

## Mode Detection

Parse the use-case description to determine mode using the trigger lists below.
If both lists match (or neither matches), call `AskUserQuestion` to ask the
user which mode applies — do NOT guess silently.

**Troubleshooting mode triggers** (any of these in the use-case description):
- HTTP error mentions: "403", "401", "400", "429", "5xx", "got an error",
  "getting <status>", "returns <status>", "fails with"
- Auth-failure phrases: "MFA loop", "can't authenticate", "auth fails",
  "token expired", "missing scope", "invalid grant", "unauthorized",
  "forbidden", "consent required"
- Symptom language: "not working", "broken", "stops responding", "hangs",
  "silently fails", "intermittent", "regression"
- Diagnostic verbs at the head of the description: "debugging",
  "diagnosing", "troubleshooting", "investigating", "why does",
  "why is", "what's wrong with"

**Pre-coding mode triggers** (default if no troubleshooting trigger matches):
- Action verbs in future/infinitive tense: "manage", "create", "list",
  "delete", "update", "build", "implement", "add", "set up", "integrate",
  "wire up", "support", "enable"
- Planning language: "before I code", "what do I need", "preflight",
  "check requirements", "what permissions", "what scopes", "prerequisites"

**Decision rule:**
1. Scan the use-case description for any troubleshooting trigger → troubleshooting mode.
2. Otherwise, scan for any pre-coding trigger → pre-coding mode.
3. If both match (e.g. "build retry logic for the 429 errors"), ask the user
   which mode applies — both phases can run, but the output ordering differs.
4. If neither matches (rare — purely descriptive prompt), default to
   pre-coding mode and note the ambiguity in the output.

Troubleshooting mode adds Step 3b and prioritizes operational gotchas over spec-level
constraints in the output.

---

## Phase 0: Constraint Graph Query (fastest path)

`constraint_graph.py` lives at `~/Documents/api-docs/constraint_graph.py`
and is **invoked** by both `/api-ingest` (Phase 4.5 verification with
`--dump`) and `/api-preflight` (Phase 0 with `--dump`). On first ingest
`/api-ingest` **bootstraps a minimal stub** of it (Phase 4.5a) so this
fast-path has a working utility; a richer environment-shipped version, if
present, is left untouched. `/api-preflight` only reads it: query it if
present, and skip this phase cleanly if absent (e.g. `/api-ingest` has
not run yet, or bootstrap was skipped).

Before any search, check that the script exists and query it:

```bash
GRAPH=~/Documents/api-docs/constraint_graph.py
if [ ! -f "$GRAPH" ]; then
  echo "Note: constraint_graph.py not found at $GRAPH — skipping Phase 0." >&2
  echo "Proceeding to Phase 1 (indexed-docs search) without graph fast-path." >&2
  # Do NOT abort — Phase 1 / Phase 2 are fully sufficient on their own.
else
  python3 "$GRAPH" --dump | python3 -c "import json, sys; nodes = json.load(sys.stdin)['nodes']; filtered = [n for n in nodes if n.get('api') == '{api-name}']; print(json.dumps({'nodes': filtered}))"
fi
```

If the graph script is missing:
- Skip directly to Phase 0b / Phase 1 — they do not depend on it.
- Note in the final output: "Constraint graph fast-path unavailable; results
  derived from indexed docs + topic files only."

If the graph returns nodes for this API:
- Extract operation and scope nodes as the initial constraint data (deterministic, no reasoning needed)
- Still run Phase 1 Steps 2-3 for gotchas and supplementary context and chain completion
- Phase 2 is optional (graph provides initial structure; indexed docs + topic files fill gaps)

If the graph returns nothing (API not in graph, or no matching operations):
- Proceed to Phase 1 as normal

**Note:** The bootstrap stub supports `--dump` only. Environment-shipped versions (if present) may
support additional flags like `--shared`, `--cross-api`, and `--deep` for advanced queries;
check the script's help or docstring if using a richer version.

---

## Phase 0b: Staleness Check

Check the indexed docs age:

1. Read modification date of `~/Documents/api-docs/{api-name}/constraints.md`. Use one of:
   - Bash: `stat -c %Y ~/Documents/api-docs/{api-name}/constraints.md` (Linux) or `stat -f %m ~/Documents/api-docs/{api-name}/constraints.md` (macOS) — returns Unix epoch seconds.
   - Python: `import os; os.path.getmtime("~/Documents/api-docs/{api-name}/constraints.md")` (expand `~` with `os.path.expanduser`).
   - If the file does not exist: treat as "not indexed" — skip Phase 0b and direct user to /api-ingest.
2. Compute age = `(now - mtime) / 86400` days.
3. If **>30 days stale**: warn: "API docs last updated {N} days ago. Run /api-ingest to refresh."
4. If **>90 days stale**: strongly recommend refresh before proceeding.

---

## Phase 1: Search Indexed Docs

### Step 1: Check if API docs are indexed

Query the API docs project directly — the consolidated `codebase-memory-mcp` tools take `project` as a per-call parameter (no separate switch step):
```
mcp__codebase-memory-mcp__search_code(pattern="<term>", project="api-docs-{api-name}")
```

If the project doesn't exist, inform the user:
```
"No indexed docs found for {api-name}. Run /api-ingest to add them first,
or I can search live docs via Firecrawl (slower, less reliable)."
```

If the user chooses to proceed without indexed docs, skip to Phase 2.

### Step 2: Search for constraint data

Run 3 targeted queries against the indexed docs:

1. **Auth requirements for the use case**:
   ```
   search_code(query="{use-case} authentication permissions required scopes")
   ```

2. **Token type and flow constraints**:
   ```
   search_code(query="{api-name} token type delegated application OBO client credentials")
   ```

3. **Gotchas and known issues**:
   ```
   search_code(query="{use-case} gotcha error constraint limitation")
   ```

Read the top 2-3 results from each query (6-9 file sections total). Extract:
- Required permissions/scopes
- Token type (delegated vs application)
- Admin consent requirements
- Rate limits
- Known gotchas

### Step 3: Check agent-memory topic file (HIGHEST PRIORITY SOURCE)

**Topic files outrank all other sources.** They contain battle-tested gotchas
from real production sessions — not generic doc extractions.

Read `~/.claude/agent-memory/topics/{topic-slug}.md` if it exists. Extract
any `[confirmed]` or `[observed]` gotchas relevant to the use case.

**Topic-file naming is not always the verbatim API name.** Topic slugs are
short, human-friendly identifiers — they may abbreviate the API name. Resolve
the slug with this fallback chain:

1. Try `{api-name}.md` (literal).
2. If missing, try common short aliases: e.g. `microsoft-graph` → `msgraph`,
   `google-workspace` → `gworkspace`, `amazon-web-services` → `aws`.
3. If still missing, list the topics directory and grep for the API name in
   the file headings: `grep -l -i "{api-name}" ~/.claude/agent-memory/topics/*.md`.
4. If no topic file resolves, emit the "no topic file" warning below.

Also run `mcp__memory-search__memory_search(query="{api-name} {use-case}")` to catch
cross-domain patterns stored in other topic files — this is the canonical
lookup mechanism and is not affected by slug-naming drift.

**Source priority for constraint map:**
1. Constraint graph chains (Phase 0) — deterministic, structural
2. Topic file `[confirmed]` entries — highest confidence from real sessions
3. Topic file `[observed]` entries — medium confidence, flag as observed
4. Indexed `constraints.md` — structured, auto-generated by `/api-ingest`
   from OpenAPI specs + Firecrawl extraction (no hand-curation pass)
5. Indexed per-family reference files — from OpenAPI spec
6. Firecrawl extraction — lowest confidence, generic

**When no topic file exists:** Include this warning in the output:
```
No operational gotchas on file for {api-name}. Constraint data is from
API docs only and may miss implementation-level issues.
```

### Step 3b: Troubleshooting search (troubleshooting mode only)

If the user is hitting an error, additionally search for:
```
search_code(query="{error message or HTTP status code} {api-name}")
```
And check topic file for matching error patterns. Present gotchas that
match the error scenario first, constraint chains second.

---

## Phase 2: Supplement from Live Docs (if needed)

If Phase 1 didn't produce sufficient constraint data (fewer than 2
concrete permissions identified, or no token type information), supplement
with Firecrawl.

### Option A: Targeted extraction (fast, 1 minute)

Use `firecrawl_extract` against the API's official permission reference
page with a constraint schema:

```
mcp__firecrawl__firecrawl_extract(
  urls=["<permission-reference-url>"],
  prompt="Extract all required permissions, scopes, token types, admin consent
          requirements, and constraints for: {use-case}",
  schema={
    "type": "object",
    "properties": {
      "required_permissions": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "scope": {"type": "string"},
            "type": {"type": "string", "description": "delegated or application"},
            "admin_consent": {"type": "boolean"},
            "for_operation": {"type": "string"}
          }
        }
      },
      "token_constraints": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "constraint": {"type": "string"},
            "impact": {"type": "string"}
          }
        }
      },
      "rate_limits": {"type": "string"},
      "prerequisites": {
        "type": "array",
        "items": {"type": "string"}
      }
    }
  }
)
```

Known permission reference URLs:
- Microsoft Graph: `https://learn.microsoft.com/en-us/graph/permissions-reference`
- Slack: `https://api.slack.com/scopes`

### Option B: Autonomous research (slow, 2-5 minutes)

For APIs without a clear permission reference page, use the Firecrawl agent:

```
mcp__firecrawl__firecrawl_agent(
  prompt="Find all authentication requirements, permission scopes, token types,
          rate limits, and prerequisites for: {use-case} using the {api-name} API.
          Include: what auth method is needed, what scopes/permissions are required,
          what admin setup is required, and any common gotchas or constraints.",
  urls=["<api-docs-base-url>"]  // optional, helps focus the search
)
```

Poll `firecrawl_agent_status` every 30 seconds until complete.

---

## Phase 3: Build Constraint Map

Synthesize all findings into a structured constraint map.

### Constraint chain format

For each operation in the use case, trace the full dependency chain from
the action to the root prerequisite:

```markdown
## Constraint Chain: {Use Case}

{operation}
  └─ requires: {permission/scope}
       └─ requires: {token type or installation level}
            └─ requires: {admin role or setup step}
                 └─ requires: {pre-condition}
```

### Full output format

```markdown
# API Preflight: {API Name}
## Use Case: {use-case description}

## Required Permissions

| Operation | Scope | Type | Admin Consent | Notes |
|-----------|-------|------|---------------|-------|
| ... | ... | delegated/application | yes/no | ... |

## Constraint Chains

{operation 1}
  └─ requires: {scope}
       └─ requires: {token type}

{operation 2}
  └─ requires: {scope}
       └─ requires: {setup step}

## Known Gotchas

- {gotcha 1 — from topic file or constraints.md}
- {gotcha 2}

## Pre-flight Checklist

- [ ] {concrete action item 1}
- [ ] {concrete action item 2}
- [ ] {concrete action item 3}

## Sources

- {file:line or URL for each constraint cited}
```

### Constraint chain depth

Trace each chain to at least 3 levels when possible:
1. **What permission is needed** (the scope)
2. **What grants that permission** (token type, installation level, app registration)
3. **What enables that grant** (admin role, admin consent, org-level setup)

The Slack XOXP/XOXB incident had 4 levels. The MS Graph OBO
AADSTS28003 incident had 3 levels. Surface all of them.

---

## Examples

**Example 1: Pre-coding a Graph API call**
User says: `/api-preflight microsoft-graph "list conditional access policies in GCC High"`
Actions: Phase 0 constraint graph returns chain (Policy.Read.All → application token → admin consent → Global Admin). Phase 1 Step 3 resolves the topic slug `microsoft-graph` → `msgraph.md` (via the alias fallback) and finds the topic-file gotcha about GCC High `login.microsoftonline.us` endpoint. Output includes the chain, 1 permission table row, 1 gotcha, 3 checklist items.
Result: User knows before coding: needs app registration with `Policy.Read.All`, admin consent, and GCC-specific endpoint — not the commercial default.

**Example 2: Troubleshooting a 403**
User says: `/api-preflight slack "getting 403 when listing private channels"`
Actions: Mode detector sees "getting 403", switches to troubleshooting mode. Phase 1 Step 3b searches for "403 slack private channels". Topic file `slack.md` confirms that per-user OAuth tokens can lag the app's scope set — historically `channels:read` was missing while `search:read` was available. RESOLVED 2026-07-26 for re-authorized tokens (mcp-servers #289 added the scope 2026-04-12; Slack does not retro-update issued tokens): the fix is to visit `https://service.mcp.example.internal/disconnect` THEN `https://service.mcp.example.internal/connect`, not a permanent workaround. Output leads with the gotcha and the re-authorization step, not the full chain.
Result: User re-authorizes their Slack token (disconnect-then-connect) to pick up `channels:read`, call succeeds.

## Success Criteria

- [ ] At least 1 required permission identified per operation in the use case
- [ ] Token type (delegated vs application) identified
- [ ] Admin consent requirements stated
- [ ] At least 1 constraint chain with 2+ levels produced
- [ ] Known gotchas from topic files included if they exist
- [ ] Pre-flight checklist has actionable items
- [ ] Sources cited for each constraint (file:line or URL)

## Important Rules

- Never guess at permissions — cite a source (indexed doc, topic file, or Firecrawl extraction)
- If no constraint data found, say so explicitly: "No constraint data available for {operation}. Recommend running /api-ingest first."
- Constraint chains are the primary deliverable — tables are secondary
- Check `constraints.md` (structured) in the API docs library, and the agent-memory topic file (`~/.claude/agent-memory/topics/{api-name}.md`) for operational gotchas — `/api-ingest` does not emit a `gotchas.md`; operational issues live in topic files instead.
- Phase 2 (Firecrawl) is optional — only run if Phase 1 was insufficient
