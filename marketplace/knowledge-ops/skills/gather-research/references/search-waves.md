# Phase B Search Waves — Query Construction and Wave Mechanics

Detailed reference for Steps 4-5 (Wave 1 Discovery and Wave 2 Targeted Deep Dives).

## Step 4: Wave 1 — Discovery

**Generate queries dynamically from the research questions in Step 3b.** No hardcoded queries — every search targets a specific research question. Fire **8-12 search calls in a single message** (all independent). Set `include_raw_content: false` at discovery stage — we'll deep-fetch selectively in Step 8.

### Tool routing

Follow `~/.claude/rules/web-search-preference.md` for Tavily vs Exa selection. Do not default to Tavily for all queries.

**Parameter contract: the live tool schema wins.** Load schemas via ToolSearch and pass only parameters that exist there. Provider MCP surfaces drift — earlier versions of this file mandated `chunks_per_source`, `topic: "news"`, Exa `freshness`/`enableHighlights`/`additionalQueries`, and the tools `web_search_advanced_exa`/`get_code_context_exa`, none of which existed on the deployed surface by 2026-08. Name the *intent* below; map it to whatever the live schema offers.

- Code/GitHub queries → `firecrawl_search` with `categories: ["github"]` or `["developer"]`; `gh` CLI for org-internal repos
- Recent articles / semantic discovery → Exa `web_search_exa` (semantically rich ideal-page description; include year terms for recency)
- Research-site-restricted discovery → `firecrawl_search` with `categories: ["research"]`
- Reddit/HN/forums and time-bounded news → Tavily `tavily_search` (use `time_range` and depth options as the live schema defines them)
- Broad web discovery → Tavily `tavily_search` with advanced depth
- Deep fetch of known URLs → Tavily `tavily_extract` (Exa `web_fetch_exa` is the fallback)
- Multi-source synthesis → Tavily `tavily_research` (Exa has no equivalent)

**Cap result counts at discovery**: Tavily `max_results ≤ 5` (rule hard cap); Exa `numResults ≤ 5`. Larger Exa result sets (~8+) exceed the inline tool-output cap and get persisted to a file with only a top-1 preview — see "Oversized results" below.

**Mix providers in the same wave** — route each query to the best tool per the routing above — we'll deep-fetch selectively in Step 8.

### Query construction guidelines

- One query per research question minimum. Complex questions may need 2-3 queries targeting different source types (arXiv, institutional blogs, framework docs).
- Include year terms (`2025 2026`) for fast-moving topics. Omit for established theory.
- For each question where Phase A provided a partial answer, generate at least one query that specifically tests or updates the existing knowledge.
- If the user provided a focus area, ALL queries must incorporate those terms naturally (not just appended).
- Include at least 1 `tavily_research(pro)` call for broad synthesis when the topic warrants landscape-level understanding.

### Example query types (adapt to actual research questions)

| Source type | Query pattern | When |
|---|---|---|
| arXiv preprints | `arXiv [topic] [specific technique] 2025 2026` | Always — academic preprints are the primary source |
| Institutional blogs | `Anthropic OR "Google DeepMind" OR "Meta FAIR" [topic] research 2025 2026` | Always — lab blogs often precede papers |
| Conference proceedings | `NeurIPS OR ICML OR ICLR OR ACL [topic] paper 2025 2026` | When questions involve established research areas (ACL for NLP/language model work) |
| Framework evolution | `[framework name] architecture patterns [specific pattern] 2025 2026` | When questions involve implementation |
| Benchmarks/evaluation | `[benchmark name] [task type] evaluation results 2025 2026` | When questions involve measured performance |
| Broad synthesis | `tavily_research(pro)` with focused prompt | For "state of the art in X" questions |

### Score-based pre-filtering

> For Tavily tool selection, wave execution, and graceful degradation patterns shared across all research skills, see `${CLAUDE_PLUGIN_ROOT}/skills/deep-dive/references/research-methodology.md`.

After searches return, examine the `score` field on each result:
- **score > 0.6**: Proceed to evaluation. (Lower threshold than gather-intel because academic content scores differently.)
- **score 0.4-0.6**: Include if the title or snippet contains specific research terms (paper title, author names, framework names, conference names).
- **score < 0.4**: Skip unless the title is clearly a seminal paper or major framework release.

### Oversized results (persisted tool output)

When a search result exceeds the inline output cap, the harness saves it to a JSON file and shows only a ~2KB preview. **Grading from the top-1 preview violates the K≥3 read discipline.** Before evaluating, extract the full candidate list from the persisted file with a small script, e.g.:

```bash
python3 -c "
import json,re,sys
data=json.load(open(sys.argv[1]))
text=data[0]['text'] if isinstance(data,list) else str(data)
for m in re.finditer(r'Title: (.+?)\nURL: (.+?)\n', text):
    print('-', m.group(1)[:90], '|', m.group(2)[:100])
" <persisted-file.json>
```

Then deep-fetch the specific candidates worth grading. Prevention: keep discovery result counts ≤5 (above).

### Retry on empty results

If any search returns zero or very few results (<3), immediately reformulate:
- Drop year restrictions
- Try alternative terminology (e.g., "function calling" vs "tool use", "agentic" vs "agent-based")
- Try author names if known (e.g., "Shunyu Yao" for ReAct/Tree of Thoughts)
- Exhaust 2-3 reformulations per source before marking "no results"

## Step 5: Wave 2 — Targeted Deep Dives

After Wave 1 results are evaluated, fire a second wave targeting specific high-signal sources discovered in Wave 1. This wave uses `tavily_research` for broad synthesis and `tavily_search` for targeted follow-ups.

| # | Tool | Query | Target |
|---|------|-------|--------|
| 1 | **tavily_research** (model: "pro") | Synthesize the research landscape for the highest-priority research questions from Step 3b. Focus on practical implementations and Claude/Anthropic ecosystem. 2025-2026. | Broad research synthesis |
| 2 | **tavily_research** (model: "pro") | Synthesize the state of the art for the second-highest-priority cluster of research questions. 2025-2026. | Targeted research synthesis |
| 3 | **tavily_search** (advanced) | Search for specific papers, authors, or frameworks surfaced in Wave 1 that need deeper investigation | Follow-up on high-signal Wave 1 discoveries |
| 4 | **tavily_search** (advanced) | Search for rebuttals, follow-up work, or implementations of key Wave 1 papers | Verify research findings aren't isolated |

**VERIFICATION REQUIRED for tavily_research:** For each factual claim in a `tavily_research` synthesis, identify the underlying primary source URL (paper, blog post, documentation page). If a claim cannot be traced to a specific URL, downgrade it to LOW confidence or re-search for the primary source using `tavily_search`. Claims sourced solely from `tavily_research` without traceable URLs are capped at MEDIUM priority regardless of other scoring dimensions.

### Known high-value sources

| # | Tool | URL/Query | Target |
|---|------|-----------|--------|
| 5 | **tavily_extract** | `https://www.anthropic.com/research` with `query` focused on the research questions from Step 3b | Anthropic research page — new papers and posts |
| 6 | **tavily_search** | `site:research.google.com OR "Google DeepMind" blog [focus area] agent 2025 2026` | Google DeepMind / Google Research — mandatory probe |
| 7 | **tavily_search** | `"Meta FAIR" OR "Meta AI" research [focus area] agent 2025 2026` | Meta FAIR — mandatory probe |
| 8 | **tavily_map** | `https://docs.anthropic.com/` | Anthropic docs — structural changes, new sections |
| 9 | **tavily_extract** | `https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md` with `query: "new features research agent tool"` | Changelog — new features with research backing |
| 10 | **tavily_search** | `YouTube "Claude Code" OR "AI agent" OR "MCP" conference talk presentation 2025 2026` | Conference talks — evaluate claims cautiously (no transcript extraction available; note talk title + speaker + venue, search for companion papers or blog posts before citing) |

### Adaptive follow-up

Based on Wave 1 + Wave 2 results, identify up to 5 "research threads" — clusters of related findings that form a coherent narrative (e.g., "reflection loops improve agent performance" appearing in 3+ papers). For each thread:

1. Search for the seminal paper (earliest/most-cited work in the cluster)
2. Search for the latest follow-up work
3. Search for practical implementations or framework integrations
4. Note the thread for prominent placement in the Phase C report

### Convergence check and iterative deepening

After Wave 2, assess coverage against the research questions from Step 3b:

1. **For each research question**, classify current answer confidence:
   - **Answered (High)**: Multiple corroborating papers/sources. Done for this question.
   - **Answered (Medium)**: Some evidence, limited sources. Search for corroboration.
   - **Partially answered**: Aspects addressed but gaps remain. Search for specific gaps.
   - **Unanswered**: No relevant results. Reformulate queries.

2. **Calculate new-rate**: Of all results in this wave, what percentage were genuinely new findings vs redundant/confirming? `new_rate = new_findings / total_results`

3. **Continue** (fire Wave 3+) if:
   - `new_rate > 30%`, OR
   - Any research question is still Unanswered or Partially answered and reformulations remain untried

4. **Stop** if:
   - `new_rate < 30%` for two consecutive waves (sustained diminishing returns), OR
   - All research questions are Answered (High or Medium), OR
   - Reformulated queries for unanswered questions also return no results

5. When stopping with unanswered questions, note them honestly in the report rather than stretching weak evidence.

**Minimum**: Always complete at least Wave 1 + Wave 2. Convergence checking starts after Wave 2.

## Step 8: Deep Fetch (Selective)

For HIGH-priority findings that need more detail than search snippets provide:

### Default: `tavily_extract` with `extract_depth: "advanced"`
- arXiv abstract pages — get full abstract, authors, date
- Research blog posts — get methodology details and findings
- Framework documentation pages — get architecture diagrams and API patterns
- Conference proceedings pages — get paper listings and talk summaries

### For academic papers specifically
- Extract from the arXiv HTML page (`https://arxiv.org/html/XXXX.XXXXX`) — **NOT** the `/abs/` page: `tavily_extract` on `/abs/` returns page chrome (nav, funders, arXivLabs) with the abstract missing (measured 2026-08-22). If no HTML version exists, use Exa `web_fetch_exa` on the `/abs/` URL instead.
- If the paper has a project page or GitHub repo, extract that too
- ALWAYS provide `query` parameter focused on the specific insight relevant to this architecture

### Multi-page: `tavily_map` then `tavily_crawl`
- Framework documentation sites (e.g., LangGraph docs, CrewAI docs)
- Map first (`max_depth=1`), then crawl relevant sections with `instructions` parameter
- Focus on architecture patterns, not API reference minutiae

### Broad synthesis: `tavily_research` with `model: "pro"`
- When a research thread (from Step 5) spans many sources and needs holistic understanding
- When comparing competing approaches from different papers/frameworks

**Fallback chain**: tavily_extract with `extract_depth: "advanced"` (default) -> tavily_search with `include_raw_content: true` (last resort).

### Graceful degradation

If any individual source or tool fails during Phase B:

| Failure | Action |
|---------|--------|
| Tavily search returns 0 results | Reformulate query (2-3 attempts), then mark source as "no results" and continue |
| Tavily extract times out or returns empty | Try tavily_search with `include_raw_content: true` for that URL, or use search snippets already collected |
| Firecrawl search returns bodyless 400 | Drop the `categories` filter and retry once; if it still fails, reroute the query to Tavily/Exa (measured 2026-08-22: `categories: ["github","developer"]` combo 400'd while `["research"]` succeeded) |
| tavily_extract on an arXiv `/abs/` page returns chrome without the abstract | Re-fetch `arxiv.org/html/<id>`, or Exa `web_fetch_exa` on the `/abs/` URL |
| Anthropic research page blocked/changed | Use tavily_search for `site:anthropic.com/research` instead |
| arXiv rate-limited or slow | Extract from cached Google Scholar or Semantic Scholar results |
| CHANGELOG fetch fails | Skip version currency check for that finding, tag as `[version unknown]` |

**Never fail the entire skill because one source is unavailable.** Log the failure, skip that source, and continue with the remaining results.
