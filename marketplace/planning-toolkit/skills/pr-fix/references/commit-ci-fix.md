# Commit CI Fix Procedure (Phase 3-ci)

For `[CI]` failures triggered by push, schedule, or workflow dispatch. There is
no PR branch, so create a new fix branch and PR. Read
[`repair-worktree.md`](repair-worktree.md) first.

## 3-ci-a: Create an isolated branch worktree

Use a mapped clone only as the worktree host. Never stash, switch, rebase, or
edit that shared checkout.

```bash
SOURCE_REPO=<mapped-clone>
REMOTE=<writable-remote>
DEFAULT_BRANCH=$(gh repo view <org/repo> \
  --json defaultBranchRef --jq '.defaultBranchRef.name')
BASE_REF="$REMOTE/$DEFAULT_BRANCH"
BRANCH=fix/<short-description>-<session-suffix>
WORKTREE=$(mktemp -d "${TMPDIR:-/tmp}/pr-fix-ci-<repo>-XXXXXX")

git -C "$SOURCE_REPO" fetch "$REMOTE" "$DEFAULT_BRANCH"
git -C "$SOURCE_REPO" worktree add -b "$BRANCH" "$WORKTREE" "$BASE_REF"
test "$(git -C "$WORKTREE" branch --show-current)" = "$BRANCH"
test -z "$(git -C "$WORKTREE" status --porcelain)"
```

Use a session-unique branch name. If dependencies are untracked, run the
repository bootstrap/install step in the new worktree before testing.

## 3-ci-b: Diagnose and repair

Read the candidate run's logs and reverify currency using
`stale-failure-filter.md`. Edit only in `$WORKTREE`. If the repo is indexed,
search for variants of the root cause. Run targeted tests and the repository's
required validation.

## 3-ci-c: Commit and push

```bash
git -C "$WORKTREE" add <fixed-files>
git -C "$WORKTREE" diff --cached --check
git -C "$WORKTREE" commit -m "fix: <description of CI fix>"
git -C "$WORKTREE" push -u "$REMOTE" "$BRANCH"
```

Capture the explicit PR URL:

```bash
PR_URL=$(gh pr create --repo <org/repo> --head "$BRANCH" \
  --title "fix: <CI failure description>" \
  --body "$(printf '%s\n' \
    '## Summary' \
    '- Fix failing CI workflow: <workflow name>' \
    '- Run ID: <run-id>' \
    '- Error: <one-line error summary>')")
test -n "$PR_URL"
```

Queue that exact URL using the repository's merge mode. Merge-queue repos use
bare `gh pr merge "$PR_URL" --auto`; other protected repos use
`--auto --squash --delete-branch`. An unprotected repository uses an explicit
one-off direct merge. A repository-wide settings change still requires the
separate confirmation in Phase 3-ready.

## 3-ci-d: Cleanup and report

After the push and PR creation are verified:

```bash
test -z "$(git -C "$WORKTREE" status --porcelain)"
git -C "$SOURCE_REPO" worktree remove "$WORKTREE"
```

If verification fails, retain and report the exact worktree path. Do not use
`--force` and do not touch sibling worktrees.

Report the run ID, root cause, fix, commit, branch, PR URL, merge-queue state,
tests, and cleanup result.

## Guardrails

- Never commit directly to the default branch.
- Pass explicit `--repo`, branch, and PR URL targets.
- Never mutate the shared source checkout.
- Do not claim merged until live PR state is `MERGED`.
- Unless iterate mode was requested, do not wait on CI after queueing.
