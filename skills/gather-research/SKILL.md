---

name: gather-research
description: "Track the AI-agent research frontier (papers, talks, frameworks) and map it to our architecture."
when_to_use: Use when wanting to stay current on the research frontier for AI agent architecture. Searches academic papers, conference talks, research blogs, and framework developments (arXiv preprints via Exa, NeurIPS/ICML/ICLR/ACL proceedings, Anthropic/Google DeepMind/Meta FAIR research blogs), then maps findings to this Claude Code architecture for research-backed improvements. Academic paper search runs through Exa with category filtering (arXiv MCP not required). Do NOT use for Claude Code-specific intelligence (use /gather-claude), community pattern gathering (use /gather-intel), or internal repo evaluation (use /evaluate-repos).
# 2026-09-04: hidden from model routing. Paired A/Bs on Opus 4.8 (2026-05-31) and Fable 5.1
# (2026-09-03) measured no lift over a plain model with web search, and the harnesses never ran
# the full skill; see docs/research-skills-root-cause.md. Explicit /<name> invocation still works.
disable-model-invocation: true
argument-hint: "[optional focus area, e.g. 'agent memory', 'tool use', 'MCP patterns']"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
  body-cap: exempt
  body-cap-reason: "PERIODIC: research-frontier report reconciled run over run (Step 0 reviews the previous run), disable-model-invocation, 30-60 turns; only edge is scout-frontier"
compatibility:
  # Academic paper search runs through Exa with category=research. The
  # arxiv-mcp-server dependency was declared in a prior version but
  # never invoked in this skill body — removed to avoid a phantom
  # precondition that would block the skill on machines without that
  # MCP installed.
  requires: []
allowed-tools: AskUserQuestion Bash Edit Glob Grep Read ToolSearch Write mcp__00000000-0000-4000-8000-000000000003__web_fetch_exa mcp__00000000-0000-4000-8000-000000000003__web_search_exa mcp__exa__web_fetch_exa mcp__exa__web_search_exa mcp__firecrawl__firecrawl_search mcp__memory-search__memory_search mcp__tavily__tavily_crawl mcp__tavily__tavily_extract mcp__tavily__tavily_map mcp__tavily__tavily_research mcp__tavily__tavily_search
---

## gather-research

# Gather Research Intelligence

Search the research frontier — academic papers, conference presentations, research blogs, AI agent frameworks, and emerging standards — for findings that can improve this Claude Code architecture. Compare discoveries against the current system design to identify research-backed improvements.

Three phases: **Audit existing research baseline** (backward-looking) -> **Search the frontier** (forward-looking) -> **Synthesize research-to-practice report** (combined report with user approval).

> **Operational note**: This skill complements `gather-intel` (community knowledge from Reddit/HN/blogs). `gather-research` covers the *research* frontier: peer-reviewed papers, preprints, conference talks, framework documentation, and institutional research blogs. The two skills have different source types, evaluation criteria, and applicability frameworks. Run both for comprehensive coverage. When presenting findings, cross-reference: if research says "X works," note whether community reports (from the latest `gather-intel` run, if available) confirm or contradict it in practice.

> **Dual-skill coordination**: If `gather-intel` ran earlier in this session (check: does the session context contain a community intelligence report?), skip re-reading baseline files 1, 3, 4, 5, 6, 7 (already in context). Consume gather-intel's findings directly and specifically search for research that validates or contradicts the community findings. Note "community-first run" in the report metadata. See `skills/gather-intel/references/gather-coordination.md` for full coordination protocol.

> **Focus area**: If the user provided an argument (e.g., `/gather-research agent memory`), use it as the primary input for research question decomposition in Step 3b. ALL queries in Phase B must derive from the focus-area research questions. In Phase C, evaluate findings specifically against the focus area's role in the architecture.

---

## Scope guard

Before proceeding, verify the topic is in-scope. If the user is asking about:
- **Claude Code changelog, new features, or workarounds** → redirect to `/gather-claude`
- **Community patterns** from blogs, Reddit, or HN → redirect to `/gather-intel`
- **Evaluation of a specific repo** → redirect to `/evaluate-repos`
- **Single-topic deep research** on a non-AI-architecture subject → redirect to `/deep-dive`

If out-of-scope, tell the user which skill to use instead, then stop.

---

# Phase A: Audit Existing Research Baseline (backward-looking)

## Step 0: Review Previous Run Actions

Before auditing the baseline, check what happened since the last run:

1. **Read the research report metadata** - extract the report date (the `**Date**: YYYY-MM-DD` field defined in `references/report-format.md` is the canonical last-run timestamp)
2. **For each approved action item from the previous run**: Check if it was implemented by scanning the referenced files for changes since that report date
3. **For each queued experiment**: Check the Experiment Backlog - was it run? Were results recorded? If an experiment has been queued for 2+ runs without execution, flag it for archive or immediate execution.
4. **For each "Monitor" item**: Check for new papers or framework releases (a single targeted `tavily_search` per item)
5. **Load the rejection log** from the previous report (see `references/run-tracking.md`). Hold the rejected-finding summaries in working memory so Phase B / Phase C can deprioritize any new finding that is substantially similar to a previously-rejected one (tag `[previously-rejected-similar]`). Apply category-wide rejections as filters in Phase B. If the previous report contains no Rejection Log section, note "rejection log: absent" and continue — do not search for it elsewhere. Step 10 emits the section every run (even when empty), so this absence self-heals after one run.

Report a brief summary: "Since last run (YYYY-MM-DD): N action items implemented, N experiments still pending, N monitor items with new evidence, N rejection-log entries loaded."

If this is the first run (no existing report), skip Step 0.

## Step 1: Load Full Baseline

**Check current version first**: Run `claude --version` via Bash to confirm the installed Claude Code version. All findings will be filtered against this version.

Load the baseline **selectively, scoped to the run**. Two of these files are too large to read whole (`ARCHITECTURE.md` ~1,300 lines / ~42K tokens exceeds the Read cap; the cumulative research report grows without bound — 244KB as of 2026-08) — grep their headers first and read only the matching sections.

1. `~/.claude/ARCHITECTURE.md` — current system design. **Focused run**: grep `^#` headers, then read only the sections matching the focus area. **Full-scope run**: read the layer overviews plus each section a research question maps to; never attempt a single whole-file Read.
2. `$HOME/Documents/knowledge-base/research/claude-code-research-intelligence.md` — existing research report (if it exists; if not, this is a first run — note that and skip to Phase B). Extract via grep/sed: the metadata block, section headers, the Current State index (if present), and the full text of only the focus-relevant findings.
3. `MEMORY.md` — **do not re-read**: it is injected into session context at startup (verify by checking the session context; read from `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/MEMORY.md` only if genuinely absent).
4. `~/.claude/projects/$CLAUDE_PROJECT_ID/CLAUDE.md` — behavioral rules and constraints (skip when already injected into session context, which is the normal case).
5. `~/.claude/agent-memory/topics/` — **focused run**: only topics matching the focus area (e.g. `fastmcp.md` for MCP focus). **Full-scope run**: `security.md` + `infrastructure.md` (scan for research-derived entries).

If `$CLAUDE_PROJECT_ID` isn't set (headless / worktree sessions), resolve it
via `_shared/project-dir.md`'s recipe before items 3–4. Skip items 3–4 if no
project dir resolves rather than reading from a nonexistent path.

Also run in parallel:
- **Semantic memory search**: `mcp__memory-search__memory_search(query="<focus area or 'AI agent research architecture patterns'>", limit=10)` — surfaces relevant entries from agent memory and topic files that may connect to research findings
- **Community intel cross-reference**: If `$HOME/Documents/knowledge-base/research/claude-code-community-intelligence*.md` exists, read its ToC and Sources section to identify community findings that research may validate or contradict

If the research report exists, extract:
- **Section headers** — for topic-level dedup
- **Paper titles and URLs** — for exact citation dedup
- **Frameworks/tools mentioned** — for version currency checks

Build a list of **all research-derived recommendations currently in effect** — from the research report, ARCHITECTURE.md, CLAUDE.md, and agent prompts. Each recommendation gets audited in Steps 2-3.

## Step 2: Research Currency Audit

For each research-derived recommendation in the baseline:

1. Does it reference a specific paper, framework version, or conference year?
2. Has the referenced paper been superseded by newer work from the same authors or lab?
3. Has the framework/tool it references released major updates since the recommendation was captured?

Classify each:

| Status | Meaning | Action |
|--------|---------|--------|
| **CURRENT** | Still represents the state of the art — no superseding work found | No action needed |
| **SUPERSEDED** | Newer paper/framework version changes the recommendation | Verify the new work, update or replace the recommendation |
| **EVOLVED** | The core insight still holds but the implementation landscape changed (new tools, new APIs, new patterns) | Update the implementation guidance, keep the core insight |
| **RETRACTED** | Paper retracted, framework abandoned, or finding debunked by subsequent work | Remove the recommendation |
| **UNKNOWN** | Can't determine currency from available information | Flag for manual investigation |

Output a table of all research-tagged recommendations with their currency status.

## Step 3: Research-to-Practice Gap Audit

For each research finding that has been **implemented** in this architecture:

| Status | Criteria | Evidence to look for |
|--------|----------|---------------------|
| **APPLIED** | Research insight implemented + evidence it helps | Specific architecture component that traces back to the research finding; measurable improvement in agent behavior, context efficiency, or task success |
| **THEORETICAL** | Research insight noted but not yet implemented | Mentioned in docs/memory but no corresponding architecture change |
| **MISAPPLIED** | Research insight implemented but the implementation diverges from what the research actually recommends | e.g., paper recommends X approach, architecture implements a simplified version that loses the key benefit |
| **UNTESTED** | Implemented but no evidence of impact either way | Rule exists but never validated against the research's claimed benefit |

For each finding, note:
- Where it's implemented (file + section)
- What the original research claimed
- Whether the implementation matches the research's recommendation
- Suggested action (keep, refine, test, add missing)

**MISAPPLIED detection method**: For each APPLIED finding, re-read the referenced paper/source (use `tavily_extract` on the paper URL with `query` focused on methodology and recommendations). Compare the paper's SPECIFIC recommendation against the architecture's implementation. Common misapplication patterns:
- Paper recommends approach A with conditions X, Y, Z — architecture implements A without the conditions
- Paper's ablation study shows component B is critical — architecture omits B
- Paper evaluates on task type T — architecture applies to a different task type without validation

---

# Phase B: Search the Frontier (forward-looking)

## Step 3b: Decompose into Research Questions

Before searching, parse the focus area (or default scope: "AI agent architecture research frontier") into **5-8 specific research questions**. Each question must be answerable from external sources and map to at least one architecture component.

For each question:
1. Write it as a specific, searchable question (not a topic label)
2. Tag the architecture component it maps to (Agent system, Memory & persistence, Tool integration, Context management, Prompt engineering, Evaluation & feedback, Security & compliance, Orchestration)
3. Note any existing knowledge from Phase A that partially answers it

Log the research questions to the output, then proceed to searching. The questions are deterministic from the baseline analysis.

## Step 4-5: Parallel Source Search — Waves 1 and 2

See `references/search-waves.md` for full Wave 1 (Discovery) and Wave 2 (Targeted Deep Dives) details: tool routing (Tavily vs Exa), query construction guidelines, example query types table, Wave 2 tool/URL table, score-based pre-filtering, retry-on-empty behavior, adaptive follow-up for research threads, and convergence check with new-rate calculation. **Minimum: Always complete at least Wave 1 + Wave 2.**

## Step 6: Evaluate and Rank

Score **every** finding from Steps 4-5 using the Research Evaluation Framework (see below). This is the core quality filter.

## Step 6b: Adversarial Search

For each preliminary HIGH/MEDIUM finding from Steps 4-5, generate one targeted query seeking counterevidence:

- **Replication failures**: `"[paper title]" OR "[first author]" replication failure OR failed OR criticism`
- **Rebuttals**: `"[paper title]" rebuttal OR response OR critique OR limitation`
- **Practical failures**: `"[technique name]" problems OR limitations OR failure OR "doesn't work"`
- **Alternative approaches**: `"[technique name]" alternative OR "better than" OR comparison`

Fire all adversarial queries in a single parallel message. For each finding where adversarial search reveals significant counterevidence:

1. Note the counterevidence alongside the original finding
2. Downgrade findings with failed replications by one priority tier
3. Present findings with active rebuttals as `CONTESTED` with both sides
4. Never suppress counterevidence — the user needs both sides to make good decisions

Research papers frequently have caveats buried in methodology sections, failed replication attempts, or follow-up work that narrows the original claim. Without adversarial search, the skill would uncritically relay abstract-level claims.

**Symmetric evidentiary burden** (per `~/.claude/rules/symmetric-evidentiary-burden.md`): counter-evidence sources must meet the same PRIMARY-source bar as supporting sources. Single-source counter-evidence is preliminary signal, not refutation; pre-LLM citations cannot refute LLM-era behavioral claims; absence of supporting evidence is UNCHARTED, not REFUTED.

## Step 6c: Citation-Domain Freshness Check

Apply to BOTH supporting (Step 6) and counter-evidence (Step 6b) sources before assigning verdict labels.

See `references/citation-domain-freshness.md` for the full procedure: classify each source as PRIMARY / ADJACENT / OFF-DOMAIN against the 5 domain dimensions (model class, era, behavior surface, architecture class, modality). Apply freshness windows (≤12 months for frontier-model claims, ≤18 months generic LLM, ≤24 months agent architecture).

Verdict labels:
- **REFUTED**: requires ≥3 PRIMARY sources contradicting the claim
- **CONTESTED**: PRIMARY sources on both sides, or 1 PRIMARY + multiple ADJACENT
- **SUPPORTED**: ≥2 PRIMARY sources confirming
- **UNCHARTED**: 0 PRIMARY sources either way; document the search you ran

ADJACENT and OFF-DOMAIN sources count as context, not as evidence on the load-bearing claim.

## Step 7: Filter and Classify

Only findings scoring **MEDIUM or higher** composite priority advance to dedup and gap analysis.

**LOW findings**: List in a "Research Radar" section at the bottom of the report — these are early-stage or tangentially relevant findings worth monitoring but not acting on yet.

**DISCARD findings**: Do not mention.

### Version and feasibility check

For each HIGH/MEDIUM finding, assess implementation feasibility:

- **Implementable now**: The research insight can be applied to the current Claude Code architecture with available tools and APIs. Actionable.
- **Requires new capability**: The insight depends on a Claude Code feature, API, or tool that doesn't exist yet (e.g., native agent-to-agent communication, persistent vector memory). Tag as `[future]`.
- **Requires experimentation**: The insight is promising but needs testing to validate in this specific architecture. Tag as `[experiment]`.
- **Framework-specific**: The insight is tied to a specific framework (LangChain, AutoGen, etc.) and would need significant adaptation. Tag as `[adapt]`.

Only findings tagged **implementable now** or **requires experimentation** proceed to the gap analysis. Others go into the report as awareness items.

## Step 8: Deep Fetch (Selective)

For HIGH-priority findings that need more detail than search snippets provide, use `tavily_extract` (default, with `extract_depth: "advanced"`), `tavily_map` + `tavily_crawl` for multi-page framework docs, or `tavily_research(pro)` for broad thread synthesis. For arXiv papers, extract `arxiv.org/html/<id>` — NOT the `/abs/` page, which returns page chrome without the abstract. See `references/search-waves.md` (Step 8 section) for tool selection, fallback chain, and graceful degradation table.

## Step 9: Deduplicate

For each remaining result, check against the baseline from Step 1:

1. **Citation match**: Compare paper titles, arXiv IDs, and URLs against existing research report entries.
2. **Concept match**: Compare the research insight (not just the paper) against existing recommendations. A new paper confirming an old finding is an UPDATE, not NEW.
3. **Framework version match**: If a framework was already tracked, check if this is a new major version with architectural changes.

Classify each result:
- **NEW**: Research insight not captured in existing baseline
- **UPDATE**: Existing insight with new evidence, newer paper, or framework evolution
- **CONFIRMATION**: Independent verification of an existing finding (strengthens confidence)
- **CONTRADICTION**: Challenges or refutes an existing finding (high signal — always include)
- **KNOWN**: Already captured with no new information — skip

Proceed with NEW, UPDATE, CONFIRMATION, and CONTRADICTION results.

---

# Phase C: Synthesize Research-to-Practice Report

## Step 10-11: Combined Report + User Decision Point

See `references/report-format.md` for full report structure: metadata block, Section 1 (Research Baseline Health table), Section 2 (New Findings format + summary table + architecture components list), Section 3 (Research Threads template), Section 4 (Transfer Analysis pointer), and Step 11 user approval options per section. **NEVER auto-write.** Wait for explicit user approval before appending to `claude-code-research-intelligence.md`. Apply the skill-modification gate (skill-standards.md) for any action item that modifies `skills/*/SKILL.md`.

---

# Research Evaluation Framework

Score every finding from Phase B using the **Research Evaluation Framework** in `references/research-evaluation-framework.md`. This covers three dimensions: Research Rigor (R1-R6), Evidence Strength (Empirical-Controlled through Speculative), and Applicability (Direct/Adaptable/Conceptual/Tangential/Irrelevant). The composite priority matrix, bias indicators, and 8 special rules are also defined there.

---

# Research-to-Practice Transfer Framework

Apply the **Transfer Difficulty Assessment** and **Experiment Design Template** to every HIGH/MEDIUM finding. The canonical template for this skill lives at `references/transfer-analysis.md` — that is the version filled out and attached to the report, including its self-contained Transfer Difficulty Ratings (Low / Medium / High / Experimental) and Architecture Components map.

---

# Output File Management

See `references/output-management.md` for full details on report location, first-run setup, subsequent-run procedures, persistent research questions, and snapshot policy. Key path: `$HOME/Documents/knowledge-base/research/claude-code-research-intelligence.md`

---

# Success Criteria

## Measured Efficacy (live arm)

**Verdict: `trim` (ceiling-bound) — measured 2026-05-31, N=3, `claude-opus-4-8`, n=15 labeled claims.**
The citation-domain-freshness + PRIMARY-source verdict framework was A/B'd against
a fair baseline (same model + hosted web_search, no framework) on a hand-labeled
fixture (5 true+primary / 4 refuted / 3 outdated / 3 fabricated). **All five metrics
tied at 1.00 (Δ0.00, zero spread)**: grounding_precision, refutation_recall,
fabrication_resistance, true_recall, verdict_accuracy. A strong frontier model with
web search already hits ceiling on standard research-fact-checking, so the framework
buys **no measurable accuracy lift** to justify its ~5× cost *on this corpus*.
The arms behaved differently (framework → precise `UNCHARTED`/`CONTESTED` taxonomy +
refuses to cite for unsupported claims; baseline → flat `TRUE`/`FALSE`) but the
binary metric can't reward it. **Caveats:** n=15 is directional; the metric is
saturated (a discriminating fixture would need claims that make a strong searching
model over-claim *without* the freshness discipline). Harness + independent oracle +
frozen results: `skills/gather-research/harness/` (PROBLEM.md, fixture.json, grade.py,
run_live.py, results.json); CI gate: `tests/test_gather_research_efficacy.py`.

**Trim candidate (actionable, evidence-gated — not yet removed):** the tie is
ceiling-bound, so the responsible de-ceremony path is NOT to delete the
freshness/PRIMARY framework now — it delivers the un-measured verdict taxonomy +
no-citation-on-unsupported discipline above, and removal on a ceiling-bound n=15 tie
would violate `eval-shipping-discipline` (behavior changes need their own before/after).
The path: build a *discriminating* fixture (subtle CONTESTED cases needing the ≥3-PRIMARY
bar; near-current claims inside the 12-month frontier window) and re-A/B; **only if the
framework still shows no lift there**, trim the heaviest ceremony (the multi-bar verdict
taxonomy) with that re-measurement as evidence.

## Process criteria

- Research questions decomposed and presented to user before any searches fire (Step 3b)
- All search queries for ad-hoc topics generated dynamically from research questions. On **full-scope runs**, the 6 known authoritative sources are always probed: Anthropic research, Google DeepMind/Google Research, Meta FAIR, Anthropic docs, CHANGELOG, and YouTube conference talks. On **focused runs**, probe only the authoritative sources relevant to the focus area.
- Wave 1: all search calls fire in a single parallel message. Parameters come from the **live tool schemas** (loaded via ToolSearch), not from remembered names — provider MCP surfaces drift, and a parameter this file once mandated (`chunks_per_source`, `topic: "news"`, Exa `freshness`) can silently stop existing. Express intent (recency-bounded, advanced depth, forum-weighted) and map it to whatever the live schema supports; see `references/search-waves.md` Tool routing.
- Wave 2+: adaptive follow-ups based on Wave 1 results, including `tavily_research(pro)` with verification
- Adversarial search executed for every HIGH/MEDIUM preliminary finding (Step 6b)
- Every `tavily_research` claim traced to a primary source URL or downgraded
- Convergence-based termination (minimum 2 waves; stop when new-rate < 30% for 2 consecutive waves, OR when every Step 3b research question is answered with PRIMARY sources — the authoritative stop rule is in `references/search-waves.md`)
- Every finding scored on 3 dimensions (rigor, evidence, applicability) with bias tags where applicable
- Research threads identified when 3+ independent papers converge
- Findings presented to user for approval before writing to research report
- Report includes all 4 sections + metadata (date, waves, credits, question coverage)
- Snapshot saved before modifying cumulative report on subsequent runs

---

# Examples

Two representative invocations (full step-by-step walkthroughs, including
phase breakdowns, finding classifications, and credit accounting, are in
`references/research-examples.md`):

- **Monthly full-scope refresh** (`/gather-research`): runs Phases A→C end
  to end, exercises all 8 architecture components, ~35 Tavily credits.
- **Targeted focus area** (`/gather-research agent memory`): narrows
  decomposition to one topic, may need 3 waves on niche subjects.

---

# Run Tracking — Rejection Log, Run Metrics, Evaluation Prompts

See `references/run-tracking.md` for: (a) rejection log format and per-run deprioritization rule in Step 0, (b) Run Metrics block to append to report metadata, (c) three evaluation prompts for use with the `scripts/run-skill-evals.py` eval harness to grade skill output.
