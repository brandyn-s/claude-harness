# Gather Skills Coordination

How the five gather skills interrelate, when to run each, and what context they pass between each other.

## The Five Gather Skills

| Skill | Domain | Sources | Execution Mode | Approval |
|-------|--------|---------|---------------|----------|
| `/gather-intel` | External community patterns | Reddit, HN, GitHub, blogs | Main thread | User approval required |
| a separate skill (not included in this export) | Internal team learnings | Slack, Linear, Confluence | Main thread | User approval required |
| `/gather-repos` | Community config repos | GitHub structural search | Main thread + Explore subagents | User approval for eval |
| `/gather-claude` | Anthropic upstream changes | GitHub issues, CHANGELOG, docs | Main thread | User approval required |
| `/gather-research` | Academic research frontier | arXiv, conferences, research blogs | Main thread | User approval required |

## Recommended Run Order

For a comprehensive intelligence refresh, run in this order:

1. **`/gather-claude`** — first, because upstream changes may obsolete community workarounds
2. **`/gather-research`** — second, because research findings inform what to look for in community
3. **`/gather-intel`** — third, consumes reports from 1 and 2 for cross-reference
4. **a separate skill (not included in this export)** — any time, independent of the others
5. **`/gather-repos`** — any time, independent of the others

Skills 1-3 form a pipeline where each skill's output enriches the next. Skills 4-5 are independent and can run in any order.

## Context Passing

### gather-claude → gather-intel
- gather-intel's Phase A checks for stale workarounds — gather-claude's REMOVE_WORKAROUND findings directly inform this
- If gather-claude ran first, gather-intel skips re-reading baseline files already in context

### gather-research → gather-intel
- gather-intel cross-references community claims against research findings
- If gather-research ran first, gather-intel notes "research-first run" in metadata
- Community findings that align with research get `[research-validated]` tag

### gather-intel → gather-research
- gather-research cross-references research claims against community practice
- If gather-intel ran first, gather-research notes "community-first run" in metadata

### No cross-dependency
- a separate skill (not included in this export) and `/gather-repos` are fully independent
- They don't consume reports from other gather skills
- They can run in any session without prerequisites

## Shared Patterns

All five gather skills share these design patterns:

1. **Backward-looking audit before forward-looking search** — check what's already known before searching for new
2. **Dedup against existing knowledge** — every skill loads its baseline and deduplicates findings
3. **Quality classification** — each skill has domain-appropriate quality criteria (source authority for external, incident-verified for internal, research rigor for academic)
4. **Graceful degradation** — individual source failures don't kill the skill
5. **Tool routing** — follow `rules/web-search-preference.md` (source path: `<claude-config-repo>/rules/web-search-preference.md`; deployed copy at `~/.claude/rules/web-search-preference.md` when symlinked) for Tavily vs Exa selection (web-searching skills only)

## Tool Routing (Tavily vs Exa)

Skills that search the web (gather-intel, gather-claude, gather-research, gather-repos) should route queries to the best tool per `rules/web-search-preference.md` (source path at `<claude-config-repo>/rules/web-search-preference.md`):

- **Code/GitHub queries** → Exa `web_search_exa` (include language + identifiers)
- **Date-filtered searches** → Exa `web_search_exa` with `freshness` param
- **Domain-filtered searches** → Tavily `tavily_search` with `include_domains` (Exa's domain-filter tool was retired; gather-intel doesn't load Firecrawl)
- **Reddit/HN/forums** → Tavily `tavily_search`
- **URL content extraction** → Tavily `tavily_extract`
- **Site mapping** → Tavily `tavily_map`
- **Multi-source synthesis** → Tavily `tavily_research`

gather-internal-intel uses only internal MCP sources (Slack, Linear, Confluence) — web search tools don't apply.

## Execution Mode

All five gather skills now run in the **main thread**:
- Can prompt user for approval before writing
- Can dispatch Agent tool workers (gather-repos uses Explore subagents)
- Run interactively with user decision points
- Full 1M context window available (fork mode was limited to 200K per #40929)

**Why main thread for all**: The 200K context limit on forked skills (#40929) constrained gather-research's iterative deepening and gather-claude's deep-fetch phases. Moving to main thread provides full context and enables interactive approval at finding-level granularity.
