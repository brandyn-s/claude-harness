# Plan: 8 Architecture Improvements from Session Analysis

## Goal
Implement all 8 improvements identified from the alert remediation + audit session. Each improvement has a "before" baseline measurement and "after" validation test.

## Domains
- Primary: Architecture / Skill+Hook Development
- Supplementary: Infrastructure (CI/CD), Git workflow

## Constraints
- claude-config is a protected repo (branch + PR + CI + merge)
- Hook scripts must be Python (command type, not prompt type)
- Skills must follow skill-standards.md (kebab-case, SKILL.md, frontmatter)
- All changes in one batch commit per the git-hygiene batch rule
- A/B validation: each improvement has a testable before/after

---

## Phase A: Quick Wins (hooks + rules modifications)

### A1. Post-merge auto-sync hook
- Type: New PostToolUse hook on Bash matching `gh pr merge`
- Before: Manual `git checkout main && git fetch && git rebase` after every merge (done 7x this session)
- Implementation: Python script that detects `gh pr merge` in the command, extracts the repo path, runs sync
- After test: Merge a test PR and verify local main auto-syncs
- Files: `hooks/post-merge-sync.py`, `settings.json` (add hook entry)

### A2. Distill session-scoped dedup
- Type: SKILL.md modification
- Before: `/distill` re-reads entire conversation on each invocation, finding nothing new on 3rd call
- Implementation: Add instruction to check `last-distill.json` timestamp - if within current session, only analyze messages AFTER that timestamp
- After test: Run `/distill` twice; second run should say "nothing new since last distill at HH:MM"
- Files: `skills/distill/SKILL.md`

### A3. Auto-learn append-only history
- Type: Script modification
- Before: Only `last-auto-learn.json` (latest state). No trend data.
- Implementation: In session-stop.py, append one JSON line to `~/.claude/auto-learn-history.jsonl` alongside the marker write. Fields: date, session_id, status (launched/skipped), skip_reason, friction_signals, transcript_size_mb
- After test: End a session, verify history.jsonl has a new line
- Files: `hooks/session-stop.py`

## Phase B: Script Improvements

### B1. sync-repo.py PR workflow fallback
- Type: Script modification
- Before: `--push` fails 100% on org-ruleset-protected repos (125/125 failures this session)
- Implementation: In cmd_push(), catch the "Repository rule violations" error. When detected, fall back to: (1) update local clone, (2) create branch, (3) copy drifted files, (4) commit, (5) push branch, (6) create PR, (7) merge with --admin. The local clone path is already known (HOME/Documents/GitHub/claude-code-architecture).
- After test: Run `sync-repo.py --push` and verify it falls back to PR workflow and succeeds
- Files: `hooks/sync-repo.py`

## Phase C: New Skills

### C1. Security alerts skill (a separate skill (not included in this export))
- Type: New skill
- Before: Manual scan of each repo via GraphQL + REST, manual fix per repo (this session's approach)
- Implementation: Skill that (1) scans all Example repos for dependabot + code scanning alerts, (2) classifies by fix type (version bump vs code change), (3) for version bumps: auto-generates the fix, (4) creates PRs in parallel, (5) waits for CI, (6) merges
- After test: Run a separate skill (not included in this export) on a repo with a known alert, verify it creates and merges a PR
- Files: a separate skill (not included in this export)

### C2. Ship skill (`/ship`)
- Type: New skill
- Before: 6-8 manual commands per PR (branch, commit, push, PR create, CI wait, merge, sync)
- Implementation: Skill that takes uncommitted changes in a repo and runs the full PR lifecycle. Detects repo from cwd, checks if protected, runs the appropriate flow (PR or direct push). Handles the git stash workaround for hook-modified files.
- After test: Make a test change, run `/ship`, verify the full cycle completes
- Files: `skills/ship/SKILL.md`

## Phase D: Audit Improvements

### D1. Audit result caching in sentinel
- Type: Skill + script modification
- Before: Full audit re-evaluates all 20 skills (3 min) even if none changed
- Implementation: Store mtime of each SKILL.md in sentinel baseline. On next audit, skip Phase 2b for skills whose mtime hasn't changed. Cache phase results with timestamps.
- After test: Run audit twice without changing skills; second run should skip Phase 2b with "cached" note
- Files: `skills/audit-architecture/SKILL.md`, `agent-memory/sentinel/baselines.md`

### D2. Lightweight scheduled audit script
- Type: New utility script
- Before: Audit only runs when manually invoked
- Implementation: Python script that runs Phase 0 probes + baseline count comparison only. Can be run from SessionStart hook (weekly cadence check). If counts drift or probes fail, prints a warning.
- After test: Run the script manually, verify it produces a health summary
- Files: `hooks/scheduled-audit.py`

---

## Dependency Summary
A1 | A2 | A3 | B1 | C1 | C2 | D1 | D2 (all independent, fully parallel)

## Execution Path
Dispatch 4 parallel worker agents:
- Agent 1: A1 + A2 (quick hook/skill mods)
- Agent 2: A3 + B1 (session-stop.py + sync-repo.py)
- Agent 3: C1 + C2 (new skills)
- Agent 4: D1 + D2 (audit improvements)

Then: validate all 8, batch commit, single PR, merge.

## Verification Matrix
| # | Improvement | Before baseline | After validation |
|---|---|---|---|
| A1 | Post-merge sync | Manual sync needed 7x | Hook auto-syncs after merge |
| A2 | Distill dedup | 3rd /distill finds nothing | 2nd /distill says "nothing new since" |
| A3 | Auto-learn history | No trend data | history.jsonl has entries |
| B1 | sync-repo PR fallback | 125/125 push failures | Falls back to PR workflow |
| C1 | Security alerts skill | Manual per-repo scan+fix | Single skill scans+fixes all |
| C2 | Ship skill | 6-8 commands per PR | Single /ship command |
| D1 | Audit caching | Full 3-min skill eval | Cached skip on unchanged |
| D2 | Scheduled audit | Manual-only | Weekly auto-probe |
