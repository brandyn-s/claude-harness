# Web Track — Literal Queries (Steps 8, 8b, 9)

## Critical Gotchas (read before running anything in this file)

- **Do NOT pipe a fetch into an interpreter or a filter.** `curl … | python3 -c …`
  is blocked by `bash-security-guard [exfiltration-guard]`, and
  `producer | tail/head/grep` is blocked by `bash-tail-buffering-guard`. Both fired
  again on 2026-08-21 — the third and fourth consecutive runs to hit this class.
  **DOWNLOAD TO A FILE, THEN PARSE THE FILE.** That is the contract for every fetch
  in Steps 8, 8b and 9, not a per-command workaround:
  `curl -sS -L "$URL" -o /tmp/claude/x.json` then `python3 - <<'PY' … PY`.
- **Quote every glob and pattern.** Unquoted `*.py` / `--include=*.md` makes zsh
  ABORT the command with `no matches found` before it runs. That abort prints no
  results, which reads exactly like a zero-hit finding. Measured 2026-08-21: two
  greps "returned nothing" and were re-run quoted, at which point both found hits.
  A zero result is only a zero result if the command's exit status says it ran.
- **`curl` without `-L` on a redirecting host returns a ~111-byte HTML stub**, and
  `json.load` on it dies with `Expecting value: line 1 column 1` — which reads as a
  malformed API rather than a redirect. Always `curl -sS -L`.

## Step 8: Docs Inventory (llms.txt) + Extract Key Pages

Inventory first (one cheap GET — ~186 lines as of 2026-08-21, every page WITH a
one-line description):

```bash
curl -sS -L https://code.claude.com/docs/llms.txt -o /tmp/claude/llms.txt
```

Fallback ONLY if llms.txt 404s: `tavily_map(url="https://code.claude.com/docs/en/",
limit=100, max_depth=2)` — bare URLs, no descriptions, higher cost.

### The inventory diff is URL-NORMALISED on BOTH sides (do not skip this)

The preserved artifact (`research/claude-code-docs-inventory-<date>.txt`) stores the
**full llms.txt lines** — `- [Title](url): description` — not bare URLs. Diffing an
extracted URL list against those raw lines makes EVERY line differ, which renders as
"the entire documentation set was removed." Measured 2026-08-21: the first diff
attempt reported ~187 removals and 0 additions. The real answer was **1 removal, 0
additions**. Extract and normalise both sides, then diff:

```bash
BASE=~/Documents/knowledge-base/research/claude-code-docs-inventory-<prev-date>.txt
NOW=/tmp/claude/llms.txt
grep -oE 'https://code\.claude\.com[^)]*' "$BASE" | sed 's/\.md$//' | sort -u > /tmp/claude/docs-base.txt
grep -oE 'https://code\.claude\.com[^)]*' "$NOW"  | sed 's/\.md$//' | sort -u > /tmp/claude/docs-now.txt
echo "REMOVED:"; comm -23 /tmp/claude/docs-base.txt /tmp/claude/docs-now.txt
echo "ADDED:";   comm -13 /tmp/claude/docs-base.txt /tmp/claude/docs-now.txt
```

`sed 's/\.md$//'` matters because llms.txt has carried both `page` and `page.md`
forms across runs; without it, a format change alone fabricates a full-set churn.
**A diff whose output is "everything changed" is a diff bug until proven otherwise** —
Anthropic does not delete its documentation set. Save the new raw llms.txt as this
run's artifact so the next run has an exact baseline, and record its byte count and
SHA-256 in the metadata header.

**A REMOVED page is a real DEPRECATION signal.** 2026-08-21 lost
`agent-sdk/slash-commands` (187 → 186) — the only inventory change in a 9-day window,
and invisible to every other track.

Then extract the six high-value pages.

**Try plain `curl` of the `.md` variant FIRST — measured 2026-08-01, it returns the
full clean page and costs nothing.** `curl -s https://code.claude.com/docs/en/<page>.md`
returned complete markdown (e.g. `auto-mode-config.md` = 27,697 bytes, including every
JSON schema example and the `min-version` annotations). The Mintlify nav-shell problem
that forced firecrawl is a property of **tavily_extract on the HTML page**, not of the
`.md` variant, so the cheap path works for this host:

```bash
for p in changelog hooks skills settings sub-agents mcp; do
  curl -s "https://code.claude.com/docs/en/$p.md" -o "/tmp/claude/$p.md"
done
```

Sanity-check the byte count before trusting it (a nav shell is small); if a page comes
back short or empty, fall back to `firecrawl_scrape` — these are **Mintlify-hosted** and
per `web-search-preference.md` firecrawl is the routed tool for them (tavily_extract
returns nav-shell / `Content: undefined` on Mintlify; observed degraded 2026-07-05):

```
firecrawl_scrape(url="https://code.claude.com/docs/en/changelog.md", onlyMainContent=true)
firecrawl_scrape(url="https://code.claude.com/docs/en/hooks.md", onlyMainContent=true)
firecrawl_scrape(url="https://code.claude.com/docs/en/skills.md", onlyMainContent=true)
firecrawl_scrape(url="https://code.claude.com/docs/en/settings.md", onlyMainContent=true)
firecrawl_scrape(url="https://code.claude.com/docs/en/sub-agents.md", onlyMainContent=true)
firecrawl_scrape(url="https://code.claude.com/docs/en/mcp.md", onlyMainContent=true)
```

## Step 8b: First-Party Release-Notes Sweep (added 2026-07-05)

Filter each to entries after `{since_date}`. The Fable 5 suspension/restoration, the
Sonnet 5 `temperature`/`top_p` deprecations, and Admin-API endpoint migrations were
published ONLY in these channels — none reach the CHANGELOG or the issue tracker.

```bash
# 1. Claude Platform (API) release notes — Admin/Usage/Analytics APIs, model events
curl -s https://platform.claude.com/docs/en/release-notes/overview.md

# 2. Model deprecations — lifecycle states + retirement dates for every model we pin
curl -s https://platform.claude.com/docs/en/about-claude/model-deprecations.md

# 3. AWS Bedrock What's New (GovCloud model availability) — download, THEN parse.
#    Do NOT pipe curl into grep/python: `curl … | grep` trips our own
#    bash-security-guard exfiltration check (measured 2026-08-08 — the documented
#    pipe form was BLOCKED mid-run, the second skill step to hit this guard in one
#    session). Same download-then-parse discipline as 3b below.
curl -sS -L "https://aws.amazon.com/about-aws/whats-new/recent/feed/" -o /tmp/claude/aws-feed.xml
#    Then parse locally, pairing each matched <title> with its <pubDate> so the
#    window filter is real rather than eyeballed:
#      items = re.findall(r'<item>(.*?)</item>', xml, re.S)
#      → per item, regex <title> (strip CDATA) + <pubDate>, keep /claude|anthropic|bedrock/i
#    A feed with zero vendor items is a legitimate EMPTY result, not a failed fetch:
#    report the item count alongside the hit count so the two are distinguishable.

# 3b. On a MODEL-LAUNCH day, the RSS blurb rarely answers "is it in GovCloud?" —
#     the Bedrock region-compatibility table is definitive. Download-then-parse
#     (a curl|python3 pipe trips the exfiltration-guard); slice from the model's
#     heading to the next "Claude " heading and regex the region codes:
#     re.findall(r'[a-z]{2}-[a-z-]+-\d', block) → check for us-gov-*.
#     (Codified 2026-07-24: settled Opus 5 = commercial-only at launch in one call.)
curl -s "https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html" -o /tmp/claude/bedrock-regions.html
```

```
# 4. Claude apps / Enterprise release notes (Intercom help center — JS-rendered)
firecrawl_scrape(url="https://support.claude.com/en/articles/12138966-release-notes", onlyMainContent=true)
```

```
# 5. Claude Desktop 3P (managed/enterprise desktop) — config-key changelog + M365 connector
#    (added 2026-07-16; Mintlify on claude.com/docs — firecrawl_scrape per web-search-preference)
#    We run this surface in production: Jamf profiles "Claude 3P"/"Claude 3P Development Pilot"
#    (com.anthropic.claudefordesktop) on Bedrock GovCloud, incl. the built-in M365 local
#    connector (server:"microsoft365", azureCloud:"us-gov-high") against the GCC High tenant.
firecrawl_scrape(url="https://claude.com/docs/third-party/claude-desktop/configuration-changelog", onlyMainContent=true)
firecrawl_scrape(url="https://claude.com/docs/third-party/claude-desktop/connectors-m365", onlyMainContent=true)
```

For item 5, flag specifically:
- **New/changed `managedMcpServers` subfields** and new built-in `server:` values (websearch
  appeared 2026-06-25; M365 write tools 2026-07-07 — both only in this changelog).
- **M365 connector tool-catalog changes** — new write tools (we watch for Outlook
  mail-folder create/move, Teams posting), scope-list changes, `toolPolicy` semantics
  (send-tools ask-floor), and GCC High/DoD (`us-gov-high`/`us-gov-dod`) notes.
- **Default flips** (e.g. `isDesktopExtensionEnabled` true→false, 2026-07-07) — our deployed
  profiles inherit new-key defaults silently; diff any new key against the deployed plists.

## Step 9: Gap Fill (only if needed)

```
tavily_search(query="Claude Code {component} {year}", search_depth="advanced", max_results=5, chunks_per_source=3, time_range="month")
```

Also extract (fire in parallel):
- `https://www.anthropic.com/news` (query: "Claude Code announcement")
- `https://www.anthropic.com/research` (query: "Claude agent MCP")
- `https://www.anthropic.com/engineering` (query: "Claude Code agent SDK architecture")
- `https://www.claude.com/blog` (query: "Claude Code announcement release feature")
- `https://docs.claude.com/en/docs/claude-code/overview` (query: "Claude Code {focus_area} configuration")
- `https://support.anthropic.com` (query: "Claude Code known issue workaround")
- `https://status.claude.com` (query: "Claude Code incident") — **NOTE (measured 2026-08-01):
  `status.anthropic.com` now 302-redirects to `status.claude.com`. A `curl -s` WITHOUT `-L`
  returns a 111-byte HTML redirect stub, and `json.load` on it dies with
  `Expecting value: line 1 column 1` — which reads as a malformed API, not a redirect. Always
  use `curl -sS -L`. Machine-readable summary:
  `https://status.claude.com/api/v2/summary.json` → `.status.description` + `.incidents[]`.**

**Exa-specific gap fill** (fire in parallel with Tavily searches above):
- `web_search_exa(query="Claude Code {component} update")` — semantic catch for recent blog posts and announcements Tavily misses. NOTE: the consolidated `web_search_exa` takes only `query` (+ optional `numResults`) — no `freshness`/`include_domains`/`enableHighlights`. The retired `get_code_context_exa` / `web_search_advanced_exa` are gone (2026-06 Exa consolidation, per `web-search-preference.md`): code/repo discovery and Anthropic-repo coverage are the GitHub track's job (Steps 3-7b via `gh`); domain-filtered/operator web search routes to `firecrawl_search`.
