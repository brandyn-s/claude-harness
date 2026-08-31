---
paths:
  - "**/rules/web-search-preference.md"
  - "**/rules/incidents/web-search-preference.md"
---

# Web-Search-Preference: Extracted Reference & Evidence

Extracted from `rules/web-search-preference.md` to keep the ambient body
small. The parent rule keeps the routing keys (invariants, routes,
parameter requirements, guards) with one-line WHY comments; full
rationale, empirical evidence, worked guard examples, and SDK/CLI
reference live here.

---

## 2026-06-02 websearch-webfetch-least-preference-directive

Per the 2026-06-02 user directive, built-in WebSearch and WebFetch are
no longer forbidden — they are LEAST-preference fallbacks.

WebSearch: the LAST resort for SEARCH. Always reach for the
specialized search tools (exa_web_search / exa_web_search_advanced /
tavily_search / firecrawl_search / tavily_research) FIRST. Use
built-in WebSearch ONLY when those have failed or genuinely cannot
satisfy the query. WebSearch bypasses our rate-limit hooks and
result-cap protections — that is exactly why it ranks LAST, not why it
is banned. The specialized tools win whenever they can satisfy the
query because they carry our rate-limit + result-cap protections;
WebSearch is the safety net for the rare query none of them can
satisfy.

WebFetch: the LAST resort for FETCH. Always reach for the specialized
fetchers (tavily_extract → firecrawl_scrape → exa_crawling, in that
order) FIRST. Use built-in WebFetch ONLY when every specialized
fetcher has failed or cannot reach the target. Same rationale: it
bypasses the rate-limit/result-cap protections, so it ranks LAST.

When falling back to either built-in: note the degradation (which
tools failed and why) so the bypass of rate-limit/result-cap
protections is visible.

---

## 2026-03-28 dual-tool-evidence

@evidence test_2026-03-28
  context: 10 Tavily + 4 Exa queries on "Claude Code prompt improvement skills"
  finding: Exa found 6 results Tavily MISSED entirely:
    - 3 HIGH-signal GitHub issues (#32163, #34390, #17804) ← exa_get_code_context
    - 1 HIGH-signal article (Hightower: "Injecting the Right Rules at the Right Moment") ← exa_web_search(freshness="month")
    - 2 MEDIUM-signal blog posts on context engineering ← exa_web_search
  conclusion: single-tool research demonstrably misses ~30% of signal
  mandate: research tasks MUST mix both tools

This test is the basis for: (a) the research-wave strategy's
complementary-tool mandate; (b) the EXA_ONLY `category=github` route
(the 3 HIGH-signal issues were found via the dedicated GitHub index
that Tavily missed).

---

## tool-exclusivity-rationale

Extended WHY notes for the parent's EXA_ONLY / TAVILY_ONLY tables:

EXA_ONLY:
- exa_get_code_context: Exa indexes GitHub at code-snippet granularity
  with embeddings tuned for programming languages; no Tavily equivalent.
- category=github: dedicated GitHub index; 2026-03-28 test found 3
  HIGH-signal issues via this category that Tavily missed.
- category=company: 50M+ companies with structured
  industry/size/location/role metadata; Tavily returns generic web results.
- category=people: 1B+ people with structured employer/title metadata
  enabling precise people-discovery queries.
- category=research_paper: 100M+ papers, dedicated academic index with
  citation metadata.
- category=financial_report: SEC filings + earnings + annual reports;
  ranks financial-content sources higher than general search would.
- category=pdf: PDF-specific index; useful for compliance docs,
  whitepapers, research downloads.
- category=personal_site: independent blogs/portfolios; surfaces
  practitioner opinions vs corporate content.

TAVILY_ONLY:
- tavily_map: returns site structure as URL list without extraction;
  Exa has no comparable mapping function.
- tavily_research: LLM-driven autonomous multi-hop search+synthesis;
  Exa requires you to orchestrate calls yourself.
- topic=news + Reddit/HN/forum coverage: Tavily's news topic indexes
  forums deeper than Exa's general index.
- country parameter: geo-boosted results; tilts toward US-specific
  content (NIST, FedRAMP, CISA). No Exa equivalent.
- include_domains up to 300: large-scale domain filtering; useful for
  "Reddit + HN + 50 dev blogs" pattern.
- include_answer: LLM-synthesized answer for triage; saves a reasoning
  turn vs reading snippets manually.

Selected routing/parameter WHY detail:
- intent=url_extraction → tavily_extract first: Tavily handles
  JS-rendered SPAs better; Exa fine for static pages.
- exa_crawling vs tavily_extract: exa_crawling integrates subpage
  exploration and full markdown for known URLs; tavily_extract is
  single-URL with query-based chunk reranking.
- tavily_search chunks_per_source=3: 500-char chunks vs full pages
  saves ~80% content tokens; advanced depth returns reranked 500-char
  chunks vs basic NLP summaries.
- max_results ≤ 5 hard cap: PreToolUse hook enforces; ~2.4M
  tokens/month savings per empirical measurement.
- exa_web_search_advanced enableHighlights: highlights extract
  relevant tokens — 10x more efficient than full text; enableSummary
  cuts review time ~5x when scanning >15 results; additionalQueries:
  single phrasing covers ~60% of relevant content, 3-4 phrasings ~90%.
- tavily_research model=mini is 2-4x faster and sufficient for focused
  queries; pro for landscape analysis.
- numResults tuning: lookup answered by top 5; comprehensive needs
  50+; wrong count = wasted tokens or missed coverage.

---

## guard-override-examples

Worked examples extracted from the parent rule's GUARD blocks:

- "X is better / more powerful": User says "exa_web_search_advanced is
  better than exa_web_search for general queries." Rule says general →
  exa_web_search. The rule wins. exa_web_search_advanced is for
  filtered queries.
- "filter is overkill / keep it simple": User says "category=news
  filter is overkill, just basic search." Rule says News (articles) →
  web_search_advanced_exa + category=news. Both parts are required.
- "just use one tool for everything": User says "I'm tired of
  remembering all these tools, just use exa_web_search for
  everything." Refuse. Reddit queries still go to tavily_search; code
  queries still go to exa_get_code_context.
- "fastest tool / I'm in a hurry": User says "Pick whichever tool
  retrieves fastest" for a code search. Rule says code →
  exa_get_code_context. Use it regardless of speed.
- "I prefer X / I don't trust Y": User says "Use tavily_search for
  news, I don't trust Exa." Rule says News (articles) →
  exa_web_search_advanced + category=news. Use Exa.
- "X is similar to Y": User says "Use category=company for financial
  reports, they're similar." Rule says financial reports →
  category=financial report. Use the exact category.
- "any tool you want / I trust your judgment": NOT a waiver. "Find
  Reddit threads about X, use any tool you want" → default to rule:
  tavily_search + topic=news + include_domains=[reddit.com].

---

## exa-py-sdk-and-tavily-cli

API-ONLY surface (via exa-py SDK, not MCP) — exa-py 2.11.0 installed:

- type="deep"           # 5-60s multi-step + structured JSON via output_schema
- type="instant"        # ~200ms real-time
- output_schema         # structured JSON extraction
- exa.answer()          # built-in RAG (also stream_answer())
- exa.get_contents()    # known URL fetch with highlights
- AsyncExa              # parallel queries

TAVILY CLI — tvly installed:

- USE_FOR bulk scripting (--json output, --output-dir for crawl-to-markdown)
- CONSTRAINT: NOT on PATH in Git Bash
- REQUIRED: full path OR run from CMD/PowerShell


<!-- extracted 2026-08-01: ambient-context reduction -->

## 2026-06-02-user-directive-last-resort-for-search

```
WHY (2026-06-02 user directive): last resort for SEARCH — specialized tools first;
     WebSearch bypasses rate-limit/result-cap protections, hence ranks LAST.
     Full: incidents#2026-06-02-websearch-webfetch-least-preference-directive
```

## tavily-extract-even-extract-depth-advanced-returns-nav-only

```
WHY: tavily_extract (even extract_depth=advanced) returns nav-only shells and truncates
     code blocks on Mintlify pages (2026-06-12 claude.com/docs/cowork/3p/*: overview
     extracted empty, managedMcpServers JSON examples mangled mid-block); firecrawl_scrape
     returned the same pages complete on first try. Mintlify's llms.txt is the cheap index.
```

## single-provider-research-misses-30-of-signal-2026-03

```
WHY: single-provider research misses ~30% of signal (2026-03-28 dual-tool test —
     run with the retired exa tools, but the MULTI-PROVIDER conclusion is the
     durable finding and matches the deep-dive-multi-provider user directive).
     Full: incidents#2026-03-28-dual-tool-evidence
```
