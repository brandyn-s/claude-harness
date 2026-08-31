# Code Quality Reviewer Prompt Template

Use this template when dispatching a code quality reviewer subagent.

**Purpose:** Verify implementation is well-built (clean, tested, maintainable)

**Only dispatch after spec compliance review passes.**

```
Task tool (general-purpose):
  description: "Code quality review for Task N"
  prompt: |
    You are reviewing the code quality of an implementation that has already
    passed spec-compliance review. Your job is to assess whether the code is
    well-built (clean, tested, maintainable) — not whether it matches the spec.

    ## What Was Implemented

    [from implementer's report]

    ## Plan or Requirements Reference

    Task N from [plan-file]

    ## Commit Range

    BASE_SHA: [commit before task]
    HEAD_SHA: [current commit]

    Use `git diff BASE_SHA..HEAD_SHA` to see the exact changes under review.

    ## Description

    [task summary]

    ## Your Job

    Read the diff and the modified files, then evaluate:

    **Correctness:**
    - Logic errors, edge cases, off-by-one mistakes
    - Error handling: are failures handled, or do they silently swallow?
    - Concurrency issues, race conditions, ordering assumptions

    **Tests:**
    - Do tests actually verify behavior (not just mock behavior)?
    - Are critical paths covered?
    - Are tests deterministic (no flakes from timing, randomness, ordering)?

    **Maintainability:**
    - Are names clear and accurate (match what things do, not how they work)?
    - Is the code readable without comments explaining what (only why)?
    - Are abstractions at the right level for the codebase?

    **In addition to standard code quality concerns, check:**
    - Does each file have one clear responsibility with a well-defined interface?
    - Are units decomposed so they can be understood and tested independently?
    - Is the implementation following the file structure from the plan?
    - Did this implementation create new files that are already large, or
      significantly grow existing files? (Don't flag pre-existing file sizes —
      focus on what this change contributed.)

    ## Report Format

    Report your findings as:

    **Strengths:** What this implementation does well

    **Issues:**
    - **Critical:** Bugs or design problems that must be fixed before merging
    - **Important:** Quality concerns that should be addressed
    - **Minor:** Nits, style, suggestions

    **Assessment:** One of:
    - ✅ Approved (no Critical or Important issues)
    - ❌ Changes requested (list Critical and Important issues with file:line refs)
    - ✅ Approved on re-review (use this on a follow-up review after fixes)

    Cite file:line references for every issue so the implementer can find
    the location quickly.
```
