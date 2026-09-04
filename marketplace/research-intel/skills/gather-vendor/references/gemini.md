# gather-vendor — Google Gemini profile (channels live-verified 2026-07-05)

## Dependency map (why this vendor matters — honest thin baseline)

No wired Gemini runtime tooling today. Dependencies are real but thinner; a
"no delta affects us" run is a CORRECT outcome — do not manufacture findings.

1. **Cross-model panel arm** — `rules/eval-shipping-discipline.md` requires
   each vendor's FLAGSHIP for cross-model validation. This skill's first job is
   keeping the Gemini flagship record current (a wrong-flagship arm silently
   confounds a panel — the Nova-Pro incident shape). Current record:
   **gemini-3.1-pro-preview** (gemini-3-pro-preview retired 2026-03-09).
2. **CI attack-surface** — `skills/agentic-actions-auditor/` encodes Gemini CLI
   behaviors as attack vectors; Gemini CLI changes drift those assumptions.
   On `full` runs sweep it: `gh release list -R google-gemini/gemini-cli --limit 3`
   (2026-08-22: v0.56 nightlies only; filter to non-nightly tags for signal).
3. **GEMINI_API_KEY** (Keychain) — latent capability; probe-verified working.

## Step 1 greps (assumption indicators + flagship record)

```bash
grep -riE "gemini" ~/.claude/rules/ ${CLAUDE_PLUGIN_ROOT}/skills/agentic-actions-auditor/ ~/Documents/knowledge-base/topics/ --include="*.md" -l
# flagship record: read the prior report's "flagship record" line and PASS that id
# as the Step 2 pin (probe_models.py gemini <flagship-id>) — a pin-less probe cannot
# verify flagship currency and returns a non-OK "NO flagship pin passed" signal.
```

## Critical Gotchas

- **ai.google.dev has NO machine-readable variants**: llms.txt is 404 and appending
  `.md` returns the SAME HTML with 200 (trap). Pages ARE server-side rendered — plain
  `curl -sL` + heading/table grep works; no firecrawl for the four API-doc channels.
- **The deprecations table needs a STRUCTURAL parse** — raw regex hits nav-sidebar
  noise (the 2026-07-05 smoke defect). Use the `<tr>/<td>` python below (~83 rows).
- **AI Studio changelog is auth-gated** (Google sign-in) — excluded.
- **Google Cloud docs mid-migration** (cloud.google.com -> docs.cloud.google.com) — `curl -L`.
- Listing != serving: a model appears in ListModels after its shutdown date — the probe
  cross-checks the deprecations table for the recorded flagship.

## Standing sweep

All channels ride `scripts/fetch_channel.py` (fetch + marker assert + atomic
write; exit 0 ok / 2 HTTP / 3 marker-miss; follows the cloud.google.com ->
docs.cloud.google.com redirects):

```bash
FC="python3 ${CLAUDE_PLUGIN_ROOT}/skills/gather-vendor/scripts/fetch_channel.py"
# 1. canonical ship log (server-rendered; dated h2 anchors)
$FC https://ai.google.dev/gemini-api/docs/changelog '<h2 id="' /tmp/gem_changelog.html
grep -oE '<h2 id="[0-9-]+" data-text="[^"]+"' /tmp/gem_changelog.html
# 2. deprecations — STRUCTURAL parse (raw regex fails on sidebar noise)
$FC https://ai.google.dev/gemini-api/docs/deprecations 'eprecat' /tmp/gem_dep.html
python3 - <<'PYEOF'
import re
html = open("/tmp/gem_dep.html", encoding="utf-8").read()
for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)]
    if cells and cells[0].startswith(("gemini", "imagen", "veo", "lyria", "deep-research")):
        print(" | ".join(cells))
PYEOF
# 3. model inventory
#    NOTE 2026-08-22: the inline '-deprecated' id anchors were REMOVED from this page —
#    zero hits is now normal, not a signal. The deprecations table (channel 2) + the
#    authenticated probe carry the retirement signal.
$FC https://ai.google.dev/gemini-api/docs/models 'gemini-' /tmp/gem_models.html
grep -oE 'gemini-[a-z0-9.\-]+' /tmp/gem_models.html | sort -u
# ground truth: probe_models.py gemini (authenticated, full-pagination ListModels — Step 2)
# 4. pricing — no dated history; FIRST RUN persists the snapshot as the baseline
$FC https://ai.google.dev/gemini-api/docs/pricing 'per 1M' /tmp/gem_pricing.html
```

Baseline to persist (Step 10): `research/baselines/gemini-pricing-YYYY-MM-DD.txt`
(normalized price-table text). First run ESTABLISHES it (fetch+persist), never defers.

## SDK + security lane (gh, every run — batch)

```bash
for r in python-genai js-genai go-genai; do
  gh release list -R googleapis/$r --limit 5 --json tagName,name,publishedAt; done  # BREAKING CHANGE markers explicit
for r in python-genai js-genai go-genai; do
  echo "== $r: $(gh api repos/googleapis/$r/security-advisories --jq 'length')"; done
```

## Full-run / triggered

```bash
$FC https://docs.cloud.google.com/feeds/generative-ai-on-vertex-ai-release-notes.xml '<title>' /tmp/gem_vertex.xml  # full: Vertex partner-model EOL dates double as [cross-vendor] cross-check on Anthropic retirements -> Handoffs -> gather-claude (feed LAGS — newest entry was ~3 months old on 2026-08-22)
$FC https://deepmind.google/blog/rss.xml '<item>' /tmp/gem_dm.xml            # full: model-launch narratives (item-level diff — feeds regenerate lastBuildDate)
$FC https://developers.googleblog.com/feed/ '<item>' /tmp/gem_gdb.xml        # full: dev-facing Gemini API deep-dives + ADK/Genkit (item-level diff; ?technology_categories param is ignored)
```

```
firecrawl_scrape(url="https://aistudio.google.com/status", onlyMainContent=true, waitFor=8000)  # TRIGGERED on probe/endpoint failure (JS app)
firecrawl_scrape(url="https://gemini.google.com/updates", onlyMainContent=true, waitFor=5000)   # full: consumer surface
```

Verified-SKIP (re-probe on `full` runs; stamped 2026-07-05): AI Studio changelog
(auth-gated), Google Cloud incidents.json (Vertex lane, wrong for us), The Keyword
Gemini feed (dupes apps updates + DeepMind), Workspace Updates blog (not our tenant stack).

## Step 5 gap-fill (only if a finding needs corroboration)

```
tavily_search(query="Google Gemini {topic} {year}", search_depth="advanced", max_results=5, chunks_per_source=3, time_range="month")
web_search_exa(query="Google Gemini API {topic} announcement")
```
