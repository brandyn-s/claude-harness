# Conflict Rebase (Phase 3-conflict)

For `[PR-CONFLICT]` items authored by the authenticated actor. Never rebase or
force-push another author's branch. Read
[`repair-worktree.md`](repair-worktree.md) first.

## Staleness gate

| PR age | Default |
|---|---|
| under 3 days | Rebase using this procedure |
| 3–7 days | Run `diagnose.md` §2a-pre supersession triage FIRST; rebase only what survives it, warning that a substantive conflict is likely |
| over 7 days | Ask whether to close or rebase before touching the branch |

The 3–7 day triage-first row is measured, not cautionary: on 2026-08-22,
5 of 5 rebase attempts on 4–6-day-old PRs hit substantive conflicts, and
supersession evidence closed 4 of them without a worktree. On high-velocity
repos the rebase attempt is usually the wasted step, and it costs a fetch,
a worktree, and an abort each time.

## Procedure

Hydrate `headRefName` and `headRefOid` immediately before creating the
worktree. Use the mapped clone only as a worktree host:

```bash
SOURCE_REPO=<mapped-clone>
REMOTE=<writable-remote>
HEAD_REF=<hydrated-headRefName>
EXPECTED_HEAD=<hydrated-headRefOid>
DEFAULT_BRANCH=$(gh repo view <org/repo> \
  --json defaultBranchRef --jq '.defaultBranchRef.name')
BASE_REF="$REMOTE/$DEFAULT_BRANCH"
TEMP_BRANCH=pr-fix/rebase-<pr>-<session-suffix>
WORKTREE=$(mktemp -d "${TMPDIR:-/tmp}/pr-fix-rebase-<repo>-XXXXXX")

git -C "$SOURCE_REPO" fetch "$REMOTE" "$DEFAULT_BRANCH" \
  "refs/heads/${HEAD_REF}:refs/remotes/${REMOTE}/${HEAD_REF}"
test "$(git -C "$SOURCE_REPO" rev-parse "$REMOTE/$HEAD_REF")" = "$EXPECTED_HEAD"
git -C "$SOURCE_REPO" worktree add --detach "$WORKTREE" "$EXPECTED_HEAD"
git -C "$WORKTREE" switch -c "$TEMP_BRANCH"
test -z "$(git -C "$WORKTREE" status --porcelain)"

git -C "$WORKTREE" log "$BASE_REF..$TEMP_BRANCH" --oneline
```

After reading the commit list and diffs, choose exactly one rebase path. Preserve
all substantive commits with a plain rebase:

```bash
git -C "$WORKTREE" rebase "$BASE_REF"
```

Or, only when verified auto-generated checkpoint commits form a contiguous
prefix before every substantive PR commit, drop that prefix by naming its last
commit:

```bash
git -C "$WORKTREE" rebase --onto \
  "$BASE_REF" <last-checkpoint-to-drop> "$TEMP_BRANCH"
```

Every excluded commit is eligible for removal only after reading its diff: its
message is a checkpoint/timestamp, it is an automated snapshot, and it contains
no intentional work. A checkpoint after or between substantive commits is not
this simple prefix case; preserve it with the plain rebase unless the user
authorizes a separately reviewed history edit. When uncertain, keep it and ask.

After tests and a clean status, update the PR branch with the exact pre-rebase
lease:

```bash
git -C "$WORKTREE" push \
  --force-with-lease="refs/heads/${HEAD_REF}:${EXPECTED_HEAD}" \
  "$REMOTE" "HEAD:refs/heads/${HEAD_REF}"
```

If the lease fails, the remote moved. Fetch and reassess; never retry with
unconditional force. If the rebase conflicts substantively, abort in the
repair worktree and report the files rather than guessing a resolution.

When push verification succeeds, remove only this clean worktree:

```bash
test -z "$(git -C "$WORKTREE" status --porcelain)"
git -C "$SOURCE_REPO" worktree remove "$WORKTREE"
```

Rehydrate the PR afterward. If auto-merge is absent and queue state is
explicitly null, arm it with the repository-appropriate command; a non-null
`mergeQueueEntry` is already queued and must not be re-armed.

## Failure handling

- A dirty shared checkout is irrelevant; do not stash or switch it.
- A dirty new worktree, SHA mismatch, failed fetch, unknown queue state, or
  failed cleanup is reported and left safe.
- A failed rebase is aborted inside the dedicated worktree.
- Only `--force-with-lease` with the hydrated expected SHA may update the PR
  branch.
