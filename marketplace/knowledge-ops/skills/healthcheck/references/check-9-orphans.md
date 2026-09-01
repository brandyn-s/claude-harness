# Healthcheck — Check 9: Reverse Inventory (`orphans`)

Checks 1-8 validate forward references (does config point to real things?). Check 9 goes the opposite direction: find things on disk that nothing references. This catches debris from deregistered hooks, completed plans, deleted consumers.

## 9a: Orphan hook scripts

Glob `~/.claude/hooks/*.py`. For each file, classify it:

1. **Registered hook** — basename appears in a hook `command` string in
   `settings.json`. Not an orphan.
2. **Skill-invoked CLI utility** — basename appears in any
   `${CLAUDE_PLUGIN_ROOT}/skills/*/SKILL.md` or `${CLAUDE_PLUGIN_ROOT}/skills/*/references/*.md`
   file body. Not an orphan — it's a CLI consumed by a skill, not a
   PreToolUse/PostToolUse hook.
3. **Helper module** — file is in the known helper exclude list
   (`atomic_write.py`, `manifest_metrics.py`, `__init__.py`, files starting
   with `_`) OR is imported (not invoked as a subprocess) by another hook.
   Not an orphan.
4. **True orphan** — none of the above. Report.

Report true orphans with their category hint:
"curate-memory.py exists in hooks/ but is not registered in settings.json
and not referenced by any skill — delete or re-register."

**Why the cross-reference matters**: #548 deleted `sync-repo.py` and
`sync-knowledge.py` as "orphan hook scripts" because they were unregistered,
but both were skill-invoked CLI utilities actively consumed by `/pull-repos`,
`/capture`, `/recall`, `/retro`. Skill-body cross-reference would have
caught the misdiagnosis.

## 9b: Orphan scripts

Glob `${CLAUDE_PLUGIN_ROOT}/scripts/*.py` (excluding `_` prefixed files AND files listed
in the `KNOWN_CLI_UTILITIES` allowlist in `_check_orphans.py`). For each
remaining file, grep all `skills/*/SKILL.md` files and `hooks/*.py` files
for the script's basename. If no reference found, report as orphan.

Report: "measure-context-usage.py in scripts/ is not referenced by any skill
or hook — delete if no longer needed."

**Why the allowlist exists**: standalone CLI utilities (with a `Usage:`
docstring) are intentionally operator-invoked — the user runs them from
the shell, no skill or hook calls them programmatically. Same pattern as
`LOCAL_ONLY_SKILLS` in `_check_manifest.py`. To add a new entry, confirm
the script is a real operator tool (has a `Usage:` or argparse interface,
isn't a temporary investigation artifact) and add it to `KNOWN_CLI_UTILITIES`
with a one-line purpose comment.

## 9c: Stale plans

Glob `~/.claude/plans/*.md` and `~/.claude/plans/*.json`. For each file,
check `git log -1 --format=%ct -- <file>` to get last commit timestamp.
If older than 30 days, report as stale.

Report: "2026-03-20-sprint1-architecture-improvements.md last modified 22
days ago — delete if work is complete."

## 9d: CI workflow integrity

Glob `~/.claude/.github/workflows/*.yml`. For each file, extract all `.py`
file references (patterns like `python hooks/X.py`, `python scripts/X.py`,
`run: python X.py`). Verify each referenced file exists on disk.

Report: "tests.yml references hooks/test-routing.py which does not exist
— remove the CI step or restore the file."

## 9e: Stale local branches

Run `git branch --merged main | grep -v main` to list
branches that are already merged and safe to delete. If at least one exists,
report as a warning with the branch count.

Report: "44 merged into main — run
`git branch --merged main | grep -v main | xargs git branch -D` to clean up."

## 9f: Skill body dead references

For each `skills/*/SKILL.md`, regex for `hooks/[\w.-]+\.py` and
`scripts/[\w.-]+\.py` paths in the body text (outside code blocks that are
clearly example/template output). Verify each referenced file exists in
`~/.claude/hooks/` or `${CLAUDE_PLUGIN_ROOT}/scripts/`.

Report: "garden/SKILL.md references hooks/context-reset.py which does not
exist on disk."

## Reporting

- `"Orphans: PASS — no unreferenced files found"` if clean
- `"Orphans: WARN — {N} orphaned files, {M} stale plans, {K} stale branches"` + details
