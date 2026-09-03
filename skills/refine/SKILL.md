---
name: refine
description: "Enrich a complex prompt with missing constraints, success criteria, and decomposition."
when_to_use: 'Use when a complex prompt needs enrichment before execution — missing constraints, ambiguous terms, no success criteria, or multi-step tasks without explicit decomposition. Trigger phrases: "refine", "refine this", "improve this prompt", "before I run this". Do NOT use for building features (use brainstorm), implementation planning (use superplan), or simple one-shot queries (just execute).'
argument-hint: "[prompt to refine]"
effort: low
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Read Glob Grep
---

# Refine — Context Engineering Before Execution

> **Output grounding (REQUIRED READ)**: when refining a prompt whose execution will produce output for a non-domain-expert user, read `skills/_shared/output-grounding.md` and make the refined prompt require its three-layer contract (confidence + provenance + counterfactual). That file is NOT ambient — it was relocated out of `rules/` on 2026-08-26 after measuring EXPOSED=0 over 438 transcripts — so it is in context only if you read it. No hook grades the final answer; the in-prompt requirement and final-output evaluation are the controls.

Lightweight context engineering that injects applicable project rules as
constraints, decomposes multi-step tasks, and specifies missing data
sources. One confirmation turn, then execute.

This is context engineering, not prompt engineering. It doesn't optimize
how the prompt is phrased — it enriches what the model knows before
executing. **Read the prompt → inject governance constraints → decompose
→ confirm → go.**

---

## Step 1: Parse the Prompt

Read `$ARGUMENTS` or the user's previous message. Identify:
- The core task (what are they trying to accomplish?)
- The task type: research, analysis, comparison, implementation, debugging
- Named entities (tools, repos, APIs, people, orgs)
- Explicit qualifiers (local/remote, environment names, time ranges)

## Step 2: Rule Scan

Scan the prompt against ALL loaded rules in `~/.claude/rules/`. The rules
are already in your context — read them semantically, not by keyword
matching. For each rule that applies, extract the specific constraint.

Common high-value matches (not exhaustive — check all loaded rules):
- Comparison/adoption prompts → compare-by-need
- Fix/debug prompts → diagnose-before-fix
- Modify/remove prompts → check-before-change
- Review/audit prompts → verify-effectiveness
- Bulk data prompts → bulk-data
- Write/mutation prompts → security-confirmations
- Test/validate prompts → verify-effectiveness
- Git/PR/commit prompts → git-hygiene
- Script/encoding prompts → platform-constraints
- Search-heavy prompts → search-efficiency

Surface only rules that apply. If zero rules match, skip this section.

**Deceptively simple check**: Short prompts containing "clean up", "delete",
"remove all", "reorganize", or "restructure" that reference directories,
bulk resources, or shared state are NOT simple — they need decomposition
even if they're one sentence. Do not pass these through the escape hatch.

## Step 3: Escape Hatch (AFTER rule scan)

If the prompt is already specific — has explicit steps, data sources, and
success criteria — AND no rules triggered in Step 2, say "Looks specific
enough, executing" and proceed directly.

If the prompt is specific but rules DID trigger, present only the
constraints section (skip gap analysis) and ask to confirm.

## Step 4: Gap Analysis

Check the prompt for these five gaps. Only surface gaps that actually
exist — do not manufacture gaps in a clear prompt.

1. **Ambiguous terms** — words that need definition for execution.
   Propose a concrete interpretation; if genuinely unclear, ask.
2. **Missing data sources** — tasks referencing data without saying where.
   Specify the tool, API, or file path. **Respect explicit qualifiers**:
   when the user says "local," propose local sources (files, local MCP
   indexes); when they say "remote" or "cloud," propose APIs. Never
   substitute a remote API for a source the user qualified as local, or
   vice versa. This also applies to environment assumptions — do not
   assume ECS when the user didn't specify, or local when they said cloud.
3. **Missing success criteria** — what does "done" look like?
   Propose criteria based on the task type.
4. **Decomposition** — multi-step tasks that should be explicit steps
   with dependencies noted. Mark parallel-safe steps.
5. **Skill routing** — steps that map to existing skills or workflows.
   Distinguish between:
   - **→ invoke /skill-name**: the step should trigger this skill
   - **→ uses pattern from skill-name**: apply the skill's approach
     without formal invocation

**Escalation check**: If the enrichment would exceed 3 constraints +
3 clarifications + 7 steps, the prompt is complex enough for /superplan.
Flag it: "This is complex enough for /superplan — proceed with /refine
anyway, or switch?" Also escalate if gap analysis reveals a genuine design
problem (multiple valid approaches, unclear requirements) or the task needs
domain-specific operational context.

## Step 5: Present Enriched Prompt

Present the enriched version in this format:

```
## Enriched Prompt

### Constraints (from rules)
- [rule]: [specific constraint that applies to this prompt]

### Clarifications
- "[ambiguous term]" → [proposed definition or question]

### Steps
1. [concrete step] — source: [data source], tool: [tool/skill]
2. [step] — depends on: [step N]
   ...

### Success Criteria
- [what done looks like]
```

Ask: **"Execute this, or adjust?"**

## Step 6: Execute or Adjust

- User says "go" / "execute" / "yes" → execute (see below)
- User says "change X" → apply the change, re-present only if substantial
- User says "too much" → strip to constraints + decomposition only, execute
- User says "skip" → execute the original prompt as-is, no enrichment

**What "execute" means**: Proceed with the enriched context as the working
prompt. For steps marked "→ invoke /skill-name", invoke those skills at
the appropriate step. For steps marked parallel-safe, dispatch via agents
if independent. The enriched prompt replaces the original — work from
the decomposed steps, not the original prose.

---

## Examples

**Example 1: Research/comparison task**

User: `/refine Review my last 14 days of local session transcripts. Compare my skills with Trail of Bits. Recommend where to incorporate their skills.`

Enriched:
- **Constraints**: compare-by-need — verify each gap causes real friction; don't feature-list compare. verify-effectiveness — a review reports what it measured and what it did not.
- **Clarifications**: "incorporate" → three options: (a) drop-in import, (b) merge logic into existing skill, (c) chain skill. "Local transcripts" → `~/.claude/projects/*/` conversation files, memory-search MCP, or code-search MCP
- **Steps**: (1) Search local session data for skill usage patterns (14d), (2) Inventory existing skills, (3) Read ToB skills, (4) Compare by need — only recommend where real friction exists, (5) Recommend with evidence per gap
- **Success criteria**: Every recommendation cites a real usage gap from step 1, not a feature-list observation

**Example 2: Debugging task**

User: `/refine The code-graph MCP server keeps timing out`

Enriched:
- **Constraints**: diagnose-before-fix — read actual error before proposing any fix
- **Clarifications**: Which environment — local or ECS? Since when? (Must ask — no qualifier given)
- **Steps**: (1) Ask user for environment, (2) Read logs from that environment's source, (3) Diagnose from actual error, (4) Fix the actual cause
- **Success criteria**: Root cause identified from logs before any code change

**Example 3: Already-specific prompt, no rules triggered**

User: `/refine Run Semgrep on mcp-servers targeting Python files, important-only mode, save SARIF to ~/output/`

Response: "Looks specific enough, executing." → proceeds directly.

**Example 4: Deceptively simple destructive prompt**

User: `/refine Delete all unused skills from ~/.claude/skills/`

Response (escape hatch blocked — "delete all" + directory = deceptively simple):
- **Constraints**: check-before-change — search memory + git history for each skill's rationale before removing
- **Clarifications**: "unused" → not invoked in transcripts? Or not referenced by other skills? Both?
- **Steps**: (1) Inventory all skills, (2) Search local transcripts for invocation counts, (3) Check cross-references (skill A references skill B), (4) For each candidate: search git history for why it was created, (5) Present removal list for confirmation — do NOT delete without approval
- **Success criteria**: Zero skills deleted that have active cross-references or documented rationale

---

## When NOT to Use

- **Building something new** → brainstorm explores design space
- **Planning implementation** → superplan loads domain context and routes execution
- **Simple queries** → "how many open alerts?" needs no refinement
- **Emergency debugging** → diagnose-before-fix already loaded as a rule; just start

## Success Criteria

- Applicable rules surfaced via semantic scan of all loaded rules (not keyword-only)
- Ambiguous terms identified and clarified or questioned
- Explicit qualifiers in the user's prompt respected (local/remote/environment)
- Multi-step tasks decomposed with data sources per step
- Skill routing distinguishes invoke vs context-only
- Enriched prompt presented in ≤1 turn
- User confirms before execution
- Already-specific prompts with no rule matches pass through without ceremony
- Complex prompts (>3 constraints + 3 clarifications + 7 steps) escalated to /superplan
- Deceptively simple destructive prompts flagged for decomposition
