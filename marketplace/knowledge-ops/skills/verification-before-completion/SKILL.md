---
name: verification-before-completion
description: "Run verification commands and confirm output before claiming work complete."
when_to_use: "Use when about to claim work is complete, fixed, or passing, before committing or creating PRs — requires running verification commands and confirming output before making any success claims. Evidence before assertions, always. Do NOT use as a standalone skill — this is a workflow pattern embedded in other skills. Do NOT use for test-driven development (use /test-driven-development)."
effort: medium
metadata:
  author: example-security-engineering
  version: "1.1"
allowed-tools: Bash Read Grep AskUserQuestion
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Outcome Reconciliation Gate

Fresh evidence can prove the wrong finish line. Before running completion gates:

1. Restate the **latest user outcome** in one sentence, including any correction that replaced an
   earlier, narrower objective.
2. Inventory all **unresolved acceptance blockers** from the plan, review findings, hosted state, release
   state, and the user's own acceptance criteria.
3. Map each verification command to the outcome it proves. A credential working, a schema matching,
   or one subtask passing is evidence for that subclaim only.
4. If any blocker remains, report the precise partial state and next action; do not call the task
   complete, final, shipped, or ready.

The completion claim is valid only when the evidence covers the user outcome—not merely the most
recent subtask.

**Monitoring operational gate:** merged, deployed, staged, or heartbeat-only is not operational.
Require an enabled live path, two natural heartbeats, one real retained event, healthy queues/DLQs,
useful classification distribution, and an accepted rendered analyst output before using that word.

**Known-root scope freeze:** once the root cause and an existing end-to-end seam oracle are known,
apply the smallest root fix and verify through that oracle. Do not add a verifier workflow, identity
permission, or telemetry dependency unless the existing oracle cannot prove the named acceptance claim.

## Authoritative Verification Gate

Use the repository's authoritative command exactly as CI, documented scripts, or `--help`
defines it; a plausible equivalent, no-op direct script, or missing enforcement flag proves
nothing. Development checks may run earlier, but defer the definitive full suite and generated
parity proof until review findings are settled, or later semantic edits will invalidate it.

Reproduce CI's dependency topology as well as its command: intentionally absent packages, import
order, editable paths, and runtime version are part of the contract. A local environment with extra
SDKs can hide the exact failure the protected lane is designed to expose.

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |


### `[EXAMPLE]` Post-Gate Improvement Checklist

After the verification gate passes (evidence confirms the claim), also assess:

1. **Correctness**: What's fragile? What's one edge case from breaking?
2. **Test quality**: What has zero automated coverage?
3. **Thresholds**: Are magic numbers calibrated or guesses?
4. **Consistency**: Do counts match across related stores?
5. **Resilience**: What happens on crash or kill -9?
6. **Doc drift**: Do docstrings match behavior?

Present the fix list alongside the verification result — don't wait to be asked. See `rules/validate-to-improve.md` and `rules/verify-effectiveness.md`.


## Self-Run Verification Gates (LLM-executed)

> Selectively cloned from eysenfalk/harness `/dod` skill. Adapted from
> 10 generic gates to Example-relevant gates.

These gates are run by the model and self-reported — no Stop/PostToolUse
hook reads their exit codes or blocks a completion claim, so the discipline
of actually running each command (not asserting it) is on you.

When the Gate Function (above) says "IDENTIFY: What command proves this
claim?" — use this checklist. Run each applicable gate and report
pass/fail in a summary table.

| Gate | Command | Pass criteria | Skip when |
|------|---------|--------------|-----------|
| 1. No TODOs/FIXMEs | `grep -rn "TODO\|FIXME\|HACK\|XXX\|TEMP\|PLACEHOLDER" <changed-files>` | Zero matches (or all have issue refs) | No code files changed |
| 2. No debug leftovers | `grep -rn "console\.log\|print(.*debug\|breakpoint()\|debugger;" <changed-files>` | Zero matches | No code files changed |
| 3. Undocumented config | `grep -rn "os\.environ\|os\.getenv\|process\.env\|env(" <changed-files>` then cross-ref with `.env.example`/docs | All new env vars documented | No env var references in changes |
| 4. Lint clean | Project linter (ruff, eslint, etc.) | Exit 0, zero errors | No code files changed |
| 5. Unit tests | `pytest tests/` or project test command | All pass, coverage meets threshold | No test files exist |
| 6. Type check | `mypy` / `pyright` / `tsc` (if configured) | Exit 0 | Not configured |
| 7. Security scan | `gitleaks detect --source .` | No secrets detected | Documentation-only change, or gitleaks not installed |
| 8. Build | Project build command | Exit 0 | No build step |
| 9. CI status | `gh pr checks` or `gh run list --limit 1` | All required checks pass | No PR/push yet |

Present results as:

```
| Gate | Status | Details |
|------|--------|---------|
| 1. No TODOs/FIXMEs | PASS | 0 matches |
| 2. No debug leftovers | PASS | 0 matches |
| 3. Undocumented config | PASS | All env vars documented |
| 4. Lint clean | PASS | ruff: 0 errors |
| 5. Unit tests | PASS | 12/12 pass |
| 6. Type check | SKIP | Not configured |
| 7. Security scan | PASS | No secrets |
| 8. Build | SKIP | No build step |
| 9. CI status | PASS | validate ✓ |
```

ALL applicable gates must PASS before claiming completion. Any FAIL
requires fixing before the claim.

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |

## Key Patterns

**Tests:**
```
✅ [Run test command] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I've written a regression test" (without red-green verification)
```

**Build:**
```
✅ [Run build] [See: exit 0] "Build passes"
❌ "Linter passed" (linter doesn't check compilation)
```

**Requirements:**
```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, phase complete"
```

**Agent delegation:**
```
✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
❌ Trust agent report
```

## Why This Matters

From 24 failure memories:
- the user said "I don't believe you" - trust broken
- Undefined functions shipped - would crash
- Missing requirements shipped - incomplete features
- Time wasted on false completion → redirect → rework
- Violates: "Honesty is a core value. If you lie, you'll be replaced."

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is non-negotiable.
## Examples

**Example 1: Post-implementation verification**
User says: [implicitly, when Claude is about to claim "done"]
Actions: Run all 9 gates — check for TODOs, scan for debug leftovers, confirm config documented, run linter, run tests, type check, security scan, build, verify CI status. Only claim completion if ALL gates pass with fresh output.
Result: Verified completion with evidence from each gate, or specific failure report.

**Example 2: Test fix verification**
User says: "fix the failing test in test_auth.py"
Actions: Read the actual test failure first, fix the code (not the test), re-run the specific test, then run the full suite, verify no regressions.
Result: Fix verified with fresh test output showing the specific test AND the full suite passing.
## Success Criteria

- No completion claims without fresh verification output in the same message
- All 9 automated gates checked: TODOs removed, no debug leftovers, config documented, lint clean, tests pass, types check, security scan clean, build succeeds, CI green
- "Fresh" means run in THIS message — cached or remembered results are not evidence
- If any gate fails, the failure is reported instead of a completion claim
