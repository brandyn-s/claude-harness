# Phase C Report Format — Sections, Templates, and Metadata

Detailed reference for Step 10 (Combined Report) and Step 11 (User Decision Point).

## Report metadata (include at the top of the report)

- **Date**: YYYY-MM-DD
- **Focus area**: (if specified, or "full scope")
- **Waves completed**: N
- **Research questions**: X answered (High) / Y answered (Medium) / Z unanswered
- **Estimated Tavily credits consumed**: Calculate from tool usage: `tavily_search(basic)` = 1, `tavily_search(advanced)` = 2, `tavily_research(pro)` = ~5, `tavily_extract` = 1 per 5 URLs, `tavily_map` = 1 per 10 pages, `tavily_crawl` = 1 per 10 pages

Produce a single **run report** with the four numbered sections (1–4) below. When appending the run report into the cumulative knowledge-base file `claude-code-research-intelligence.md`, route each numbered section into the appropriate cumulative bucket defined in `references/output-management.md` (Active Findings, Research Threads, Research Radar, Experiment Backlog, Archived, Citations). The four numbered run-report sections describe what THIS run produces; the cumulative file has additional structural buckets (Table of Contents, Architecture Component Index) that are maintained across runs, not authored per run.

## Section 1 — Research Baseline Health (from Phase A)

Combine outputs of Steps 2-3:

| Research Finding | Source Paper/Framework | Year | Currency Status | Practice Status | Action |
|---|---|---|---|---|---|
| ReAct-style tool use | Yao et al. 2023 | 2023 | EVOLVED (newer ReAct variants exist) | APPLIED | Update to latest variant |
| Context window management | (internal pattern) | 2025 | CURRENT | UNTESTED | Design validation experiment |

Include subsections for:
- **SUPERSEDED items** — what replaced them and whether the replacement applies here
- **EVOLVED items** — what changed and whether the architecture needs updating
- **MISAPPLIED items** — how the implementation diverges and whether to correct it
- **UNTESTED items** — proposed validation experiments

## Section 2 — New Research Findings (from Phase B, ranked by composite priority)

Standard finding format for each NEW, UPDATE, CONFIRMATION, or CONTRADICTION:

```
## [HIGH/MEDIUM] Finding Title
- **Paper/Source**: [Title, Authors, Year] — [URL] ([venue/tier])
- **Research claim**: [1-2 sentence summary of what the research found]
- **Evidence strength**: [grade] — [methodology: controlled experiment / ablation study / case study / theoretical analysis / benchmark evaluation]
- **Applicability**: [Direct/Adaptable/Conceptual] — [which architecture component it maps to]
- **Transfer path**: [How to apply this research insight to THIS Claude Code architecture]
  - Specific files to modify
  - Specific patterns to adopt or adapt
  - Experiments to run
- **Feasibility**: [implementable now / requires experimentation / requires new capability / framework-specific]
- **Related work**: [Other findings in this report that connect to this one]
```

Present a summary table grouped by architecture component:

| # | Finding | Source | Venue | Evidence | Architecture Component | Transfer Path | Feasibility | Priority |
|---|---------|--------|-------|----------|----------------------|---------------|-------------|----------|

### Architecture components to map against

- **Agent system** (agent definitions, delegation, routing)
- **Memory & persistence** (agent memory, topic files, checkpoints)
- **Tool integration** (MCP servers, hooks, skill routing)
- **Context management** (compaction, summarization, token budgets)
- **Prompt engineering** (CLAUDE.md, agent prompts, skill instructions)
- **Evaluation & feedback** (self-improvement loops, quality metrics)
- **Security & compliance** (guardrails, confirmation patterns, audit trails)
- **Orchestration** (parallel dispatch, sequential pipelines, error recovery)

## Section 3 — Research Threads

For each research thread identified in Step 5 (clusters of 3+ related findings):

```
## Thread: [Thread Title]
- **Core insight**: [1-2 sentences summarizing the converging research direction]
- **Key papers**: [List of papers in this thread, chronologically]
- **Maturity**: [Emerging / Establishing / Established / Declining]
- **Architecture impact**: [How this thread relates to the current architecture]
- **Recommended action**: [Monitor / Experiment / Adopt / Adapt existing implementation]
```

## Section 4 — Research-to-Practice Transfer Analysis

See `references/transfer-analysis.md` for the full Implementation Verification Gate, gap analysis table template, transfer difficulty ratings, and architecture component mapping.

## Step 11: User Decision Point

Present all of Sections 1–4. Ask the user to approve actions:

**Section 1 (Research Baseline Health):**
- Update SUPERSEDED/EVOLVED recommendations
- Correct MISAPPLIED implementations
- Design experiments for UNTESTED items
- Remove RETRACTED items

**Section 2 (New Research Findings):**
For each finding, options:
1. **Add to research report** — Append to `claude-code-research-intelligence.md`
2. **Create action item** — Specific change to implement (file + what to change)
3. **Queue experiment** — Design and add to experiment backlog
4. **Monitor** — Add to Research Radar for future check-ins
5. **Skip** — Finding noted but no action

**Section 3 (Research Threads):**
- Confirm thread assessments
- Approve monitoring or adoption recommendations

**Section 4 (Transfer Analysis):**
- Approve or reprioritize gap items
- Select which gaps to address first

Present all of Sections 1–4. Ask the user to approve actions. **NEVER auto-write.** Wait for explicit user approval.

After user approval:
- For report additions: append to `claude-code-research-intelligence.md` (create if first run)
- **Always emit a Rejection Log table** in the appended section — even when empty — and a Run Metrics block (see `references/run-tracking.md`); the next run's Step 0 depends on both existing
- **Regenerate the Current State index** for the run's focus area (see `references/output-management.md`) so the cumulative file has one authoritative per-finding status view despite its append-only history
- For removals: delete stale entries with a note about why
- For action items: present a summary list of changes to implement
- **Skill-modification gate**: If an action item modifies a skill file (`skills/*/SKILL.md`), check the proposed change against skill-standards.md quality criteria before applying: CSO compliance (description = when-to-use only), 250-char trigger phrase window, no stale-prone version-specific content in skill body. Research findings are inputs to skill design, not direct edits. (don't implement yet — that's a separate task)
- For experiments: write experiment designs to a designated section of the report
- Update the Citations section with all new papers and URLs
