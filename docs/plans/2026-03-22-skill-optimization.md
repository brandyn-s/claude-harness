# Skill Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all critical bugs, structural gaps, token bloat, and CSO non-compliance across 42 skills identified in the 2026-03-22 evaluation.

**Architecture:** Four phases of increasing scope — critical bugs first (6 skills), then structural compliance (10 skills), then token optimization (6 skills), then CSO sweep (39 skills). Each phase is independently shippable. All changes are to markdown files in `~/.claude/skills/`.

**Tech Stack:** Markdown (YAML frontmatter), Python (for bulk edits in Phase 4)

---

## Phase 1: Critical Bugs (6 tasks)

### Task 1: Fix YAML frontmatter in garden

**Files:**
- Modify: `~/.claude/skills/garden/SKILL.md:1-15`

**Step 1: Read the current frontmatter**

Current broken state (line 5 `model: sonnet` is inside the `description: >` block):
```yaml
---

name: garden
description: >
model: sonnet
  Tend the digital garden knowledge base...
```

**Step 2: Fix the YAML — move `model: sonnet` before `description:`**

```yaml
---

name: garden
model: sonnet
description: >
  Tend the digital garden knowledge base. Runs a curation pass: finds orphan
  topics (no wiki-links from other pages), suggests merges for related topics,
  promotes growth stages, checks MoC coverage, and presents a garden health
  report. Use weekly or when the garden feels overgrown. Trigger phrases:
  "garden", "tend the garden", "garden health", "curate knowledge base",
  "prune topics".
  Do NOT use for capturing new knowledge (use /capture), pushing to GitHub
  (use /capture push), or operational memory audits (use /review-learnings).
argument-hint: "[omit for full health check]"
effort: low
```

**Step 3: Verify the fix**

Run: `head -16 ~/.claude/skills/garden/SKILL.md`
Expected: `model: sonnet` appears on its own line BEFORE `description: >`

---

### Task 2: Fix YAML frontmatter in sync-repo

**Files:**
- Modify: `~/.claude/skills/sync-repo/SKILL.md:1-15`

**Step 1: Read the current frontmatter**

Same bug as garden — `model: sonnet` on line 5 inside `description: >` block.

**Step 2: Fix the YAML — move `model: sonnet` before `description:`**

```yaml
---

name: sync-repo
model: sonnet
description: >
  Audit, update, and push Claude Code architecture files to the GitHub backup repo
  (example-org/claude-code-architecture). Compares documented state...
```

The rest of the description stays the same.

**Step 3: Verify the fix**

Run: `head -6 ~/.claude/skills/sync-repo/SKILL.md`
Expected: `model: sonnet` on its own line before `description: >`

---

### Task 3: Remove duplicate finding definitions in mcp-forge-audit

**Files:**
- Modify: `~/.claude/a separate skill (not included in this export):479-533`

**Step 1: Read lines 467-534 to confirm the duplication boundaries**

Lines 468-478 define B6, B7, W9, W10, I14, I15, B8, W11, W12, I16 in a table.
Lines 479-488 repeat the exact same table rows.
Lines 497-533 repeat the detailed definitions of B6, B7, W9, W10, I14, I15, B8, W11, W12, I16 that were already defined at lines 490-528.

**Step 2: Delete the duplicate content**

Remove lines 479-488 (duplicate table rows) and lines 509-533 (duplicate detailed definitions). Keep only the first occurrence of each.

**Step 3: Verify no duplicate finding codes remain**

Run: `grep -c "^\*\*B6:" ~/.claude/a separate skill (not included in this export)
Expected: `1` (not `2`)

Run: `grep -c "^\*\*W12:" ~/.claude/a separate skill (not included in this export)
Expected: `1` (not `2`)

---

### Task 4: Fix stale MCP tool reference in preflight

**Files:**
- Modify: `~/.claude/skills/preflight/SKILL.md:35`

**Step 1: Replace the stale tool name**

Change line 35 from:
```
ToolSearch("select:mcp__codebase-memory-mcp__index_status")
```
To:
```
ToolSearch("select:mcp__code-graph__index_status")
```

Also update line 60 output example from:
```
  [x] MCP: code-search loaded, codebase-memory-mcp loaded
```
To:
```
  [x] MCP: code-search loaded, code-graph loaded
```

**Step 2: Verify**

Run: `grep "codebase-memory-mcp" ~/.claude/skills/preflight/SKILL.md`
Expected: no matches

---

### Task 5: Fix broken cost-analyze skill

**Files:**
- Modify: `~/.claude/skills/cost-analyze/SKILL.md`

The skill delegates entirely to a nonexistent `analyze.py`. Since the skill is meant to be lightweight (model: sonnet, effort: low), rewrite it to contain the analysis logic inline rather than creating a complex script.

**Step 1: Rewrite SKILL.md with inline analysis process**

```markdown
---

name: cost-analyze
description: >
  Use when analyzing Claude Code session costs or optimizing token spend.
  Trigger phrases - "cost analyze", "cost breakdown", "how much am I spending".
  Do NOT use for real-time monitoring (statusline does that).
argument-hint: "[overview|deep|optimize] [7d|30d]"
model: sonnet
effort: low
---

# Cost Analyze

Analyze Claude Code session costs from conversation logs.

## Modes

| Mode | What it does |
|------|-------------|
| `overview` | Dashboard: total spend, sessions, avg cost/session |
| `deep` | Attribution: cost by model, by tool, by skill |
| `optimize` | Recommendations: identify expensive patterns |

## Process

**Step 1: Collect session data**

Use `mcp__claude_platform__get_claude_code_usage_report` with the requested
time range (default: 7 days). If MCP unavailable, read conversation logs
from `~/.claude/projects/*/conversations/`.

**Step 2: Analyze by mode**

- **overview**: Sum input/output tokens, compute cost at model rates
  (Opus: $5/$25 per 1M, Sonnet: $3/$15 per 1M, Haiku: $1/$5 per 1M).
  Present as dashboard table.
- **deep**: Break down by model, group by skill invocations (grep for
  "Launching skill:" in transcripts), identify top-5 most expensive sessions.
- **optimize**: Flag sessions with >100K output tokens, subagent fan-out >5,
  repeated tool calls (>10 of same tool), and skills running on Opus that
  could run on Sonnet.

**Step 3: Present results**

Format as tables. Include total estimated cost and comparison to previous period.

## Success Criteria

- Cost breakdown presented as formatted tables
- Recommendations are actionable (specific skills/patterns to change)
- Time range matches user request
```

**Step 2: Verify**

Run: `wc -w ~/.claude/skills/cost-analyze/SKILL.md`
Expected: ~250-300 words (a functional skill, not 80)

---

### Task 6: Fix gather-claude fork vs. approval contradiction

**Files:**
- Modify: `~/.claude/skills/gather-claude/SKILL.md`

**Step 1: Read the approval steps to understand the contradiction**

The skill has `context: fork` but Steps 14-15 demand interactive user approval.
`gather-research` (a sibling) correctly handles this: "Write findings automatically
(this skill runs in context: fork and cannot prompt for approval)."

**Step 2: Update the approval steps to match fork behavior**

Find the interactive approval steps (likely near the end of the file) and change
them to auto-write, matching gather-research's pattern. Add a note:
"This skill runs in `context: fork` and cannot surface prompts to the parent session.
Findings are written automatically."

**Step 3: Verify consistency**

Grep for "wait for" or "approval" or "confirmation" in the file:
Run: `grep -i "wait for\|approval\|confirmation" ~/.claude/skills/gather-claude/SKILL.md`
Expected: No remaining references to waiting for user approval (only references
to the auto-write behavior).

---

## Phase 2: Structural Compliance (10 tasks)

Each of these skills is missing required Examples and/or Success Criteria sections.
The pattern is the same for all: add a `## Examples` section with 2 concrete
scenarios and a `## Success Criteria` section with 3-5 bullet points.

### Task 7: Add Examples + Success Criteria to codebase-memory-exploring

**Files:**
- Modify: `~/.claude/skills/codebase-memory-exploring/SKILL.md` (append before end)

**Step 1: Add sections**

```markdown
## Examples

**Example 1: Explore repo structure**
User: "What's the architecture of this codebase?"
→ Run `search_graph` with `query: "MATCH (m:MODULE) RETURN m.name, m.file_path"`
→ Present module map with file counts per directory

**Example 2: Find all API routes**
User: "Show me all the API endpoints"
→ Run `search_graph` with `query: "MATCH (f:FUNCTION)-[:DECORATED_BY]->(d) WHERE d.name = 'route' RETURN f.name, f.file_path"`
→ Present route table with HTTP methods

## Success Criteria

- Codebase structure presented as organized hierarchy
- Functions/classes listed with file locations
- Relationships between modules identified
- Output is actionable (user can navigate to specific files)
```

---

### Task 8: Add Examples + Success Criteria to codebase-memory-quality

**Files:**
- Modify: `~/.claude/skills/codebase-memory-quality/SKILL.md` (append before end)

**Step 1: Add sections** (same pattern — 2 examples, 3-5 success criteria bullets focused on dead code and quality analysis)

---

### Task 9: Add Examples + Success Criteria to codebase-memory-reference

**Files:**
- Modify: `~/.claude/skills/codebase-memory-reference/SKILL.md` (append before end)

**Step 1: Add sections** (2 examples showing real Cypher queries, success criteria about correct tool selection)

---

### Task 10: Add Examples + Success Criteria to codebase-memory-tracing

**Files:**
- Modify: `~/.claude/skills/codebase-memory-tracing/SKILL.md` (append before end)

**Step 1: Add sections** (2 examples showing call chain tracing, success criteria about complete caller/callee identification)

---

### Task 11: Add Examples + Success Criteria to cross-repo

**Files:**
- Modify: `~/.claude/a separate skill (not included in this export)

**Step 1: Add workflow steps for each mode** (currently one-liners — expand to 3-5 steps with actual git commands)

**Step 2: Add Examples + Success Criteria sections**

---

### Task 12: Add Examples + Success Criteria to guardrail

**Files:**
- Modify: `~/.claude/a separate skill (not included in this export)

**Step 1: Add concrete boto3/CLI commands for each mode** (list, add, remove, test)

**Step 2: Add Examples + Success Criteria sections**

---

### Task 13: Add Examples + Success Criteria to index-repo

**Files:**
- Modify: `~/.claude/skills/index-repo/SKILL.md` (append)

**Step 1: Add sections** (2 examples: new repo indexing, re-index after code changes)

---

### Task 14: Add Success Criteria to obsidian

**Files:**
- Modify: `~/.claude/a separate skill (not included in this export) (append)

**Step 1: Add Success Criteria** (what successful onboard/offboard looks like)

---

### Task 15: Add Examples to resume

**Files:**
- Modify: `~/.claude/skills/resume/SKILL.md` (append)

**Step 1: Add 2 examples and a note about checkpoint creation source**

---

### Task 16: Add Examples + Success Criteria to preflight

**Files:**
- Modify: `~/.claude/skills/preflight/SKILL.md` (append)

**Step 1: Add 2 examples and success criteria**

---

### Task 17: Add cross-references to codebase-memory-* suite

**Files:**
- Modify: all 4 codebase-memory-* SKILL.md files + code-explore SKILL.md

**Step 1: Add a "Related Skills" line to each**

Add to each codebase-memory-* skill:
```markdown
> **Related:** code-explore (routing), codebase-memory-exploring, codebase-memory-quality, codebase-memory-reference, codebase-memory-tracing
```

Add to code-explore:
```markdown
> **Related:** codebase-memory-exploring, codebase-memory-quality, codebase-memory-reference, codebase-memory-tracing
```

---

## Phase 3: Token Optimization (5 tasks)

### Task 18: Extract shared STIG content to _shared

**Files:**
- Create: `~/.claude/skills/_shared/stig-common.md`
- Modify: `~/.claude/a separate skill (not included in this export)
- Modify: `~/.claude/a separate skill (not included in this export)
- Modify: `~/.claude/a separate skill (not included in this export)

**Step 1: Create `_shared/stig-common.md`** with the "Two-Repo Model" and "CKLB Handling - CRITICAL" sections

**Step 2: In each STIG skill, replace the duplicated sections with:**
```markdown
> **Required context:** Read `~/.claude/skills/_shared/stig-common.md` for the two-repo model and CKLB handling rules before proceeding.
```

---

### Task 19: Deduplicate mcp-forge-audit finding definitions into references

**Files:**
- Create: `~/.claude/a separate skill (not included in this export)
- Modify: `~/.claude/a separate skill (not included in this export)

**Step 1: Move the detailed per-code definitions (B6-B8, W7-W12, I14-I16) to the reference file**

**Step 2: Replace inline definitions with:**
```markdown
> **Finding code definitions:** See `references/finding-definitions.md` for detection logic per code.
```

Target: reduce SKILL.md from ~7100 to ~4000 words.

---

### Task 20: Deduplicate security-alerts PR workflow

**Files:**
- Modify: `~/.claude/a separate skill (not included in this export)

**Step 1: Replace Phase 5's PR creation workflow (~80 lines) with a reference to /ship:**
```markdown
### Phase 5: Create PRs

For each repo with fixes, follow the /ship skill Phase 4 workflow with these additions:
- Branch prefix: `fix/security-`
- Commit message includes GHSA ID: `fix(deps): bump X to Y (GHSA-xxxx)`
- PR body references the alert URL
```

---

### Task 21: Extract review-learnings output template to references

**Files:**
- Create: `~/.claude/skills/review-learnings/references/output-format.md`
- Modify: `~/.claude/skills/review-learnings/SKILL.md`

**Step 1: Move the ~70-line output format template and lossy compression guidance to the reference file**

**Step 2: Replace with one-line reference**

---

### Task 22: Create shared repo map

**Files:**
- Create: `~/.claude/skills/_shared/repo-map.md`
- Modify: `~/.claude/skills/pr-fix/SKILL.md` (reference shared map)
- Modify: `~/.claude/a separate skill (not included in this export) (reference shared map)
- Modify: `~/.claude/a separate skill (not included in this export) (reference shared map)

**Step 1: Create the shared repo map** with all managed repos, local paths, and GitHub URLs

**Step 2: In each skill, replace the inline repo list with:**
```markdown
> **Repos:** See `~/.claude/skills/_shared/repo-map.md` for the current repo list.
```

---

## Phase 4: CSO Description Sweep (1 task, bulk edit)

### Task 23: Rewrite all descriptions to start with "Use when..."

**Files:**
- Modify: 39 SKILL.md files (all except investigate, mcp-diagnose, retrospective)

**Step 1: Write a Python script to audit and propose rewrites**

```python
# Read each SKILL.md, extract description, check if starts with "Use when"
# For non-compliant, propose a rewrite preserving trigger phrases and negative triggers
# Output a mapping: {skill_name: {current: "...", proposed: "Use when..."}}
```

**Step 2: Review the proposed rewrites manually** — descriptions affect discoverability, so each must be reviewed

**Step 3: Apply the approved rewrites via Python script**

**Step 4: Verify**

Run a validation pass: all 42 descriptions should now start with "Use when"

---

## Commit Strategy

- **Phase 1**: One commit — `fix: resolve 6 critical skill bugs (YAML, broken refs, missing script)`
- **Phase 2**: One commit — `feat: add missing Examples/Success Criteria to 10 skills`
- **Phase 3**: One commit — `refactor: extract shared content and reduce token bloat`
- **Phase 4**: One commit — `style: standardize all skill descriptions to "Use when..." convention`

Each phase is a separate PR to keep reviews manageable.
