# Gather-Intel Report Templates

Reference file for Phase C report generation. Read this file when generating the combined report.

---

## Metadata Header

```
Run date: YYYY-MM-DD | Claude Code version: vX.Y.Z
Tavily credits consumed: N (Wave 1: N, Wave 2: N, Wave 3: N, Deep Fetch: N)
Phase A: N items audited (N STALE, N UNVALIDATED, N OVERHEAD, N GAP, N RECONCILE)
Phase B: N findings evaluated, N advanced to dedup, N adversarial queries fired
Final: N HIGH, N MEDIUM, N LOW (Community Radar), N CONTESTED
Research cross-refs: N community findings validated by research, N contradicted
```

---

## Section 1 — Existing Intel Health (from Phase A)

Combine the outputs of Steps 2, 3, and 4 into a single health table:

| Recommendation | Source File | Version Status | Effectiveness | Constraint Status | Research Cross-Ref | Action |
|---|---|---|---|---|---|---|
| "Always limit=5 first" | CLAUDE.md | CURRENT | UNVALIDATED | TEST | No research support found | Design experiment: run 10 queries without limit, measure failure rate |
| Ripgrep workaround | CLAUDE.md | STALE (v2.1.23 fix) | N/A | REMOVE | N/A | Delete from CLAUDE.md Search Reliability section |
| 70% autocompact | ARCHITECTURE.md | CURRENT | KEEP (deliberate) | KEEP | Partial research support (context degradation studies) | No action - rationale documented |
| PreToolUse limit check | settings.local.json | CURRENT | UNVALIDATED | TEST | N/A | Check hook fire count vs actual limit-related failures |

Include subsections for:
- **STALE items** (recommend removal with specific file + section)
- **UNVALIDATED items** (recommend test plans - use the Experiment Design Template from `~/.claude/skills/deep-dive/references/transfer-framework.md` for each)
- **OVERHEAD items** (recommend relaxing with reasoning)
- **RECONCILE items** (show both sides, ask user to resolve)
- **GAP items** (community recommends, we don't do - should we? Include transfer difficulty assessment.)
- **Research-validated items** (community recommendations with independent research support - highest confidence)
- **Research-contradicted items** (community recommendations contradicted by research findings - flag for resolution)

---

## Section 2 — New Findings (from Phase B, ranked by composite priority)

### Gap Verification Gate

Before filling the **Gap** field for any finding, read the actual implementation
file for the architecture component the finding targets -- not just the
ARCHITECTURE.md summary from Phase A. Phase A reads high-level docs; gap claims
require implementation-level verification.

| Gap claim type | Verify by reading |
|---|---|
| Skill capability | `skills/*/SKILL.md` + its `references/` files |
| Hook enforcement | `hooks/*.py` source code |
| Rule coverage | `rules/*.md` |
| Agent/memory pattern | `agent-memory/topics/*.md` |
| Shared methodology | `skills/_shared/*.md` |

If the implementation already covers the external pattern (even if ARCHITECTURE.md
doesn't mention it), set Gap to "Already covered by [file:section]" and demote
actionability to Backlog. Gaps that survive verification are genuine.

### Standard Finding Format

```
## [HIGH/MEDIUM] Finding Title
- **Source**: [URL] ([authority tier])
- **Evidence**: [grade] - [1-sentence summary of evidence]
- **Applicability**: [Direct/Partial] - [which ARCHITECTURE.md section it maps to]
- **What it says**: [2-3 sentence summary]
- **Gap**: [What this architecture is missing or could improve]
- **Transfer difficulty**: [Drop-in / Pattern adoption / Skill-hook creation / Architecture evolution / Infrastructure addition]
- **Research support**: [If the research report contains a related finding, note it here with citation. "None found" otherwise.]
- **Actionability**: [Immediate / Planned / Project / Backlog]
- **Recommended action**: [Specific file + change, or "investigate further"]
```

### Actionability Levels

| Actionability | Criteria |
|---|---|
| **Immediate** | HIGH + Drop-in or Pattern adoption |
| **Planned** | HIGH + Skill/hook creation, or MEDIUM + Drop-in |
| **Project** | HIGH + Architecture evolution or Infrastructure |
| **Backlog** | MEDIUM + anything above Drop-in |

Sort the summary table by Actionability first, then priority.

Transfer difficulty levels (from `~/.claude/skills/deep-dive/references/transfer-framework.md`): Drop-in (single session config/prompt change), Pattern adoption (1-2 sessions with testing), Skill/hook creation (planned implementation), Architecture evolution (project-level via superplan), Infrastructure addition (significant project).

### Summary Table

| # | Finding | Source | Authority | Evidence | Applicability | Current State | Gap | Transfer Difficulty | Actionability | Files to Modify | Priority |
|---|---------|--------|-----------|----------|---------------|---------------|-----|--------------------|-----------------|---------|

HIGH findings first, then MEDIUM.

---

## Section 3 — Community Threads

For each community thread identified in Step 6 (clusters of 3+ related findings from independent sources):

```
## Thread: [Thread Title]
- **Core pattern**: [1-2 sentences summarizing the converging community direction]
- **Key sources**: [List of sources in this thread, with upvotes/stars]
- **Maturity**: [Emerging / Establishing / Established / Declining]
- **Architecture impact**: [How this thread relates to the current architecture]
- **Recommended action**: [Monitor / Experiment / Adopt / Adapt existing implementation]
```

---

## Section 4 — Popularity vs Effectiveness Analysis

Cross-reference community popularity (upvotes, stars, citation frequency) with actual effectiveness in this architecture:

| Recommendation | Popularity | Implemented? | Evidence of effectiveness? | Verdict |
|---|---|---|---|---|
| "Use subagents for ALL exploration" | 345pts Reddit | Partially (routing table has skip clause) | Yes - keeps main context clean | VALIDATED |
| Agent teams for cross-tool investigation | 425pts Reddit | Not yet (future upgrade path in ARCHITECTURE.md) | None for this setup | HYPE until tested |
| "40% context cliff" | T3 consensus (3+ posts) | Contradicted (we use 70%) | No measured degradation at 50-70% | UNVALIDATED - test or accept deviation |
| Some obscure hook pattern | 23pts Reddit | No | Includes working code + test results | HIDDEN GEM - investigate |

### Verdict Definitions

| Verdict | Definition |
|---------|-----------|
| **VALIDATED** | Popular AND effective - we implemented it, measurable improvement |
| **UNVALIDATED** | Popular AND implemented, but no evidence it helps - needs testing |
| **HYPE** | Popular but NOT implemented, AND no evidence for this setup type - deprioritize |
| **HIDDEN GEM** | Low popularity BUT strong evidence + direct applicability - investigate |
| **OVERHEAD** | Implemented but evidence suggests net negative - suggest relaxing |

---

## Examples

**Example 1: Monthly intelligence refresh**
User says: "/gather-intel"
Actions:
1. Phase A: Load baseline (including research report for cross-reference) + run memory_search("Claude Code community patterns"). Audit 25 existing recommendations for version currency and effectiveness.
2. Phase A finds: 2 STALE (fixed in current version), 3 UNVALIDATED, 1 OVERHEAD, 2 research-validated
3. Step 4b: Decompose default scope into 6 community questions covering agent architecture, hooks, context management, MCP patterns, memory, and Windows deployment. Present to user for approval.
4. Phase B Wave 1: 10 parallel basic searches dynamically generated from the 6 community questions
5. Phase B Wave 2: 2 tavily_research (pro) syntheses + targeted follow-ups + known sources check. Adversarial search for 4 HIGH findings.
6. Convergence check: Wave 2 returned 40% new results + 1 adversarial contradiction found. Wave 3 fires 3 targeted queries on the contradiction.
7. Phase B identifies 2 community threads: "hook-based routing replacing keyword matching" (4 sources, triangulation-verified), "agent memory pruning patterns" (3 sources)
8. Phase C: Combined report with health table (including research cross-refs) + ranked new findings (1 tagged CONTESTED) + community threads + popularity analysis. Reports 18 Tavily credits consumed.
Result: User approves trimming 2 stale items, adding 3 HIGH findings (1 with adversarial caveat), creating test plans for 3 UNVALIDATED items, and monitoring 2 community threads.

**Example 2: Targeted technique search**
User says: "/gather-intel hooks"
Actions:
1. Phase A: Load baseline (files 1-5 only, skip agents/hooks config - focus area is hooks so those files are less relevant than the architecture and community report). Run memory_search("Claude Code hooks patterns").
2. Phase A: Audit existing hook-related recommendations in ARCHITECTURE.md and community report. Cross-reference any hook-related research findings.
3. Step 4b: Decompose "hooks" into 6 community questions: best hook patterns for routing, PreToolUse vs PostToolUse trade-offs, hook performance overhead, hook-based validation patterns, community hook libraries/examples, hook debugging techniques. Present to user.
4. Phase B Wave 1: 10 basic searches dynamically generated from the 6 hook-focused questions
5. Phase B Wave 2: tavily_research (pro) for "Claude Code hooks best practices", adversarial search for top findings ("Claude Code hooks problems limitations"), follow-ups on specific hook repos/authors found in Wave 1
6. Convergence check: Wave 2 returned 65% redundant. Stop - no Wave 3 needed.
7. Phase B identifies 1 community thread: "PreCompact hooks for context management"
8. Phase C: Report focused on hook patterns with gap analysis, research cross-references, and transfer difficulty. Reports 14 Tavily credits consumed.
Result: User approves adding 2 new patterns (both Drop-in difficulty) and investigating 1 experimental pattern.
