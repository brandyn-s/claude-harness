# Superplan Reference Tables

*Last updated: 2026-02-25*

## Domain Detection Matrix

When a task matches multiple domains, mark the **first match** as primary
(deepest context loading) and others as supplementary (load topic file only,
skip agent memory supplementary files). If ambiguous, ask the user which
domain is primary before loading context.

| Domain | Indicators | Worker topics | Deep reference (project memory) | MCP servers |
|--------|-----------|--------------|-------------------------------|-------------|
| Security | CrowdStrike, Tenable, Airlock, detection, vulnerability, hash, compliance, STIG, CMMC, contain, IOC, triage, block, allowlist | security.md + crowdstrike.md / tenable.md / airlock.md | crowdstrike-patterns.md, tenable-patterns.md, airlock-patterns.md | crowdstrike, tenable, airlock |
| Identity/Compliance | Entra, MFA, sign-in, conditional access, Graph, directory roles, risky user, audit log | msgraph.md | msgraph-patterns.md | msgraph |
| Finance | Ramp, spend, expense, vendor, budget, transaction, card, merchant | ramp.md | ramp-patterns.md | ramp |
| Recruiting | Lever, candidate, pipeline, hiring, requisition, offer, interview | lever.md | lever-patterns.md | lever |
| Project Management | Linear, issue, milestone, sprint, initiative, backlog, cycle | linear.md | linear-server-patterns.md | linear-server |
| Infrastructure/Cloud | ExampleTarget, firewall, network, AWS, ECS, ECR, Fargate, Docker, deploy, Terraform | infrastructure.md | aws-deployment-patterns.md, github-patterns.md | (none - use Python/Terraform CLI) |
| Documentation | Confluence, wiki, playbook, procedure, knowledge base | confluence.md | confluence-fedramp-patterns.md | confluence-fedramp |
| Automation | PowerShell, runbook, Azure Automation, scheduled task, mail-send | runbook.md | msgraph-patterns.md | msgraph |
| MCP Development | MCP server, FastMCP, build server, tool definition, OPA policy, Colin | architecture.md | mcp-development-patterns.md, api-research-patterns.md | (none - code task) |
| Skill/Hook Development | skill, SKILL.md, hook, create skill, agent config, routing | architecture.md | skill-development-patterns.md | (none - code task) |
| Communication | Slack, channel, message, thread, user lookup | slack.md | slack-patterns.md | slack |
| Research/Search | search, web research, Tavily, deep dive, compare, evaluate | (none - main thread) | tavily-patterns.md | tavily |
| Library/Docs Lookup | context7, library docs, API reference, code examples | (none - main thread) | context7-docs-patterns.md | context7-docs |
| Cross-domain | Touches 2+ domains above | Multiple topic files | Multiple pattern files | Multiple servers |

## Execution Path Options

| Path | When to use | How |
|------|------------|-----|
| **MCP direct** | Small queries, read-only lookups, interactive exploration | Delegate to `worker` agent with topic files, or handle in main thread |
| **Python script** | Bulk data, writes to read-only tools, complex pagination | Write .py file, execute with `python3 script.py` |
| **PowerShell script** [Windows-era] | Azure/Graph automation (prior Windows host) | Write .ps1, run `pwsh -File script.ps1`. **macOS:** prefer a Python script (`python3`) — pwsh isn't installed by default. |
| **Parallel dispatch** | 2+ independent entities/streams that don't depend on each other | Multiple Task calls in one message, each to the appropriate agent |
| **Sequential pipeline** | Steps that depend on previous results | Agent Task → read result → next Agent Task |
| **Example SDLC chain** | Full software development lifecycle (design → plan → implement → test → commit) | brainstorm → /superplan → superpowers:subagent-driven-development → /ship |
| **Main thread inline** | Simple task, no agent memory benefit, no MCP tools needed | Handle directly, no delegation |

## Plan Structure Template

The template below is the **literal shape** supergoal's `parse_plan.py` consumes. Each labelled / headed section maps to a state-file field; omissions cause parse errors or downstream warnings. Do not silently drop sections — leave them as `N/A` with justification if inapplicable.

```markdown
# Plan: [Task Title]

Demo: [One-line success criterion — what an outsider could observe when this plan is done. Cite a specific target-system entity (file:line, edge target, metric on real target) for size-of-effect plans. REQUIRED — parse_plan.py errors if missing.]

Effort: [XS|S|M|L|XL — drives supergoal turn/wallclock/token budgets. Defaults to M if omitted.]

## Goal
[1-2 sentences]

## Target-State Baseline
[From Phase 3.5, when applicable — required for any plan claiming size-of-effect on a real target.
Cite the sibling baseline file, e.g.:
  - "PSM HTTP_CALLS = 17 (cmd: `MATCH (a)-[r:HTTP_CALLS]->(b) RETURN count(r)` on indexed PSM)"
  - "PSM IMPLEMENTS Rust recall = 27.3% (341 emitted of 1251 impl_blocks_seen)"
  - "PSM source: 5 reqwest::get sites read at file:lines [...] — all use literal-URL form"
Full findings in `~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>-baseline.md`.

For size-of-effect phases, include a `### Phase 3.5 Baseline` subsection with `currently <N>, expected <M>` so parse_plan.py extracts numeric anchors.]

### Phase 3.5 Baseline
[currently <N>, expected <M> — numeric anchors. Optional; if omitted, supergoal still runs but cannot detect baseline drift.]

## Domains Involved
[List detected domains with primary/supplementary designation, agents, MCP servers]

## Known Constraints
[From Phase 2: gotchas, limitations, read-only restrictions, relevant agent memory entries]

## Execution Path
[Which path from Phase 3, and why]

## Execution Budget

```yaml
execution_budget:
  repair_cycles: 1
  full_suite_runs: 1
  live_probes: 1
  nonblocking_findings: backlog
```

[These are default maxima, not targets. Raise one only when a concrete risk or
mandatory external gate requires it and record the reason in Known Constraints.]

## Steps

### Phase A: [Phase name] (if >8 steps, group into phases)

#### Step 1: [Action]
- **Tool**: [MCP tool / Python script / agent dispatch]
- **Agent**: [which agent, or main thread]
- **Depends on**: [step number(s), or "none" if independent]
- **Gotcha**: [relevant gotcha from topic file or agent memory, if any]
- **Expected output**: [what success looks like]

#### Step 2: [Action]
- **Depends on**: Step 1
...

#### Steps 3-4: [Can run in parallel]
- **Depends on**: Step 2
- **Parallel**: yes — dispatch simultaneously
...

## Dependency Summary
[For plans with 5+ steps, include a brief dependency notation]
Example: 1 → 2 → [3 | 4] → 5 → 6
(brackets = parallel, arrows = sequential)

## Verification

[Prose summary of how to confirm the plan succeeded — what evidence to inspect. The
authoritative measurement commands belong in the three labelled subsections below
(parse_plan.py reads those — fenced bash blocks under `### Metric Commands`,
`### Guard Commands`, `### Artifact Probe`). The legacy `Verification:` label-form
is still supported, but new plans should use the labelled subsections.]

### Metric Commands
[REQUIRED — parse_plan.py errors if both this section AND the legacy `Verification:` block are missing.
Shell commands whose final line matching `^METRIC <name>=<value>` is the authoritative measurement.]

```bash
# Example:
# echo "METRIC HTTP_CALLS=$(cypher_count_query.sh)"
```

### Guard Commands
[Recommended — parse_plan.py warns if missing. Commands that must continue to pass
(existing tests, lints). Separate from metric — guards catch regressions, metrics drive progress.]

```bash
# Example:
# pytest tests/ -x
```

### Artifact Probe
[Recommended — parse_plan.py warns if missing. Commands that observe the *artifact*
(not the metric) — different surface area. Run only at exit as a Goodhart probe.]

```bash
# Example:
# ls -la build/artifact.bin && file build/artifact.bin
```

### Forbidden Actions
[Recommended — parse_plan.py warns if missing. Tool-call patterns the agent must NOT take during the loop.]
- Bash(rm *)
- Edit(file_path=/etc/*)
- Bash(git push --force *)

## Falsifiers
[Required for M/L/XL plans. For each phase, state at least one observation that would invalidate
the plan's working theory — and the action to take when it triggers.

Example:
  - **Phase A**: if `implementsRust.summary` shows `traitQN-empty < 100` after the Tier 2 trait
    resolver lands, Phase B's "extend resolveAsClass for additional label" hypothesis was wrong
    — re-diagnose. Action: drop Phase B, ship the resolver, re-baseline.
  - **Phase C**: if PSM HTTP_CALLS stays at the baseline value (17) after the new extractor
    ships, the "missing extractor" diagnosis was wrong — the real gap is downstream
    (matchAndLink, sameService, path normalization). Action: stop before Phase D, run
    instrumentation against actual PSM call sites, identify the real failure mode.

A plan with no documented falsifier means the planner can't tell when the plan is failing.]

## Execution
[How to run this plan]:
- For agent work: "Delegate to {agent} via Task tool"
- For scripts: "Write to {path}, execute with {command}"
- For parallel work: "Dispatch N Tasks simultaneously"
- For SDLC chain: "Hand off the plan to superpowers:subagent-driven-development for parallel-subagent execution"
```

## Plan Quality Checks

- Every step references a specific tool, agent, or execution method
- Known gotchas from agent memory / topic files are noted at the relevant step
- Read-only tools are never used for write operations in the plan
- Bulk data operations use Python scripts, not MCP pagination
- Cross-domain steps specify which agent handles which part
- Verification uses evidence, not assumptions
- Knowledge base entries older than 30 days are flagged, not treated as constraints
- Plans with >8 steps are grouped into named phases with per-phase depth
- Independent steps are marked as parallelizable with `Depends on: none` or grouped
- A dependency summary is included for plans with 5+ steps
- **Self-contained session**: zero calendar gates between steps ("wait N days", "≥N days of telemetry", "30-day clean-run", "weekly during eval window"). Zero external-approval gates between steps ("requires X sign-off", "pending team review"). Steps that would have observed data over time instead generate fixtures, run signal-based test batteries, or glean from prior session transcripts / logs / KB entries. External reviews are terminal artifacts (evidence packs, writeups), never in-plan gates blocking subsequent steps.
- **Target-state baseline**: every size-of-effect prediction ("lift to N", "≥ M%", "reduces X") cites a "currently M" baseline measured in Phase 3.5 on the same target. No magnitude prediction without measurement. Forbidden: `Demo: HTTP_CALLS ≥ 30` without "currently 17" baseline on the same metric/target.
- **Demo specificity**: every Demo line for a size-of-effect phase references a specific target-system entity (file:line, edge target, metric on real target). Synthetic-fixture passes are supplementary regression evidence, never the standalone demo for a real-target claim.
- **Phase ordering for observable systems**: when the plan touches extractors, parsers, resolvers, indexers, or rankers, default ordering is (1) Instrument, (2) Investigate, (3) Implement, (4) Verify. Skip Instrument only if the system already emits the needed signal. The Implement phase cites file:lines from the Investigate artifact.
- **Falsifiers section present** (M/L/XL plans): every phase has at least one stated observation that would invalidate the diagnosis, with the corresponding re-diagnosis action.
- **Scope drift check (during execution)**: If the plan has grown beyond
  the original step count, classify the drift:

  | Net change | Verdict | Action |
  |-----------|---------|--------|
  | ≤10% | **On Track** | Continue |
  | 10-25% | **Minor Creep** | Acknowledge additions, confirm intent |
  | 25-50% | **Significant Creep** | Stop. Cut, defer, or formally extend. |
  | >50% | **Out of Control** | Stop. Re-plan from scratch. |

  For each added step, ask: Cut (remove), Defer (later session), Keep
  (genuinely needed), or Flag (needs user decision). This prevents plans
  from silently growing from 5 steps to 12.
  (Pattern source: donchitos/claude-code-game-studios scope-check — Context7 registry 2026-04-08)

## Execution Routing Matrix

| Plan type | Recommended execution |
|----------|----------------------|
| Single-domain, few steps | Delegate to the domain agent directly with the plan as context |
| Multi-step implementation (code, scripts, configs) | Hand off to `superpowers:subagent-driven-development` for one-subagent-per-task execution |
| Cross-domain investigation | Use `security-investigation` pattern: parallel Tasks to domain agents, main thread correlates |
| Bulk data collection | Use `bulk-api-script` skill, then process results |
| One-shot query with context | Delegate to domain agent — the plan is the prompt |
| Large plan (>8 steps) with phases | Execute phase-by-phase: complete Phase A, review, then Phase B |
