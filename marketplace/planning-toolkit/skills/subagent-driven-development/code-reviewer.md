# Code Reviewer Template

Reusable prompt template for dispatching a code reviewer subagent. Other
skills (notably `subagent-driven-development`) can reference this template
when they need a combined reviewer for normal product code or a quality
reviewer for a high-risk implementation whose spec review is already complete.

**Purpose:** One complete review of an implementation — requirements,
correctness, tests, maintainability, and integration concerns.

**When to use:**
- As the single combined review for normal product code
- After separate spec review for a production mutation or security boundary
- Before marking an implementation ready to ship

```
Task tool (general-purpose):
  description: "Final code review for [feature/task]"
  prompt: |
    You are performing one bounded review on a completed implementation.
    Your job is to assess requirements, code quality, correctness, and
    integration concerns before this code ships. Return one complete issue
    set; do not reserve adjacent findings for later review cycles.

    ## What Was Implemented

    [from implementer's report, or summary of the feature]

    ## Plan or Requirements Reference

    [link to plan file or summary of acceptance criteria]

    ## Commit Range

    BASE_SHA: [commit before work started]
    HEAD_SHA: [current HEAD]

    Use `git diff BASE_SHA..HEAD_SHA` to see all changes under review.

    ## Your Job

    Read the diff and the modified files, then evaluate:

    **Requirements:**
    - Does the implementation satisfy the stated acceptance criteria?
    - Did it add behavior outside the requested scope?

    **Correctness:**
    - Logic errors, edge cases, off-by-one mistakes
    - Error handling: failures handled, or silently swallowed?
    - Concurrency issues, race conditions, ordering assumptions

    **Tests:**
    - Do tests verify behavior (not just mock interactions)?
    - Are critical paths covered?
    - Are tests deterministic (no flakes from timing, randomness, ordering)?

    **Maintainability:**
    - Are names clear and accurate (match what things do, not how)?
    - Is the code readable without comments explaining what (only why)?
    - Are abstractions at the right level for the codebase?

    **File structure and decomposition:**
    - Does each file have one clear responsibility?
    - Are units decomposed so they can be understood independently?
    - Did this implementation create new files that are already large, or
      significantly grow existing files?

    **Integration:**
    - Does this integrate cleanly with surrounding code?
    - Are existing patterns followed where appropriate?
    - Are there any places where the new code conflicts with established conventions?

    ## Report Format

    **Strengths:** What this implementation does well

    **Issues:**
    - **Critical:** Bugs or design problems that must be fixed before merging
    - **Important:** Quality concerns that should be addressed
    - **Minor:** Nits, style, suggestions

    **Assessment:** One of:
    - Approved (no Critical or Important issues)
    - Changes requested (list Critical and Important issues with file:line refs)
    - Approved on re-review (use this on a follow-up review after fixes)

    Cite file:line references for every issue so the implementer can find
    the location quickly.
```

## Skill Compatibility

This file is a template, not a skill in its own right. It has no
`SKILL.md`. Other skills reference it by path:

- `skills/subagent-driven-development/SKILL.md` — combined review for normal
  product code or quality review after high-risk spec review.

If you add new references from other skills, list them above so consumers
know which workflows depend on this template.
