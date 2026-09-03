---
name: differential-review
description: "Security-focused review of PRs, commits, or diffs, with blast-radius and test-coverage checks."
when_to_use: 'Use when reviewing PRs, commits, or diffs for security issues. Trigger phrases: "diff review", "review this PR", "what changed", "security review of changes". Do NOT use for SCA compliance (the /sca-review prototype is intentionally unavailable), STIG assessment, or general scanning (use /semgrep). Performs security-focused differential review with blast radius calculation, test coverage checks, and markdown reports.'
effort: high
allowed-tools: Read Write Grep Glob Bash AskUserQuestion
argument-hint: "[PR-number, commit-range, or branch]"
compatibility:
  optional:
    - cli: gh
      fallback: "Use git log/diff against base branch instead of gh pr view; PR-number target requires gh."
metadata:
  author: example-security-engineering
  version: "1.0"
---

# Differential Security Review

Security-focused code review for PRs, commits, and diffs.

## Core Principles

1. **Risk-First**: Focus on auth, crypto, value transfer, external calls
2. **Evidence-Based**: Every finding backed by git history, line numbers, attack scenarios
3. **Adaptive**: Scale to codebase size (SMALL/MEDIUM/LARGE)
4. **Honest**: Explicitly state coverage limits and confidence level
5. **Output-Driven**: Always generate comprehensive markdown report file

---

## Rationalizations (Do Not Skip)

| Rationalization | Why It's Wrong | Required Action |
|-----------------|----------------|-----------------|
| "Small PR, quick review" | Heartbleed was 2 lines | Classify by RISK, not size |
| "I know this codebase" | Familiarity breeds blind spots | Build explicit baseline context |
| "Git history takes too long" | History reveals regressions | Never skip Phase 1 |
| "Blast radius is obvious" | You'll miss transitive callers | Calculate quantitatively |
| "No tests = not my problem" | Missing tests = elevated risk rating | Flag in report, elevate severity |
| "Just a refactor, no security impact" | Refactors break invariants | Analyze as HIGH until proven LOW |
| "I'll explain verbally" | No artifact = findings lost | Always write report |

---

## Quick Reference

### Codebase Size Strategy

| Codebase Size | Strategy | Approach |
|---------------|----------|----------|
| SMALL (<20 files) | DEEP | Read all deps, full git blame |
| MEDIUM (20-199) | FOCUSED | 1-hop deps, priority files |
| LARGE (200+) | SURGICAL | Critical paths only |

### Risk Level Triggers

| Risk Level | Triggers |
|------------|----------|
| HIGH | Auth, crypto, external calls, value transfer, validation removal |
| MEDIUM | Business logic, state changes, new public APIs |
| LOW | Comments, tests, UI, logging |

---

## Vulnerability Determination Criteria

> Selectively cloned from tobihagemann/turbo `/review-security` and
> `/review-correctness` determination gates.

Flag an issue only when **ALL** of these hold:

1. It is a concrete security weakness, not a theoretical concern or
   defense-in-depth suggestion
2. The vulnerability is discrete and actionable (not a general architecture
   issue)
3. In diff mode: the issue was introduced or worsened by the changeset
   (do not flag pre-existing issues unless the change removes a mitigation)
4. The vulnerable code path is reachable with attacker-controlled input or
   attacker-influenced state
5. The author would likely fix the issue if aware of the security implications
6. The issue is demonstrable through a specific attack scenario, not
   speculation

### Transformation Chain Bypass Patterns

In addition to standard vulnerability classes, explicitly check for:

- **Validate-then-decode**: Input validated before URL/HTML/base64 decoding —
  post-decode value is unconstrained
- **Partial normalization**: Unicode normalization applied to part of the
  chain — bypasses character-level filters
- **Parsing differential**: Two components parse the same input differently
  (URL parser vs routing engine, JSON parser vs validator)
- **State-and-invariant violations**: Security operations proceed without
  required preconditions; assumptions about execution order that concurrent
  or out-of-order requests can violate

## Workflow Overview

```
Pre-Analysis → Phase 0: Triage → Phase 1: Code Analysis → Phase 2: Test Coverage
    ↓              ↓                    ↓                        ↓
Phase 3: Blast Radius → Phase 4: Deep Context → Phase 5: Adversarial → Phase 6: Report
```

---

## Decision Tree

**Starting a review?**

```
├─ Need detailed phase-by-phase methodology?
│  └─ Read: methodology.md
│     (Pre-Analysis + Phases 0-4: triage, code analysis, test coverage, blast radius)
│
├─ Analyzing HIGH RISK change?
│  └─ Read: adversarial.md
│     (Phase 5: Attacker modeling, exploit scenarios, exploitability rating)
│
├─ Writing the final report?
│  └─ Read: reporting.md
│     (Phase 6: Report structure, templates, formatting guidelines)
│
├─ Looking for specific vulnerability patterns?
│  └─ Read: patterns.md
│     (Regressions, reentrancy, access control, overflow, etc.)
│
└─ Quick triage only?
   └─ Use Quick Reference above, skip detailed docs
```

---

## Pre-Conclusion Audit (MANDATORY before finalizing)

Before producing final findings, explicitly verify your coverage:

1. **List every file you reviewed** and confirm you read it completely
2. **List every checklist item** and note whether you found issues or confirmed clean
3. **List any areas you could NOT fully verify** and why (missing context, external deps, etc.)
4. Only then produce final findings

This prevents phantom verification — claiming "reviewed" without evidence of what was read.
(Pattern source: getsentry/skills `find-bugs` — Context7 registry 2026-04-16)

## Quality Checklist

Before delivering:

- [ ] Pre-conclusion audit completed (coverage gaps documented)
- [ ] All changed files analyzed
- [ ] Git blame on removed security code
- [ ] Blast radius calculated for HIGH risk
- [ ] Attack scenarios are concrete (not generic)
- [ ] Findings reference specific line numbers + commits
- [ ] Report file generated
- [ ] User notified with summary

---

## Integration

This skill is methodology-only and does not chain into other skills automatically.
External tooling can consume the generated markdown report (filename
`<PROJECT>_<TARGET-SLUG>_DIFFERENTIAL_REVIEW_<UTC-TIMESTAMP>.md` — see
`reporting.md`; never overwrite an existing report) as input for
downstream issue tracking, audit reports, or stakeholder summaries; perform
that step manually using whatever issue-tracking tool the project uses
(GitHub Issues via `gh issue create`, Linear, Jira, etc.).

**Optional CLI dependency:**
- `gh` — required only when the target argument is a GitHub PR number (used
  by `gh pr view <number>` in `methodology.md`). For local commit ranges or
  branches, `git diff` and `git log` suffice.

---

## Example Usage

### Quick Triage (Small PR)
```
Input: 5 file PR, 2 HIGH RISK files
Strategy: Use Quick Reference
1. Classify risk level per file (2 HIGH, 3 LOW)
2. Focus on 2 HIGH files only
3. Git blame removed code
4. Generate minimal report
Time: ~30 minutes
```

### Standard Review (Medium Codebase)
```
Input: 80 files, 12 HIGH RISK changes
Strategy: FOCUSED (see methodology.md)
1. Full workflow on HIGH RISK files
2. Surface scan on MEDIUM
3. Skip LOW risk files
4. Complete report with all sections
Time: ~3-4 hours
```

### Deep Audit (Large, Critical Change)
```
Input: 450 files, auth system rewrite
Strategy: SURGICAL
1. Manual baseline context: read invariants, trust boundaries, validation
   patterns, and call graphs for the changed subsystem on the baseline commit
2. Deep analysis on auth changes only
3. Blast radius analysis
4. Adversarial modeling
5. Comprehensive report
Time: ~6-8 hours
```

---

## When NOT to Use This Skill

- **Greenfield code** (no baseline to compare)
- **Documentation-only changes** (no security impact)
- **Formatting/linting** (cosmetic changes)
- **User explicitly requests quick summary only** (they accept risk)

For these cases, use standard code review instead.

---

## Red Flags (Stop and Investigate)

**Immediate escalation triggers:**
- Removed code from "security", "CVE", or "fix" commits
- Access control modifiers removed (onlyOwner, internal → external)
- Validation removed without replacement
- External calls added without checks
- High blast radius (50+ callers) + HIGH risk change

These patterns require adversarial analysis even in quick triage.

---

## Tips for Best Results

**Do:**
- Start with git blame for removed code
- Calculate blast radius early to prioritize
- Generate concrete attack scenarios
- Reference specific line numbers and commits
- Be honest about coverage limitations
- Always generate the output file

**Don't:**
- Skip git history analysis
- Make generic findings without evidence
- Claim full analysis when time-limited
- Forget to check test coverage
- Miss high blast radius changes
- Output report only to chat (file required)

---

## Supporting Documentation

- **[methodology.md](methodology.md)** - Detailed phase-by-phase workflow (Phases 0-4)
- **[adversarial.md](adversarial.md)** - Attacker modeling and exploit scenarios (Phase 5)
- **[reporting.md](reporting.md)** - Report structure and formatting (Phase 6)
- **[patterns.md](patterns.md)** - Common vulnerability patterns reference

---

**For first-time users:** Start with [methodology.md](methodology.md) to understand the complete workflow.

**For experienced users:** Use this page's Quick Reference and Decision Tree to navigate directly to needed content.
## Examples

**Example 1: PR security review**
User says: "/differential-review mcp-servers#305"
Actions: Fetches PR diff, identifies security-sensitive files (*.py with argparse, Dockerfile changes), runs blast radius analysis (which services affected, what breaks on rollback), checks for input validation gaps, env var handling, and injection vectors.
Result: Risk assessment table with 2 HIGH findings (hardcoded port, missing input validation on user-supplied path), 1 MEDIUM (broad except clause), suggested fixes inline.

**Example 2: Commit diff review**
User says: "review the changes on this branch before I ship"
Actions: Runs `git diff main...HEAD`, classifies each file by risk tier, checks for secrets in env blocks, validates CI workflow SHA pins, reviews Dockerfile USER directive. No security-sensitive files found.
Result: "3 files changed. Risk: LOW. No security findings. Ship when ready."

## Success Criteria

- Security-relevant changes identified within the first pass (auth, crypto, value transfer, external calls)
- Blast radius calculated for each finding (how many callers, what data flows through)
- No findings without reading the actual changed code — diff context is required evidence
- Severity judgments include transformation chain analysis (can attacker-controlled input reach the sink?)
- Pre-Conclusion Audit completed (files reviewed, checklist items, and could-not-verify gaps all listed) — the audit is MANDATORY above but was previously absent from this checklist, so a rushed pass could skip it
- Report includes both findings AND "no issues found" sections for audited areas
