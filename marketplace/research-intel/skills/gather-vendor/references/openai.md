# gather-vendor — OpenAI profile (channels live-verified 2026-07-05)

## Dependency map (why this vendor matters)

1. **Cross-provider second rater** — the standing different-vendor rater required by
   `rules/eval-shipping-discipline.md` + `rules/best-in-class-for-cross-model.md`.
   Current flagship line: **gpt-5.6-sol** (GA 2026-07-09; alias `gpt-5.6` -> sol).
2. **/roundtable arm** — `skills/roundtable/scripts/adapters/openai_adapter.py` pins
   `gpt-5.6-sol` (default) + `gpt-5.6-terra` + `gpt-5.5-pro` (as of 2026-08-22 —
   always trust the Step 1 grep over this prose).
3. **API key** — Keychain item is `OPENAI_PLATFORM_API` (inference key; the old
   `OPENAI_API_KEY` item was renamed 2026-08-04 — see memory/openai-keychain-items.md).
   probe_models.py tries env OPENAI_API_KEY then that Keychain item. Endpoint drift
   already cost two PRs (2026-05-01 gpt-5.5-pro 404 misdiagnosed as tier-gating;
   real cause was a changed endpoint).

`~/Documents/api-docs/openai/` IS ingested (2026-08-22, from the official
api/llms-full.txt export; ~231 endpoints, `[catalog-only]` entries flagged).
Re-run `/api-ingest https://developers.openai.com/api/llms-full.txt --name openai`
when this skill detects API-surface drift.

## Step 1 greps (workaround indicators + live pins)

```bash
grep -riE "openai|gpt-5" ~/.claude/rules/ ~/Documents/knowledge-base/topics/ --include="*.md" -l
grep -hoE "gpt-[0-9a-z.\-]+" ${CLAUDE_PLUGIN_ROOT}/skills/roundtable/scripts/adapters/openai_adapter.py | sort -u   # live pins -> Step 2
```

## Critical Gotchas

- **Soft-404 trap**: developers.openai.com returns HTTP **200 with "Page not found"
  HTML** for nonexistent `.md` paths — content-verify with a marker, never trust status.
- **The catalog HTML does not carry `-pro` IDs**: `gpt-5.5-pro` appears in NO textual
  form in the catalog HTML. The probe's authenticated `/v1/models` check is PRIMARY.
- **Do NOT** use `gh api '/advisories?affects=openai'` (returns 0, misses the real codex
  advisory) — query per-repo advisories.
- Use developers.openai.com (has llms.txt); platform.openai.com is the same content
  behind a heavier shell with no llms.txt.

## Standing sweep (marker in comment; assert it per Step 3)

All channels ride `scripts/fetch_channel.py` (fetch + marker assert + atomic
write; exit 0 ok / 2 HTTP / 3 marker-miss = dead/rewritten channel):

```bash
FC="python3 ${CLAUDE_PLUGIN_ROOT}/skills/gather-vendor/scripts/fetch_channel.py"
# lifecycle authority — real .md twin (~36KB)
$FC https://developers.openai.com/api/docs/deprecations.md '# Deprecations' /tmp/claude/oai_dep.md
# API changelog — HAS a real .md twin since ~2026-08 (~60KB; month "## " + day "### " headings;
#   the old HTML date-grep is obsolete — dates live in headings now)
$FC https://developers.openai.com/api/docs/changelog.md '# Changelog' /tmp/claude/oai_changelog.md
# pricing — markdown TABLES since ~2026-08 (the JSON-array format is gone)
$FC https://developers.openai.com/api/docs/pricing.md '| gpt-' /tmp/claude/oai_pricing.md
grep -E '^\| *(gpt|o[0-9])' /tmp/claude/oai_pricing.md
# docs inventory diff — root llms.txt RESTRUCTURED ~2026-08 into a PRODUCT INDEX
#   (per-product llms.txt: api/docs, api/reference, ads, plugins, workspace-agents,
#   codex, commerce, blog). Baseline = root link list; a new/removed PRODUCT row is
#   itself a finding.
$FC https://developers.openai.com/llms.txt 'Documentation sets' /tmp/claude/oai_llms.txt
# news RSS (works via curl-class fetch even though openai.com HTML 403s; CDATA titles)
$FC https://openai.com/news/rss.xml '<item>' /tmp/claude/oai_rss.xml
```

Baseline to persist (Step 10): `research/baselines/openai-llms-links-YYYY-MM-DD.txt`
(root product-index links + the api/docs/llms.txt link list) — diff run-over-run.
First established 2026-08-22 (the 2026-07-05 run logged a count but persisted no file).

## SDK + security lane (gh, every run)

```bash
for r in openai-python openai-node openai-agents-python; do
  gh release list --repo openai/$r --limit 10 --json tagName,name,publishedAt; done
# MAJOR version bump = canonical breaking-change flag; view bodies only on new tags
for r in openai-python openai-node openai-agents-python codex; do
  echo "== $r"; gh api repos/openai/$r/security-advisories --jq '[.[] | {ghsa:.ghsa_id, sev:.severity, summary:.summary}]'; done
```

## Full-run / triggered

```bash
# ToS / data-use drift (roundtable ships internal content to the vendor)   full runs
$FC https://developers.openai.com/api/docs/guides/your-data.md '# Data controls' /tmp/claude/oai_yourdata.md
$FC https://developers.openai.com/api/docs/guides/rate-limits.md '# Rate limits' /tmp/claude/oai_ratelimits.md
# Staff Announcements (Discourse JSON; sort by created_at — pinned 2021 topics lead)   full runs
#   fetch_channel retries one 429 after 12s natively (Discourse cloud_60_secs_limit)
$FC https://community.openai.com/c/announcements/6.json 'topic_list' /tmp/claude/oai_ann.json
# Status (FedRAMP component present) — TRIGGERED when a probe/endpoint call fails
$FC https://status.openai.com/api/v2/summary.json 'status' /tmp/claude/oai_status.json
```

```
firecrawl_scrape(url="https://help.openai.com/en/articles/10128477-chatgpt-enterprise-edu-release-notes", onlyMainContent=true)   # full runs (Cloudflare 403s curl)
```

Verified-SKIP (re-probe on `full` runs only; stamped 2026-07-05): consumer ChatGPT
release notes (API retirements owned by deprecations.md), trust.openai.com (attestations,
no ship cadence).

## Step 5 gap-fill (only if a finding needs corroboration)

```
tavily_search(query="OpenAI {topic} {year}", search_depth="advanced", max_results=5, chunks_per_source=3, time_range="month")
web_search_exa(query="OpenAI {topic} announcement")
```
