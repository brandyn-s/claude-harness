---
name: interview
description: "Adversarially stress-test a plan, design, or proposal to expose hidden assumptions."
when_to_use: 'Adversarial stress-test for plans, designs, proposals, or skill drafts. Asks probing non-obvious questions that expose hidden assumptions, missing edge cases, and untested dependencies before committing to implementation. Use after /superplan produces a plan, before an architecture decision is locked in, or before a proposal ships to stakeholders. Trigger phrases: "interview this", "stress-test this plan", "challenge this", "poke holes", "what am I missing". Do NOT use for brainstorming (use /brainstorm), prompt enrichment (use /refine), or planning from scratch (use /superplan).'
argument-hint: "[plan, design, or proposal to interrogate]"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Read Grep Glob AskUserQuestion mcp__memory-search__memory_search
---

# interview

Adversarial interrogation of plans, designs, and proposals. Finds the hidden assumptions
before implementation does.

## When to use

- After `/superplan` produces a plan, before executing
- Before committing to an architecture decision (new skill, new hook, new rule)
- Before shipping a proposal to a teammate or stakeholder
- When the plan "looks right" but hasn't been tested against failure modes

## Phase 1: Understand the artifact

Read the plan/design/proposal. Identify the goal, the steps, the dependencies, and the
scope boundary.

## Phase 2: Generate probing questions (5-8)

Ask questions the author would NOT think to ask. Target the non-obvious.

| Category | What it targets | Example |
|----------|----------------|---------|
| **Assumption exposure** | Implicit beliefs not stated or verified | "Step 3 assumes paginated results. What if the API returns everything at once and exceeds memory?" |
| **Dependency fragility** | Steps depending on exact output from other steps | "Step 5 parses step 2's JSON. What if step 2 returns partial JSON due to timeout?" |
| **Missing error paths** | What happens when things go wrong | "The plan doesn't mention what happens if the PR check fails. Stop, retry, or skip?" |
| **Scale/edge cases** | Behavior at boundaries | "This works for 3 repos. What about 20? What about 0?" |
| **Prior art conflicts** | Whether this contradicts existing decisions | "Search memory -- has this been tried before? Was it rejected?" |
| **Ordering sensitivity** | Whether step order matters more than stated | "Would reordering steps 4 and 5 break anything?" |
| **Scope creep** | Whether the plan quietly exceeds its stated scope | "The goal says 'update config' but step 7 modifies CI. Is that in scope?" |
| **Requirements coverage** | Whether every requirement from the original request has a corresponding plan step | Decompose the original request into numbered requirements. For each, verify a plan step addresses it. "The request says 'with error recovery' — which step handles that?" (ag-grid/ag-charts plan-review specification-coverage — Context7 registry 2026-04-07) |

**Anti-patterns**: No "Have you considered...?" (too gentle). No yes/no questions (force
explanation). No questions about things the plan already addresses. No hypotheticals that
can't happen in this architecture.

## Phase 3: Present and resolve

For each question: state it, identify what breaks if the assumption is wrong, suggest how
to verify (command, file read, or test).

## Phase 4: Produce revised spec

Original plan + `## Interview Findings` section documenting what was challenged, what held,
and what changed.

## Constraints

- Minimum 5 questions, maximum 8
- Every question must reference a specific step, tool, or assumption in THIS plan
- Search memory before asking prior-art questions (use `mcp__memory-search__memory_search`)
- Skip for plans under 4 steps

## Examples

**Example 1: Multi-repo deployment plan**

Questions: "Step 4 merges mcp-servers before step 5 starts mcp-infra. If step 5 fails,
rollback for step 4 isn't documented." / "Step 3 uses `gh pr checks --watch` which returns
exit 1 on non-required failures. Does the workflow distinguish required from non-required?"

**Example 2: New skill design**

Questions: "The classification uses >7 = critical. Boundary tests at exactly 7?" /
"Dispatches 3 parallel agents but worktree limit is 2. Will this race on .git/config.lock?"

## Success Criteria

- 5-8 specific, non-obvious questions targeting hidden assumptions
- At least 3 question categories represented
- Every question references a specific step, tool, or assumption
- Answerable questions ARE answered from codebase (not left open)
- Revised spec produced with findings incorporated
- Prior art checked via memory search for at least 1 question
