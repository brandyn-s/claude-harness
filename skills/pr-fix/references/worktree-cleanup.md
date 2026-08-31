# Worktree Cleanup Procedure (Phase 3-wt)

For `[WT]` items only. Remove a linked worktree only after exact-path user
confirmation and affirmative proof that no unique work will be lost.

## Pre-pass: prunable registrations and out-of-scope roots

Before classifying candidates, split the porcelain listing three ways:

- **`prunable` entries** (git already knows the gitdir is gone) are dead
  REGISTRATIONS, not working trees — removing one deletes no files. Handle
  them first via `git worktree prune --dry-run` from the main clone, show
  the exact list, and prune only after the same exact-path confirmation as
  removals.
- **Worktrees under other tools' managed roots** (`~/.Codex`, `~/.codex`,
  `~/Documents/Codex`, `/tmp`, `$TMPDIR`) belong to those tools' lifecycles.
  Count and report them, but exclude them from removal candidates unless the
  user names them explicitly — a repo can carry 100+ such registrations
  (mcp-infra measured ~180, 2026-08-22) and sweeping them is not this
  skill's call.
- Everything else proceeds through classification below.

## Scope and kind

Run `git worktree list --porcelain` from each mapped repository. Skip the main
entry. A candidate must appear in that output and contain a `.git` **file**.
A path with a `.git` directory is a standalone clone, not a worktree: report
its status and stash count and exclude it from this workflow.

Never enumerate a home-directory glob and never bulk-force sibling paths.

## Classification

For each linked worktree, capture clean state, branch, and tip:

```bash
STATUS=$(git -C <worktree-path> status --porcelain)
BRANCH=$(git -C <worktree-path> branch --show-current)
TIP=$(git -C <worktree-path> rev-parse HEAD)
IN_USE=$(lsof -a -d cwd -- <worktree-path> 2>/dev/null | tail -n +2 | wc -l)
test -z "$STATUS"
test -n "$BRANCH"
test "$IN_USE" -eq 0
```

A dirty or detached worktree is NOT SAFE.

## A live process makes a worktree unsafe regardless of merge evidence

**A worktree that is any live process's cwd is NOT SAFE, however clean it looks
and however thoroughly its branch merged.** Merge evidence describes the branch,
not whether a process is running there now. A concurrent agent, a detached
build, or a shell in the directory all present as clean-and-merged, and removing
it corrupts that work with no warning to its owner.

Measured 2026-08-15: of 64 worktrees passing every clean/branch/merge test, one
had **3 live processes** as cwd and was otherwise indistinguishable. Two more
changed state between classification and removal, which is why this check
repeats immediately before each removal.

Next, query live PR evidence:

```bash
OPEN_COUNT=$(gh pr list --repo <org/repo> --head "$BRANCH" --state open \
  --json number --jq 'length')
MERGED_JSON=$(gh pr list --repo <org/repo> --head "$BRANCH" --state merged \
  --limit 100 --json number,headRefOid)
MERGED_MATCH=$(printf '%s\n' "$MERGED_JSON" \
  | jq --arg tip "$TIP" '[.[] | select(.headRefOid == $tip)] | length')
```

Classify as SAFE when clean and either:

1. `OPEN_COUNT == 0` and a merged PR's `headRefOid` exactly equals `TIP`; or
2. the branch has no commits unique to the verified remote default branch.

For the second path, resolve a real default ref independently of an upstream:

```bash
REMOTE=<writable-remote-from-repo-map>
DEFAULT_BRANCH=$(gh repo view <org/repo> \
  --json defaultBranchRef --jq '.defaultBranchRef.name')
git -C <repo-path> fetch "$REMOTE" "$DEFAULT_BRANCH"
DEFAULT_REF="$REMOTE/$DEFAULT_BRANCH"
git -C <worktree-path> rev-parse --verify "$DEFAULT_REF^{commit}"

UNIQUE_COUNT=$(git -C <worktree-path> rev-list --count \
  "$DEFAULT_REF..$BRANCH")
```

Never use the branch's same-name upstream for this count: a stale remote-tracking
ref at the same tip would make the count zero even when a manually deleted
branch contains unique work. An absent upstream also must never become a
negative revision. If the default branch, PR state, or ref cannot be verified,
classification is UNKNOWN and NOT SAFE.

Remote branch absence is not merge proof. A branch may have been manually
deleted while its only commits still exist in this worktree. Require the exact
merged-head match or zero unique commits.

## Confirmation

List only SAFE candidates with repository, absolute path, branch, tip, and the
proof (`merged PR #N at same SHA` or `zero unique commits`). List every skipped
path separately with its reason. Ask to remove those exact paths; a generic
cleanup instruction is not enough.

## Removal and verification

After confirmation, re-run status, the live-process check, and the applicable
proof immediately before each removal. Confirmation was granted against the
classification snapshot, and the gap between that snapshot and the removal is
long enough for a worktree to acquire processes or become dirty — 2 of 63 did on
2026-08-15. If anything changed, skip. Then:

```bash
git -C <repo-path> worktree remove <exact-worktree-path>
git -C <repo-path> worktree list --porcelain
```

Do not retry with `--force`. Ignored build output, a lock, a running process,
or any other refusal makes the result a SKIP requiring separate review.

Report each exact path as `REMOVED`, `SKIP`, or `VERIFY-FAILED`. Never claim
cleanup from command silence; confirm the path is absent from the worktree
registry and filesystem.

**Registry-absence check must compare exact entries, not substrings.** Parse
`worktree list --porcelain` into per-block `worktree <path>` values and test
equality; a substring test false-positives whenever one worktree path is a
prefix of another (measured 2026-08-22: `corpdev-pryzm` reported
VERIFY-FAILED because `corpdev-pryzmco` was still registered — all four
"failures" that run were prefix collisions, the removals had succeeded).
