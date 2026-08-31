# Step 10: Deep Fetch

For all HIGH-priority findings and any finding that needs more detail than search snippets provide, deep-fetch the source content.

**IMPORTANT**: On all `tavily_extract` calls, ALWAYS provide a `query` parameter to focus extraction on relevant content.

## Default: `tavily_extract` with `extract_depth: "advanced"`
- GitHub repo root URLs - READMEs, structured content
- JS-rendered SPAs and aggregator sites
- Reddit and HN threads (full thread content, not just OP)
- Blog posts from any domain
- Any "awesome-*" or "toolkit" repo
- Community forums and discussion threads
- Small static pages (`code.claude.com`, GitHub specific files, CHANGELOG.md)

## Multi-page: `tavily_map` -> `tavily_crawl`
- Documentation sites with multiple pages to explore
- Map first to understand structure (`max_depth=1`), then crawl specific `select_paths`
- Use `instructions` parameter to focus the crawler

## Broad synthesis: `tavily_research` with `model: "pro"`
- When a community thread (from Step 6) spans many sources and needs holistic understanding
- When comparing competing approaches or recommendations from different practitioners
- For broad "state of the community" synthesis

**Fallback chain**: tavily_extract with `extract_depth: "advanced"` (default) -> tavily_search with `include_raw_content: true` (last resort).

## Graceful degradation

If any individual source or tool fails during Phase B:

| Failure | Action |
|---------|--------|
| Tavily search returns 0 results | Reformulate query (2-3 attempts per CLAUDE.md Adaptive Execution), then mark "no results" and continue |
| Tavily extract times out or returns empty | Try tavily_search with `include_raw_content: true` for that URL, or use search snippets already collected |
| CHANGELOG fetch fails | Skip version currency check for that finding, tag as `[version unknown]` |
| GitHub awesome-* repo unavailable | Use tavily_search for the repo name instead of direct fetch |

**Never fail the entire skill because one source is unavailable.** Log the failure, skip that source, and continue with remaining results.
