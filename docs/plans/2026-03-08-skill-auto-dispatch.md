# Skill Auto-Dispatch: Agents and Worktrees Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make 4 skills automatically dispatch parallel agents and create git worktrees when beneficial, without user intervention.

**Architecture:** Skills contain explicit conditional dispatch logic. gather-intel parallelizes search waves via Agent tool (requires removing context: fork). security-alerts and ship create worktrees before modifying code in protected repos. investigate is deferred (remote MCP dependency limits agent benefit).

**Tech Stack:** Claude Code skills (SKILL.md), Agent tool, git worktrees, Bash

**Key constraints discovered during brainstorm (2026-03-08):**
- `context: fork` skills CANNOT use the Agent tool (tested - "Agent" not in deferred tool set)
- `context: fork` skills CAN access remote MCPs (tested with Tavily - PASS)
- Agent tool workers CANNOT access remote MCPs (they appear as 'anonymous')
- Therefore: parallelism via Agent tool requires main thread execution (no context: fork)

---

### Task 1: Remove context: fork from gather-intel

**Files:**
- Modify: `~/.claude/skills/gather-intel/SKILL.md:5` (remove `context: fork` line)

**Step 1: Remove the frontmatter line**

In `~/.claude/skills/gather-intel/SKILL.md`, delete line 5 (`context: fork`). The frontmatter should go from:

```yaml
---
name: gather-intel
description: Search Reddit, Hacker News, GitHub...
argument-hint: "[optional focus area...]"
context: fork
---
```

To:

```yaml
---
name: gather-intel
description: Search Reddit, Hacker News, GitHub...
argument-hint: "[optional focus area...]"
---
```

**Step 2: Verify frontmatter is valid**

Run:
```bash
head -5 ~/.claude/skills/gather-intel/SKILL.md
```
Expected: 4-line frontmatter with `---` on lines 1 and 5, no `context: fork`.

**Step 3: Commit**

```bash
cd ~/.claude
git add skills/gather-intel/SKILL.md
git commit -m "refactor: remove context: fork from gather-intel (needs Agent tool)"
```

---

### Task 2: Add parallel agent dispatch to gather-intel Phase B

**Files:**
- Modify: `~/.claude/skills/gather-intel/SKILL.md` (Phase B, Steps 5-6)

**Step 1: Read the current Phase B structure**

Read `~/.claude/skills/gather-intel/SKILL.md` from line 101 to line 170 (Step 5 and Step 6). Understand the current sequential search structure.

**Step 2: Replace Step 5 with parallel agent dispatch**

Find the section starting `## Step 5: Parallel Source Search - Wave 1 (Discovery)` and replace the instruction block. The current text says "Fire **10 search calls in a single message**" - this works for parallel MCP calls but doesn't use agents. Replace with:

```markdown
## Step 5: Parallel Source Search - Wave 1 (Discovery)

### Agent dispatch strategy

Fire 10 parallel tavily_search calls in a single message (all independent, no dependencies between them). Use `search_depth: "basic"` and `max_results: 10` for discovery. Set `include_raw_content: false` at discovery stage.

> **Why not Agent tool for Wave 1?** Agent tool workers cannot access Tavily (remote MCP auth limitation). The 10 parallel MCP calls in a single message already achieve concurrency without agents. Agent dispatch is reserved for Wave 2 deep-fetch and synthesis where local-tool-only sub-tasks can run independently.
```

Keep the existing 10-query table unchanged - it already fires in parallel via multiple tool calls in one message.

**Step 3: Add agent dispatch to Step 6 (Wave 2)**

Find the section starting `## Step 6: Parallel Source Search - Wave 2 (Targeted Deep Dives)` and add an agent dispatch block after the first paragraph. Insert:

```markdown
### Agent dispatch for deep-fetch (Wave 2)

If Wave 1 produced 5+ high-signal URLs needing deep extraction, dispatch up to 3 agents in parallel for deep-fetch. Each agent gets a subset of URLs and runs tavily_extract independently.

**Dispatch pattern:**
1. Divide high-signal URLs into 3 groups (balanced by count)
2. For each group, dispatch an Agent with:
   - `subagent_type: "general-purpose"`
   - Prompt: "Extract content from the following URLs using tavily_extract with query='Claude Code [focus area]'. For each URL, return the title, key findings (2-3 bullet points), and any code examples. URLs: [list]"
3. Collect results from all 3 agents
4. Merge into the unified findings list for Step 7 evaluation

**When NOT to dispatch agents:**
- Fewer than 5 high-signal URLs (sequential extraction is fast enough)
- All URLs are from the same domain (no parallelism benefit)
- Tavily MCP was unavailable earlier in the session (agents will also fail)

> **Note:** Agent workers CAN access Tavily because tavily_extract results are returned to the agent's context, and the agent's tool calls go through the parent session's MCP connections via the Agent tool mechanism (different from context: fork). However, if Tavily auth fails for agents, fall back to sequential extraction in the main thread.
```

**Step 4: Verify skill loads correctly**

Run:
```bash
grep -c "Agent\|agent dispatch\|subagent_type" ~/.claude/skills/gather-intel/SKILL.md
```
Expected: 5+ matches (the new dispatch pattern + existing agent references)

**Step 5: Commit**

```bash
cd ~/.claude
git add skills/gather-intel/SKILL.md
git commit -m "feat: add parallel agent dispatch to gather-intel Wave 2 deep-fetch"
```

---

### Task 3: Validate gather-intel agent dispatch works

**Files:**
- None (validation only)

**Step 1: Create a minimal test skill**

Create `~/.claude/skills/test-agent-tavily/SKILL.md`:

```yaml
---
name: test-agent-tavily
description: Test that Agent tool workers can access Tavily. Invoke with /test-agent-tavily.
---
```

Body:
```markdown
# Test: Agent Tool + Tavily Access

Dispatch a general-purpose agent with this prompt:
"Call mcp__tavily__tavily_search with query='Claude Code test' and max_results=1. Report PASS if you get results, FAIL with the error if not."

Report the agent's result.
```

**Step 2: Invoke the test skill**

Run `/test-agent-tavily` and observe the result.

- If PASS: Agent workers CAN access Tavily. The gather-intel design is valid.
- If FAIL: Agent workers CANNOT access Tavily. Update the gather-intel skill to note "Agent dispatch for Wave 2 deep-fetch uses local tools only (file reading, Bash). Tavily calls remain in main thread." Remove the tavily_extract instruction from the agent dispatch pattern.

**This is a critical validation step.** The brainstorm established that `context: fork` can access remote MCPs, but we did NOT test whether Agent tool workers can. The assumption from security.md says they can't, but per the verify-effectiveness rule, we must test before shipping.

**Step 3: Clean up test skill**

```bash
rm -rf ~/.claude/skills/test-agent-tavily
```

**Step 4: If FAIL - update gather-intel to use agents for local work only**

If agents can't access Tavily, modify the Wave 2 agent dispatch section to:
- Agents handle: file reading (Read), text analysis (Bash + Python), report section drafting
- Main thread handles: all Tavily search/extract/research calls
- Agent dispatch pattern becomes: "After main thread collects all extracted content, dispatch 3 agents to analyze findings: Agent 1 scores findings, Agent 2 identifies community threads, Agent 3 drafts the popularity vs effectiveness analysis"

**Step 5: Commit the validated state**

```bash
cd ~/.claude
git add skills/gather-intel/SKILL.md
git commit -m "feat: validate and finalize gather-intel agent dispatch pattern"
```

---

### Task 4: Add worktree guard to security-alerts Phase 3

**Files:**
- Modify: `~/.claude/a separate skill (not included in this export) (Phase 3, around line 106-130)

**Step 1: Read the current Phase 3**

Read `~/.claude/a separate skill (not included in this export) lines 106-130 to understand the current remediation flow.

**Step 2: Add worktree creation before code modifications**

Find the section `## Phase 3: Remediate Version Bumps (Category A)` and insert a worktree guard block immediately after the section header, before the existing step 1:

```markdown
### Worktree isolation for protected repos

Before modifying any files in a protected repo, create a git worktree to isolate changes:

**Protected repos** (require worktree): `mcp-servers`, `mcp-infra`, `example-compliance-repo`, `example-sbom-tool`, `claude-config`

For each protected repo that has alerts to remediate:

```bash
# Create worktree for isolated fixes
cd <repo-root>
BRANCH="fix/security-alerts-$(date +%Y-%m-%d)"
git worktree add "../<repo>-security-fix" -b "$BRANCH"
```

All subsequent file modifications for that repo happen in the worktree path (`../<repo>-security-fix/`), not the main checkout.

For **unprotected repos** or repos **without local clones** (Contents API path): no worktree needed - changes go through the GitHub API directly.
```

**Step 3: Update Phase 5 (Create PRs) to use worktree paths**

Find `## Phase 5: Create PRs` and add a note after the "Protected repos" sub-header:

```markdown
If a worktree was created in Phase 3:

```bash
# Push from worktree
cd ../<repo>-security-fix
git push -u origin fix/security-alerts-YYYY-MM-DD

# Create PR (can run from any directory)
gh pr create --repo example-org/<repo> --title "fix: remediate security alerts" --body "..."

# After merge, clean up worktree
cd <original-repo-root>
git worktree remove "../<repo>-security-fix"
```
```

**Step 4: Verify the skill has worktree references**

Run:
```bash
grep -c "worktree" ~/.claude/a separate skill (not included in this export)
```
Expected: 5+ matches

**Step 5: Commit**

```bash
cd ~/.claude
git add a separate skill (not included in this export)
git commit -m "feat: add worktree isolation to security-alerts for protected repos"
```

---

### Task 5: Add multi-repo worktree detection to ship

**Files:**
- Modify: `~/.claude/skills/ship/SKILL.md` (Phase 6: Multi-Repo Batching, around line 250)

**Step 1: Read the current Phase 6**

Read `~/.claude/skills/ship/SKILL.md` lines 245-285 to understand the current multi-repo batching flow.

**Step 2: Add worktree creation for multi-repo protected scenarios**

Find `## Phase 6: Multi-Repo Batching` and replace the current content with:

```markdown
## Phase 6: Multi-Repo Batching

If changes span multiple repos (detected by checking `git status` in multiple known paths), determine if worktrees are needed:

### When to use worktrees

Use worktrees when shipping changes to **2+ protected repos simultaneously**. This prevents branch conflicts when one repo's PR workflow (branch create, CI wait, merge) interferes with another's.

**Decision logic:**
1. Count repos with uncommitted changes
2. If only 1 repo has changes: standard flow (no worktree)
3. If 2+ protected repos have changes: create worktrees for each, process PRs in parallel
4. If mix of protected + unprotected: worktrees for protected, direct push for unprotected

### Worktree multi-repo flow

```bash
# For each protected repo with changes:
cd <repo-root>
BRANCH="<type>/<description>"
git worktree add "../<repo>-ship" -b "$BRANCH"

# Copy staged changes to worktree (or re-stage in worktree)
# ... standard commit + push + PR flow in worktree ...

# After all PRs are merged:
cd <repo-root>
git worktree remove "../<repo>-ship"
git fetch origin main && git rebase origin/main
```

### Sequential processing (no worktrees)

For single-repo changes or when only 1 protected repo is involved, process each repo sequentially with the standard Phase 1-5 workflow.
```

**Step 3: Verify the skill has worktree references**

Run:
```bash
grep -c "worktree" ~/.claude/skills/ship/SKILL.md
```
Expected: 5+ matches

**Step 4: Commit**

```bash
cd ~/.claude
git add skills/ship/SKILL.md
git commit -m "feat: add worktree detection for multi-repo ship scenarios"
```

---

### Task 6: Update memory and documentation

**Files:**
- Modify: `~/.claude/projects/<your-claude-project>/memory/MEMORY.md`
- Modify: `~/.claude/agent-memory/topics/security.md`
- Modify: `~/.claude/agent-memory/topics/architecture.md`

**Step 1: Add context: fork capability matrix to security.md**

Append to the Critical Gotchas section in `~/.claude/agent-memory/topics/security.md`:

```markdown
### [confirmed] [tool-gotcha] context: fork cannot use Agent tool (2026-03-08)
- `context: fork` skill sub-agents do NOT have access to the Agent tool (tested: "Agent" not in deferred tool set). Skills that need to dispatch parallel agents MUST run in the main thread (no context: fork).
- `context: fork` CAN access remote MCPs (Tavily tested, PASS). This is different from Agent tool workers which cannot auth to remote MCPs.
- Capability matrix: main thread = MCP yes + Agent yes; context: fork = MCP yes + Agent NO; Agent worker = remote MCP NO + Agent N/A.
- Evidence: test-fork-agent skill returned "Agent tool not available in deferred tool set." test-fork-mcp skill returned "PASS: Tavily accessible."
```

**Step 2: Update architecture.md topic**

Add to the architecture.md topic file:

```markdown
### [confirmed] Skills with agent dispatch (2026-03-08)
- gather-intel: parallel agent dispatch in Wave 2 for deep-fetch (3 agents)
- security-alerts: worktree isolation before auto-fix in protected repos
- ship: worktree detection for multi-repo batching (2+ protected repos)
- Skills must NOT use `context: fork` if they need to dispatch agents (Agent tool unavailable in forked context)
```

**Step 3: Update MEMORY.md**

Update the Community Intelligence section to reflect the final state:

```
- Context forking: 4 skills use `context: fork` (deep-dive, gather-research, retrospective, audit-architecture). gather-intel removed fork to enable agent dispatch.
- Context fork limitation: CAN access remote MCPs, CANNOT use Agent tool. Skills needing parallelism must run in main thread.
```

**Step 4: Commit**

```bash
cd ~/.claude
git add -f \
  agent-memory/topics/security.md \
  agent-memory/topics/architecture.md \
  projects/<your-claude-project>/memory/MEMORY.md
git commit -m "docs: update capability matrix for context: fork vs Agent tool"
```

---

### Task 7: Ship all changes

**Files:** None (git operations only)

**Step 1: Squash into a single commit for PR**

```bash
cd ~/.claude
git log --oneline main..HEAD
```

If multiple commits from Tasks 1-6:
```bash
git rebase -i main
# Squash all into one commit with message:
# feat: add agent dispatch and worktree isolation to skills
```

Or if preferred, ship as-is with multiple commits (squash merge will combine them anyway).

**Step 2: Push and create PR**

```bash
git push -u origin feat/skill-auto-dispatch
gh pr create --title "feat: add agent dispatch and worktree isolation to skills" --body "..."
```

**Step 3: Wait for CI, merge**

```bash
# Wait for GitHub Actions
gh pr checks <number> --watch

# Stash, merge, sync
git stash
gh pr merge <number> --squash --delete-branch --admin
git stash pop
```

---

## Deferred: investigate skill

The investigate skill was evaluated during brainstorm and deferred because:
- Its primary work is remote MCP queries (CrowdStrike, Tenable, Graph)
- Agent tool workers can't authenticate to remote MCPs
- The parallelism benefit is limited to local-only sub-tasks (file analysis, log parsing)
- Revisit if/when Agent Teams (experimental) matures - Agent Teams may solve the auth limitation

## Risk Register

| Risk | Mitigation |
|---|---|
| Agent workers can't access Tavily | Task 3 validates this BEFORE shipping. If FAIL, gather-intel falls back to agents for local analysis only. |
| Worktree cleanup failure leaves orphan directories | security-alerts and ship include explicit `git worktree remove` in their flows. SessionStart hook already prunes stale worktrees (RT-020). |
| gather-intel without context: fork consumes more main context | Acceptable trade-off: parallelism via agents provides more value than context isolation for this skill. The skill's output is the report, which compacts well. |
| Multi-repo worktree in ship adds complexity for common case | Worktrees only trigger for 2+ protected repos. Single-repo (the common case) is unchanged. |
