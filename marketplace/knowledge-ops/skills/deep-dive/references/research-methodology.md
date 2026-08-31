# Shared Research Methodology

Canonical reference for research patterns shared across `gather-intel`, `gather-research`, and `deep-dive` skills. Each skill still contains inline quick-reference sections; this file is the single source of truth for updates.

> **v2.0 multi-provider note (deep-dive):** `/deep-dive` runs across **Tavily + Exa + Firecrawl** in parallel for every research question. The Tavily-centric sections below were the original gather-intel/gather-research baseline; the Firecrawl rows in Sections 1, 5, and 6 close the v2.0 gap.

---

## 1. Provider Tool Selection Guide

### Tavily tools

| Tool | Parameters | When to use | Cost |
|------|-----------|-------------|------|
| `tavily_search` | `search_depth: "advanced"`, `chunks_per_source: 3`, `max_results: 5` | Default discovery. Token-efficient: returns 500-char reranked snippets. Add `topic: "news"` + `time_range: "month"` for Reddit/HN/forums. Add `topic: "finance"` for vendor/spend analysis. | 2 credits |
| `tavily_research` | `model: "mini"` or `"pro"` | Synthesis spanning many sources. `mini` (~30s) for "What does X do?". `pro` (~60-120s) for "X vs Y", landscape analysis. Better ROI than assembling 5+ individual searches. | Variable |
| `tavily_extract` | `extract_depth: "basic"`, `query: "<focused question>"` | Full content from a known URL. **ALWAYS include `query`** to focus extraction. Try `basic` first; retry with `"advanced"` if URL appears in `failed_results`. | 1 credit per 5 URLs |
| `tavily_map` | `max_depth: 1`, `categories: ["Documentation"]` | Discover site structure before crawling. Use `categories` to filter URL types. | 1 credit per 10 pages |
| `tavily_crawl` | `select_paths: [...]`, `instructions: "..."`, `chunks_per_source: 3` | Crawl specific sections after mapping. `chunks_per_source` requires `instructions`. | 1 credit per 10 pages |

### Exa tools

| Tool | Parameters | When to use |
|------|-----------|-------------|
| `web_search_exa` | `query`, `numResults` | Semantic search — recent articles, blogs, code/GitHub (include language + identifiers), and verticals via an in-query `category:people`/`category:company`. Highlights built-in. (Exa consolidated upstream — `get_code_context_exa`, `web_search_advanced_exa`, and `crawling_exa` were retired; compose code/vertical/domain queries in-query or via `firecrawl_search` operators.) |
| `web_fetch_exa` | `urls` (batch), `maxCharacters` | Full page content from known URLs (clean markdown). Successor to the retired `crawling_exa`. |

### Firecrawl tools

| Tool | Parameters | When to use |
|------|-----------|-------------|
| `firecrawl_search` | `query`, `limit` | Run alongside Tavily and Exa for every research question. Surfaces GitHub READMEs, changelogs, release notes, and docs sites that keyword/semantic indexes often rank lower. |
| `firecrawl_scrape` | `url`, `formats: ["markdown"]` | **Primary deep-fetch tool** in `/deep-dive` v2.0. Cleanest markdown output; preferred for JS-rendered SPAs. Fall back to `tavily_extract` or `web_fetch_exa` if scrape returns thin content. |
| `firecrawl_map` | `url`, `limit` | Discover site structure before crawling. Returns cleaner URL inventories than `tavily_map` for many doc sites. |
| `firecrawl_crawl` | `url`, `maxDepth: 2`, `limit: 20` | Crawl docs sites after mapping. For very large sites, fire async and poll with `firecrawl_check_crawl_status`. |
| `firecrawl_extract` | `urls`, `schema` (JSON) | Structured-field extraction (version, price, release date) across multiple URLs when you need fields, not prose. |

### Cost rules

- Default to `search_depth: "advanced"` on `tavily_search` — the token savings from `chunks_per_source: 3` outweigh the 2x credit cost. Never use `auto_parameters` (silently upgrades depth).
- Use `tavily_research` with `model: "mini"` for focused queries (2-4x faster than `pro`).
- Check `failed_results` on `tavily_extract`/`tavily_crawl` and retry failures with `extract_depth: "advanced"`.
- Use Exa `web_search_exa` (include language + identifiers) for GitHub/code searches — finds issues Tavily misses (2026-03-28 empirical test).
- Use Exa `web_search_exa` with an in-query `category:` (people/company) for vertical discovery, or `firecrawl_search` operators for domain/site-filtered discovery.
- For `/deep-dive` v2.0, fire `tavily_search` + `web_search_exa` + `firecrawl_search` in the same parallel message for every research question. Each provider surfaces different hits (keyword vs semantic vs structured); single-provider coverage downgrades a question's confidence by one tier.

---

## 2. Wave-Based Search Pattern

The common execution pattern across all research skills:

### Wave 1: Discovery

1. **Fire all independent queries in a single parallel message.** Typically 6-12 calls. No dependencies between them.
2. Mix both tools per `agent-memory/rules/web-search-preference.md` Research Wave Strategy:
   - Exa `web_search_exa` — GitHub issues, code examples (include language + identifiers in query)
   - Exa `web_search_exa` — recent articles, blog posts (express recency in the query)
   - Exa `web_search_exa` with an in-query `category:` — vertical discovery (or `firecrawl_search` operators for domain-filtered)
   - Tavily `tavily_search` with `search_depth: "advanced"`, `chunks_per_source: 3` — broad web
   - Tavily `tavily_search` with `topic: "news"`, `time_range: "month"`, `chunks_per_source: 3` — Reddit/HN/forums
3. Fire 2-3 `web_search_exa` phrasings per research question (the retired `additionalQueries` Exa param is gone — issue separate calls).

### Between waves: Score, assess, plan

4. **Score results** using the score-based pre-filtering thresholds (see Section 3).
5. **Gap analysis**: For each research question, assess current answer confidence:
   - **Answered (High)**: Multiple corroborating sources. Done for this question.
   - **Answered (Medium)**: Some evidence, limited sources. Search for corroboration.
   - **Partially answered**: Aspects addressed but gaps remain. Search for specific gaps.
   - **Unanswered**: No relevant results. Reformulate queries (see Section 4).
6. **Follow leads**: Deep-fetch high-signal results. Follow citation chains. Search for authors' other work on the topic.

### Wave 2+: Targeted deep dives

7. **Fire targeted queries** for gaps and leads identified above. Use `tavily_research(pro)` for synthesis and `tavily_search` for specific follow-ups.
8. Check known high-value sources (Anthropic research page, official docs, CHANGELOG, YouTube talks).
9. Identify "threads" -- clusters of related findings forming a coherent narrative (same pattern appearing in 3+ independent sources).

### Convergence check

10. **Continue** if any question is still Unanswered/Partially answered AND the current wave returned at least 30% new information.
11. **Stop** if:
    - All questions are Answered (High or Medium), OR
    - New rate < 30% for two consecutive waves (sustained diminishing returns), OR
    - Reformulated queries for unanswered questions also return no results (the information likely does not exist publicly)
12. When stopping with unanswered questions, note them honestly rather than stretching weak evidence.

---

## 3. Score-Based Pre-Filtering

After Tavily searches return, examine the `score` field on each result:

| Score range | Action |
|-------------|--------|
| **> 0.6** | Proceed to evaluation. |
| **0.4 - 0.6** | Include if the title or snippet contains domain-specific terms (tool names, config patterns, architecture terms, author names, paper titles, framework names, conference names). |
| **< 0.4** | Skip unless the title is clearly relevant (known high-value resource, seminal paper, major framework release). |

These thresholds apply uniformly. Academic content sometimes scores lower due to different language patterns, so err on the side of inclusion when the title matches known research terms.

---

## 4. Query Reformulation on Empty Results

If any search returns zero or very few results (<3), immediately reformulate. Exhaust 2-3 reformulations per query before marking "no results."

**Reformulation strategies** (try in order):

1. **Drop year restrictions** -- remove `2025 2026` terms
2. **Try alternative terminology** -- examples:
   - "Claude Code" vs "ClaudeCode"
   - "skills" vs "custom commands"
   - "function calling" vs "tool use"
   - "agentic" vs "agent-based"
   - "Windows" vs "Git Bash"
   - "MCP" vs "tool server"
3. **Try platform-specific terms** -- narrow to the platform or ecosystem
4. **Try author names** -- if known experts work on the topic (e.g., "Shunyu Yao" for ReAct)
5. **Broaden scope** -- remove qualifiers, search for the parent topic

After exhausting reformulations, mark the source as "no results" and continue. Never stall the skill on a single failing query.

---

## 5. Graceful Degradation

If any individual source or tool fails, apply the fallback and continue. **Never fail the entire skill because one source is unavailable.**

| Failure | Action |
|---------|--------|
| `tavily_search` returns 0 results | Reformulate query (2-3 attempts per Section 4). After exhausting reformulations, mark "no results" and continue. |
| `tavily_extract` times out or returns empty | Retry with `tavily_search` using `include_raw_content: true`. If that also fails, try `firecrawl_scrape` or `web_fetch_exa` on the same URL before giving up. |
| `tavily_research` returns low-quality synthesis | Supplement with targeted `tavily_search` + Exa + Firecrawl queries to fill specific gaps. |
| `tavily_map`/`tavily_crawl` fails | Fall back to `firecrawl_map` → `firecrawl_crawl`, or `tavily_search` with `site:domain.com`. |
| `mcp__exa__web_search_exa` returns 0 results | Retry with an in-query `category:` or `firecrawl_search` operators. If still empty, continue with Tavily + Firecrawl hits and mark "[Exa silent]". |
| `web_fetch_exa` times out or returns empty | Try `firecrawl_scrape` or `tavily_extract` on the same URL before giving up. |
| `mcp__firecrawl__firecrawl_search` returns 0 results | Retry with alternate phrasing, or switch to `firecrawl_map` on the target domain. If still empty, continue with Tavily + Exa hits and mark "[Firecrawl silent]". |
| `firecrawl_scrape` times out or returns empty | Try `tavily_extract` (advanced) or `web_fetch_exa` on the same URL. JS-rendered pages often need Firecrawl; login-walled pages sometimes open to Exa. |
| `firecrawl_crawl` times out on a large site | Switch to async pattern: fire `firecrawl_crawl` without waiting, then poll `firecrawl_check_crawl_status`. If still failing, fall back to `tavily_map` / `tavily_crawl`. |
| Any provider returns an error (402, 429, 5xx, timeout) | **Capture raw error text verbatim** in the report header. Do NOT interpret the cause without the raw payload. Continue with other providers; do not abandon the skill on one provider's error. |
| Entire provider (Tavily, Exa, or Firecrawl) MCP unavailable | Log "[<provider> MCP unavailable: <raw error>]" in the report header. Continue with remaining providers and downgrade affected findings' confidence by one tier. Two-of-three is the minimum for `/deep-dive`. |
| CHANGELOG fetch fails | Skip version currency check for that finding. Tag as `[version unknown]`. |
| `memory_search` unavailable | Skip local knowledge scan. Note "Memory search unavailable" in output. |
| Specific high-value site blocked/changed (e.g., Anthropic research) | Use `tavily_search` for `site:domain.com/path`, or `firecrawl_scrape` directly. |
| arXiv rate-limited | Extract from cached Google Scholar or Semantic Scholar results. |
| GitHub awesome-* repo unavailable | Use `tavily_search` / `firecrawl_search` for the repo name instead of direct fetch. |

Log every failure inline so the final report reflects source coverage honestly.

---

## 6. Deep Fetch Decision Tree

When a result needs full content beyond search snippets, select the retrieval tool:

```
Need full content from a URL?
|
+-- Is it a multi-page documentation site?
|   YES --> firecrawl_map first (preferred for cleaner URL inventory),
|           then firecrawl_crawl with maxDepth=2, limit=20.
|           Alternate: tavily_map (max_depth=1) -> tavily_crawl with select_paths + instructions.
|
+-- Do you need broad synthesis across many related sources?
|   YES --> tavily_research with model: "pro" (still cross-check claims against Exa + Firecrawl)
|
+-- Default (blog post, Reddit thread, arXiv abstract, GitHub README, forum, any single page)
    --> Primary: firecrawl_scrape (cleanest markdown; preferred for JS-rendered SPAs).
        Alternate: tavily_extract with extract_depth: "advanced" + query parameter,
                   or web_fetch_exa with maxCharacters.
```

### Fallback chain

If the primary tool fails, walk the chain in order:

1. `firecrawl_scrape` with `formats: ["markdown"]` (preferred default for `/deep-dive` v2.0)
2. `tavily_extract` with `extract_depth: "advanced"` + `query`
3. `web_fetch_exa` with `maxCharacters` (batch urls[])
4. `tavily_search` with `include_raw_content: true` (last resort — snippets with raw content)

For `/deep-dive` v2.0, try the other two providers on the same URL before giving up — JS-rendered pages often need Firecrawl while login-walled pages sometimes open to Exa.

### Key rules

- **ALWAYS** provide a `query` parameter on `tavily_extract` calls to focus extraction on relevant content.
- Use `instructions` parameter on `tavily_crawl` / `firecrawl_crawl` to focus the crawler on the specific content needed.
- Use `tavily_research(pro)` when the goal is synthesis, not raw extraction. Good for: comparing competing approaches, understanding a research thread that spans many papers, summarizing the current state of a topic.
- Use `firecrawl_scrape` first for any single-page deep-fetch in `/deep-dive` v2.0; Tavily/Exa serve as fallbacks.
- Default to Tavily / Exa / Firecrawl MCP tools per `agent-memory/rules/web-search-preference.md`. WebFetch/WebSearch are last-resort fallbacks in fully-degraded mode (all three providers unavailable).
