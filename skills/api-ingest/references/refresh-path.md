# Phase 5b: Persist newly-discovered constraints (re-ingest path)

If this invocation is a **refresh** of an already-ingested API (constraints.md
already exists at `~/Documents/api-docs/{api-name}/constraints.md`) and the
caller surfaced new constraints discovered during downstream use (e.g.,
`/api-preflight` Firecrawl-extracted a permission absent from the ingested
docs), merge those entries into the existing `constraints.md` before the
Phase 4 re-index:

1. **Append to constraints.md**: Add new permission entries or gotchas to
   `~/Documents/api-docs/{api-name}/constraints.md` under the appropriate
   resource-area or gotcha section.

2. **Re-index** (this is the Phase 4 incremental index — running it after
   the merge ensures the new constraints are searchable). **Index the parent
   directory** so it lands in the single canonical api-docs project (auto-derived
   from the path as `Users-<user>-Documents-api-docs`); per-subdir indexing
   fragments it away from the canonical project that downstream consumers like
   `api-doc-lookup` expect. **Pass `force=true`** — an incremental run updates the
   graph but does NOT regenerate the Voyage embeddings, so the merged constraints
   would parse but stay unsearchable (verified 2026-06):
   ```
   mcp__codebase-memory-mcp__index_repository(
     repo_path="/Users/<user>/Documents/api-docs",
     force=true,
     skip_report=true
   )
   ```

3. **Inform the user**: "New constraints discovered and persisted for future sessions."

This belongs in `/api-ingest` (not `/api-preflight`) because the writer of
`constraints.md` is the ingestion pipeline; `/api-preflight` is a reader.
