# Phase 3-dirty: Ship Pending Artifacts

Use only for `[DIRTY]` items selected by the Phase 1 bucket rules.

## Invariants

- Never stage with `git add -A`.
- Auto-ship only when every non-transient dirty path is a recognized
  prior-session artifact. Mixed or feature-shaped state requires a question;
  no answer means skip.
- Never switch, stash, reset, pull, or commit in the dirty shared checkout.
- Publish from a dedicated worktree and leave the source checkout byte-for-byte
  unchanged. Cleaning its original files is a separate owner action.

## Prior-session artifacts

Record the exact selected paths and inspect both their status and diff. Create
a dedicated worktree from the remote default branch:

```bash
SOURCE_REPO=<dirty-mapped-clone>
REMOTE=<writable-remote>
DEFAULT_BRANCH=$(gh repo view <org/repo> \
  --json defaultBranchRef --jq '.defaultBranchRef.name')
BRANCH=chore/prior-session-artifacts-<session-suffix>
WORKTREE=$(mktemp -d "${TMPDIR:-/tmp}/pr-fix-dirty-<repo>-XXXXXX")

git -C "$SOURCE_REPO" fetch "$REMOTE" "$DEFAULT_BRANCH"
git -C "$SOURCE_REPO" worktree add -b "$BRANCH" "$WORKTREE" \
  "$REMOTE/$DEFAULT_BRANCH"
```

## A tracked modification from a behind checkout can be a REVERT

The dirty diff is computed against the checkout's own base, not against
`origin/main`. When that base is behind, a "modification" carries the OLD text of
every line the file has changed upstream since — so shipping it silently reverts
newer work, and the PR reads as ordinary added content.

Before transferring any **tracked** modification, measure the gap and inspect
what upstream has done to that exact file:

```bash
git -C "$SOURCE_REPO" fetch "$REMOTE" "$DEFAULT_BRANCH"
BEHIND=$(git -C "$SOURCE_REPO" rev-list --count \
  "HEAD..$REMOTE/$DEFAULT_BRANCH")
git -C "$SOURCE_REPO" log --oneline \
  "HEAD..$REMOTE/$DEFAULT_BRANCH" -- <real-file>
```

A non-empty log means upstream changed this file after the checkout's base. Diff
the working copy against `$REMOTE/$DEFAULT_BRANCH` — not against `HEAD` — and
ship only if every upstream line survives. When in doubt, exclude the file and
say why; an untracked artifact has no such hazard and can still ship.

Measured 2026-08-15: a knowledge-base checkout 88 commits behind held a modified
research file whose working copy still contained two factually wrong lines that
`origin/main` had corrected **20 minutes earlier in the same session**. Shipping
it would have reverted that correction, and nothing downstream would have caught
it. The 25 untracked artifacts beside it were safe and shipped.

## Transfer

Transfer only the reviewed paths:

- For tracked modifications and deletions, create a binary patch scoped to the
  exact paths with `git -C "$SOURCE_REPO" diff --binary -- <real-files>` and
  apply it in `$WORKTREE`.
- For a reviewed untracked artifact, create its parent directory and copy that
  exact file into `$WORKTREE` individually.
- Compare every destination file or deletion with the source diff before
  staging. Do not copy a directory or wildcard.
- Drop any untracked path already present and byte-identical on the default
  branch; another session shipped it. 14 of 25 candidates were duplicates on
  2026-08-15.

Then commit specific paths and publish:

```bash
git -C "$WORKTREE" status --short
git -C "$WORKTREE" add <real-files>
git -C "$WORKTREE" diff --cached --check
git -C "$WORKTREE" commit -m \
  "chore: ship prior-session artifacts (<short summary>)"
# A file-modifying pre-commit hook ABORTS the commit after rewriting the files.
# Re-stage and re-commit, then prove HEAD actually moved before pushing.
git -C "$WORKTREE" add <real-files>
git -C "$WORKTREE" commit -m \
  "chore: ship prior-session artifacts (<short summary>)"
test "$(git -C "$WORKTREE" rev-list --count "$REMOTE/$DEFAULT_BRANCH"..HEAD)" -ge 1
git -C "$WORKTREE" push -u "$REMOTE" "$BRANCH"
PR_URL=$(gh pr create --repo <org/repo> --head "$BRANCH" \
  --title "..." --body "...")
```

A repository whose `core.hooksPath` runs formatters (`trim trailing whitespace`,
`fix end of files`) fixes the files and exits non-zero, so **nothing is
committed**. The staged diff still looks complete and `git diff --stat
origin/main` still lists every file, so the failure is invisible unless HEAD is
checked. Measured 2026-08-15 on claude-knowledge-base: 5 files were rewritten,
the commit did not exist, and `git log -1` still showed the base commit.

Queue the exact PR URL using the repository's merge mode. Merge-queue repos use
bare `--auto`; unprotected repos use a one-off direct merge. Do not change
repository-wide settings without the separate Phase 3-ready confirmation.

After push/PR verification, remove only the clean worktree created here. Do not
restore or clean the dirty source checkout. Report that its selected paths
remain unchanged and may still appear dirty until their owning session
reconciles them with the landed commit.

## In-progress or mixed work

List the exact paths and why they appear feature-shaped, then ask whether to
ship from an isolated worktree or skip. Never offer stash as a cleanup action.
Default to skip when no answer arrives.

## Transients only

Report them as excluded and take no action. Do not delete or restore them.

## Report

For each repository state `SHIPPED`, `ASKED/SKIPPED`, or `TRANSIENTS ONLY`.
For shipped artifacts include paths, commit, PR, live merge state, dedicated
worktree cleanup, and the fact that the source checkout was left unchanged.
