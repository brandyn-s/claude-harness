# Isolated Repair Worktree

Read this before any `[PR-FAIL]`, `[PR-CONFLICT]`, or `[CI]` code change.
Existing clones are lookup/control points only. Never stash, switch, reset, or
edit a shared checkout; another session may own its branch or dirty state.

Every refspec here braces the variable before the colon
(`${HEAD_REF}:refs/…`, never `$HEAD_REF:refs/…`): under zsh — this host's
Bash-tool shell — `$VAR:r` applies the `:r` history modifier to the
expansion and silently corrupts the refspec into `…efs/remotes/…`
(measured 2026-08-22: two consecutive fetches failed exactly this way).
Do not "simplify" the braces away.

## Existing PR branch

Resolve the source clone and writable remote from `../_shared/repo-map.md`. If
there is no clone, clone on demand into a unique temporary directory. From an
existing clone, create a detached dedicated worktree at the exact hydrated PR
head:

```bash
SOURCE_REPO=<mapped-clone>
REMOTE=origin
HEAD_REF=<hydrated-headRefName>
EXPECTED_HEAD=<hydrated-headRefOid>
WORKTREE=$(mktemp -d "${TMPDIR:-/tmp}/pr-fix-<repo>-XXXXXX")

git -C "$SOURCE_REPO" fetch "$REMOTE" \
  "refs/heads/${HEAD_REF}:refs/remotes/${REMOTE}/${HEAD_REF}"
test "$(git -C "$SOURCE_REPO" rev-parse "$REMOTE/$HEAD_REF")" = "$EXPECTED_HEAD"
git -C "$SOURCE_REPO" worktree add --detach "$WORKTREE" "$EXPECTED_HEAD"
test "$(git -C "$WORKTREE" rev-parse HEAD)" = "$EXPECTED_HEAD"
```

If either SHA check fails, stop and rehydrate the PR. Do not repair stale code.
Run the repository's dependency/bootstrap step in the new worktree before the
first build when dependencies are not tracked.

Read the PR diff and failure logs, edit only in `$WORKTREE`, run targeted tests,
then commit. Push the detached commit to the PR's branch with an expected-SHA
lease so a concurrent push fails safely:

Before editing, call `mcp__codebase-memory-mcp__index_status`. When the repair
repository is indexed, use `mcp__codebase-memory-mcp__search_code` for variants
of the diagnosed pattern and `mcp__codebase-memory-mcp__trace_call_path` for
affected callers. When it is not indexed, state that limitation and keep the
fix scoped to source and test evidence already read.

```bash
git -C "$WORKTREE" add <fixed-files>
git -C "$WORKTREE" commit -m "fix: <description>"
git -C "$WORKTREE" status --short
git -C "$WORKTREE" push \
  --force-with-lease="refs/heads/${HEAD_REF}:${EXPECTED_HEAD}" \
  "$REMOTE" "HEAD:refs/heads/${HEAD_REF}"
```

A lease rejection means the PR moved. Fetch, inspect the new commits, and
rebuild or rebase the fix; never bypass it with `--force`.

## Commit-CI branch

There is no existing PR branch. Fetch the default branch and create a new,
session-unique branch in its own worktree:

```bash
SOURCE_REPO=<mapped-clone>
REMOTE=origin
BASE_REF="$REMOTE/main"
BRANCH=fix/<short-description>-<session-suffix>
WORKTREE=$(mktemp -d "${TMPDIR:-/tmp}/pr-fix-<repo>-XXXXXX")

git -C "$SOURCE_REPO" fetch "$REMOTE" main
git -C "$SOURCE_REPO" worktree add -b "$BRANCH" "$WORKTREE" "$BASE_REF"
test "$(git -C "$WORKTREE" branch --show-current)" = "$BRANCH"
```

Make and verify the fix in `$WORKTREE`, push `-u "$REMOTE" "$BRANCH"`, and
create the PR with an explicit `--repo`. Never update the shared clone's local
`main` as part of this workflow.

## Cleanup

After a successful push, ensure the repair worktree is clean, leave it, and
remove only the exact worktree created by this run:

```bash
test -z "$(git -C "$WORKTREE" status --porcelain)"
git -C "$SOURCE_REPO" worktree remove "$WORKTREE"
```

If cleanup fails, report the exact path. Do not force-remove it and do not sweep
sibling worktrees. A clone created on demand may be removed only after checking
its status and stash list and only when its creation/removal was in the named
scope of this run.
