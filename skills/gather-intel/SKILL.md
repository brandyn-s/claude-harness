---

name: gather-intel
description: "Discover new Claude Code community patterns from Reddit, HN, GitHub, X, and blogs."
when_to_use: Use when wanting to update community intelligence or discover new Claude Code patterns from external sources. Searches Reddit, Hacker News, GitHub, X/Twitter, and blogs, then compares findings against this architecture to identify improvements. Do NOT use for internal team intelligence from Slack, Linear, or Confluence (use gather-internal-intel instead), or for capturing patterns from the current session (use /distill or /capture instead).
argument-hint: "[focus area, e.g. 'hooks', 'MCP patterns', 'Windows tips']"
effort: medium
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires Tavily MCP and Exa MCP for multi-source community intelligence gathering.
  # Firecrawl is intentionally omitted: this skill makes no firecrawl_* calls in its body or references.
  requires:
    - mcp: tavily
    - mcp: exa
allowed-tools: Agent Bash Read mcp__exa__web_search_exa mcp__memory-search__memory_search mcp__tavily__tavily_extract mcp__tavily__tavily_research mcp__tavily__tavily_search
# 2026-09-04: hidden from model routing. Paired A/Bs on Opus 4.8 (2026-05-31) and Fable 5.1
# (2026-09-03) measured no lift over a plain model with web search, and the harnesses never ran
# the full skill; see docs/research-skills-root-cause.md. Explicit /<name> invocation still works.
disable-model-invocation: true
---

## gather-intel

# Gather External Intelligence

Search external sources for Claude Code community knowledge. Audit existing intel for staleness and effectiveness. Compare new findings against the current architecture to identify gaps and improvements.

Three phases: **Audit existing** (backward-looking) -> **Gather new** (forward-looking) -> **Synthesize & present** (combined report with user approval).

> **Operational note**: Phase A (audit existing) typically yields higher ROI per item than Phase B (search new). The backward-looking audit finds immediately actionable items (specific file + line to change), while new web findings often need further investigation before acting. Don't skip Phase A to rush to Phase B.

> **Dual-skill coordination**: If `gather-research` ran earlier in this session — a tool result wrote `claude-code-research-intelligence.md`, an assistant turn produced its metadata header (the `**Date**: YYYY-MM-DD` / `**Focus area**:` / `**Waves completed**:` block from `skills/gather-research/references/report-format.md`), or the user said so — skip re-reading baseline files 1, 4, 5, 6, 7, 8, consume its findings directly, search specifically for community evidence that validates or contradicts them, and note "research-first run" in the report metadata. Otherwise treat this as a standalone run and read the full baseline. Full protocol: `references/gather-coordination.md`.

> **Focus area**: If the user provided an argument (e.g., `/gather-intel hooks`), narrow ALL searches in Phase B to that focus area. Append the focus terms to every query. In Phase C, evaluate findings specifically against the focus area's role in the architecture.

> **Repos**: For community repo discovery and assessment, use `/gather-repos`
> (separate skill). If the user says `/gather-intel repos`, redirect to
> `/gather-repos`.

---

## Scope guard

Before proceeding, verify the request is in-scope. If the user is asking about:
- **Internal team messages** (Slack threads, Linear issues, Confluence pages) → redirect to `/gather-internal-intel`
- **Patterns from the current session** → redirect to `/distill` or `/capture`
- **Specific repo evaluation** (not discovery of patterns) → redirect to `/evaluate-repos`
- **Community repo discovery** (find repos, not patterns/tips) → redirect to `/gather-repos`

If out-of-scope, tell the user which skill to use instead, then stop.

---

# Phase A: Audit Existing Intel (backward-looking)

## Step 0: Review Previous Run Actions

Before auditing the baseline, check what happened since the last run:

1. **Read the community report metadata** - extract the last-updated date
2. **For each approved action item from the previous run**: Check if it was implemented by scanning the referenced files for changes since the last-updated date (use `git log --since="<date>" -- <file>` where applicable)
3. **For each queued experiment**: Check the Experiment Backlog - was it run? Were results recorded? If an experiment has been queued for 2+ runs without execution, flag it for archive or immediate execution.
4. **For each "Monitor" item**: Search for new evidence (a single targeted `tavily_search` per monitor item, `search_depth: "basic"`)

Report a brief summary: "Since last run (YYYY-MM-DD): N action items implemented, N experiments still pending, N monitor items with new evidence." This grounds Phase A in what actually changed rather than re-auditing from scratch.

If this is the first run (no existing report), skip Step 0.

## Step 1: Load Full Baseline

**Check current version first**: Run `claude --version` via Bash to confirm the installed Claude Code version. All findings will be filtered against this version.

Read these files to establish what is already known. **For focused runs** (user provided an argument like `/gather-intel hooks`), prioritize files 1-5 and skip 6-8 unless the focus area overlaps with agents or hooks.

1. `ARCHITECTURE.md` — read the canonical source at `<claude-config-repo>/ARCHITECTURE.md` (typically `/home/user/claude-config/ARCHITECTURE.md`). Only fall back to `~/.claude/ARCHITECTURE.md` if a deployment copies it; the deployed path does not resolve by default. Silently reading the deployed path would corrupt the baseline.
2. `$HOME/Documents/knowledge-base/research/claude-code-community-intelligence*.md` - existing community report. **Find the most recent file matching this glob pattern** (the suffix may be empty for the canonical first-run file, or a date like `-2026-02` / version for snapshots). Read first 50 lines for ToC, then jump to Sources section at the end for URL dedup.
3. `$HOME/Documents/knowledge-base/research/claude-code-research-intelligence.md` - existing research report (if it exists). Cross-reference: research findings may validate or contradict community patterns. Extract key research-backed recommendations to compare against community claims in Phase B.
4. `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/MEMORY.md` - current memory
5. `~/.claude/projects/$CLAUDE_PROJECT_ID/CLAUDE.md` - behavioral rules and constraints

If `$CLAUDE_PROJECT_ID` is unset (headless / worktree sessions), resolve it
via the recipe in `_shared/project-dir.md` before the reads in items 4–5.
Skipping this fallback silently reads empty paths and corrupts the baseline.
6. `~/.claude/agent-memory/topics/security.md` - security domain gotchas and patterns
7. `~/.claude/agent-memory/topics/infrastructure.md` - infrastructure domain gotchas and patterns. **Precondition**: only a subset of source `topics/*.md` files are symlinked into the deployed `~/.claude/agent-memory/topics/` directory. If this file does not resolve, fall back to the source path at `<claude-config-repo>/agent-memory/topics/infrastructure.md` (typically `/home/user/claude-config/agent-memory/topics/infrastructure.md`) before declaring the baseline empty.

**Semantic memory search**: Run `mcp__memory-search__memory_search(query="<focus area or 'Claude Code community patterns'>", limit=10)` in parallel with the file reads above. This surfaces relevant entries from agent memory and topic files that may not be in the files listed above (e.g., `[tool-gotcha]` and `[operational]` entries in `~/.claude/agent-memory/`).

Extract from the community report:
- **ToC topics** (section headers) - for topic-level dedup
- **Sources URLs** (from the Sources section at the bottom) - for exact URL dedup

Extract from the research report (if it exists):
- **Research-backed recommendations** - community claims that align with or contradict research findings get noted for cross-reference in Phase C

Build a list of **all recommendations currently in effect** - from community report, research report, ARCHITECTURE.md, CLAUDE.md, agent prompts, and hooks. Each recommendation gets audited in Steps 2-4.

## Step 2: Version Currency Audit

For each recommendation in the community report and ARCHITECTURE.md:

1. Does it reference a specific Claude Code version (v2.1.X) or feature release?
2. Is the current installed version (from Step 1) newer than the referenced version?
3. Does the CHANGELOG (`tavily_extract` on `https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md` with `query: "features fixes changes"`) show the referenced behavior was fixed, changed, or graduated?

Classify each:

| Status | Meaning | Action |
|--------|---------|--------|
| **CURRENT** | Still applies - behavior hasn't changed, or no version reference | No action needed |
| **STALE** | Fix landed in a version we have, or feature graduated from experimental | Verify the fix, then recommend trimming from community report |
| **UNKNOWN** | Can't determine from CHANGELOG - version-specific but no clear resolution | Flag for manual testing |

Output a table of all version-tagged recommendations with their status.

## Step 3: Effectiveness Audit

For each recommendation that has been **implemented** in this architecture (present in CLAUDE.md, ARCHITECTURE.md, hooks, or agent prompts):

| Status | Criteria | Evidence to look for |
|--------|----------|---------------------|
| **VALIDATED** | Implemented + evidence it helps | Reduced error counts in debug logs; successful agent memory entries referencing the pattern; PostToolUseFailure hook firing less often for that error type |
| **UNVALIDATED** | Implemented + no evidence either way | Rule exists in CLAUDE.md/hooks but we've never measured if it's working |
| **OVERHEAD** | Implemented + evidence it's not helping or causing friction | e.g., PreToolUse hook fires on every MCP call but the gotchas it checks for haven't occurred recently; rule adds latency without measurable benefit |
| **GAP** | Recommended by community but NOT implemented in this architecture | Community says to do X, our architecture doesn't |

For each recommendation, note:
- Where it's implemented (file + section)
- What evidence exists (or doesn't) for its effectiveness
- Suggested action (keep as-is, create a test plan, relax, add missing)

## Step 4: Self-Imposed Constraint Audit

Scan CLAUDE.md, ARCHITECTURE.md, agent .md files, and hooks for constraints that may be:

| Classification | What to look for | Example |
|----------------|-----------------|---------|
| **KEEP** | Justified, working, evidence of benefit | "Write-to-file-then-execute" rule - prevents real quoting bugs on Windows |
| **TEST** | Unvalidated - added defensively but never tested | "Always use limit=5 first" - has this actually prevented errors, or does it just add a round-trip? |
| **RELAX** | More conservative than community consensus without documented rationale | 70% autocompact vs community's 40% cliff - is our choice deliberate or accidental? |
| **REMOVE** | Stale or redundant - duplicates what hooks enforce, or from an older CC version | Ripgrep workaround - v2.1.23 fixed this; advisory rule that duplicates a PreToolUse hook check |
| **RECONCILE** | Contradicted between files | CLAUDE.md says X, ARCHITECTURE.md says Y; agent prompt conflicts with CLAUDE.md |

For each constraint found, output:
- **Constraint**: What the rule says
- **Location**: File + line/section
- **Classification**: KEEP / TEST / RELAX / REMOVE / RECONCILE
- **Reasoning**: Why this classification
- **Recommended action**: Specific change, test plan, or "no action"

---

# Phase B: Gather New Intel (forward-looking)

## Step 4b: Decompose into Community Questions

Before searching, parse the focus area (or default scope: "Claude Code community best practices and architecture patterns") into **5-8 specific community questions**. Each question must be answerable from external practitioner sources and map to at least one architecture component.

For each question:
1. Write it as a specific, searchable question (not a topic label)
2. Tag the architecture component it maps to (Agent system, Memory & persistence, Tool integration, Context management, Prompt engineering, Hooks & routing, Security & compliance, Orchestration)
3. Note any existing knowledge from Phase A that partially answers it

Present the community questions to the user: "I've decomposed your topic into these community questions: [list]. Anything to add or adjust before I start searching?"

If the user modifies questions, regenerate the query plan below.

## Step 5: Parallel Source Search - Wave 1 (Discovery)

### Dynamic query generation

**Generate queries from the community questions in Step 4b.** No hardcoded queries - every search targets a specific community question. Fire **8-12 search calls in a single message** (all independent). Set `include_raw_content: false` at discovery stage - we'll deep-fetch selectively in Step 10.

**Tool routing**: Follow `rules/web-search-preference.md` (source: `<claude-config-repo>/rules/web-search-preference.md`; deployed at `~/.claude/rules/web-search-preference.md`) for Tavily vs Exa selection. Do not default to Tavily for all queries. Key routing:
- Code/GitHub queries → Exa `web_search_exa` (include the language + repo/"github" terms in query; finds repos, issues, implementations)
- Recent articles → Exa `web_search_exa` with `freshness: "month"`
- Category/vertical discovery → Exa `web_search_exa` with an in-query `category:people`/`category:company` (the advanced category + domain-filter params were retired; for domain/operator targeting use Tavily, since this skill doesn't load Firecrawl)
- Reddit/HN/forums → Tavily `tavily_search` with `topic: "news"`, `time_range: "month"`, `chunks_per_source: 3`
- Broad web discovery → Tavily `tavily_search` with `search_depth: "advanced"`, `chunks_per_source: 3`
- X/Twitter discussions → run `python3 ~/.claude/bin/x-monitor.py --mode event --query "..."` (xAI Agent Tools API `x_search`). The old `mcp__x-search__*` MCP tools were retired and are not on macOS. Optional — skip if XAI_API_KEY isn't set.
- Deep fetch of known URLs → Tavily `tavily_extract` (Exa has no equivalent)
- Multi-source synthesis → Tavily `tavily_research` (Exa has no equivalent)

> **Why not Agent tool for Wave 1?** The parallel MCP calls in a single message already achieve concurrency without agents. Agent dispatch is reserved for Wave 2 deep-fetch where independent sub-tasks benefit from parallel execution. Note: non-fork agents CAN access Tavily and Exa through the parent session's MCP connections (unlike `context: fork` agents which cannot).

**NOTE**: Do NOT use `site:reddit.com/r/...` queries - search engines don't index Reddit well with site-restricted queries. Use broad queries like `reddit ClaudeCode ...` instead.

**Query construction guidelines:**
- One query per community question minimum. Broad questions may need 2-3 queries targeting different platforms (Reddit, HN, GitHub, blogs).
- Include year terms (`2025 2026`) for fast-moving topics. Omit for established patterns.
- For each question where Phase A provided a partial answer, generate at least one query that specifically tests or updates the existing knowledge.
- If the user provided a focus area, ALL queries must incorporate those terms naturally (not just appended).
- Vary platform targeting across queries: ensure at least 2 target Reddit, 1 targets HN, 1 targets GitHub, and 1 targets blogs/tutorials.

**Example query types** (adapt to actual community questions):

| Source type | Query pattern | When |
|---|---|---|
| Reddit community | `reddit ClaudeCode [topic] [specific pattern] 2026` | Always - Reddit is the primary community source |
| Reddit architecture | `reddit Claude Code [architecture component] tips workflow 2026` | When questions involve architecture patterns |
| Hacker News | `Hacker News Claude Code [topic] practitioner 2026` | Always - HN has practitioner discussions |
| Blogs/tutorials | `Claude Code [topic] blog tutorial deep dive 2026` | When questions involve workflows or techniques |
| GitHub repos | `awesome-claude-code OR claude-code-toolkit github [topic] 2026` | When questions involve tooling or extensions |
| MCP patterns | `Claude Code MCP [specific pattern] production lessons 2026` | When questions involve MCP integration |
| Cross-platform | `Claude Code [topic] best practices advanced 2026` | For broad discovery across all platforms |
| Official docs | `site:docs.anthropic.com OR site:code.claude.com [topic] 2026` | When questions involve core platform capabilities |
| X/Twitter | `bin/x-monitor.py --mode event --query "Claude Code [topic]"` (xAI Agent Tools API `x_search`; old `mcp__x-search__*` retired) | Optional - catches real-time practitioner discussion and Anthropic announcements not on Reddit/HN |

### Score-based pre-filtering

> For Tavily tool selection, wave execution, and graceful degradation patterns shared across all research skills, see `~/.claude/skills/deep-dive/references/research-methodology.md`.

After Tavily searches return, examine the `score` field on each result:
- **score > 0.6**: Proceed to evaluation.
- **score 0.4-0.6**: Include if the title or snippet contains specific practitioner terms (tool names, config patterns, architecture terms, known community author names).
- **score < 0.4**: Skip unless the title is clearly relevant (e.g., a known high-value resource).

### Retry on empty results

If any search returns zero or very few results (<3), immediately reformulate:
- Drop year restrictions
- Try alternative terminology (e.g., "Claude Code" vs "ClaudeCode", "skills" vs "custom commands")
- Try platform-specific terms (e.g., "Windows" vs "Git Bash", "MCP" vs "tool server")
- Exhaust 2-3 reformulations per source before marking "no results"

## Step 6: Parallel Source Search - Wave 2 (Targeted Deep Dives)

After Wave 1 results are evaluated, fire a second wave targeting specific high-signal sources discovered in Wave 1. This wave uses `tavily_research` for broad synthesis and `tavily_search` for targeted follow-ups.

### Agent dispatch for deep-fetch (Wave 2)

If Wave 1 produced 5+ high-signal URLs needing deep extraction, dispatch up to 3 agents in parallel for deep-fetch. Each agent gets a subset of URLs and runs tavily_extract independently.

**Dispatch pattern:**
1. Divide high-signal URLs into 3 groups (balanced by count)
2. For each group, dispatch an Agent with:
   - `subagent_type: "general-purpose"`
   - Prompt: "Extract content from the following URLs using tavily_extract with query='Claude Code [focus area]'. For each URL, return the title, key findings (2-3 bullet points), and any code examples. URLs: [list]"
3. Collect results from all 3 agents
4. Merge into the unified findings list for Step 7 evaluation

**When NOT to dispatch agents:**
- Fewer than 5 high-signal URLs (sequential extraction is fast enough)
- All URLs are from the same domain (no parallelism benefit)
- Tavily MCP was unavailable earlier in the session (agents will also fail)

**Agent result limit:** Agent results may be truncated by the runtime (observed around ~8,000 characters; treat that as a working budget, not a verified constant). Instruct agents to return concise summaries (title + 2-3 bullet points per URL), not raw extracted content — ~1,600 chars per URL for 5 URLs. If Tavily auth fails for agents, fall back to sequential extraction in the main thread.

| # | Tool | Query | Target |
|---|------|-------|--------|
| 1 | **tavily_research** (model: "pro") | `Claude Code community best practices: hooks, skills, agent architecture, MCP servers, context management, multi-agent workflows. Focus on battle-tested patterns and Windows deployment. 2025-2026.` | Broad community practice synthesis |
| 2 | **tavily_research** (model: "pro") | `State of the art in Claude Code configuration: CLAUDE.md patterns, project memory, agent delegation, skill design, hook-based routing. Practical lessons from production use. 2025-2026.` | Configuration and architecture synthesis |
| 3 | **tavily_search** (advanced) | Search for specific authors, repos, or patterns surfaced in Wave 1 that need deeper investigation | Follow-up on high-signal Wave 1 discoveries |
| 4 | **tavily_search** (advanced) | Search for critiques, counter-patterns, or alternative approaches to key Wave 1 findings | Verify findings aren't one-sided |

Additionally, check these known high-value sources:

| # | Tool | URL/Query | Target |
|---|------|-----------|--------|
| 5 | **tavily_extract** | `https://www.anthropic.com/research` with `query: "Claude Code MCP agent architecture"` | Anthropic research page - new Claude/MCP posts |
| 6 | **tavily_map** | `https://docs.anthropic.com/en/docs/claude-code` | Claude Code docs - structural changes, new sections |
| 7 | **tavily_extract** | `https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md` with `query: "new features behavior changes hooks skills agents"` | Changelog - new features and behavior changes |
| 8 | **tavily_search** (advanced) | `YouTube "Claude Code" OR "MCP server" tutorial walkthrough 2025 2026` | Video tutorials and conference talks |

### Adaptive follow-up - Community Threads

Based on Wave 1 + Wave 2 results, identify up to 5 "community threads" - clusters of related findings that form a coherent narrative (e.g., "hook-based routing is replacing keyword delegation" appearing in 3+ independent sources). For each thread:

1. Search for the earliest/most-cited source in the cluster
2. Search for the latest follow-up or evolution of the pattern
3. Search for real-world implementations or GitHub repos demonstrating it
4. Note the thread for prominent placement in the Phase C report

### Convergence check (after Wave 2)

After Wave 2 completes, assess whether further searching is warranted:

**Continue to Wave 3** if:
- Any high-signal community thread has fewer than 3 independent sources (needs more corroboration)
- Adversarial searches (Step 7b) surfaced contradictions that need deeper investigation
- More than 30% of Wave 2 results were genuinely new (not confirming Wave 1)

**Stop** if:
- Wave 2 returned >=70% redundant/confirming results (diminishing returns)
- All focus areas have at least 2 independent high-authority sources
- Adversarial searches found no significant counter-evidence

Wave 3 (if triggered) should be 3-5 targeted queries, not another full wave. Focus on gaps and contradictions only.

## Step 7: Evaluate and Rank

Score **every** finding from Steps 5-6 (and Step 7b adversarial results) using the Source Evaluation Framework (see below). This is the core quality filter - do not skip it.

## Step 7b: Adversarial Search (executes BEFORE Step 8's filter)

After completing Steps 5-6, before Step 8's filter, generate one targeted search for each HIGH-priority provisional finding seeking counterarguments, failures, or limitations. This prevents one-sided assessments. **Execution order: Steps 5-6 (identify findings) → assign provisional priorities (Step 7) → Step 7b adversarial search → Step 8 filter & classify.** The document order ("Step 7" then "Step 7b") reflects deliverable layout, not execution sequence, per the invariant in Success Criteria ("Adversarial search fires for every HIGH-priority finding before filtering"). Run the adversarial pass, then feed both the original findings and the adversarial results into Step 8's filter.

| Finding type | Adversarial query pattern |
|---|---|
| "Pattern X is great" | `"pattern X" problems OR limitations OR pitfalls` |
| "Tool Y solves Z" | `"tool Y" criticism OR alternatives OR vs` |
| Community consensus pattern | `[pattern] failure OR "doesn't work" OR deprecated` |
| Specific configuration recommendation | `[config] issues OR conflicts OR regression` |

Fire adversarial queries as part of Wave 2 or as a targeted Wave 3 burst (all in a single parallel message). Use `tavily_search` with `search_depth: "advanced"`, `max_results: 5`, `chunks_per_source: 3`.

**Handling adversarial results:**
- If counter-evidence is found: tag the original finding as `CONTESTED` and present both sides in the report. Never suppress counter-evidence.
- If no counter-evidence is found after 2 queries: the finding's confidence increases. Note "no counter-evidence found" in the report.
- If counter-evidence comes from a higher-authority source than the original: demote the original finding by one priority level.

## Step 8: Filter and Classify

Only findings scoring **MEDIUM or higher** composite priority advance to dedup and gap analysis.

> **Cost tracking**: After Steps 5-6, tally Tavily credits consumed so far (basic search = 1, advanced search = 2, research = variable, extract = 1 per 5 URLs, map/crawl = 1 per 10 pages). Include the running total in the Phase C report metadata.

**LOW findings**: List in a "Community Radar" section at the bottom of the report - early-stage or tangentially relevant findings worth monitoring but not acting on yet.

**DISCARD findings**: Do not mention at all.

### Version and feasibility check

For each HIGH/MEDIUM finding, assess both version applicability and implementation feasibility:

- **Available now**: Feature exists in our version or earlier. Actionable.
- **Newer version required**: Feature was added after our version. Tag as `[requires vX.Y.Z]` - note it but don't recommend adoption until we upgrade.
- **Experimental/flag-gated**: Requires env var flags (e.g., `CLAUDE_CODE_EXPERIMENTAL_*`). Tag as `[experimental]` - note the flag and any known stability issues.
- **Deprecated/removed**: Feature was in an older version but removed. Tag as `[deprecated]` - skip.
- **Requires experimentation**: Pattern is promising but needs testing to validate in this specific architecture. Tag as `[experiment]`.

Only findings tagged **available now** or **requires experimentation** proceed to the gap analysis. Others go into the report as awareness items with their version tags.

## Step 9: Deduplicate

For each remaining result, check against the baseline from Step 1:

1. **URL match**: Compare result URLs against Sources section URLs - but distinguish **static vs living** sources:
   - **Static** (blog posts, HN discussions, specific commits): URL match = KNOWN, skip.
   - **Living** (GitHub repos, official docs, aggregator sites like awesome-*): URL match = REVISIT. Check if content has changed or expanded since last capture. If so, classify as UPDATE.
2. **Topic match**: Compare result topic against ToC section headers. If the finding covers the same topic with no new information = KNOWN.
3. **Classify each result**:
   - **NEW**: Not in community report at all (new topic or new source)
   - **UPDATE**: Topic exists but result has newer/better information
   - **CONFIRMATION**: Independent source verifying an existing finding (strengthens confidence)
   - **CONTRADICTION**: Challenges or refutes an existing finding (high signal - always include)
   - **KNOWN**: Already captured with no new information - skip

Proceed with NEW, UPDATE, CONFIRMATION, and CONTRADICTION results.

## Step 10: Deep Fetch

For HIGH-priority findings, deep-fetch source content via `tavily_extract`
(default), `tavily_map`+`tavily_crawl` (multi-page docs), or `tavily_research`
(broad synthesis). Full per-tool decision criteria, fallback chain, and the
graceful-degradation table for failed sources live in `references/deep-fetch.md`.
**Never fail the entire skill because one source is unavailable** — log,
skip, continue.

---

# Phase C: Synthesize & Present

## Step 11: Combined Report

Produce a single report with a **metadata header** and **four sections**. Read `references/report-templates.md` for the full templates, finding format, actionability levels, gap verification gate, and examples.

**Four sections:**
1. **Existing Intel Health** — Phase A health table (STALE, UNVALIDATED, OVERHEAD, GAP, RECONCILE subsections)
2. **New Findings** — Phase B findings ranked by composite priority with gap verification gate
3. **Community Threads** — Clusters of 3+ independent sources converging on a pattern
4. **Popularity vs Effectiveness** — Cross-reference popularity with actual effectiveness (VALIDATED/UNVALIDATED/HYPE/HIDDEN GEM/OVERHEAD verdicts)

## Measured Efficacy (live arm)

**Verdict: `trim` — measured 2026-05-31, N=3, `claude-opus-4-8`, n=15 (vs fair baseline):**
the source-authority + adversarial framework is directionally net-positive on every
metric, but every delta is within the N=3 noise floor, so it does not clearly earn its
~5× cost. Full record, the evidence-gated trim candidate, and the condition that flips
this to `keep`: `references/measured-efficacy.md`. Harness + frozen results:
`skills/gather-intel/harness/`; CI gate: `tests/test_gather_intel_efficacy.py`.

## Success Criteria

- Phase A (audit existing) completes before Phase B (search new)
- Semantic memory search runs in parallel with Phase A file reads
- Community questions decomposed and presented to user before any searches fire (Step 4b)
- All search queries generated dynamically from community questions (no hardcoded queries)
- Wave 1: all search calls fire in a single parallel message (Tavily: `search_depth: "advanced"`, `chunks_per_source: 3`; Reddit/HN: add `topic: "news"`, `time_range: "month"`)
- Wave 2: adaptive follow-ups based on Wave 1 results, including tavily_research (pro)
- Adversarial search (Step 7b) fires for every HIGH-priority finding before filtering (not after)
- Convergence check after Wave 2 determines whether Wave 3 is warranted
- Every finding scored on 3 dimensions (authority, evidence, applicability) with bias tags where applicable
- `tavily_research` claims without traceable URLs capped at Theoretical/T4
- Community threads identified when 3+ independent sources converge (triangulation-verified)
- Research cross-references included where the research report contains related findings
- 0 findings written to community report without user approval
- Phase C report (in-session deliverable) includes all 4 sections: Existing Intel Health, New Findings, Community Threads, Popularity vs Effectiveness. Distinct from the on-disk community-intelligence file, which has 10 persistent sections per `references/output-management.md` and `references/run-tracking.md` (TOC, Active Recommendations, Community Threads, Community Radar, Experiment Backlog, Archived, Sources, Active Questions, Rejection Log, Run Metrics).
- Report metadata includes Tavily credits consumed and Phase A/B summary counts

## Examples

**Example 1**: See `references/report-templates.md` for full worked examples of monthly refresh and targeted technique search runs.

**Example 2: Researching community patterns for a specific skill**
User says: "/gather-intel prompt-improvement"
Actions: Searches GitHub, Reddit/r/ClaudeCode, Hacker News, and arxiv for prompt improvement techniques. Evaluates each source for signal quality and relevance. Cross-references against existing skills.
Result: "Found 8 high-signal sources. 3 novel techniques not in our portfolio: instruction hierarchy, chain-of-draft, and context stuffing budget. Recommend evaluating chain-of-draft for integration with /refine."

## Step 12: User Decision Point

Present all four sections; for each, request user approval on per-section
action options (trim/add/create-action/queue-experiment/monitor/skip).
Full per-section option lists, approval prompt template, post-approval
action flow, and the skill-modification quality gate live in
`references/user-decision-point.md`. **NEVER auto-write — wait for explicit
user approval before modifying any files.**

---

# Output File Management

Read `references/output-management.md` for full details on report location, snapshots, first-run setup, subsequent-run procedures, persistent question bank, and metadata header format. Key path: `$HOME/Documents/knowledge-base/research/claude-code-community-intelligence*.md`

---

# Source Evaluation Framework

Score every finding from Phase B using the **Source Evaluation Framework** in `references/source-evaluation-framework.md`. This covers three dimensions: Source Authority (T1-T5), Evidence Strength (Verified/Observed/Theoretical/Anecdotal), and Applicability (Direct/Partial/Tangential/Irrelevant). The composite priority matrix, bias indicators, triangulation rules, and 9 special rules are also defined there.

---

# Popularity vs Effectiveness Assessment

Apply the **Popularity vs Effectiveness** verdicts from `references/popularity-effectiveness.md` in **Section 4** of the report. Five verdict categories: VALIDATED, UNVALIDATED, HYPE, HIDDEN GEM, OVERHEAD.

---

# Evaluation Prompts

Three evals (monthly refresh, focused technique search, cross-reference with
research) live in `references/evals.md`. Load when grading a run with the
`scripts/run-skill-evals.py` eval harness.

# Rejection Log and Run Metrics

See `references/run-tracking.md` — Rejection Log (deprioritizes previously-rejected findings during Step 0) and Run Metrics (timings, query counts, signal-to-noise) both persist in the community report file across runs.
