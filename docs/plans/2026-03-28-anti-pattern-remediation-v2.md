# Anti-Pattern Remediation v2 — Corrected Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 3 anti-patterns correctly. V1 of this plan shipped 3 changes that automated the wrong thing or solved a non-problem. V2 eliminates duplication instead of automating it.

**Context from the session that produced this plan:**
- The audit-architecture skill had a discovery bug (project-scoped MCPs invisible) — **fixed in PR #391, keep**
- We built a generator to auto-sync ARCHITECTURE.md tables — **wrong approach, tables should be removed**
- We built a gate pre-filter for ship — **not effective (9% savings on 30 real PRs), remove**
- We built opt-in batch/flush mode — **correct idea, wrong implementation (should be automatic, not opt-in)**

**V1 mistakes to avoid:**
- Don't ship until outcome tests pass
- Don't automate duplication — eliminate it
- Don't build features without measuring whether the problem exists at assumed scale

---

## Task 1: Revert generator, strip tables from ARCHITECTURE.md

**Problem:** ARCHITECTURE.md has ~400 lines of tables duplicating filesystem state. PR #400 added a generator to keep them in sync. The correct fix is removing the tables.

**Files:**
- Delete: `hooks/generate-architecture.py`
- Delete: `tests/test-generate-architecture.py`
- Modify: `ARCHITECTURE.md` (remove tables, keep narrative)

**Outcome test BEFORE shipping:**
Write a script that starts from the slimmed ARCHITECTURE.md (narrative only) and verifies a session can still discover all components:
- `json.load('~/.claude.json')` finds all 34 MCP servers
- `ls rules/*.md` finds all 20 rules
- `ls skills/*/SKILL.md` finds all 45 skills
- `ls agent-memory/topics/*.md` finds all 17 topics
- ToolSearch can load tools from any MCP server

If all pass: the tables were redundant and safe to remove.

**Sections to KEEP in ARCHITECTURE.md:**
- What This Is
- Philosophy (3 principles)
- Layer 1: MCP Servers (intro paragraph + Remote servers table + Key MCP constraints). The remote servers table stays because it has deployment-specific info (OPA gating, OBO auth) that isn't in config files.
- Layer 2: Agent + Memory (worker description, dispatch protocol, topic-indexed memory description, MEMORY.md description)
- Layer 3: Skills (intro paragraph, routing precedence). Remove the 6 skill inventory tables.
- Layer 4: Hooks and Rules (intro paragraphs, hook event descriptions with inline/prompt hooks). Remove the per-event hook tables — they duplicate settings.json. Keep the narrative about what each event type does.
- Self-Improvement Loop
- Token Configuration
- CI/CD Architecture
- AWS Infrastructure
- File Map (simplified — just the directory tree structure, no per-file listings)
- Plugins
- Growth Conventions

**Sections to REMOVE:**
- Local stdio servers table
- Hosted/remote utility servers table
- All 6 skill inventory tables (Operations, Planning, Knowledge, Code Intelligence, MCP Development, System Maintenance)
- PreToolUse/PostToolUse/PostToolUseFailure/etc hook tables
- Rules table
- Topic files table
- Detailed file map listings (individual skill files, hook scripts, rule files, topic files)

---

## Task 2: Make ship batching automatic

**Problem:** `/ship batch` is opt-in. The user has to know it exists and remember to use it. The default `/ship` creates a new branch + PR every time.

**Fix:** Change the default behavior. If `/ship` detects it's already on a feature branch with commits ahead of main (from an earlier `/ship` in the same session), add to that branch instead of creating a new one. The PR stays open and gets updated.

**Files:**
- Modify: `skills/ship/SKILL.md`
- Delete: `tests/test-gate-prefilter.py` (removing gate pre-filter)
- Modify: `tests/test-ship-batch.py` (update to test automatic behavior)

**Changes to ship skill:**
- Remove the `batch` and `flush` arguments
- Remove the Gate Pre-Filter section
- Remove the Batch Mode and Flush Mode sections
- Modify Phase 4a: before creating a feature branch, check `git branch --show-current`. If already on a feature branch with commits ahead of origin/main, STAY on it. Add a new commit to the existing branch. Push. Update the PR description to include the new commit's summary. Do NOT create a new branch or PR.
- Add Phase 4k: after shipping, if this was the 2nd+ commit to the same branch, note it in the report: "Added to existing PR #N (now N commits)"

**Outcome test BEFORE shipping:**
In a temp repo, simulate:
1. First `/ship`: creates branch, commits, "pushes" — verify new branch created
2. Second `/ship`: detects existing branch, commits there — verify same branch, 2 commits ahead
3. Third `/ship`: same branch, 3 commits — verify accumulation
4. Final merge: squash all 3 — verify single commit on main with all files

---

## Task 3: Simplify Architecture Documentation Gate

**Problem:** The gate (#393) was designed to catch missing table updates. With tables removed, it only needs to fire for narrative changes — new design decisions, constraint changes, philosophy updates.

**Files:**
- Modify: `skills/ship/SKILL.md`

**Changes:**
- Narrow component patterns: only `hooks/*.py` (new hooks change the safety net narrative), `agents/*.md` (new agents change the dispatch model). Remove `rules/*.md`, `skills/*/SKILL.md`, `agent-memory/topics/*.md` — these are just files on disk, no ARCHITECTURE.md narrative to update.
- Simplify the warning: "This PR adds a new hook/agent. Does the ARCHITECTURE.md narrative need updating?"

---

## Execution Order

1. Task 1 (strip tables) — most impactful, eliminates the root cause
2. Task 2 (auto-batch) — workflow improvement, independent
3. Task 3 (simplify gate) — depends on Task 1 being done

Ship as **1 PR** after all 3 tasks pass outcome tests.

## What NOT to do

- Don't add more automation to ARCHITECTURE.md
- Don't add new gates or hooks
- Don't ship incrementally — batch all changes and validate the combined outcome
