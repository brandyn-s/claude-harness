---
name: healthcheck
description: "Quick architecture health check — hooks, config syntax, skill frontmatter, memory, and indexes."
when_to_use: 'Quick architecture health check — runs hook tests, validates config syntax, checks skill frontmatter, verifies memory consistency, detects stale file paths, ARCHITECTURE.md drift, dead routing references, and MCP index integrity. Use when: "run tests", "health check", "check everything", "run checks", "are things healthy", "validate config", "hygiene check", "verify indexes". Do NOT use for full architecture audit (/audit-architecture), change-specific validation (/validate-changes), or MCP server debugging (inspect the server with /mcp and its logs).'
argument-hint: "[optional: hooks, config, skills, memory, paths, drift, routing, targets, orphans, manifest, indexes, or omit for all]"
effort: medium
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Agent AskUserQuestion Bash Glob Grep Read
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


## healthcheck

# Quick Architecture Health Check

Fast validation of the Claude Code architecture.

**Runtime expectations**:
- All checks except hook tests: ~30 seconds total
- Check 1 hook tests: **~1 minute on macOS** (1160 cases — 1111 passed, 49
  skipped — in 88.1s, measured 2026-07-03; case count grows as hooks/skills
  are added, re-measure rather than trust this number long-term);
  **~11 minutes on the Windows host** (Git Bash subprocess overhead,
  measured 2026-05-22). Skip with `/healthcheck <name>` if you don't need
  them.

**Path convention** [Windows-only]: on the Git Bash host `~/` expands to
MSYS-style `/c/Users/...` which Python `open()` can't resolve — use
`$HOME/.claude/...` in shell snippets there. On macOS either form works.

> **Focus area**: If the user provides an argument (e.g., `/healthcheck hooks`),
> run only that check. Otherwise run all 12 total — Check 0 (freshness) plus
> the 11 main checks — with Check 0 always running first.

> **Run all at once** (no argument): prefer the orchestrator —
> `python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_all.py` (add
> `--no-hooks` to skip the ~1-min pytest). It runs Check 0 + every check,
> AUTO-STAMPS each row `[POSSIBLY STALE]` and prepends the banner when Check 0
> WARNs (so stamping is mechanical, not model-dependent), labels a
> drift/manifest-only FAIL `(WIP)` under staleness instead of forcing a hard
> UNHEALTHY, and prints the matrix + Overall in one pass. The per-check sections
> below remain the source for focused `/healthcheck <name>` runs and for
> interpreting individual results.

---

## Check 0: Main Checkout Freshness (`freshness`) — always runs first

Every other check in this skill reads from `CLAUDE_CONFIG_DIR` (default `~/.claude`).
When that checkout is stale — on a feature branch instead of `main`, many commits
behind `origin/main`, OR carrying **uncommitted tracked edits** — every downstream
check reads that state as current and findings turn into false positives.

Staleness is not only a commit-position property. An uncommitted edit is read by
the checks exactly as if it were committed, so it can MANUFACTURE findings that do
not exist in committed code (2026-08-30, below). Untracked files are reported as
context only and never trigger: the deployed dir carries a large permanent
untracked population (48 measured) against 1 tracked modification, so triggering
on them would engage the stamp on every run.

**INCIDENT 2026-05-29**: an auto-checkpoint branch left the main checkout 27
commits behind origin/main. The subsequent healthcheck reported 33 findings;
30 of them were stale-checkout artifacts (skill bodies that had been split in
a later commit, dead refs to renamed files, removed skill directories). Hours
of investigation chasing phantoms. This check exists to surface that condition
before it poisons the rest of the report.

Run the helper:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_freshness.py
```

Exit codes: `0` = fresh (on `main`, ≤5 commits behind, **no tracked
modifications**), `1` = stale, `2` = couldn't determine (not a git repo, fetch
fully blocked).

**INCIDENT 2026-08-30 (dirty ≠ clean)**: the helper measured branch and
behind/ahead only, so a checkout on `main`, 0 behind, 0 ahead, carrying an
uncommitted `settings.json` rewrite returned **PASS** — and because the
orchestrator keys both its `[POSSIBLY STALE]` stamping and its WIP-FAIL
labelling on this exit status, nothing was stamped and `Overall: UNHEALTHY`
was printed. 19 findings traced to working-tree state, not committed code:
11 drift findings from a locally regressed `ARCHITECTURE.md` (HEAD held all
11 entries), 5 drift-gate violations + 2 hook-test failures from the
`settings.json` rewrite, and 3 hook-test failures from untracked files absent
on `origin/main`. A clean worktree at `origin/main` reported 0 drift and passed
the gate. The near-miss is the point: the "fix" for those 11 was to ADD entries
`ARCHITECTURE.md` already contained — 11 duplicates.

**If Check 0 fails (WARN)**: all subsequent findings should be treated as
potentially stale. Stamp each check's output with `[POSSIBLY STALE]` and
include "main checkout was N commits behind / on branch X / N tracked files
modified" in the final summary's first line. Recovery steps are emitted by the
helper. When the WARN names dirty files, **confirm each finding against
committed state before acting on it** — cut a worktree at `origin/main` and
re-run the specific check there. A finding that does not reproduce is a
working-tree artifact, and "fixing" it can duplicate content HEAD already has.

**Why it's not a hard fail**: the user might intentionally be running the
healthcheck on a worktree mid-PR. WARN lets them proceed knowingly; the
stamp keeps the bias visible.

---

## Check 1: Hook Tests (`hooks`)

Two sub-checks: test suite results AND hook coverage.

Run the pytest test suite for all hooks. Allow up to 15 minutes — `git push`
integration tests cause occasional timeouts under concurrent load (flaky, not a
real failure; re-run the single test in isolation to confirm).

```bash
cd $HOME/.claude/hooks && python3 -m pytest test-hooks/ --tb=line -q
```

Report:
- Total tests, passed, failed, errors
- For each failure: test name + assertion + which hook is involved
- If all pass: `"Hooks: PASS — {N} tests passed"`
- If failures: `"Hooks: FAIL — {passed}/{total} passed, {failed} failures"` + details

### 1b + 1c + 1d: Hook Coverage, Error Handling & Plugin Hooks

**Run the helper** rather than re-implementing inline:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_hooks_aux.py
```

It measures coverage (each real hook has a `test_*.py`) and error handling
(a hook that reads stdin / makes syscalls MUST wrap its body in try/except —
a crash otherwise blocks every tool call on its matcher). Only ACTUAL hooks
count toward the denominators: a hook fires because it's registered in
settings.json OR reads stdin; imported helper modules (`_platform.py`,
`atomic_write.py`, `git_lock.py`, …) are reported separately, not as failures.
Counting helpers as hooks produced false WARNs (2026-06-16: `_platform.py`
flagged for no try/except; 4 helpers flagged "untested").

The same helper independently reads every `installPath` in
`plugins/installed_plugins.json` and inventories `hooks/hooks.json` by default,
or the manifest `hooks` string/array/object sources when that field is present.
The manifest field replaces the default hook file. Manifest paths must be relative, begin with `./`,
and remain inside the plugin root after symlink resolution. Inventory is
independent of enablement: each definition is tagged `enabled`, `disabled`, or
`unknown` after applying the locally observable user < project <
`settings.local.json` precedence and then marketplace/manifest
`defaultEnabled` fallback. A disabled plugin with
hook definitions is WARN because upstream #85893 shows such hooks can remain
active; unresolved state is WARN rather than being mislabeled disabled.
Managed/server-provided and session-only CLI settings are outside this static
filesystem resolver, so the tag is local evidence rather than a claim about the
effective runtime. `/hooks` and debug output remain the runtime authority.
Unreadable/malformed registry, settings, manifest, or hook metadata is FAIL: a
partial inventory must not be presented as clean.

Exit 0 = PASS, 1 = WARN, 2 = FAIL (incomplete plugin-hook inventory). Report:
- `"Hook coverage: {tested}/{total} hooks have tests"` + any untested hook
- `"Hook error handling: PASS"` or `"WARN — {M} hooks missing try/except"`
- `"Plugin hooks: PASS — {N} installed definitions"`,
  `"DISABLED PLUGIN HOOKS"` with evidence, or
  `"UNKNOWN PLUGIN HOOK STATE"` with state-source evidence, or
  `"PLUGIN HOOK INVENTORY INCOMPLETE"` with the unreadable metadata path

---

## Check 2: Config Syntax (`config`)

**Run the helper** rather than re-implementing inline:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_config.py
```

It JSON-parses each config file — settings.json, settings.local.json,
~/.mcp.json, ~/.claude.json, hooks/skill-rules.json, and the project
settings.json at `projects/$CLAUDE_PROJECT_ID/` — skipping absent ones and
reporting the first parse error with its filename. It then inventories personal
skills and legacy commands, project skills/commands from the starting directory
and every parent through the repository root, nested project skills that can
load on file access, and each installed plugin's documented default/custom/root
skill and MCP shapes. Plugin inventory is informational because plugin skills
and MCP servers have scoped runtime names and installed plugins may be disabled.
Custom `skills` directories add to the default scan, while MCP sources use their
documented merge rules. Synced enterprise skills are outside this local
collision oracle, so a PASS is bounded
to discoverable personal/project sources plus informational installed plugins.

The hard oracle compares only standalone MCP and skill/command runtime names.
An **exact, case-sensitive** match is FAIL because Claude Code can silently omit
the MCP server (#85827). Personal/project skill identity comes from the skill
directory; command identity comes from the file stem; frontmatter `name` is not
used. The guard does not NFKC-normalize, trim, or case-fold names without runtime
evidence that Claude does so. Project scopes are compared only where they can
coexist. Every finding includes both evidence paths and the rename action.
Honors `CLAUDE_CONFIG_DIR`.

If the platform-specific system `managed-mcp.json` exists, its server map is
exclusive: the guard compares only that MCP set and suppresses user, project,
and plugin MCP definitions while continuing to discover local skills. A
malformed managed file fails closed. On macOS the authoritative path is
`/Library/Application Support/ClaudeCode/managed-mcp.json` (with the documented
Linux/WSL and Windows paths selected on those platforms).

Nested recursion is limited to the active project or a verified repository and
prunes dependency/build/cache trees. Historical non-repository entries in
`~/.claude.json` are checked only at their direct project location so an old
HOME/Documents/Downloads record cannot turn this check into an unbounded walk.

Exit 0 = PASS, 1 = FAIL. Report:
- `"Config: PASS — {N} files valid; {M} MCP names vs {S} skill names, 0 exact runtime-name collisions"`
- `"Config: FAIL — {file}: {error}"` or
  `"Config: FAIL — MCP/skill name collision … rename the MCP server or skill"`

---

## Check 3: Skill Frontmatter (`skills`)

**Run the helper** rather than re-implementing inline — this is the
single source of truth for Tier A/B/C validation:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_skills.py
```

Exit codes: `0` = all pass, `1` = WARN-only (Tier B/C), `2` = at least
one Tier-A FAIL. Do NOT re-write the iteration in ad-hoc Python —
INCIDENT 2026-05-29 surfaced two systematic divergences in inline impls
(missed underscore-dir exclusion + over-broad XML pattern matching bare
placeholders).

The 15 checks the helper enforces — Tier A (Anthropic-authoritative,
FAIL: frontmatter validity, name rules with the documented
`gather-claude` exception, 500-line body cap, `## Examples` present),
Tier B (Anthropic-recommended, WARN: third-person description), and
Tier C (local conventions, WARN: Success Criteria section,
context-fork/Agent exclusion, AskUserQuestion in allowed-tools) — are
documented per-check in
[references/skill-tier-checks.md](references/skill-tier-checks.md).

> The `AskUserQuestion in allowed-tools` WARN is **two-bucket — not "add it everywhere"**: either declare the tool for a skill with a real decision gate, OR exempt a pure-pipeline skill via `PURE_PIPELINE_SKILLS` in `_check_skills.py`. Triage per skill; blanket-adding it to a non-interactive skill (e.g. `garden`, which is full-automation) is wrong.

Report:
- `"Skills: PASS — {N} skills validated"` if all pass
- `"Skills: FAIL — {N} skills, {M} Tier-A violations"` if any Tier A fail
- `"Skills: WARN — {N} passed, {M} Tier-B/C issues"` if only Tier B/C issues
- Group issues by tier and check number for easy batch fixing.

---

## Check 4: Memory Consistency (`memory`)

**Run the helper** rather than re-implementing inline:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_memory.py
```

It delegates to `doc_accuracy_audit.py`'s `audit_memory_md` — the single source
of truth, also used by Check 6. That logic correctly resolves MEMORY.md links
that point OUTSIDE the memory dir (e.g. `~/Documents/knowledge-base/topics/*.md`)
and treats intentionally-local gitignored entries as non-orphans. Do NOT re-glob
the memory dir inline: an earlier inline version assumed every link was local to
the memory dir and flagged each KB-topic link as a false "missing" finding
(2026-06-16: 3 phantom misses).

Exit 0 = PASS, 1 = WARN (orphans / missing refs), 2 = could not run audit.

Report:
- `"Memory: PASS — {N} links resolve, all consistent"` if clean
- `"Memory: WARN — {issues}"` + findings if any

---

## Check 5: Stale File Paths (`paths`)

Verify that all file paths referenced in config actually exist on disk.

Run the helper (handles 5a–5c: hook scripts, MCP args, hook-to-disk):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/check_paths.py
```

The helper uses `shlex.split` on hook command strings instead of a naive
regex — earlier ad-hoc versions pulled partial substrings out of quoted
paths (e.g. extracting `hooks/foo.py` from `"$HOME/.claude/hooks/foo.py"`
and resolving it against the wrong base), producing dozens of false
positives. Do NOT rebuild the check inline; call the helper.

Exit 0 = clean. Exit 1 = broken paths listed to stdout. Exit 2 = a config
target exists but cannot be parsed as JSON (error + recovery hint on stderr).

### 5d: Hooks declared in settings.json (not only local)

Load `$HOME/.claude/settings.json` and `$HOME/.claude/settings.local.json`. For each
PreToolUse/PostToolUse hook registration in `settings.local.json`, verify the
same hook is also registered in `settings.json`. **Windows bug GitHub #50243
(v2.1.113)**: hooks that live ONLY in `settings.local.json` silently fail to
fire. Warn on any hook that is local-only.

Report any hooks present in local but missing from settings.json.

### 5e: Staged hook specs whose fix already shipped

`hooks/staged/*.spec.md` is a work queue with **no completion mechanism** —
`/ship-hook` installs a spec but nothing deletes it, so an obsolete spec sits
there indefinitely and a later session (especially on a checkout behind
`origin/main`) re-derives solved work.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/staged-spec-staleness.py
```

Exit 0 = no stale specs. Exit 1 = at least one spec's marker is already present
in its target file; the output names the `git rm` to run. A spec with no declared
marker reports as `unverifiable` and is NEVER auto-flagged — a false "stale"
verdict would recommend deleting live work, so silence beats a wrong delete. When
adding a new staged spec, add its `target`/`marker` pair to `MARKERS` in that
script.

Incident 2026-07-28: `tail-guard-preserve-exit-status.spec.md` was read and
fully re-implemented (fix + 11 tests + 5/5 mutation kills) two days *after*
PR #1713 shipped the same spec's preferred fix. The clobber guard in `/ship`
caught it only at transplant time, when the diff showed 30 deletions that were
the real fix about to be reverted.

Report:
- `"Paths: PASS — {N} paths verified"` if all exist
- `"Paths: FAIL — {M} broken paths"` + list of missing files with which config references them
- `"Paths: WARN — {K} hooks local-only (#50243)"` if any local-only hooks detected
- `"Paths: WARN — {J} staged spec(s) already shipped"` if 5e exits 1

---

## Check 6: Documentation Accuracy (`drift`)

Run the documentation accuracy scanner:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/audit-architecture/references/doc_accuracy_audit.py 2>/dev/null
```

The scanner checks ARCHITECTURE.md, CLAUDE.md, and MEMORY.md against disk state:
- Every skill, agent, topic, rule, and MCP server on disk is mentioned in ARCHITECTURE.md
- CLAUDE.md delegation table references only skills that exist locally or in an installed plugin (`superpowers:` names are valid)
- MEMORY.md links all resolve and no orphaned files exist

If the scanner script is unavailable, fall back to manual checks:

### 6a: Count comparison

| Component | How to count actual | Where documented |
|-----------|-------------------|-----------------|
| MCP servers | Keys in `~/.mcp.json` + `~/.claude.json` (top-level AND project-scoped) | ARCHITECTURE.md server tables |
| Agents | `~/.claude/agents/*.md` (excluding TEMPLATE.md, README.md) | ARCHITECTURE.md Layer 2 agent table |
| Skills | `${CLAUDE_PLUGIN_ROOT}/skills/*/SKILL.md` directories | ARCHITECTURE.md skill inventory table |
| Hooks | `~/.claude/hooks/*.py` files | ARCHITECTURE.md hooks table |
| Rules | `~/.claude/rules/*.md` files | ARCHITECTURE.md rules section |

### 6b: Bidirectional MCP diff

Extract every MCP server name from ARCHITECTURE.md's three tables (remote,
local stdio, hosted/remote utility). Compare against actual config in BOTH
directions:
- Servers documented but NOT in config → "documented phantom"
- Servers in config but NOT documented → "undocumented server"

### 6c: Hook table diff

Extract every hook script name from ARCHITECTURE.md's hooks table. Compare
against actual `~/.claude/hooks/*.py` in BOTH directions:
- Hooks documented but NOT on disk → "documented phantom"
- Hooks on disk but NOT documented → "undocumented hook"

### 6d: CLAUDE.md stale reference check

Grep CLAUDE.md for skill names that don't exist locally or in an installed plugin under
`${CLAUDE_PLUGIN_ROOT}/skills/`. Flag deprecated references.

Report:
- `"Drift: PASS — counts match, no phantoms"` if clean
- `"Drift: WARN — {N} count mismatches, {M} phantoms, {K} undocumented"` + details

---

## Check 7: Routing Health (`routing`)

**Run the helper** rather than re-implementing inline:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_routing.py
```

It validates `~/.claude/hooks/skill-rules.json`: structure (a dict with `rules`
+ `skip_patterns`, not the legacy bare array), dead skill refs (skill dir
missing from `${CLAUDE_PLUGIN_ROOT}/skills/`), dead agent refs (agent `.md` missing from
`~/.claude/agents/`), and duplicate patterns (the second is dead under
first-match-wins). Each rule carries BOTH `skill` and `agent` keys with one set
to `null` — a null value is NOT a dead reference. Do NOT re-implement inline: an
earlier inline version treated `"skill": null` as a reference to a skill dir
named "None" and reported 85 phantom dead refs (2026-06-16).

Exit 0 = PASS, 1 = WARN. Report:
- `"Routing: PASS — {N} rules valid, no dead references"` if clean
- `"Routing: WARN — {dead} dead references, {dupes} duplicates"` + details

---

## Check 8: Skill Output Targets (`targets`)

Verify that output paths referenced by skills actually exist on disk. This
catches "designed but never-firing" features — skill steps that reference
output files or directories that were never created.
(2026-04-05: analysis found retro steps 4b-2/4c/4d, distill T3, and distill
history all had missing prerequisites. None had ever produced output.)

### Target verification table

| Skill | Step | Output target | Check type |
|-------|------|--------------|------------|
| /distill | T0-hook staging | `~/.claude/hooks/staged/` | directory exists |
| /distill | last-run marker | `~/.claude/last-distill.json` | file exists (overwritten each run — proves the skill produces output) |
| /capture | KB topics dir | `~/Documents/knowledge-base/topics/` | directory has .md files |
| /gather-repos | ledger | `~/.claude/assessed-repos.md` | file exists + has `## Assessed` |

(2026-05-03: removed `/retro Step 4c pruning` and `/retro Step 4d absorb`
rows. `/retro` was pared down — these mandatory steps had 4% and 0% real
output rates over 30 days. The output targets `harness-pruning-candidates.md`
and absorb-profile `## Violation Log` sections may return to this table if
`/garden` gains scheduled writes to them.)

(2026-06-16: removed `/distill T3 pattern files` row. distill T3 was retired
2026-06-10 (PR #1160) — folded into T4 and the `~/.claude/memory/*-patterns.md`
stubs were deleted; `~/.claude/memory/` no longer exists. The row was checking
a target for a feature that no longer ships, a permanent false WARN.)

(2026-07-03: corrected the `/distill` history row. `distill-history.jsonl`
has zero git history — no distill design ever wrote it; distill/SKILL.md
only ever writes `~/.claude/last-distill.json`, a single overwritten
session-dedup marker, not an append-log. This was the same permanent-false-WARN
class as the 2026-06-16 T3 row, found live while observing `/healthcheck`
end-to-end. Row retargeted to the file distill actually produces.)

### How to check

**Run the helper** rather than re-implementing inline:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_targets.py
```

It checks the targets in the table above against disk (KB topics needs ≥1
`.md` in the dir). Honors `CLAUDE_CONFIG_DIR`. Exit 0 = PASS, 1 = WARN.

Report:
- `"Targets: PASS — {N} output targets verified"` if all exist
- `"Targets: WARN — {M} missing targets"` + list of which skill step
  is affected and what file/dir needs to be created

**Missing targets are WARN, not FAIL** — the skill will still run, it
just won't produce output for that step (which is the problem).

---

## Check 9: Reverse Inventory (`orphans`)

Find things on disk that nothing references — debris from deregistered hooks,
completed plans, deleted consumers. Six sub-checks (9a hook scripts, 9b scripts,
9c stale plans, 9d CI workflow integrity, 9e stale local branches, 9f skill
body dead references).

Run the helper:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_orphans.py
```

Exit 0 = clean. Exit 1 = findings; stdout lists them grouped by sub-check.

The helper does the full cross-reference (settings.json + skill bodies + hook
bodies + manifests + workflows + helper exclude list) so skill-invoked CLI
utilities like `sync-repo.py` are correctly recognized, not flagged as orphans
(PR #548 deleted two such CLIs based on a settings.json-only regex check; this
helper exists to prevent that recurrence). For 9f it resolves references
against skill-local `scripts/` and `references/` subdirs before the global
`~/.claude/hooks/` and `${CLAUDE_PLUGIN_ROOT}/scripts/` — so a skill referencing its own
co-located script doesn't get flagged as dead.

Full procedure (classification rules, sub-check definitions, history of the
PR #548 misdiagnosis): `references/check-9-orphans.md`.

Report:
- `"Orphans: PASS — no unreferenced files found"` if clean
- `"Orphans: WARN — {N} finding(s)"` + the helper's stdout

---

## Check 10+12: Marketplace Manifest + Drift (`manifest`)

Source of truth: `${CLAUDE_PLUGIN_ROOT}/skills/*/SKILL.md`. Publish target:
`$HOME/.claude/marketplace/<plugin>/skills/<name>/SKILL.md`, assembled by
`${CLAUDE_PLUGIN_ROOT}/scripts/build-marketplace.py` from the `PLUGINS` list.

When healthcheck runs from an installed marketplace plugin, the repository
source tree and build script are intentionally absent. In that mode the helper
validates `.claude-plugin/dependency-lock.json`: every locked skill, composed
skill edge, shared asset, and root helper must exist inside the installed
plugin, and no undeclared skill or escaping path may be substituted. Source
mode retains the registration and byte-drift checks below.

Three failure modes, split by severity:

1. **FAIL — missing source** (PLUGINS references a file that doesn't exist):
   the marketplace bundle is broken; installers will hit missing files.
   `build-marketplace.py` won't fix it — the manifest itself needs editing
   to point at the right file. Seen 2026-05-22: `audit-patterns.md` was
   renamed but PLUGINS wasn't updated, shipping a broken bundle.
2. **FAIL — phantom registration** (PLUGINS references a deleted skill):
   same broken-bundle outcome.
3. **WARN — drift** (source and bundle bytes differ): a prior PR shipped
   source without rebuilding. Usually fixed by running
   `python3 scripts/build-marketplace.py` and committing.
4. **WARN — unregistered skill** (on disk but not in PLUGINS): might be
   intentionally local-only, or might be a missed `/ship` step. `PLUGINS` is
   a hand-written literal list with no glob-based auto-discovery — running
   `build-marketplace.py` does NOT register a new skill. Fix by adding an
   explicit `PLUGINS` entry, or adding the skill to `LOCAL_ONLY_SKILLS` in
   `_check_manifest.py` if intentionally unpublished.

Run the helper:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_manifest.py
```

Exit codes: 0 = PASS, 1 = WARN-only, **2 = FAIL** (broken bundle requires
manifest edit, not just rebuild). The helper parses `PLUGINS` via AST (not
regex) so `scripts/`, `test-fixtures/`, and non-published files are correctly
excluded from drift comparison.

Report:
- `"Manifest+Drift: PASS"` if exit 0
- `"Manifest+Drift: WARN — {N} drift/unregistered"` if exit 1
- `"Manifest+Drift: FAIL — {N} broken bundle"` if exit 2 (treat as a real
  failure; the marketplace is shipping missing files)

---

## Check 11: MCP Index Integrity (`indexes`)

Filesystem-level corruption scan across code-graph (`~/.cache/codebase-memory-mcp/*.db`) and code-search (`~/.claude_code_search/projects/*/index/`). Faster than `/index-repo --audit` and catches orphans the registry audit misses; does not need any MCP server running.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/verify-indexes.py
```

Exit 0 = clean. Exit 2 = corruption detected; stdout lists each issue.

What the script checks:
- SQLite `PRAGMA integrity_check` on every code-graph `*.db` and code-search `metadata.db` + `fts5.db`
- Orphan edges (source_id / target_id pointing to a missing node) and orphan embeddings in code-graph
- code-search `chunk_ids.pkl` ≤ 10 bytes (known 2026-04-20 empty-pickle corruption sentinel — see `~/.claude_code_search/CORRUPTION_FIX_NOTES.md`)
- code-search aborted indexes: directories with `code.index` but no `chunk_ids.pkl` or vice versa
- Orphan `*.db-wal` / `*.db-shm` sidecars where the parent `.db` has been deleted

Report:
- `"Indexes: PASS — {N} code-graph DBs + {M} code-search projects clean"`
- `"Indexes: FAIL — {K} issues"` + per-issue line, plus remediation pointers:
  - `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cleanup-indexes.py` (plan aborted-index + duplicate-hash cleanup; `--execute` to delete)
  - `/index-repo --audit` (registry-aware audit via MCP; deeper investigation for live projects)

Note: duplicate provider-hash directories (same repo indexed under multiple embedding fingerprints) and pending WAL content are NOT corruption — they're surfaced by `cleanup-indexes.py` as disk-reclaim opportunities, not healthcheck failures.

---

## Check 13: launchd Agents (`launchd`)

Every `templates/launchd/*.plist` in this repo should be installed in
`~/Library/LaunchAgents`, loaded in `launchctl list`, and exiting 0 — or recorded
as a deliberate exception.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/healthcheck/references/_check_launchd.py
```

Exit 0 = PASS (or SKIP off-macOS). Exit 1 = WARN with a per-agent line.

**Why three assertions and not one.** Both failures that motivated this check
looked healthy to everything else, and a file-existence check would have caught
only the first:

- `com.example.claude.transcript-backup.plist` sat in `templates/` for **ten days**
  without being installed. Its script's bytes were deployed to `~/.claude/bin` and
  its PR was merged, so every "is it built?" signal said yes while `launchctl list`
  had no such label and the backup had not run since the day it shipped.
- Once installed, the agent **failed its next two scheduled runs** (a bash 3.2
  empty-array expansion). It logged START and never OK. The only place that
  surfaced was the **last-exit-status column** of `launchctl list`.

So the check reports `NOT INSTALLED`, `NOT LOADED`, and `LAST EXIT <n>` as separate
findings, plus `UNDECLARED` for a loaded `com.example.*` agent with no template
(an agent nobody can reconstruct from source) and `NO LABEL` for an unreadable
template.

**A last-exit of `-` is not a failure** — it means "not run in this session", the
normal state for a daily agent that has not fired yet. Gating on it would fire
every healthy morning.

**Reads the Label with `plutil`, not `plistlib`.** `plutil` wraps CFPropertyList,
the same implementation launchd uses, so it is the semantics that decide whether an
agent actually loads. `plistlib` is strict expat and rejects files CFPropertyList
accepts — measured 2026-08-12, a template whose comment contained a double hyphen
(illegal in XML comments, tolerated by Apple's parser) yielded no Label under
`plistlib`, and the working agent then appeared as `UNDECLARED`. Choosing the
stricter parser produced a confident wrong answer about a healthy agent.

Two recorded-exception dicts live at the top of the helper, and both require a
written reason — the point of the check is that "not installed" must be a decision
rather than an accident:

- `NOT_INSTALLED_ON_PURPOSE` — a template deliberately not installed on this host
- `UNDECLARED_ON_PURPOSE` — a loaded agent whose source legitimately lives elsewhere
  (currently the three `com.example.jed-*` harness agents)

macOS-only: `launchctl` does not exist elsewhere, so the check exits 0 with a SKIP
line on other platforms rather than failing the ubuntu/windows CI legs. An
*unavailable* `launchctl` on macOS reports WARN/UNKNOWN, not PASS — an absent
instrument is not an empty result.

---

## Modifying a check

Before changing a check's behavior, target list, or output shape in
`references/_check_*.py`, look for a matching golden test at
`tests/test_check_*.py` (e.g. `_check_targets.py` ↔ `tests/test_check_targets.py`).
These pin assumptions the check script itself doesn't state — a target's
`optional` flag, an exact label string — and a narrow local re-run of just
the check script won't catch a mismatch; only the dedicated test (or the
full `pytest skills/` CI sweep) will. (2026-07-03: a Check 8 target retarget
shipped clean locally, then failed CI because `tests/test_check_targets.py`
had a golden test pinning the old "optional" label the retarget removed.)

---

## Report

Present a summary table mapping Check 0 plus each of the 11 main checks to
PASS / WARN / FAIL, plus an `Overall:` line (HEALTHY / HEALTHY-with-warnings
/ UNHEALTHY). The orchestrator (`_check_all.py`, see "Run all at once" above)
emits exactly this matrix — already `[POSSIBLY STALE]`-stamped and with
WIP-FAIL labelling applied — so prefer relaying its output over hand-assembling
the table. For failures, list actionable fix suggestions and offer to fix
auto-safe issues (orphan memory entries, dead routing rules, stale branch
cleanup, etc.).

**Freshness banner (Check 0 WARN)**: if Check 0 reported WARN, prepend
the summary with a banner naming the staleness condition ("main checkout
was N commits behind origin/main / on branch X") AND stamp each check
result with `[POSSIBLY STALE]` so the reader can discount findings.
Without this stamp, a downstream consumer can't tell stale-state artifacts
from real findings — see INCIDENT 2026-05-29 in Check 0.

Exact table format, severity precedence rule (`Manifest+Drift: FAIL` = exit 2),
and fix-suggestion conventions live in `references/report-format.md`.

---

## Success Criteria

- Check 0 (freshness) runs first and stamps subsequent findings as `[POSSIBLY STALE]` when WARN
- All 11 main checks run to completion (no silent skips)
- Hook test failures include the specific test name and assertion
- Disabled/unknown plugin hooks include plugin/event/state-source evidence; incomplete plugin metadata hard-fails
- Config errors include the file path and parse error details
- Exact case-sensitive standalone MCP/skill-or-command collisions hard-fail with both sources; plugin namespaces do not false-collide
- Skill issues grouped by type for easy batch fixing
- Memory orphans identified with specific filenames
- Stale paths identified with which config file references them
- ARCHITECTURE.md drift shows bidirectional diff (phantoms + undocumented)
- Dead routing references name the missing skill/agent
- Total runtime under 30 seconds when hook tests are excluded; ~11 minutes when `hooks` (Check 1) is run (see "Runtime expectations" near the top of this skill)

## Examples

See `references/examples.md` for 5 worked invocations covering full-run,
hooks-only, drift-after-MCP-add, routing-after-skill-delete, and
orphans-cleanup scenarios.
