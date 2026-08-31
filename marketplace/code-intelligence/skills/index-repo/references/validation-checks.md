# Index Validation Checks

Concrete audit-only corruption signals for code-search, code-graph, and unified
codebase-memory-mcp indexes. This reference supports `/index-repo --audit` and
legacy-index cleanup only. Normal split indexing and post-index readiness are
owned by the installed release-bound `codebase-search` plugin skill; do not add
these filesystem heuristics as a second success gate. For unified-backend
readiness, use the Unified backend section in `SKILL.md`.

## Critical Gotchas

- **`project_hash` is required in every delete call** (even though the
  tool schema marks it optional). `mcp__code-search__delete_project`
  takes `project_name` (required) AND `project_hash` (nominally optional).
  Name-only matching iterates `iterdir()` in non-deterministic order and
  can kill the wrong project (incident 2026-04-17: deleted populated
  97.7MB index instead of an empty skeleton). **Always pass both.**
  Code-graph's `delete_project` takes the full `name` field returned by
  `list_projects` — copy it verbatim.
- **`list_projects` stats can be stale.** After `rebuild_chunk_ids.py` ran
  on 2026-04-20, the rebuilt projects still show `total_chunks: 0` in
  `list_projects`. Do not treat registry stats as definitive without
  cross-checking on-disk file sizes.
- **Empty-pickled-list signature is 5 bytes exactly** (`\x80\x04]\x94.`),
  but the operational corruption threshold is `<= 10 bytes`. Five bytes is
  the known incident signature; the wider bound also catches other truncated
  or empty pickle forms.
- **Backups are evidence, not corruption.** A `chunk_ids.pkl.bak.<ts>`
  file of 5 bytes alongside a healthy current `chunk_ids.pkl` means the
  project was repaired and is now fine.

## Healthy index fingerprint — code-search

Each `~/.claude_code_search/projects/<name>_<hash>/` directory MUST contain:

| File | Healthy state | Corruption signal |
|---|---|---|
| `project_info.json` | JSON with name, path, provider | Missing → ORPHAN |
| `index/chunk_ids.pkl` | > 10 bytes (pickled list of chunk IDs) | <= 10 bytes → CORRUPT (including 5-byte empty-pickle truncation) |
| `index/code.index` | > 0 bytes (FAISS vectors) | Missing or 0 bytes → CORRUPT |
| `index/metadata.db` | > 0 bytes (SQLite diskcache KV) | Missing or 0 bytes → CORRUPT |
| `index/fts5.db` | > 0 bytes (SQLite FTS5) | Missing or 0 bytes → CORRUPT |
| `index/stats.json` | JSON with chunk counts | Missing → STALE (recover via reindex) |

## Healthy index fingerprint — unified codebase-memory-mcp

Unified backend indexes are stored as SQLite at `~/.cache/codebase-memory-mcp/<project>.db` (WAL mode). The validation gate is covered in SKILL.md's Unified backend section: `index_status(project=<name>)` MUST return `status == "ready"`, `nodes > 0`, and fresh `indexed_at`; the `.db` file MUST exist and be non-zero-byte.

## Healthy index fingerprint — code-graph

Use architecture and count probes to diagnose an unhealthy audit entry. Normal
post-index status and identity verification belong to the installed
release-bound plugin workflow, not this audit-only reference.

| Probe | Healthy | Corruption signal |
|---|---|---|
| `mcp__code-graph__get_architecture(project=<name>)` | Returns architecture content | Empty/error → NOT INDEXED |
| `mcp__code-graph__query_graph(project=<name>, cypher="MATCH (n) RETURN count(n) AS nodes")` | nodes > 0 | nodes == 0 → CORRUPT |
| Same with `MATCH ()-[r]->() RETURN count(r) AS edges` | edges > 0 | edges == 0 with nodes > 0 → PARTIAL (warn, not fatal) |

`mcp__code-graph__list_projects` also reports `size_bytes`. Threshold bands
for any non-trivial repo (the audit algorithm uses these exact bounds — see
below):

| `size_bytes` band | Classification |
|---|---|
| `>= 100 KB` | HEALTHY — expected size for a non-trivial repo |
| `50 KB <= size < 100 KB` | GRAY ZONE — plausible for small repos; warn only if peer indexes for the same path are much larger |
| `< 50 KB` | SUSPECT — flag as warn (Tier C-adjacent); cross-check node/edge counts |
| `< 50 KB` AND `nodes == 0` | CORRUPT — covered by Tier A code-graph signals above |

The 50 KB warn floor and the 100 KB healthy floor are NOT contradictory:
50 KB is the lower bound where the algorithm emits a warning, 100 KB is the
expected upper-side ceiling for "definitely healthy non-trivial repo". Sizes
in the 50-100 KB band are intentionally not flagged on their own (small repos
land there legitimately).

## Corruption tiers

### Tier A — CORRUPT (hard gate, block delivery, recommend delete)

Any ONE of the following:

**Registry signals** (`list_projects`):
- Missing `index_stats` field entirely
- `index_stats.total_chunks == 0` AND `files_indexed == 0` AND
  `index_type == "None"` (empty skeleton — never successfully indexed)
- **Partial-index** — for the same `project_path`, this entry's
  `files_indexed` is < 25% of the largest peer entry's `files_indexed`,
  AND the peer has >= 20 files indexed. Catches the case where indexing
  fails after processing a handful of files but writes a non-trivial
  chunk pickle, passing the zero-chunk and 5-byte checks (2026-05-22
  incident: knowledge-base voyage-context indexed 1 of 693 files, 29
  chunks, 4171-byte pkl — passed every other hard check). At Step 8
  post-index, the equivalent check uses the indexer's return blob:
  `result.index_stats.files_indexed < 25% of result.index_stats.supported_files`
  (skip when supported_files < 20).

**On-disk signals** (`~/.claude_code_search/projects/<dir>/`):
- `index/` directory exists but is empty (0 files)
- `index/chunk_ids.pkl` is missing or `<= 10 bytes` (including the known
  5-byte empty-pickle signature)
- `index/code.index` missing or 0 bytes (FAISS absent)
- `index/metadata.db` missing or 0 bytes (metadata absent)
- `index/fts5.db` missing or 0 bytes (text index absent)
- `index/` contains only `fts5.db` with no vector files

**code-graph signals**:
- `status != "ready"` after indexing completes (indexing/failed/other)
- `nodes == 0`

### Tier B — ORPHAN (on-disk without registry, delete on-disk dir)

- On-disk project directory not present in `list_projects` output
- On-disk project directory missing `project_info.json`

### Tier C — STALE (path invalid OR provider trails peer — recommend re-index, not delete)

- Registry entry with `project_path` that does not exist on the filesystem
  (e.g., pytest temp dirs under `AppData\Local\Temp\pytest-of-*`)
- Registry entry in any system temp directory
- Registry entry with `pipeline_version` older than any currently-healthy
  entry (will be force-reindexed on next use, but clutters `list_projects`)
- **Cross-provider drift** — within the same `project_path`, the older
  `embedding_provider` entry's `created_at` trails the newer **healthy**
  peer's `created_at` by more than 7 days. The older provider is
  functional but the dual-model consensus is broken until it's re-indexed
  (2026-05-22 audit: 7 voyage entries from 2026-05-09 trailed their
  voyage-context peers from 2026-05-22). Recommend re-index, not delete
  — the older entry is still usable. Path-invalid and temp-dir entries
  are the only Tier C signals that warrant deletion.
  Implementation note: the drift check runs AFTER the partial-index
  CORRUPT pass and excludes already-CORRUPT entries from the peer set
  — otherwise a broken-but-newer entry would mark its healthy older
  peer as STALE just for trailing the broken peer's timestamp.

### Tier D — DUPLICATE (same path + same provider, multiple hashes)

Keep newest (`created_at`), delete older.

## Audit algorithm

```
load_registry_code_search  = list_projects() from code-search MCP
load_registry_code_graph   = list_projects() from code-graph MCP
load_disk_code_search      = ls ~/.claude_code_search/projects/*/

for each registry entry:
  check Tier A signals (registry-side)
  check on-disk presence → if missing, classify PHANTOM
  check Tier C signals (path validity, pipeline version)

for each on-disk dir:
  validate project_info.json and the complete healthy fingerprint:
    chunk_ids.pkl, code.index, metadata.db, fts5.db, stats.json
  check Tier A signals (including chunk_ids.pkl <= 10 bytes)
  missing stats.json → STALE; missing project_info.json → ORPHAN
  check registry presence → if missing, classify ORPHAN

for each (path, provider) pair in code-search registry:
  if multiple hashes → classify oldest as DUPLICATE

for each path with multiple entries in code-search registry:
  # Pass 1: partial-index cross-entry check
  peer_max = max(files_indexed across all entries for this path)
  if peer_max >= 20:
    for each entry where files_indexed < 0.25 * peer_max → CORRUPT
  # Pass 2: cross-provider drift check — exclude CORRUPT entries from
  # the peer set so a partial newest-entry doesn't demote its healthy
  # older peer (otherwise voyage[693, 2026-05-09] gets STALE because
  # voyage-context[1, 2026-05-22, CORRUPT] is the technical newest)
  healthy_entries = entries not classified CORRUPT in Pass 1
  if len(healthy_entries) > 1:
    newest_created_at = max(created_at across healthy_entries)
    for each entry in healthy_entries where
      created_at < newest_created_at - 7 days → STALE

for each code-graph project:
  check status != "ready" → CORRUPT
  check nodes == 0 → CORRUPT  # also covers most size_bytes < 50 KB cases
  check size_bytes < 50 KB AND nodes > 0 → suspect (warn — sub-floor band)
  # 50-100 KB is the gray zone: not flagged on its own; cross-check against
  # peer indexes for the same path before warning. The 50 KB warn floor and
  # the 100 KB healthy floor are two bounds of a single banded scheme, not
  # competing thresholds — see the size_bytes band table above.

emit report grouped by tier, with delete commands prepared but NOT executed
```

## Cleanup commands (for the delete plan)

**code-search** (pass BOTH args — name alone risks the 2026-04-17 failure mode):
```
mcp__code-search__delete_project(project_name="<name>", project_hash="<hash>")
```

**code-graph**:
```
mcp__code-graph__delete_project(name="<full name from list_projects>")
```

**On-disk orphan cleanup** (no registry entry, safe to rm):
```
rm -rf ~/.claude_code_search/projects/<orphan_dir>/
```

**STALE via cross-provider drift** (re-index, do NOT delete):
```
mcp__code-search__index_directory(
    directory_path="<project_path>",
    provider="<lagging_provider>",   # e.g., "voyage" when voyage-context is newer
    incremental=false,
)
```

## Post-cleanup re-index

If the original `project_path` still exists on disk and the corruption was
in the index (not the source), return to the split-backend section in
`SKILL.md`. Discover the enabled plugin with `claude plugin list --json`, read
its `skills/index-repo/SKILL.md` completely, and execute that release-bound
workflow for the canonical repository root. Do not resurrect provider-specific
launches or this audit reference as a parallel readiness contract. The
release-bound workflow owns asynchronous completion, graph precision, final
identity equality, activation, and backend lifecycle-delta reporting.
