# gather-vendor — xAI / Grok profile (channels live-verified 2026-08-22)

## Dependency map (why this vendor matters — deprecation-first)

VENDOR IDENTITY: xAI is now **SpaceXAI** (SpaceX acquired xAI 2026-02-02; branding
fully switched by 2026-08). API host, docs.x.ai, and model slugs are unchanged.

xAI already burned us: Live Search retired 2026-01-12, discovered via 410s post-hoc.
Deprecation signal is this vendor's top priority.

1. **x-monitor** — `bin/x-monitor.py` rides the Agent Tools API (`POST /v1/responses`
   with `x_search`+`web_search`, `/v1/batches`, `/v1/search`) pinned to `grok-4.3`.
2. **/roundtable arm** — `skills/roundtable/scripts/adapters/xai_adapter.py` pins
   `grok-4.6` (default) + `grok-4.20-0309-reasoning` as of 2026-08-22 (migrated to
   /v1/responses 2026-07-05, #1551) — always trust the Step 1 grep over this prose.
3. **xai MCP** — abandoned community npm at 0.1.0; `answer_query_websearch` 410s
   (retired Live Search). Watch for a first-party successor (docs.x.ai/api/mcp exists).
4. **XAI_API_KEY** (Keychain); `~/Documents/api-docs/xai/` IS ingested (2026-06-12
   vintage) — re-run `/api-ingest` when this skill detects API-surface drift.

## Step 1 greps (workaround indicators + live pins)

```bash
grep -riE "grok|x\.ai|xai" ~/.claude/rules/ ~/Documents/knowledge-base/topics/ --include="*.md" -l
grep -hoE "grok-[0-9a-z.\-]+" ${CLAUDE_PLUGIN_ROOT}/bin/x-monitor.py ${CLAUDE_PLUGIN_ROOT}/skills/roundtable/scripts/adapters/xai_adapter.py | sort -u  # live pins -> Step 2
```

## Critical Gotchas

- **Retirements are NOT in release notes** — they live in (a) `/developers/migration/*`
  pages, (b) SILENT removal of docs sections, (c) inline "Deprecated" markers.
- **Silent slug redirects (worse than 410)**: retired ids resolve 200 but are served
  by a different model + rebilled — the probe's canonical-id check catches this.
- **`/docs/changelog` alias is BROKEN** (308->404); only `/release-notes` works.
- **release-notes.md is month-granular** — run-over-run CONTENT diff drives detection.
- **x.ai/* 403s plain curl** (Cloudflare); docs.x.ai does not. console.x.ai is auth-walled.

## Standing sweep (all plain curl, all free)

All channels ride `scripts/fetch_channel.py` (fetch + marker assert + atomic
write; exit 0 ok / 2 HTTP / 3 marker-miss = dead/rewritten channel):

```bash
FC="python3 ${CLAUDE_PLUGIN_ROOT}/skills/gather-vendor/scripts/fetch_channel.py"
# canonical ship log (month-granular; content-diff, not date-diff)
$FC https://docs.x.ai/developers/release-notes.md 'Release Notes' /tmp/xai_rel.md
# THE deprecation detector: full-corpus llms.txt (~164 '===/path===' sections, 2026-08-22)
#   marker '===' proves shape; ALSO assert >=100 sections (grep -c below) — a corpus
#   that shrank below 100 is a restructure finding, not a quiet vendor.
#   PERSIST the full section list as a baseline (Step 10); diff vs prior run:
#   NEW section = feature; VANISHED section = silent removal; new .../migration/* = retirement
#   ALSO per-section content-hash the x-monitor + roundtable wire surfaces
#   (===/developers/tools/*=== and ===/developers/rest-api-reference/inference/*===) and
#   surface a unified diff on any change — a tool-schema rewrite keeping the section NAME
#   is invisible to a name-only diff (the docs-REWRITE class).
$FC https://docs.x.ai/llms.txt '===' /tmp/xai_llms.txt
grep -c '^===' /tmp/xai_llms.txt   # >=100 required
grep '^===' /tmp/xai_llms.txt
# model lineup + pricing (a vanished row is a retirement tell; agent-tool rows = x-monitor cost)
#   markers are pin-INDEPENDENT (a pinned-model row vanishing is the SIGNAL, not channel death)
$FC https://docs.x.ai/developers/models.md 'Model' /tmp/xai_models.md
$FC https://docs.x.ai/developers/pricing.md '1M tokens' /tmp/xai_pricing.md
```

Baselines to persist (Step 10):
`research/baselines/xai-llms-sections-YYYY-MM-DD.txt` (the `grep '^==='` list) AND
`research/baselines/xai-tools-hashes-YYYY-MM-DD.txt` (per-section sha of the
`/developers/tools/*` + `/rest-api-reference/inference/*` sections).

## SDK / GitHub + security lane (full runs; we consume REST directly)

```bash
gh release list -R xai-org/xai-sdk-python --limit 5 --json tagName,name,publishedAt
gh api 'repos/xai-org/xai-proto/commits?per_page=10' --jq '.[] | [.commit.committer.date, (.commit.message|split("\n")[0])] | @tsv'   # releases stale at v1.0.0 — watch COMMITS
for r in plugin-marketplace xai-sdk-python xai-proto xai-cookbook grok-prompts x-algorithm grok-1; do
  echo "== $r: $(gh api repos/xai-org/$r/security-advisories --jq 'length')"; done   # zero-baseline 2026-07-05; alert on nonzero
```

## Triggered

```bash
$FC "https://docs.x.ai/developers/migration/<slug>.md" 'igration' /tmp/xai_migration.md  # TRIGGERED by an llms.txt section diff hit
$FC https://status.x.ai/feed.xml '<rss' /tmp/xai_status.xml                              # TRIGGERED on probe/endpoint failure (RSS 2.0; title "SpaceXAI System Status" — live-verified 2026-08-22)
```

```
firecrawl_scrape(url="https://x.ai/news", onlyMainContent=true)   # full runs (Cloudflare 403s curl; unique signal = cross-cloud availability e.g. Grok on Bedrock)
```

**@xai on X** — ONLY when Steps 3-4 surface an ambiguous docs change needing
first-party corroboration — via `bin/x-monitor.py` (Agent Tools API x_search;
cost-bearing $5/1k), scoped to the official handles (@xai, @grok). NOT a
deprecation channel (handle-scoped posts only). Descoped from unconditional
full runs 2026-08-22: the docs + x.ai/news sweep is first-party and complete;
a zero-ambiguity run gains nothing from the pull (log SKIPPED with reason).

**Verify (grok-specific, Step 6):** for API-shape claims, `~/Documents/api-docs/xai/openapi.json`
+ the raw `llms.txt` corpus are vendor text; NEVER cite our own distilled
`reference.md` as vendor confirmation (the 2026-06-12 circular-evidence trap,
`rules/api-doc-lookup.md` inversion note). Check ingested-docs staleness with
`ls -la ~/Documents/api-docs/xai/reference.md` — if this run finds API-surface
changes newer than that mtime, queue `/api-ingest`.

Verified-SKIP (re-probe on `full` runs; stamped 2026-07-05): xAI Docs MCP at
docs.x.ai/api/mcp (interactive lookup, not a diffable channel — but IS the successor
if we replace the abandoned community npm), console.x.ai (auth-walled).

## Step 5 gap-fill (only if a finding needs corroboration)

```
tavily_search(query="xAI Grok {topic} {year}", search_depth="advanced", max_results=5, chunks_per_source=3, time_range="month")
web_search_exa(query="xAI Grok {topic} deprecation OR retirement")
```
