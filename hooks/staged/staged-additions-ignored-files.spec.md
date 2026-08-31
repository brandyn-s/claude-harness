# Staged hook spec: extend staged-additions-guard — ignored files under an added directory

## Problem (measured 2026-08-24, mcp-servers PR #1293)
`git add <new-dir>` on a directory containing gitignored files is a SILENT
PARTIAL no-op (exit 0). The repo-wide `*.json` ignore dropped 4 eval fixtures
from the staged set; the PR merged; the shipped tool was broken-as-merged
(FileNotFoundError on fixtures reported as delivered). Merge verification
proves the PR merged — not that the intended file set was in it. Caught a PR
later only because a staged-count failed to reconcile with the on-disk count.

## Enforcement
Extend `hooks/staged-additions-guard.py` (which already inspects staged state
at commit time): when the staged set includes new files under a directory D
added this commit, run `git status --ignored --short D` (bounded to the added
dirs); if ignored files exist under D, WARN with the list and the negation
hint (`!path/**/*.ext`), requiring `CLAUDE_GIT_ALLOW_IGNORED_UNDER_ADDED=1`
or a second identical commit invocation to proceed. Warn-then-confirm, not
hard block — ignoring can be intentional.

## Tests (hooks/test-hooks/)
- known-positive: repo ignoring `*.json`; `git add dir/` with dir/{a.py,b.json}; commit -> WARN lists b.json
- known-negative: same tree with `!dir/**/*.json` negation present -> silent pass
- known-negative: ignored files exist elsewhere but not under an added dir -> silent pass
