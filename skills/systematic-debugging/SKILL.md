---
name: systematic-debugging
description: "Root-cause-first debugging — gather evidence, form hypotheses, test systematically."
when_to_use: 'Use when encountering any bug, test failure, or unexpected behavior, including when the user asks why something is not working or broken. Enforces root-cause-first debugging: gather evidence, form hypotheses, test systematically — never guess-and-fix. Trigger phrases: "debug this", "debug why", "debug what", "why is X failing", "why is X not working", "why is X broken", "X is not working", "X is not working again", "X no longer working", "find the root cause", "test failure". Do NOT use for known issues with documented fixes, for adding new features, or for MCP-server-specific issues (any "X mcp not working" / "why is X mcp broken" pattern routes to /mcp-diagnose — that skill owns MCP diagnostics).'
argument-hint: "[error message or symptom to debug]"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Bash Read Grep Agent AskUserQuestion
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


# Systematic Debugging

> Forked from superpowers v4.3.1. Local additions are marked with `[EXAMPLE]` —
> grep the marker for the current set (a hardcoded count here drifted stale).

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue

**Don't skip when:**
- Issue seems simple (simple bugs have root causes too)
- You're in a hurry (rushing guarantees rework)
- Manager wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully**
   - Don't skip past errors or warnings
   - They often contain the exact solution
   - Read stack traces completely
   - Note line numbers, file paths, error codes

### `[EXAMPLE]` Infrastructure Diagnostic Pattern

For ECS, Terraform, CI, or API failures — before any hypothesis:

1. **Write a boto3 diagnostic script** (10 seconds to run locally)
2. **Read the actual error** — ECS `describe-services` events, CloudWatch `filter_log_events`, Terraform apply logs
3. **For API errors reported by user**: pull CloudWatch logs IMMEDIATELY with the error code as filter — do not hypothesize
4. **Never ship a "fix" without first confirming what's broken**

See `rules/diagnose-before-fix.md` for the full pattern. The rule says the same thing this phase teaches, but for Example's specific infrastructure.

2. **Reproduce Consistently**
   - Can you trigger it reliably?
   - What are the exact steps?
   - Does it happen every time?
   - If not reproducible -> gather more data, don't guess

3. **Check Recent Changes**
   - What changed that could cause this?
   - Git diff, recent commits
   - New dependencies, config changes
   - Environmental differences

4. **`[EXAMPLE]` Enumerate Mechanisms Before Hypothesizing**

   **BEFORE forming any theory about the cause, read the affected component's
   code and list every unusual operation.** Trace forward from the code, not
   backward from the error message.

   - Read initialization, setup, and teardown paths with the same scrutiny
     as the execution path. Connection setup is not "boilerplate" -- it's
     where extensions load, modes change, and state mutates.
   - List everything the code does that is non-obvious: loaded extensions,
     monkey-patches, global state mutations, background threads, signal
     handlers, atexit hooks, imported-but-unused modules.
   - For each unusual operation, ask: "Could this cause or contribute to
     the observed error?" Write down yes/no/maybe for each.

   **The anti-pattern this prevents:** Pattern-matching the error message
   against training data (e.g., "SQLite bad parameter" -> "must be thread
   safety") instead of reading what the code actually does. In a 2026-03-28
   session, 30 "bad parameter" errors were attributed to concurrent SQLite
   access because the error message matched that pattern. The actual cause
   was an unused sqlite-vec C extension loaded on every connection -- 8
   lines in a 2000-line file, read but not connected to the error because
   the hypothesis was already formed.

   **Do this BEFORE step 5.** Hypotheses formed after reading the code
   forward are mechanistic. Hypotheses formed from error messages are
   pattern-matched guesses.

5. **Gather Evidence in Multi-Component Systems**

   **WHEN system has multiple components (CI -> build -> signing, API -> service -> database):**

   **BEFORE proposing fixes, add diagnostic instrumentation:**
   ```
   For EACH component boundary:
     - Log what data enters component
     - Log what data exits component
     - Verify environment/config propagation
     - Check state at each layer

   Run once to gather evidence showing WHERE it breaks
   THEN analyze evidence to identify failing component
   THEN investigate that specific component
   ```

   **Example (multi-layer system):**
   ```bash
   # Layer 1: Workflow
   echo "=== Secrets available in workflow: ==="
   [ -n "$IDENTITY" ] && echo "IDENTITY: SET" || echo "IDENTITY: UNSET"

   # Layer 2: Build script
   echo "=== Env vars in build script: ==="
   env | grep -q '^IDENTITY=' && echo "IDENTITY in environment" || echo "IDENTITY not in environment"

   # Layer 3: Signing script
   echo "=== Keychain state: ==="
   security list-keychains
   security find-identity -v

   # Layer 4: Actual signing
   codesign --sign "$IDENTITY" --verbose=4 "$APP"
   ```

   **This reveals:** Which layer fails (secrets -> workflow OK, workflow -> build FAIL)

6. **Trace Data Flow**

   **WHEN error is deep in call stack:**

   See `root-cause-tracing.md` in this directory for the complete backward tracing technique.

   **Quick version:**
   - Where does bad value originate?
   - What called this with bad value?
   - Keep tracing up until you find the source
   - Fix at source, not at symptom

### Phase 2: Pattern Analysis

**Find the pattern before fixing:**

1. **Find Working Examples**
   - Locate similar working code in same codebase
   - What works that's similar to what's broken?

2. **Compare Against References**
   - If implementing pattern, read reference implementation COMPLETELY
   - Don't skim - read every line
   - Understand the pattern fully before applying

3. **Identify Differences**
   - What's different between working and broken?
   - List every difference, however small
   - Don't assume "that can't matter"

4. **Understand Dependencies**
   - What other components does this need?
   - What settings, config, environment?
   - What assumptions does it make?

### Phase 3: Hypothesis and Testing

**Scientific method:**

1. **`[EXAMPLE]` Form Multiple Hypotheses**
   - Generate **at least 2** candidate explanations before committing to any
   - **Generate across all 6 failure mode categories** to avoid tunnel vision:

     | Category | What to check |
     |----------|---------------|
     | **Logic Error** | Wrong conditional, off-by-one, missing edge case, wrong algorithm |
     | **Data Issue** | Invalid input, type mismatch, null where value expected, encoding/serialization |
     | **State Problem** | Race condition, stale cache, wrong initialization, unintended mutation |
     | **Integration Failure** | API contract violation, version incompatibility, config mismatch, missing env var |
     | **Resource Issue** | Memory leak, connection pool exhaustion, file handle leak, disk/quota |
     | **Environment** | Missing dependency, wrong library version, platform-specific behavior, permissions |

     (wshobson/agents parallel-debugging ACH framework — Context7 registry 2026-04-06)

   - For each: "I think X is the root cause because Y"
   - Write them ALL down before testing any
   - Rank by: (a) evidence from Phase 1, (b) simplicity, (c) testability
   - Test the highest-ranked first, but keep the others visible

   **The anti-pattern this prevents:** Committing to the first plausible
   theory and seeking confirming evidence. In the same 2026-03-28 session,
   "concurrent SQLite access" was hypothesis A. Once formed, investigation
   only sought confirming evidence (found FastMCP's thread pool). Hypothesis
   B ("unused extension modifies connection") was never generated because
   A was already committed to. Requiring 2+ hypotheses forces re-reading
   the code looking for DIFFERENT explanations, breaking tunnel vision.

   **If you can only think of one hypothesis:** You haven't read the code
   thoroughly enough. Return to Phase 1 step 4 (Enumerate Mechanisms).

### `[EXAMPLE]` Evidence Strength Evaluation

   Before testing hypotheses, classify the evidence supporting each one:

   | Tier | Type | Example | Weight |
   |------|------|---------|--------|
   | 1 | **Direct** | Code shows the mechanism (read the function, traced the data flow) | Strongest — test this hypothesis first |
   | 2 | **Correlational** | Symptom correlates with a change (git blame, timing, config diff) | Moderate — verify causation |
   | 3 | **Testimonial** | Error message pattern-matches training data ("X usually means Y") | Weak — most common source of wrong hypotheses |
   | 4 | **Absence** | "Nothing else could cause this" (argument from elimination) | Weakest — only valid after exhausting tiers 1-2 |

   **Rank hypotheses by evidence tier, not by plausibility.** A hypothesis
   backed by Direct evidence (you read the code and see the bug) beats a
   hypothesis backed by Testimonial evidence (the error message reminds you
   of a similar bug) even if the Testimonial one "feels" more likely.

   The sqlite-vec incident (2026-03-28): "concurrent SQLite access" was Tier 3
   (error message pattern matching). "Unused C extension modifies connection"
   was Tier 1 (code shows the mechanism). Tier 1 was correct. 30 turns wasted
   on Tier 3.
   (Pattern source: wshobson/agents ACH framework — Context7 registry evaluation 2026-04-05)

### `[EXAMPLE]` Parallel Hypothesis Investigation

> Selectively cloned from tobihagemann/turbo `/investigate` parallel
> hypothesis pattern. Added budget constraints and merge protocol.

**When 3+ hypotheses are generated AND the problem is not a simple
typo/import/syntax error**, spawn parallel investigators to test hypotheses
concurrently instead of sequentially:

1. Launch one Agent subagent per hypothesis (model: "opus", foreground).
   Each receives: the hypothesis, relevant file paths, what evidence to
   look for, and a budget of **max 5 tool calls**.
2. Each subagent reports: **Confirmed** / **Refuted** / **Inconclusive**
   with the specific evidence found.
3. After all complete, merge results into the hypothesis table.

**Skip parallel dispatch when:**
- 1-2 hypotheses where the stack trace points directly to the bug
- Simple issues (typo, missing import, syntax error)
- Hypotheses are sequential (testing H2 requires H1's result)

**Cycle budget**: Maximum 2 parallel rounds before escalating to the user.
If all hypotheses are refuted after 2 rounds, present findings and ask for
direction rather than generating more hypotheses autonomously.

   2. **Test Minimally**
   - Make the SMALLEST possible change to test hypothesis
   - One variable at a time
   - Don't fix multiple things at once

3. **Verify Before Continuing**
   - Did it work? Yes -> Phase 4
   - Didn't work? Test NEXT hypothesis from list
   - DON'T add more fixes on top

4. **When You Don't Know**
   - Say "I don't understand X"
   - Don't pretend to know
   - Ask for help
   - Research more

### Phase 4: Implementation

**Fix the root cause, not the symptom:**

1. **Create Failing Test Case**
   - Simplest possible reproduction
   - Automated test if possible
   - One-off test script if no framework
   - MUST have before fixing
   - Use the `test-driven-development` skill for writing proper failing tests

2. **Implement Single Fix**
   - Address the root cause identified
   - ONE change at a time
   - No "while I'm here" improvements
   - No bundled refactoring

3. **Verify Fix**
   - Test passes now?
   - No other tests broken?
   - Issue actually resolved?

4. **If Fix Doesn't Work**
   - STOP
   - Count: How many fixes have you tried?
   - If < 3: Return to Phase 1, re-analyze with new information
   - **If >= 3: STOP and question the architecture (step 5 below)**
   - DON'T attempt Fix #4 without architectural discussion

5. **If 3+ Fixes Failed: Question Architecture**

   **Pattern indicating architectural problem:**
   - Each fix reveals new shared state/coupling/problem in different place
   - Fixes require "massive refactoring" to implement
   - Each fix creates new symptoms elsewhere

   **STOP and question fundamentals:**
   - Is this pattern fundamentally sound?
   - Are we "sticking with it through sheer inertia"?
   - Should we refactor architecture vs. continue fixing symptoms?

   **Discuss with the user before attempting more fixes**

   This is NOT a failed hypothesis - this is a wrong architecture.

## Red Flags - STOP and Follow Process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it differently"
- "Here are the main problems: [lists fixes without investigation]"
- Proposing solutions before tracing data flow
- **"One more fix attempt" (when already tried 2+)**
- **Each fix reveals new problem in different place**
- **"The error message means X" (without reading the code first)**

**ALL of these mean: STOP. Return to Phase 1.**

**If 3+ fixes failed:** Question the architecture (see Phase 4.5)

## Signals You're Doing It Wrong

**Watch for these redirections:**
- "Is that not happening?" - You assumed without verifying
- "Will it show us...?" - You should have added evidence gathering
- "Stop guessing" - You're proposing fixes without understanding
- "Ultrathink this" - Question fundamentals, not just symptoms
- "We're stuck?" (frustrated) - Your approach isn't working
- **"Are these the best options?" - You committed to a hypothesis without alternatives**
- **"Review your recommendations" - You shipped a fix for an unverified cause**

**When you see these:** STOP. Return to Phase 1.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. Process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "I'll write test after confirming fix works" | Untested fixes don't stick. Test first proves it. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Causes new bugs. |
| "Reference too long, I'll adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms != understanding root cause. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. Question pattern, don't fix again. |
| **"The error message is a known X issue"** | **Error messages describe symptoms. Read the code to find the mechanism.** |
| **"I only need one theory"** | **One theory = confirmation bias. Two theories = investigation.** |

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, **enumerate mechanisms**, gather evidence | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare | Identify differences |
| **3. Hypothesis** | Form **2+ theories**, test minimally | Confirmed or next hypothesis |
| **4. Implementation** | Create test, fix, verify | Bug resolved, tests pass |

## When Process Reveals "No Root Cause"

If systematic investigation reveals issue is truly environmental, timing-dependent, or external:

1. You've completed the process
2. Document what you investigated
3. Implement appropriate handling (retry, timeout, error message)
4. Add monitoring/logging for future investigation

**But:** 95% of "no root cause" cases are incomplete investigation.

## Supporting Techniques

These techniques are part of systematic debugging and available in this directory:

- **`root-cause-tracing.md`** - Trace bugs backward through call stack to find original trigger
- **defense-in-depth** (planned, not yet written) - Add validation at multiple layers after finding root cause
- **condition-based-waiting** (planned, not yet written) - Replace arbitrary timeouts with condition polling

**Related skills:**
- **test-driven-development** - For creating failing test case (Phase 4, Step 1)
- **verification-before-completion** - Verify fix worked before claiming success

## Prevention Checklist (After Fix)

After resolving the bug, prevent recurrence:

1. **Test**: Regression test written that would catch this bug?
2. **Documentation**: Anything to add to runbooks, topic files, or inline comments?
3. **Tooling**: Could a lint rule, hook, or CI check catch this earlier?
4. **Pattern**: Is this a recurring class of bug? Should it inform a rule or skill?

(Pattern source: chriswiles/claude-code-showcase — Context7 registry 2026-04-06)

## Real-World Impact

From debugging sessions:
- Systematic approach: 15-30 minutes to fix
- Random fixes approach: 2-3 hours of thrashing
- First-time fix rate: 95% vs 40%
- New bugs introduced: Near zero vs common
## Examples

**Example 1: ECS service crash**
User says: "the MCP server keeps crashing after deploy"
Actions: Read actual error from ECS events and CloudWatch logs FIRST (no guessing), generate 2+ hypotheses from evidence, investigate each with specific diagnostic commands, identify root cause, implement fix with test.
Result: Root cause identified with evidence, fix implemented and verified.

**Example 2: Intermittent test failure**
User says: "this test passes locally but fails in CI"
Actions: Read CI logs for the actual failure, check for environment differences (OS, Python version, network access), generate hypotheses (timing, state leakage, missing fixture), test each.
Result: Environmental root cause identified with reproducible fix.
## Success Criteria

- Actual error read from logs/output BEFORE any hypothesis is formed
- Minimum 2 hypotheses generated for non-obvious bugs
- Each hypothesis tested with a specific diagnostic command, not just reasoning
- Fix includes a test that would have caught the original bug
- If 3+ fix attempts fail, architecture questioning gate triggers — step back and challenge assumptions
