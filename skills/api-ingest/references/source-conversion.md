# Phase 2 — Convert to Markdown: per-source recipes 2a–2e

Relocated verbatim from `skills/api-ingest/SKILL.md` on 2026-09-04 (docs/skill-cap-decisions.md).
Phase 1's detection table selects exactly one of these per run.

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

