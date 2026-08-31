# Retrospective: {date_range} ({window})

## Dashboard

| Metric | Value |
|--------|-------|
| Sessions | {session_count} |
| Avg session duration | {avg_duration} |
| Total tool calls | {total_tool_calls} |
| **Real errors** | **{total_errors} ({error_rate}%)** |
| Hook blocks | {hook_blocks} (separate) |
| Retries | {total_retries} ({retry_rate}%) |
| First-try success rate | {first_try_rate}% |
| **Friction score** | **{friction_total} (avg {friction_avg}/session)** |
| - Empty/useless results | {empty_results} |
| - User corrections | {user_corrections} |
| - Approach changes | {approach_changes} |
| Skills invoked | {skill_count} unique ({skill_total} total) |
| Sessions without skills (standard+) | {no_skill_sessions} of {nontrivial} ({no_skill_pct}%) |
| Trivial sessions (<10min/<20 tools) | {trivial_count} (excluded from skill-less metric) |
| Auto-learn coverage | {autolearn_captured}/{autolearn_total} ({autolearn_rate}%) |
| Tokens (input/output) | {tokens_input} / {tokens_output} |

## What Was Accomplished

{Built from git_commits and pr_data. Summarize per repo:}

### {repo_name}: {commit_count} commits, {pr_count} PRs merged

| Metric | Value |
|--------|-------|
| Lines changed | +{insertions}/-{deletions} |
| PRs merged | {count} |

**Key deliverables:**
- {PR title} (+{additions}/-{deletions})
- ...

{Cross-reference with session user_requests to show which sessions drove which deliverables.}

### Output Metrics

| Metric | Value |
|--------|-------|
| Total commits | {sum across repos} |
| Total PRs merged | {sum across repos} |
| Total lines changed | +{total_ins}/-{total_del} |
| Sessions with commits | {count}/{total} ({pct}%) |
| Sessions with file writes | {count}/{total} ({pct}%) |
| Sessions ending in error only | {count}/{total} ({pct}%) |

### Commit Classification

| Type | Count | % |
|------|-------|---|
| feat: | {n} | {pct}% |
| fix: | {n} | {pct}% |
| chore: | {n} | {pct}% |
| docs: | {n} | {pct}% |
| refactor: | {n} | {pct}% |
| ci: | {n} | {pct}% |
| test: | {n} | {pct}% |
| other | {n} | {pct}% |

**Fix ratio**: {fix_count}/{total} = {pct}%
{If >40%: "High fix ratio — more time chasing bugs than building. Investigate root causes."}
{Trend vs previous retro: up/down/stable}

### Hotspot Files (top 10 most changed)

| Rank | File | Changes | Rework (changed again <7d) | Repos |
|------|------|---------|---------------------------|-------|
| {n} | {filepath} | {count} | {yes/no} | {repo} |

{Hotspot files with rework=yes are architectural pain points or files doing too much.}

### PR Failure Rate (Change Failure Rate)

| Metric | Value |
|--------|-------|
| Total PRs merged | {n} |
| Fix-follow PRs (fix: within 48h of prior PR, same files) | {n} |
| Explicit reverts | {n} |
| **Change failure rate** | **{pct}%** |

{If >15%: "Elevated failure rate. Review CI coverage and pre-merge checks."}
{If 0%: "Clean — no reverts or fix-follows in the window."}

## Lessons Captured

{Built from /distill and /capture invocations. Show what was written to topic files and knowledge base.}

| Session | Skill Used | Topics Updated |
|---------|-----------|----------------|
| {session_id} | {distill/capture} | {topic names} |

**Lessons being re-discovered** (errors that match existing topic file entries):
- {pattern that already has a rule/topic but keeps occurring}

## Error Classification

### Bash Errors ({bash_total})

| Subcategory | Count |
|-------------|-------|
| {subcategory} | {count} |

### Tool Errors ({tool_total})

| Subcategory | Count |
|-------------|-------|
| {subcategory} | {count} |

### API Errors ({api_total})

| Subcategory | Count |
|-------------|-------|
| {subcategory} | {count} |

## Friction Analysis

### Top Friction Sessions

| Rank | Friction | Errors | Empty | User Corrections | Duration | What Happened |
|------|----------|--------|-------|------------------|----------|---------------|
| {n} | {score} | {errors} | {empty} | {user_cor} | {duration} | {summary} |

### Empty Results: Search Misses vs Validation Checks

| Category | Count | % of Empty Results |
|----------|-------|--------------------|
| Search-miss friction | {empty_results_friction} | {pct}% |
| Validation-check (Edit/Write then Grep) | {empty_results_validation} | {pct}% |
| Total empty results | {empty_results} | 100% |

{Only friction empties contribute to the friction score. Validation empties are intentional absence checks.}

### Empty Results by Tool

| Tool | Empty Results | Total Calls | Empty Rate |
|------|--------------|-------------|------------|
| {tool} | {empty} | {total} | {rate}% |

### User Correction Themes

| Theme | Count | Example |
|-------|-------|---------|
| {theme} | {count} | {example} |

## What Went Well

### 1. {title}

**Evidence**: {transcript excerpts, tool call patterns}
**Metrics**: {relevant numbers}
**Why it worked**: {analysis}

## What Went Wrong

### 1. {title}

**Evidence**: {error messages, retry patterns, user corrections}
**Metrics**: {error count, friction score, time wasted}
**Root cause**: {analysis}
**Already captured?**: {cross-reference with topic files, rules, knowledge base}

## Skill Usage Metrics

### Frequency Table (top 20)

| Rank | Skill | Sessions | % | Trend |
|------|-------|----------|---|-------|
| {n} | {skill} | {count} | {pct}% | {up/down/new/stable vs prev retro} |

### Top Co-Occurrence Pairs

| Pair | Sessions Together | Pattern |
|------|-------------------|---------|
| {skill_a} + {skill_b} | {count} | {description} |

### Parent-Skill Attribution

| Orchestrator | Invocations | Child skills attributed |
|-------------|-------------|----------------------|
| /retro | {parent_skill_invocations["retro"]} | retro>distill: {n}, retro>capture: {n} |
| /retrospective | {parent_skill_invocations["retrospective"]} | ... |
| (standalone) | {remaining} | Bare distill, capture not attributed to a parent |

{Note: /retro chains distill+capture only. `retro>ship` does NOT exist — /ship is opt-in and never auto-chained from /retro. All `retro>X` entries are child invocations of /retro, not standalone.}

### Skill Execution Cost (top 5 by total tokens)

| Rank | Skill | Invocations | Total Tokens | Avg Tokens/Invocation | Trend |
|------|-------|------------|-------------|----------------------|-------|
| {n} | {skill} | {count} | {tokens} | {avg} | {up/down/stable} |

{Flag skills where avg tokens/invocation exceeds 50K — these are candidates for optimization or scope reduction.}

## ToB Integration Health

| Integration | Eligible Sessions | Fired | Rate | Status |
|---|---|---|---|---|
| insecure-defaults (ship Step A) | {n} | {n} | {pct}% | {OK/INVESTIGATE/BROKEN} |
| differential-review (ship Step B) | {n} | {n} | {pct}% | {OK/INVESTIGATE/BROKEN} |
| agentic-actions-auditor (CI gate) | {n} | {n} | {pct}% | {OK/INVESTIGATE/BROKEN} |
| fp-check (triage Phase 2d) | {n} | {n} | {pct}% | {OK/INVESTIGATE/BROKEN} |
| variant-analysis (triage Phase 2e) | {n} | {n} | {pct}% | {OK/INVESTIGATE/BROKEN} |
| sharp-edges (stig-assess Step 5b) | {n} | {n} | {pct}% | {OK/INVESTIGATE/BROKEN} |
| semgrep (security-alerts Phase 1b) | {n} | {n} | {pct}% | {OK/INVESTIGATE/BROKEN} |

Status: OK = >80% fire rate on eligible sessions, INVESTIGATE = 1-80%, BROKEN = 0%.

## Rationalization Calibration

### Fired (matched real shortcuts)

| Skill | Rationalization | Sessions Matched |
|-------|----------------|-----------------|
| {skill} | "{rationalization text}" | {count} |

### Never Relevant (0 matches — removal candidates after 3 retros)

| Skill | Rationalization | Retros at Zero |
|-------|----------------|---------------|
| {skill} | "{rationalization text}" | {count}/3 |

### Uncovered Shortcuts (new entry candidates)

| Skill | Shortcut Observed | Sessions | Proposed Rationalization |
|-------|------------------|----------|------------------------|
| {skill} | {what happened} | {count} | "{proposed entry}" |

### Miscalibrated (blocked correct shortcuts)

| Skill | Rationalization | What It Blocked | Fix |
|-------|----------------|----------------|-----|
| {skill} | "{entry}" | {legitimate shortcut description} | {add qualifier} |

## Security Gate Effectiveness

### Ship Security Review Gate

| Gate | Triggers | Findings | User Accepted | User Skipped | Skip Rate |
|------|----------|----------|---------------|-------------|-----------|
| Step A: insecure-defaults | {n} | {n} | {n} | {n} | {pct}% |
| Step B: differential-review | {n} | {n} | {n} | {n} | {pct}% |
| CI: agentic-actions-auditor | {n} | {n} | {n} | {n} | {pct}% |

{If skip rate >80% on any gate: "Gate X triggers too broadly. Review the decision table."}
{If skip rate <20% and findings >0: "Gate X is well-calibrated."}

## Skill Completion Rates

| Skill | Invocations | Completed | Abandoned | Rate | Common Abandonment Phase |
|-------|------------|-----------|-----------|------|-------------------------|
| triage | {n} | {n} | {n} | {pct}% | {phase name} |
| investigate | {n} | {n} | {n} | {pct}% | {phase name} |
| stig-assess | {n} | {n} | {n} | {pct}% | {phase name} |
| ship | {n} | {n} | {n} | {pct}% | {phase name} |
| superplan | {n} | {n} | {n} | {pct}% | {phase name} |

{Abandonment rate >30%: "Skill X has friction at {phase}. Investigate workflow."}

## Anti-Pattern Recurrence

### Most Violated Rules (top 5)

| Rank | Rule | Constraint | Sessions Violated | Age (days) | Enforcement |
|------|------|-----------|-------------------|------------|-------------|
| {n} | {rule file} | "{constraint text}" | {count} | {days since rule created} | {rule/hook/skill step} |

{If violations persist >30 days: "Rule is not working at current enforcement level. Escalate: rule → hook or skill step."}

### Never-Violated Rules (removal candidates after 3 retros)

| Rule | Constraint | Retros at Zero | Verdict |
|------|-----------|---------------|---------|
| {rule file} | "{constraint}" | {n}/3 | {keep (may be silently preventing) / remove} |

### New Anti-Patterns (no rule exists)

| Pattern | Sessions | Example Error/Correction | Proposed Rule/Entry |
|---------|----------|------------------------|-------------------|
| {description} | {count} | "{user correction or error msg}" | {where to codify: rule/rationalization/hook} |

### Rule Enforcement Escalation Tracker

| Constraint | Current Level | Violation Rate | Recommended Level |
|-----------|--------------|---------------|------------------|
| {constraint} | rule (ambient) | {pct}% | {hook (automatic) / skill step (explicit)} |
| {constraint} | rationalization | {pct}% | {skill step / hook} |

## Pattern Emergence

### Codified Patterns (already in skills/rules — effectiveness check)

| Pattern | Where Codified | Sessions Using | Still Effective? |
|---------|---------------|---------------|-----------------|
| {pattern description} | {skill/rule name} | {count} | {yes/degrading/no} |

### Emerging Patterns (3+ sessions, not codified)

| Pattern | Type | Sessions | Example Sequence | Recommendation |
|---------|------|----------|-----------------|---------------|
| {description} | {tool-sequence / skill-chain / recovery} | {count} | {tool1 → tool2 → tool3} | {new rule / new skill step / new skill} |

### Recovery Patterns (error → successful recovery)

| Error Type | Recovery Action | Frequency | Recommendation |
|-----------|----------------|-----------|---------------|
| {error category} | {what fixed it} | {count} | {hook (automatic) / rationalization (awareness)} |

{Recovery patterns appearing 5+ times are strong candidates for automatic hooks.}

## Strategic Analysis

### Skill Opportunities

{Analyze sessions_without_skills. What tasks were done without skills? Which recurring task patterns could become skills?}

### Automation Candidates

{Analyze sessions with max_consecutive_bash >= 10. What multi-step Bash workflows could be automated with a hook, script, or skill?}

### Agent Effectiveness

{How well are worker agents performing? What task types succeed vs fail? Should new agent types or topic files exist?}

### Architecture Improvements

{Based on the full error breakdown, what new hooks, rules, or guardrails would prevent the top error categories? Which existing rules aren't working?}

### MCP Tool Utilization

{Which tools have high empty-result rates? Are there tools that exist but aren't being used? Are there capability gaps where no MCP tool exists?}

### Workflow Pattern Analysis

{Which skills are heavily used? Which exist but are never invoked (possible routing issue or obsolete skill)? Are there naming collisions (brainstorm vs brainstorm)?}

## Gap Analysis

### P1: {gap_title}

**Signal**: {what in the data revealed this gap}
**Frequency**: {how many sessions affected}
**Recommendation**: {concrete action}
**Effort**: {small/medium/large}

### P2: {gap_title}
...

## Trends

{Compare against previous retrospective if one exists in ~/.claude/retrospectives/.}

{If windows differ (e.g., 10d vs 7d), add:}
> **Window mismatch**: Current {X}d vs previous {Y}d. Per-day rates used for fair comparison.

- Error rate: {current_pct}% vs {previous_pct}% ({delta}pp) — percentages are already normalized
- Friction/day: {current_per_day} vs {previous_per_day} ({delta}%) (raw: {current_raw} vs {prev_raw})
- Sessions/day: {current_per_day} vs {previous_per_day}
- New gaps identified vs resolved vs recurring
- Skill utilization changes (use parent_skill_invocations for orchestrator trends)
- Empty result split: friction empties vs validation empties

{If no previous retrospective:}
- First retrospective at this depth. Run again for trend data.
