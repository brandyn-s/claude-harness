---

name: deep-dive
description: "Thorough multi-source research (Tavily + Exa + Firecrawl) synthesized into an evidence-graded report."
when_to_use: Use when thorough research is needed on any subject — security tools, compliance frameworks, vendor comparisons, technology decisions, architecture patterns. Searches web, academic, and local knowledge across Tavily + Exa + Firecrawl with discrepancy flagging, then synthesizes findings into a saved report with evidence-graded claims. Do NOT use for Claude Code community patterns (use gather-intel), AI research frontier (use gather-research), or internal team comms (use gather-internal-intel).
argument-hint: "[topic or question, e.g. 'zero-trust for NixOS', 'Airlock vs Carbon Black for FedRAMP']"
# 2026-09-04: hidden from model routing. Paired A/Bs on Opus 4.8 (2026-05-31) and Fable 5.1
# (2026-09-03) measured no lift over a plain model with web search, and the harnesses never ran
# the full skill; see docs/research-skills-root-cause.md. Explicit /<name> invocation still works.
disable-model-invocation: true
context: fork
effort: max
allowed-tools: ["Agent", "Bash", "Read", "Write", "Glob", "Grep", "mcp__tavily__tavily_search", "mcp__tavily__tavily_extract", "mcp__tavily__tavily_research", "mcp__tavily__tavily_crawl", "mcp__tavily__tavily_map", "mcp__exa__web_search_exa", "mcp__exa__web_fetch_exa", "mcp__firecrawl__firecrawl_search", "mcp__firecrawl__firecrawl_scrape", "mcp__firecrawl__firecrawl_map", "mcp__firecrawl__firecrawl_crawl", "mcp__firecrawl__firecrawl_check_crawl_status", "mcp__firecrawl__firecrawl_extract", "mcp__memory-search__memory_search", "AskUserQuestion"]
metadata:
  author: example-security-engineering
  version: "2.1"
compatibility:
  # Requires Tavily, Exa, and Firecrawl MCP servers for multi-source research with discrepancy flagging. X/Twitter via bin/x-monitor.py (xAI Agent Tools API; the xai MCP X-search tools were retired/not on macOS). arXiv via firecrawl site:arxiv.org or exa web_search_exa (arxiv MCP not on macOS).
  requires:
    - mcp: firecrawl
    - mcp: tavily
    - mcp: exa

---

## deep-dive

# Deep Research

General-purpose research skill. Takes any topic, dynamically generates research questions, searches across web and academic sources while checking local knowledge, then synthesizes findings with honest evidence assessment. Every run saves a report.

**Priority: synthesis quality.** Clear trade-offs, honest uncertainty, and defensible recommendations matter more than source quantity. Cost and speed are not constraints.

> **Output grounding (REQUIRED READ)**: before writing research findings, read `skills/_shared/output-grounding.md` and apply its three-layer contract (confidence + provenance + counterfactual) to every load-bearing claim. That file is NOT ambient — it was relocated out of `rules/` on 2026-08-26 after measuring EXPOSED=0 over 438 transcripts — so it is in context only if you read it. No hook grades the final answer; skill instructions and final-output evaluation are the controls.

---

## Scope guard

Before proceeding, verify the topic is in-scope for this skill. If the user is asking about:
- **Claude Code community patterns** (Reddit tips, HN threads, GitHub config repos) → redirect to `/gather-intel`
- **AI research frontier** (arXiv papers, NeurIPS/ICML proceedings, lab research blogs) → redirect to `/gather-research`
- **Internal team comms** (Slack threads, Linear issues, Confluence pages) → redirect to `/gather-internal-intel`

If out-of-scope, tell the user which skill to use instead, then stop. Do not proceed to Phase 1.

---

## Invocation contract — read this before Phase 1 (qualified on 2.1.226)

This skill is `context: fork`. Claude Code renders invocation arguments into
the skill block before starting the forked context.

**Invocation topic:** `$ARGUMENTS`

If the invocation topic is empty, do not guess from ambient session context.
Say that no topic was provided and ask for one. A guessed topic can burn a
multi-wave pass on a plausible but unrelated question.

## Scale the wave to the parent's context, not to the budget

**"Cost and speed are not constraints" is about SYNTHESIS DEPTH, not fan-out width.** Measured 2026-07-30: a fork that read that line as licence for "a full multi-wave campaign… all three providers in parallel" **stalled with zero results and was killed by the 600 s watchdog**. A bounded main-thread pass — 2 searches, 3 targeted fetches — then produced better-sourced findings than the agent had, faster.

- Fire **one batch at a time** and read it before firing the next. A parallel burst across all providers is the documented stall shape.
- Dispatching from a **large parent context** raises the stall risk (see `rules/agent-delegation.md` — parent context is the constraint, not the prompt). When the parent is deep into a long session, prefer running the wave inline.
- Go **authoritative-source-first**: one domain-filtered search against the primary source (a government or vendor domain) usually beats a broad multi-provider sweep. In the observed run, `cyber.gov.au` and the vendor's own docs answered the question in 2 searches + 3 fetches.

---

# Phase 1: Context Intake and Prior Knowledge Scan

Before any external search, check what the system already knows.

## Step 0: Check for Prior Research

Scan `~/Documents/knowledge-base/research/` for existing reports with overlapping topic keywords. If prior reports exist on the same or related topic, read their Key Findings and Recommendations. In the new report, include a "Changes from Prior Research" section when applicable.

## Step 1: Parse the Topic

From the user's argument (or prompt), extract:
- **Core question**: The single question this research must answer
- **Sub-questions**: 3-7 specific research questions that, if answered, would comprehensively address the core question
- **Constraints**: Any scope limits the user specified (e.g., "for FedRAMP", "on NixOS", "under $N thousand/year")
- **Context**: Any additional context the user provided about why they're asking

For evolving topics, ensure at least one question addresses trajectory: "How has X changed in the last 6-12 months?" or "What is the development velocity of X?"

Log the research questions to the output, then proceed immediately to searching. Present the research questions to the user for confirmation or adjustment before proceeding. If the user approves or adjusts, proceed with the final question set.

## Step 2: Local Knowledge Scan

Run these in parallel:

1. **Semantic memory search**: `mcp__memory-search__memory_search(query=<topic>, limit=10)` — surfaces relevant entries from agent memory and topic files
2. **Topic file scan**: If the topic touches a known domain, scan both `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/*-patterns.md` and `~/.claude/agent-memory/topics/*.md` for matching files
3. **Architecture check**: Only if the topic is about this system's own design — read `~/.claude/ARCHITECTURE.md`

## Step 3: Present Prior Knowledge

Summarize what the system already knows about this topic. For each piece of prior knowledge, note the source (which memory file or topic file).

**No early exit by default**: If local knowledge appears to answer the research questions, do NOT silently skip external search. Always note the local knowledge and verify it externally — present any delta between local knowledge and external findings.

## Step 3b: Freshness gate (proportional mode)

Before defaulting to full multi-wave ceremony, check whether the user's question is narrow enough to be answered by a verify-only single wave. Apply this gate only when ALL of:

1. The user's question is narrow (1-2 research questions, not 5-7) — typical shape: "is X still true?", "what's the current price of Y?", "did Z change?"
2. Local knowledge has at least one `[confirmed]` entry covering the question
3. The relevant local entry is ≤ 30 days old (check the date stamp on the memory file or topic entry)

If all three hold, **propose to the user**: "Local knowledge from <date> says X. Want a verify-only run (1 wave, ~3-5 min, ~$1-2) to confirm it's still current, or full /deep-dive ceremony (multi-wave, ~25 min, ~$15-25)?"

If the user picks verify-only:
- Run a single Wave 1 with 3-6 calls (one query × 3 providers × 1-2 reformulations) targeting only the specific freshness check
- Skip Phase 2 (Dynamic Search Strategy multi-wave planning), Phase 3 (Iterative Deepening), Step 6b (Adversarial Search), Step 11b (Cross-Model Jury — full-ceremony only)
- Write a short report to `$HOME/Documents/knowledge-base/research/YYYY-MM-DD-topic-slug.md` (same path as the full-ceremony output at Step 12; verify-only just produces a shorter report) with one finding (still-current OR delta-found) and a Counterfactual line
- Done. Do NOT escalate to full ceremony unless the verify-only run finds a delta the user wants to investigate further.

If any of the three conditions fails, proceed to Phase 2 (full ceremony). Specifically: if local knowledge is older than 30 days, the user has not provided a narrow question, or no `[confirmed]` entry exists, skip Step 3b silently.

**Why this exists**: the 2026-05-03 roundtable identified "no early exit" + "Cost and speed are not constraints" as creating sunk-cost friction on narrow questions where the user already has fresh local knowledge. This gate gives the user a proportional path while preserving full ceremony as the default for genuinely open research. `/gather-intel` and `/gather-research` cover narrow Claude-Code-community and AI-research-frontier scopes respectively — for everything else (vendor pricing, version checks, "is X still true"), the verify-only mode lives inside `/deep-dive`.

---

# Phase 2: Dynamic Search Strategy

Generate search queries tailored to this specific topic. **No hardcoded queries** — every search is derived from the research questions in Step 1.

## Step 4: Map Research Questions to Tools

> For Tavily tool selection, wave execution, and graceful degradation patterns shared across all research skills, see `${CLAUDE_PLUGIN_ROOT}/skills/deep-dive/references/research-methodology.md`.

**MULTI-SOURCE DEFAULT (v2.0):** Every research question MUST be queried across **Tavily + Exa + Firecrawl** in parallel, not one provider alone. Single-source research under-samples the web — Tavily's keyword-weighted index, Exa's semantic/embedding index, and Firecrawl's structured site crawl surface different hits. This is the `/vendor-breach` multi-source-with-discrepancy-flagging pattern, generalized to all research. Follow `rules/web-search-preference.md` for per-query tool shape (source: `<claude-config-repo>/rules/web-search-preference.md`; deployed at `~/.claude/rules/web-search-preference.md`).

**REQUIRED ERROR DIAGNOSIS:** If any provider returns an error (402, 429, 5xx, timeout), capture the exact error text and surface it in the report header. Do NOT interpret an unexplained error as "credits exhausted" or any other specific cause without the raw error payload — misdiagnosis has caused false claims about provider availability.

| Source type | Tool | When to use |
|---|---|---|
| General web — keyword | `tavily_search` with `search_depth: "advanced"`, `chunks_per_source: 3`, `max_results: 5` | Product docs, vendor sites, blog comparisons, forums, how-to guides. Use `topic: "news"` + `time_range: "month"` for current events; `topic: "finance"` for vendor/spend analysis. |
| General web — semantic | `mcp__exa__web_search_exa` with `freshness: "month"` | Run ALONGSIDE `tavily_search` for the same question. Exa's embedding index surfaces hits Tavily misses (and vice versa). Highlights built-in. |
| General web — structured | `mcp__firecrawl__firecrawl_search` | Run ALONGSIDE Tavily/Exa. Firecrawl surfaces GitHub READMEs, changelogs, release notes, and docs sites that the keyword/semantic indexes often rank lower. |
| Deep synthesis | `tavily_research` with `model: "pro"` | Complex questions spanning many sources — "What is the current state of X?", comparisons, landscape analysis. **VERIFICATION REQUIRED:** For each factual claim in a `tavily_research` synthesis, identify the underlying primary source URL. If a claim cannot be traced to a specific URL, downgrade it to Low confidence or re-search. Still cross-check key claims against Exa + Firecrawl. |
| Academic/standards | `tavily_search` + `mcp__exa__web_search_exa` (semantic; "<topic> RFC/standard/paper") or `mcp__firecrawl__firecrawl_search` (filetype:pdf / site:nist.gov) | NIST publications, RFCs, compliance frameworks, conference proceedings. Run both. |
| Academic papers (arXiv) | `mcp__firecrawl__firecrawl_search` ("site:arxiv.org ...") or `mcp__exa__web_search_exa` ("paper about ..."), then `firecrawl_scrape`/`web_fetch_exa` on the arxiv URL for full text | arXiv preprints and published papers. The arxiv MCP is not on macOS. Use when research questions involve academic work, algorithms, or formal methods. |
| Code/GitHub | `mcp__firecrawl__firecrawl_search` (site:github.com) + `mcp__exa__web_search_exa` (include language + identifiers) | Code examples, implementations, GitHub issues. Always include programming language in query. Run both providers. |
| Category/vertical discovery | `mcp__exa__web_search_exa` with in-query `category:people`/`category:company` + `mcp__firecrawl__firecrawl_search` operators (site:/intitle:) | Company, people, news, pdf, personal site. The advanced category + domain-filter params were retired; compose verticals in-query or via firecrawl operators. |
| Recent articles/blogs | `mcp__exa__web_search_exa` with `freshness: "month"` + `tavily_search` with `topic: "news"` | Blog posts, announcements. Run both. |
| X/Twitter discussions | `bin/x-monitor.py --mode event --query "..."` (xAI Agent Tools API `x_search`; the `mcp__xai__*` X-search MCP tools were retired/not on macOS) | Real-time practitioner opinion, vendor announcements, breaking developments. Optional. |
| Full page from URL | Primary: `mcp__firecrawl__firecrawl_scrape` (cleanest markdown output). Alternates: `tavily_extract` with `extract_depth: "advanced"` + `query`, or `mcp__exa__web_fetch_exa` with `maxCharacters` (batch urls[]). | Known high-value pages found in earlier results. Use Firecrawl first for JS-rendered SPAs; fall back to Tavily/Exa if scrape returns thin content. |
| Multi-page documentation | `mcp__firecrawl__firecrawl_map` → `mcp__firecrawl__firecrawl_crawl` (preferred), or `tavily_map` → `tavily_crawl` (alternate) | Documentation sites needing structural exploration. Firecrawl's map returns cleaner URL inventories; crawl with `maxDepth: 2`, `limit: 20`. For very large sites, fire `firecrawl_crawl` as async and poll with `firecrawl_check_crawl_status`. |
| Structured extraction (schema'd) | `mcp__firecrawl__firecrawl_extract` with JSON schema | When you need specific fields (version, price, release date) extracted from multiple URLs, not prose. |

**Guidelines for query construction:**
- **Multi-provider parallel**: For every research question, fire at minimum `tavily_search` + `mcp__exa__web_search_exa` + `mcp__firecrawl__firecrawl_search` in the same parallel message. Single-provider queries are the exception, not the default.
- One logical question per sub-wave; each sub-wave spans 3 providers minimum.
- Include year terms (`2025 2026`) for fast-moving topics. Omit for stable topics (RFCs, established standards).
- For comparison topics, search for each subject independently AND for direct comparisons — across all three providers.
- For compliance/standards topics, search for the standard itself AND for practical implementation guidance — across all three providers.
- For each question where local knowledge provided a partial answer, generate at least one query (per provider) that specifically tests or updates the existing knowledge. Example: if local knowledge says "Product X lacks feature Y," search "Product X feature Y 2026 update."
- If any research question is primarily answerable from a known documentation site (docs.aws.amazon.com, learn.microsoft.com, etc.), include a **Firecrawl Map → Crawl** plan for that site (preferred over Tavily map for cleaner structured output). Crawling official docs is higher-value than searching for blog posts about them.
- Default to `search_depth: "advanced"` with `chunks_per_source: 3` for all Tavily searches. Default Exa to `freshness: "month"` for time-sensitive queries. Use `topic: "news"` + `time_range: "month"` (Tavily) for current events; `topic: "finance"` for vendor/spend queries. See `rules/web-search-preference.md` for parameter reference.

**Use `tavily_research(pro)` liberally** — it produces better synthesis than assembling individual search results. Good for: "What are the pros and cons of X?", "How does X compare to Y?", "What is the current state of X in the industry?" Still cross-check its claims against Exa and Firecrawl results in the same wave. **VERIFICATION REQUIRED:** For each factual claim in a `tavily_research` synthesis, identify the underlying primary source URL. If a claim cannot be traced to a specific URL, downgrade it to Low confidence or re-search for the primary source using `tavily_search` + Exa + Firecrawl.

## Step 5: Fire Wave 1

Fire all independent search queries in a **single parallel message**. For a typical research question set (3-7 questions), Wave 1 is 15-30 calls: each question × 3 providers (Tavily + Exa + Firecrawl), plus 1-2 `tavily_research(pro)` synthesis calls (arXiv via firecrawl site:arxiv.org; X/Twitter via `bin/x-monitor.py` if needed).

**Per-provider coverage requirement**: every research question must have hits from at least two of {Tavily, Exa, Firecrawl}. If only one provider returns results for a question, reformulate and retry on the silent provider(s) in Wave 2 — single-provider evidence downgrades that question's confidence tier by one.

After Wave 1 returns, proceed to Phase 3.

---

# Phase 3: Iterative Deepening (Convergence-Based)

No artificial wave limit. Keep searching until convergence.

## Step 6: Score and Assess Results

After each wave, for each result:

1. **Relevance**: Does this directly address one of our research questions? (Yes/Partial/No)
2. **Source quality**: Apply the evidence framework from `references/evidence-framework.md` — High/Medium/Low
3. **Novelty**: Does this add new information beyond what we already have? (New/Confirms/Redundant)

Drop results that are No relevance or Redundant. Keep everything else.

## Step 6b: Adversarial Search

For each HIGH or MEDIUM-priority finding from the current wave (not just Wave 1), generate one targeted query seeking counterarguments, failures, criticisms, or alternatives. Examples: if a finding says "Product X is excellent," search "Product X problems" or "Product X criticism." For comparisons, always search "[each product] problems" and "[each product] alternatives." Fire adversarial queries as part of the next wave. New findings from Wave 2+ also receive adversarial treatment.

## Step 7: Gap Analysis

For each research question, assess current answer confidence:

| Status | Meaning | Action |
|---|---|---|
| **Answered (High)** | Multiple corroborating sources with strong evidence | Done — no more searching needed for this question |
| **Answered (Medium)** | Some evidence but from limited or secondary sources | Search for corroboration or primary sources |
| **Partially answered** | Some aspects addressed but gaps remain | Search for the specific gaps |
| **Unanswered** | No relevant results found | Reformulate queries, try different terms, try different source types |

## Step 8: Follow Leads

For high-signal results from the current wave:

1. **Deep-fetch**: Use `mcp__firecrawl__firecrawl_scrape` first, `tavily_extract` (with `query`) or `mcp__exa__web_fetch_exa` as fallback, to get full content from promising URLs
2. **Citation chains**: If a source references another important source (a paper, a standard, a vendor page), search for it across all three providers
3. **Author follow-up**: If a source is by a recognized expert, search for their other work on this topic

## Step 9: Fire Next Wave

Construct targeted queries for:
- Gaps identified in Step 7
- Follow-up leads from Step 8
- Reformulated queries for unanswered questions (try different terminology, drop date restrictions, broaden scope)
- Silent-provider retries (any question where only one provider returned hits in the last wave)

Fire all independent queries in a single parallel message.

## Step 10: Check Convergence

After each wave (starting at Wave 2), explicitly count: of N total results, X were new findings, Y were redundant/confirming. Calculate new rate = X/N.

**MINIMUM**: Always complete at least 2 waves. Wave 1 is discovery; convergence checking starts at Wave 2.

**Continue** if:
- New rate > 30%, OR
- Any research question is still Unanswered or Partially answered and reformulations remain untried, OR
- Any research question still has single-provider coverage and a retry on the silent provider hasn't been attempted

**Stop** if:
- New rate < 30% for two consecutive waves (sustained diminishing returns), OR
- All research questions are Answered (High or Medium) with at least two-provider coverage, OR
- Reformulated queries for unanswered questions also return no results (topic gap — the information likely doesn't exist publicly)

> The 30% convergence gate and the "two consecutive waves" dampener are
> inherited defaults — see `references/tuning-notes.md` for rationale
> and how to log evidence when adjusting them.

When stopping with unanswered questions, note them honestly in the report rather than stretching weak evidence.

Return to Step 6 for the next wave, or proceed to Phase 4.

---

# Phase 4: Synthesis and Delivery

The most important phase. Synthesis quality is the primary success metric.

## Step 11: Cross-Reference and Synthesize

1. **Group findings by research question** — organize all evidence collected for each question
2. **Identify agreements** — where 2+ independent sources (preferably from different providers) say the same thing, note as high confidence
3. **Identify disagreements** — where sources contradict, present both sides with evidence levels
4. **Flag provider discrepancies** — when Tavily, Exa, and Firecrawl return materially different hits for the same query, call out what each surfaced. If one provider found a claim and the others didn't, explicitly note "[single-provider: Tavily only]" in the Sources column and downgrade confidence by one tier. Cross-provider corroboration is a confidence multiplier; silent providers are a warning.
5. **Identify silences** — questions where no strong evidence exists, note as gaps
6. **Assess source bias** — flag vendor-produced content, sponsored research, competitive comparisons. Apply bias tags from `references/evidence-framework.md`.

## Step 11b: Cross-Model Jury (contested / decision-critical claims)

Steps 6b, 7, and 11 are all run by the **synthesizing** model, so they share its blind spot. Same-model self-verification is the **worst-case judge config**: a model prefers its own outputs (self-preference / familiarity bias) and is unreliable on claims it can't independently ground (the "can't-solve-it" judge collapse). This step adds an **independent jury of disjoint models** for the few claims where a wrong call is expensive. Rationale/citations: [[llm-as-judge-validity-2026]] (PoLL panel-of-judges, pointwise > pairwise, sample-not-greedy, position bias).

**When to convene a jury (gate — keep it small).** A claim qualifies only if it is (a) **load-bearing for the Recommendation** AND (b) **contested** (sources disagree), **single-provider**, or **HIGH-impact but only Medium-confidence**. Cap at ~5 claims per report; if more qualify, jury the most decision-critical. Uncontested, multi-provider, High-confidence facts do NOT need a jury — do not burn the ceremony on them.

**Convene the jury.** For each qualifying claim, dispatch **three `general-purpose` Agents with disjoint `model` overrides — `opus`, `sonnet`, `haiku`** (the `Agent` tool's `model` param). Give each juror ONLY:
- the claim, stated neutrally;
- the candidate evidence already collected — **source URLs + quoted snippets**, not your synthesis prose;
- the instruction: return a **pointwise** verdict — `SUPPORTED` / `REFUTED` / `INSUFFICIENT` — with a one-line justification that **cites a specific source URL**. Ground the verdict in the supplied evidence, NOT in prior knowledge.

**Controls (each maps to a measured judge-bias failure):**
- **Pointwise, not pairwise** — each juror scores the claim on its own (Tripathi: pointwise is the more robust protocol). Do not ask "is claim A better than anti-claim B."
- **Order-swap** — give half the jurors the evidence (and the claim-vs-anti-claim framing) in one order and half in the reverse, to cancel position bias.
- **Disjoint-from-synthesizer** — this skill is itself running on a Claude-family model, so the jury reduces but does **not** eliminate intra-family self-preference. Weight the two jurors that are NOT the synthesizing model. The panel is an honest **partial** mitigation, not a cross-vendor jury.

**Aggregate (PoLL majority) — uncertainty downgrades, never upgrades:**
- **Unanimous SUPPORTED** → keep the finding's confidence (do not inflate above what the evidence tier already allows).
- **Split** → downgrade one tier and tag the finding `DISPUTED`.
- **Majority REFUTED** → drop the finding or restate it in its refuted form.
- **Majority INSUFFICIENT** → the jury could not ground it → downgrade to **Low** and flag "[jury: ungroundable]". An INSUFFICIENT verdict MUST NOT be read as SUPPORTED — failing the right way means an unverifiable claim *loses* confidence; it does not coast on the synthesizer's say-so.

Record the outcome on each juried finding with a `**Jury:**` line (models, per-juror verdict, aggregate) — see `references/report-template.md`.

**Graceful degradation.** If disjoint-`model` Agent dispatch is unavailable in the runtime, fall back to **N≥3 independent same-model samples with order-swap** (sample-not-greedy still beats a single greedy self-check) and label the finding "[same-model jury — partial]". For a single claim decision-critical enough to warrant a true cross-vendor panel (Opus + Grok + GPT), escalate to `/roundtable` rather than approximating it here.

**Dispatch PROHIBITED is a different case from dispatch UNAVAILABLE — and silently skipping is not one of the options.** A standing user/project directive against Agent dispatch does not make the jury optional; it only rules out the *disjoint-model* path. When dispatch is prohibited rather than absent, do BOTH: (a) run the same-model N≥3 fallback above, which needs no Agent tool; and (b) name the qualifying findings and offer the disjoint-model jury explicitly at the gate — `AskUserQuestion` is in `allowed-tools` for exactly this. Do not defer the disclosure to a report footnote; a footnote is not a decision point the user can act on. (2026-08-17: Step 11b was skipped citing a no-Agent directive and disclosed only in the report header. When the user later asked for it, the jury **changed two of three findings** — one downgraded to Low as ungroundable, one restated after a unanimous verdict that its comparative claim was unsourced. The same-model fallback was available the whole time and went unused, and the report shipped an unadjudicated overclaim in the interim.)

**Not yet measured.** The jury's accuracy lift over Step-11 synthesis is a hypothesis, not a result — it has NOT been A/B'd in `harness/`. Per ship-discipline, don't claim it "improves" verification until the harness measures it on a fixture hard enough to produce judge errors (the current fixture is ceiling-accuracy — see Measured Efficacy). It is justified by the *direction* of the judge-bias evidence, not a local measurement.

## Step 12: Write the Report

Follow the template in `references/report-template.md` exactly.

**TEMPLATE COMPLIANCE CHECK**: Before saving, verify the report contains ALL mandatory sections: header metadata (Date, Waves completed, Research Questions stats, Provider status per-provider call counts and any raw errors encountered, Estimated credits consumed per provider), Research Questions, Key Findings (each with Claim/Confidence/Sources-with-provider-attribution/Evidence/Caveats/**Counterfactual**), Unanswered Questions, Recommendation, Sources table with authority tiers and provider column. If any mandatory section is missing, add it before saving.

**Verify-only carve-out (Step 3b mode)**: When Step 3b verify-only mode was taken, Step 12 TEMPLATE COMPLIANCE CHECK is reduced. The verify-only short report MUST still include: Date, Waves completed (1), Provider status (per-provider call counts + raw errors), one Key Finding with Claim/Confidence/Sources/Evidence/Caveats/**Counterfactual**, and a one-line Recommendation. The Sources table is required (with authority tier and provider columns) but may be condensed per the report-template.md "fewer than 10 sources" rule. Sections that may be skipped in verify-only: Prior Knowledge subsections beyond a single sentence, Comparison Matrix, Changes from Prior Research, multi-finding Trade-offs and Disagreements (a single-line note is sufficient). Per-provider credit accounting is still required. Full-ceremony reports remain bound by the unreduced compliance check.

**PER-FINDING COUNTERFACTUAL** (mandatory): Each Key Finding MUST include a Counterfactual line stating the inverted hypothesis and a SURVIVES / COLLAPSES / AMBIGUOUS verdict. A boilerplate "what if X were not true" without engagement does NOT satisfy this — the inversion must be specific enough that someone could disprove the original finding by checking it. The 2026-05-03 roundtable identified counterfactuals as the structurally weakest layer of the three-layer defense; this check closes the gap. See `references/report-template.md` for examples.

**COMPARATIVE-CLAIM GATE** (mandatory): before saving, re-read every finding title and claim for a **comparison or superlative** — "X **not** Y", "the primary/limiting/binding factor", "matters more than", "the real discriminator", "biggest". For each one, name the source that makes *that comparison*. Sources that independently establish "X is a serious problem" do **not** license "X outranks Y" — the ranking is then yours, not theirs. If no source ranks them, either delete the comparison and keep the qualitative finding, or restate it as an explicit open question. This is the single most likely place for synthesis to outrun evidence, because a comparative framing reads as a sharper insight and therefore survives self-review. (2026-08-17: a finding asserted "false-alarm rate — **not** detection range — is the limiting factor"; three jurors independently returned INSUFFICIENT with the identical objection that no supplied source compared the two. The qualitative half was well-sourced across three non-vendor sources spanning 2019–2025; only the ranking was invented, and it was in the finding's title.)

1. Create the output directory if it doesn't exist: `mkdir -p "$HOME/Documents/knowledge-base/research"`
2. Generate the topic slug (lowercase, hyphens, max 50 chars)
3. Write the report to `$HOME/Documents/knowledge-base/research/YYYY-MM-DD-topic-slug.md`
4. **Readback verification**: re-read the saved file and verify (a) it is non-empty, (b) every `### Finding N:` block contains a `**Counterfactual:**` line, and (c) the in-conversation summary placeholder is NOT in the file — specifically, grep for the literal token `**Research complete: [Topic]**` (defined in `references/report-template.md` line 91 as the PLACEHOLDER TOKEN); if that literal string survives in the saved file, real content was not written. Also check for the unsubstituted slots `[2-3 sentence executive summary` and `[N] findings` as secondary placeholder leaks. If any check fails, surface the failure to the user — do NOT claim the report is saved.

## Step 13: Present In-Conversation Summary

After saving the report, present the in-conversation summary format from `references/report-template.md`. Keep it concise — the full report is on disk.

---

# Graceful Degradation

If any tool or source fails during research:

| Failure | Action |
|---------|--------|
| `tavily_search` returns 0 results | Reformulate query: drop year terms, try alternate terminology, broaden scope. Retry 2-3 times, then continue with Exa + Firecrawl hits for that question and mark "[Tavily silent]". |
| `mcp__exa__web_search_exa` returns 0 results | Retry with an in-query `category:` or `mcp__firecrawl__firecrawl_search` operators. If still empty, continue with Tavily + Firecrawl and mark "[Exa silent]". |
| `mcp__firecrawl__firecrawl_search` returns 0 results | Retry with alternate phrasing or switch to `firecrawl_map` on the target domain. If still empty, continue and mark "[Firecrawl silent]". |
| Any provider returns an error (402, 429, 5xx, timeout, `fetch failed`) | **Capture the raw error text verbatim.** Do NOT interpret the cause without the raw payload. Surface in the report header: "Exa returned 429 on call 4/12: <raw error>". Continue with other providers; do not abandon the skill on one provider's error. **RETRY THE IDENTICAL QUERY ONCE before recording it as a coverage gap.** Note the asymmetry this fixes: the three zero-results rows above prescribe 2-3 retries, but a hard error historically got none — backwards, because a transient network fault is far more likely to clear on retry than a genuine zero-result is. A one-call retry is cheaper than the finding you lose. (2026-08-17: `web_search_exa error: fetch failed` was recorded as a permanent gap and "recovered via Firecrawl"; the identical query retried later succeeded and surfaced four facts Firecrawl had missed — a 41% vendor price contradiction, a conflicting compliance claim, a government competition award, and an entire new finding that changed a recommendation. The fallback provider is not equivalent coverage.) |
| `tavily_extract` / `mcp__firecrawl__firecrawl_scrape` / `mcp__exa__web_fetch_exa` times out or returns empty | Try the other two providers on the same URL before giving up — JS-rendered pages often need Firecrawl while login-walled pages sometimes open to Exa. If all three fail, fall back to search snippets already collected. |
| `tavily_research` returns low-quality synthesis | Supplement with targeted multi-provider searches to fill gaps. Verify all claims against traceable URLs before accepting. |
| `tavily_map`/`tavily_crawl` fails | Use `mcp__firecrawl__firecrawl_map` → `firecrawl_crawl` instead. |
| `firecrawl_crawl` times out on a large site | Switch to async pattern: fire `firecrawl_crawl` without waiting, then poll `firecrawl_check_crawl_status`. If still failing, fall back to `tavily_map`. |
| Entire provider (Tavily, Exa, or Firecrawl) MCP unavailable | Log "[<provider> MCP unavailable: <raw error>]" in the report header, continue with remaining providers, and downgrade affected findings' confidence by one tier. Two-of-three is the minimum — if two providers are down, surface that to the user before continuing. |
| `memory_search` unavailable, errors, or hangs | **Do NOT record "local knowledge not checked" — fall back to grep, which is deterministic and takes seconds.** Run `Grep`/`Bash` for the topic's distinctive nouns across `$HOME/.claude/projects/$PROJECT_ID/memory/`, `$HOME/.claude/agent-memory/topics/`, and `$HOME/Documents/knowledge-base/`, then read any adjacent report the hits name. Report the corpora searched, the file counts, and the hit counts so the check is auditable. Only if the grep ALSO cannot run may you note the scan as skipped. (2026-08-17: `memory_search` hung 1800 s on a degraded VPN link; this row's former "skip and note it" guidance turned a 5-second fallback into a published gap in the report, which the user flagged. Grep found 0 hits across 179 memory files and 2 adjacent reports — a complete answer the semantic tool never delivered.) |
| Output directory write fails | The `worktree-enforcement.py` hook explicitly allows `knowledge-base/research/` writes from forked skill context (ALLOWED_SUBPATHS), so this should not occur. If a write still fails (disk full, permissions), capture the raw error and fall back to `$HOME/Documents/`, noting the failure path in the in-conversation summary. |

**Never fail the entire skill because one source or tool is unavailable.** Log the failure, skip that source, continue with remaining results. Partial multi-provider coverage (2 of 3) is acceptable with documented caveats; single-provider research is not — pause and surface to the user.

**ZERO providers reachable is a HARD ABORT, not a degradation — and in a forked run it is the DEFAULT, not an edge case.** This skill is `context: fork`, and the standing project limitation is that **Agent-tool workers cannot authenticate to remote MCPs**. All three discovery providers are remote MCPs, so the expected forked outcome is *all three unavailable at once*: the "two of three is the minimum" row above reads like an unlikely tail and is in fact the modal case for this skill's own execution mode.

REQUIRED, before Wave 1: issue ONE cheap probe per provider. If **zero** return results, do NOT proceed to synthesis. Emit `INSUFFICIENT_PROVIDERS: 0/3 reachable — remote-MCP auth unavailable in forked context; run the research wave from the main thread` as the skill's result and stop. A report assembled from prior-turn context with a "providers unavailable" header is **not research** — it restates the briefing it was handed, and every confidence and provenance label in it is unearned.

(2026-08-26: all three providers errored in a forked run. The fork continued anyway, produced a 47 KB report whose only inputs were the invoking turn's own ground truth, labelled it with an honest provider-status line — and introduced a fabricated figure, "outlook … 99 tools", against a real filter list of 30. The main thread then re-ran the identical wave successfully in 11 searches, because from the main thread those same three providers work. Cost: one wasted fork run plus the full re-run. The honest provider-status header is what made it survive review: it looked like disclosed degradation rather than a null result.)

---

# What This Skill Does NOT Do

- Does NOT search internal comms (Slack/Linear/Confluence) — use `gather-internal-intel`
- Does NOT maintain a cumulative intelligence report — each run is independent
- Does NOT modify architecture files, agent memory, or CLAUDE.md — research output only
- Does NOT replace gather-intel or gather-research — those maintain cumulative domain-specific reports

---

# Examples

**Example 1: Vendor comparison for compliance**
User says: `/deep-dive Airlock Digital vs Carbon Black for FedRAMP`
Actions:
1. Phase 1: Parse into 5 research questions (FedRAMP status, feature comparison, independent reviews, limitations, integration with existing stack). Memory search finds airlock-patterns.md — prior knowledge on Airlock.
2. Phase 2: 15+ parallel searches — 5 questions × 3 providers (Tavily + Exa + Firecrawl) + 2 tavily_research(pro) syntheses.
3. Phase 3: Wave 1 answers 3/5 questions with two-of-three provider coverage. Wave 2 targets gaps (pricing, integration specifics) and retries silent providers. Wave 3 deep-fetches 4 high-signal vendor pages via firecrawl_scrape. Convergence reached.
4. Phase 4: Report with 7 findings (3 High, 3 Medium, 1 Low). 1 disagreement flagged. Provider attribution per finding. Report saved.
Result: Structured comparison with evidence-graded, provider-attributed claims and honest assessment of vendor bias.

**Example 2: Standards deep dive**
User says: `/deep-dive FIPS 140-3 validation timeline for Tailscale`
Actions:
1. Phase 1: 3 research questions. Memory search finds tailscale-patterns.md.
2. Phase 2: 9 parallel searches — 3 questions × 3 providers + 1 tavily_research(pro).
3. Phase 3: Wave 1 mostly answers questions. Wave 2 extracts CMVP database page (firecrawl_scrape) and Tailscale's security docs (tavily_extract cross-check). Convergence in 2 waves.
4. Phase 4: Report with 4 findings (1 High, 2 Medium, 1 Low). 1 unanswered. Report saved.
Result: Clear assessment with the High-confidence answer that Tailscale is not FIPS-validated, Medium-confidence timeline estimate, and alternatives list.

**Example 3: Technology best practices**
User says: `/deep-dive best practices for OPA policy testing in CI/CD`
Actions:
1. Phase 1: 4 research questions. Memory search finds OPA source repo reference.
2. Phase 2: 12+ parallel searches — 4 questions × 3 providers + 1 tavily_research(pro) + firecrawl_map on OPA docs site.
3. Phase 3: Wave 1 answers 3/4 questions. Wave 2 crawls OPA docs (firecrawl_crawl) for testing section. Wave 3 extracts 3 high-signal blog posts. Convergence in 3 waves.
4. Phase 4: Report with 6 findings (2 High, 3 Medium, 1 Low). No major disagreements. Report saved.
Result: Comprehensive practices guide grounded in official docs (firecrawl) and practitioner experience (tavily + exa).

---

# Success Criteria

## Measured Efficacy (live arm)

The live-arm efficacy measurements (what each pipeline stage contributes, measured on real research runs) are in `references/measured-efficacy.md`.

## Success Criteria

- Topic decomposed into specific research questions before any searches fire
- Research questions presented to user for adjustment before searching
- Local knowledge checked before external searches (always verified externally — no early exit)
- All search queries generated dynamically from the topic (no hardcoded queries)
- Every research question has two-of-three provider coverage (Tavily + Exa + Firecrawl) minimum, or documented single-provider caveat with downgraded confidence
- Convergence-based termination (no artificial wave limit) — **except** in Step 3b verify-only mode, which is intentionally capped at a single Wave 1 of 3-6 calls and skips iterative deepening
- Every claim in the synthesis tagged with evidence level (High/Medium/Low) AND provider attribution (Tavily / Exa / Firecrawl / multi)
- Source bias flagged where present (vendor, sponsored, competitor, dated, no methodology)
- Disagreements between sources AND between providers explicitly presented with both sides
- Contested / decision-critical claims (load-bearing AND disagreeing / single-provider / HIGH-but-Medium) put through a disjoint-model jury (Step 11b), aggregated PoLL-majority with uncertainty downgrading confidence — or the same-model-sample fallback documented when disjoint dispatch is unavailable (full-ceremony runs only; verify-only mode skips it)
- Any provider errors captured with raw error text in the report header — no interpretive diagnosis without evidence
- Report saved to `$HOME/Documents/knowledge-base/research/` for every run
- Unanswered questions honestly called out with suggested next steps
- In-conversation summary presented after report is saved

## References

See `references/transfer-framework.md` for the transfer difficulty assessment framework.
