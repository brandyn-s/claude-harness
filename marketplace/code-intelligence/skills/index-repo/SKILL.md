---

name: index-repo
description: "Index a repository for code search, or audit existing indexes for corruption."
when_to_use: Use when a repository needs to be indexed for code search capabilities, or when existing indexes need corruption auditing. Host-adaptive - drives the unified codebase-memory-mcp server where registered, or delegates the split code-search + code-graph path to its installed release-bound plugin skill, with a hard-gated post-index validation either way. Trigger phrases - "index repo", "index this repo", "index-repo", "set up search for", "audit indexes", "find corrupted indexes", "clean up indexes". Do NOT use for searching (use code-explore), or for indexing only one tool.
argument-hint: "[repo-path] [--graph-precision heuristic|scip|auto] [--scip-policy preferred|required] [--scip-index path] | --audit"
model: sonnet
effort: low
metadata:
  author: example-security-engineering
  version: "1.3"
compatibility:
  # One backend or the other must be registered; Step 3 detects which.
  optional:
    - mcp: codebase-memory-mcp
      fallback: "Use the split code-search + code-graph backend path"
    - mcp: code-search
      fallback: "Use the unified codebase-memory-mcp backend path"
    - mcp: code-graph
      fallback: "Use the unified codebase-memory-mcp backend path"
allowed-tools: AskUserQuestion Bash Read mcp__codebase-memory-mcp__delete_project mcp__codebase-memory-mcp__index_health mcp__codebase-memory-mcp__index_repository mcp__codebase-memory-mcp__index_status mcp__codebase-memory-mcp__list_projects mcp__codebase-memory-mcp__query_graph mcp__code-graph__delete_project mcp__code-graph__get_architecture mcp__code-graph__list_projects mcp__code-graph__query_graph mcp__code-search__delete_project mcp__code-search__index_directory mcp__code-search__list_projects
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


## index-repo

# Index Repo

Index a repository for both code-search (semantic) and code-graph (graph) in a single invocation.

## Usage

- `/index-repo $HOME/Documents/GitHub/mcp-servers` — index a repo
- `/index-repo <repo> --graph-precision auto --scip-policy preferred` — use
  the release-bound automatic compiler-precision path when supported
- `/index-repo <repo> --graph-precision scip --scip-index /path/index.scip` —
  ingest a supplied SCIP artifact
- `/index-repo --audit` — scan every existing project for corruption and
  produce a delete plan (no indexing; see Audit mode below)

If neither a path nor `--audit` is provided, ask the user what they want.

## Steps

0. **Mode selection.** If the argument is `--audit` (no path), skip Steps
   1-2 and continue at Step 3; run only that backend's audit procedure.
   Otherwise, use Steps 1-2 before selecting an indexing backend.

1. **Resolve the repository path.** If a short name is given (for example,
   `mcp-servers`), check these locations in order and retain the first match:
   - `~/Documents/GitHub/<name>/`
   - `~/Documents/GHES/<name>/`
   - `~/Documents/<name>/`

2. **Verify and canonicalize the repository.** Resolve the selected path to
   `repo_path`, require it to be a directory, then run:
   ```bash
   git -C "$repo_path" rev-parse --show-toplevel
   ```
   Continue only when the command exits 0 and returns one existing directory.
   Record that exact canonical output as `<resolved-root>` and use it for the
   selected backend. This accepts normal clones, linked worktrees, and paths
   below the repository root without guessing from `.git` shape.

3. **Backend detection.** ToolSearch for
   `select:mcp__codebase-memory-mcp__index_repository`. If found, this
   host runs the **unified backend** — use the Unified backend section
   below and SKIP the split-backend section. If not
   found, ToolSearch for `select:mcp__code-search__index_directory` and
   use Steps 4-8. If NEITHER resolves, the relevant MCP is disconnected —
   for the unified backend, fall back to its CLI (see Unified backend →
   CLI fallback); for the split backend, ask the user to reconnect via
   `/mcp`.

## Unified backend (codebase-memory-mcp)

One server covers graph + text + semantic search; storage is SQLite at
`~/.cache/codebase-memory-mcp/<project>.db` (WAL mode). No separate
code-search index, no provider pairs, no `--single` flag.

**Index** (using the path verified in Steps 1-2):

```
mcp__codebase-memory-mcp__index_repository(repo_path=<path>, mode="full", skip_report=true)
```

`mode="full"` is the server default — the split-backend Nix carve-out
does not apply here. Report nodes, edges, elapsed.

**`skip_report=true` is the default posture, not an opt-in.** Without it the
indexer writes `ARCHITECTURE_REPORT.md` into the repo ROOT. Measured 2026-07-29:
of 11 repos re-indexed, only 3 gitignore that path — so a bare call leaves 8
clean protected checkouts dirty, and on a read-only repo (PSM) it violates the
no-writes policy outright. Omit it only when the user explicitly asks for the
report AND the repo ignores or tracks it (`git check-ignore -q
ARCHITECTURE_REPORT.md`).

**Validation gate (HARD — same bar as Step 8):**
- `mcp__codebase-memory-mcp__index_status(project=<generated-name>)` —
  FAIL unless `status == "ready"`, `nodes > 0`, and `indexed_at` is
  newer than the indexing call. WARN if `edges == 0` with `nodes > 0`.
- FAIL if the `.db` file is missing or zero-byte at
  `~/.cache/codebase-memory-mcp/<generated-name>.db`.
- On any FAIL: report the check + project name and STOP — no
  "repo is ready" message.

**Audit (`--audit`):**
1. Call `mcp__codebase-memory-mcp__list_projects` for the full registry:
   `root_path`, `nodes`, `edges`, `indexed_at`, `db_path`, `status`,
   `identity_status`, `identity_reason`, and `index_identity`.
2. Run the repository's read-only filesystem/SQLite verifier and retain its
   JSON even when it exits 2 for hard corruption:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify-indexes.py" --json
   ```
   Reconcile `code_graph_corruption` with unified entries by `project` or
   `db_path`; report `code_search_corruption` separately as legacy split-index
   findings. `transient_locks` are contention, not corruption: wait for active
   indexing to settle and retry once. If locks persist, mark those indexes
   `UNKNOWN` and do not recommend deletion. If verifier `status == "skip"`,
   its JSON is invalid, or it cannot run, label the integrity audit incomplete
   and do not claim the registry is clean.
3. Classify every unified entry by this precedence (first match wins).
   `identity_status` remains authoritative for freshness after hard integrity
   and path failures; do not re-derive freshness from timestamps.
   - **CORRUPT** — the entry appears in `code_graph_corruption`, its `.db` is
     missing/zero-byte at `db_path`, or `nodes == 0`. Recommend delete only
     after approval; a re-index cannot make a damaged database trustworthy.
   - **STALE-PATH** — `root_path` no longer exists. Recommend delete, not
     re-index.
   - **IDENTITY-ERROR** — `identity_status == "error"`; the index is queryable
     but freshness is unknowable. Repair the checkout first (a Git repository
     needs an initial commit so `source_revision` exists), then re-index; offer
     deletion only if the root is intentionally retired.
   - **IDENTITY-MISSING** — `identity_status == "missing"`; this is a legacy
     index without a captured source identity. Recommend
     `index_repository(repo_path=<root_path>, mode="full", skip_report=true)`.
   - **STALE-SOURCE** — `identity_status == "stale_source"`. Recommend the
     same safe re-index command with `skip_report=true`.
   - **HEALTHY** — `identity_status == "captured"`, `status == "ready"`, and
     no earlier integrity/path rule fired.
   - **UNKNOWN** — any other combination (for example `pending`, a persistent
     verifier lock, or a non-ready status with nonzero nodes). Do not delete;
     call `mcp__codebase-memory-mcp__index_health(project=<name>)` and report
     the unresolved state.
4. Print one table grouped by classification with `identity_reason`, verifier
   detail, and the exact proposed command. Do not execute any remediation
   without per-entry approval. Delete with
   `mcp__codebase-memory-mcp__delete_project(project_name=<name>)`; re-index
   only with `mode="full", skip_report=true`.

Do not re-index merely because the server binary was upgraded:
`index_generation` derives from repository id + source revision + dirty
fingerprint and takes no binary-version input (2026-07-29).

**CLI fallback (MCP disconnected):** the same binary serves a CLI — do
not block on reconnection (verified 2026-06-12, 5-repo re-index batch):

```bash
"$HOME/.local/bin/codebase-memory-mcp-launch" cli index_repository '{"repo_path": "<path>", "mode": "full", "skip_report": true}'
"$HOME/.local/bin/codebase-memory-mcp-launch" cli --raw list_projects
```

Use the launcher (not the bare binary) — it injects Keychain API keys
for embeddings and tees slog to `~/.cache/codebase-memory-mcp/server.log`.
Both paths write the same WAL-mode SQLite, so a reconnected MCP sees
CLI-built indexes immediately. Filesystem-level integrity scanning is
also MCP-independent: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/verify-indexes.py`.

## Split backend (code-search + code-graph) — Steps 4-8

The installed `codebase-search` plugin owns the current split-backend indexing
contract. Keep that workflow in one release-bound location; this host-adaptive
skill must not copy or reinterpret it.

4. Run `claude plugin list --json` and select exactly one enabled entry whose
   id is `codebase-search@example-code-intelligence`. Require a non-empty,
   existing `installPath`, record it as `<split-runtime-root>`, and verify that
   `<split-runtime-root>/skills/index-repo/SKILL.md` and
   `<split-runtime-root>/component-bom.json` are regular files. If discovery is
   missing, ambiguous, disabled, or malformed, stop before indexing and ask the
   user to install or update the plugin. Do not guess a cache path or fall back
   to this skill's former provider-specific workflow.

5. Locate `<split-runtime-root>/skills/index-repo/SKILL.md` and read it
   completely—read it completely before acting. Treat it as the single release-bound workflow
   for split indexing, including live BOM
   and schema preflight, canonical Git-root binding, asynchronous code-search
   completion, graph precision selection, exact cross-engine identity checks,
   and switching the active project only after both engines verify. Do not reproduce
   or weaken it, and do not layer additional readiness gates over that contract.

6. Execute that workflow for `<resolved-root>` with the caller's exact
   `--graph-precision heuristic|scip|auto`, `--scip-policy
   preferred|required`, and `--scip-index` arguments. Defaults and invalid
   combinations are owned by the release-bound skill. `--audit` never reaches
   this delegation; it uses the read-only split audit below.

7. Preserve the release-bound result without reclassification. A success must
   include the verified semantic and graph identities, active project, graph
   precision/SCIP coverage, and the backend-issued lifecycle deltas:
   `files_added`, `files_modified`, `files_removed`, `chunks_added`, and
   `chunks_removed` for code-search; `index_delta.mode` (`full`, `noop`, or
   `incremental`) plus `files_discovered`, `files_changed`, and
   `files_unchanged` for code-graph. These are **non-gating lifecycle telemetry**.
   Missing delta telemetry does not override readiness, and a
   `noop` graph result means only that no changed source files were observed;
   do not infer semantic equivalence. Peak memory, physical storage, cold-index
   timing, and semantic equivalence remain the bounded measurement harness's
   job, not routine `/index-repo` indexing.

8. Report the delegated workflow's terminal result verbatim. Confirm ready
   only when its full contract passes. Otherwise say **partial index**, name
   the failed release-bound gate, and provide its safe retry action.

## Audit mode (split backend)

Invoked as `/index-repo --audit` on a split-backend host. Scans every
existing project in both code-search registries and the code-graph
registry, producing a delete plan the user approves per-entry. Does NOT
index. (Unified-backend hosts use the audit procedure in the Unified
backend section instead.)

1. `mcp__code-search__list_projects` — pull the full registry.
2. List `~/.claude_code_search/projects/` to find on-disk directories.
3. `mcp__code-graph__list_projects` — pull the code-graph registry, then use
   architecture and graph-count probes from the audit reference to diagnose
   suspect entries. The release-bound plugin owns normal post-index status and
   identity verification; this audit lane does not duplicate it.

4. Classify every entry against the tiers in
   `references/validation-checks.md`:
   - **CORRUPT** — registry or on-disk corruption signal; delete recommended.
     Includes partial-index detection: for the same `project_path`, if one
     entry's `files_indexed` is < 25% of a peer entry (where the peer has
     >= 20 files indexed), classify the smaller as CORRUPT.
   - **ORPHAN** — on-disk dir with no registry entry; delete recommended
   - **STALE** — path no longer exists, lives in a system temp dir
     (pytest artifacts, `$TMPDIR`), OR trails a peer entry for the same
     path by >7 days in `created_at` (cross-provider drift — older
     provider is functional but lags behind the newer one; recommend
     re-index, not delete)
   - **DUPLICATE** — same `project_path` + `embedding_provider` appears
     with multiple hashes; keep newest by `created_at`, flag older
   - **HEALTHY** — passes all checks

5. Produce a table of findings grouped by tier. For every non-HEALTHY
   entry, print the exact remediation command but do NOT execute:
   - code-search registry (CORRUPT/DUPLICATE/STALE-path-invalid):
     `mcp__code-search__delete_project(project_name="<name>", project_hash="<hash>")`
     — pass BOTH args; `project_name` is required by the tool schema,
     `project_hash` disambiguates when names collide (2026-04-17 incident:
     name-only matching deleted wrong project due to non-deterministic
     `iterdir()` order)
   - code-graph registry: `mcp__code-graph__delete_project(name="<full name>")`
   - on-disk orphan with no registry entry: `rm -rf ~/.claude_code_search/projects/<dir>/`
   - STALE via cross-provider drift (re-index, not delete):
     `mcp__code-search__index_directory(directory_path="<path>", provider="<lagging_provider>", incremental=false)`

6. **Hard gate on bulk action.** Do not mass-delete. Ask the user to
   confirm per entry or per tier. For re-indexable entries (path still
   exists on disk), offer to re-run the installed release-bound split workflow
   after the delete lands.

## Notes

- **code-search** selects its released embedding route at runtime. Cloud routes
  require their configured API key; supported local routes keep source on the
  host. The release-bound split skill and component BOM are authoritative for
  current provider and compatibility details.
- **code-graph** is primarily local (tree-sitter AST parsing, ~30-60s). When `VOYAGE_API_KEY` is set, it also generates Voyage embeddings for the `search_code_semantic` tool, enabling natural language search over graph nodes.
- Both split backends support incremental indexing, and their backend-issued
  lifecycle deltas are reported without becoming readiness gates.
- Pipeline version detection belongs to code-search; do not force a lifecycle
  mode by interpreting file/chunk counts in this wrapper.
- After indexing, use natural language queries. The code-explore skill handles routing.
- **Staleness detection is automatic**: the session-start `index_staleness` hook ENUMERATES the codebase-memory-mcp registry (every `*.db` in `~/.cache/codebase-memory-mcp/`) and compares each entry's captured `source_revision` against `git rev-parse HEAD`, falling back to `indexed_at`-vs-HEAD-timestamp only for DBs predating identity capture. It also surfaces `identity_status == "error"` separately, since such an index is queryable but its freshness is unknowable. No manual tracker update needed — re-indexing through any path (this skill, MCP `index_repository`, or directly) clears the warning on the next session start. Coverage is the registry itself, deliberately: the previous hardcoded 5-repo list covered 3 of 19 indexed projects, and 11 stale indexes went unreported for two days as a result (2026-07-29). The split-backend code-search side still keys off `TRACKED_REPOS`.

## Examples

**Audit on a unified-backend host:**
> "/index-repo --audit"
Step 3 detects codebase-memory-mcp. Pulls `list_projects` (19 entries), verifies each `root_path` and `.db` on disk, and reads each entry's `identity_status`. Reports 7 HEALTHY + 11 STALE (`stale_source`) + 1 IDENTITY-ERROR (`api-docs` — a doc tree that was never a git checkout, so freshness was unknowable while every path/timestamp rule scored it HEALTHY) with per-entry remediation; on approval, re-indexes the 11 with `skip_report=true` and re-validates `identity_status == "captured"` and `status == "ready"`. Real run 2026-07-29: 11 repos in 3m51s incremental.

**Index a new repo for the first time (split backend):**
> "/index-repo mcp-servers"
Resolves to `~/Documents/GitHub/mcp-servers/`, delegates to the installed
release-bound split workflow, and reports verified identities, chunk/file and
node/edge totals, graph precision, and backend lifecycle deltas.

**Re-index after major code changes:**
> "/index-repo $HOME/Documents/GitHub/mcp-infra"
Runs the current release-bound workflow on both tools and reports the backends'
actual lifecycle deltas rather than assuming the update was incremental.


**Example 2: Re-index after major refactor**
User says: "/index-repo mcp-servers"
Actions: Triggers both code-search re-index (semantic embeddings) and code-graph re-index (structural analysis) for the mcp-servers repo through the installed release-bound skill. Monitors progress and verifies both identities before activation.
Result: "mcp-servers indexed: code-search and code-graph ready on the same index generation; lifecycle deltas reported."

## Success Criteria

**Backend detection (Step 3):**
- The path taken matches the registered server — never a hand-rolled
  equivalent because the OTHER backend's tool names failed to resolve

**Unified backend:**
- `index_repository` ran (MCP or CLI launcher) and the validation gate
  passed: `status == ready`, `nodes > 0`, fresh `indexed_at`, `.db`
  present and non-zero
- Audit mode classified every registry entry HEALTHY/STALE/CORRUPT with
  explicit identity/integrity subtypes and per-entry remediation commands;
  nothing deleted without approval

**Normal indexing (split backend, Steps 1-8):**
- Exactly one enabled `codebase-search@example-code-intelligence` installation
  supplied the release-bound workflow; no cache path or provider contract was
  guessed
- The delegated code-search job reached its bound terminal success and the
  code-graph index completed without checkout mutation
- Both final status responses were ready, complete identities matched on the
  stable generation fields, and the active project switch succeeded
- Requested/effective graph precision and SCIP coverage/drift were reported
- Semantic file/chunk deltas and graph lifecycle mode/counts were reported as
  non-gating telemetry; missing telemetry was not fabricated
- If any release-bound gate failed, the wrapper did not declare success and
  instead preserved the **partial index** result and safe retry action

**Audit mode (`--audit`):**
- Every registry entry and on-disk directory classified into a tier
- Delete plan printed with exact `project_hash` for each non-HEALTHY entry
- No deletes executed without per-entry user approval
