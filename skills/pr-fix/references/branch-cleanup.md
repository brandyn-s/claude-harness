# Branch Cleanup Procedure (Phase 3-br)

For `[BR]` items only. Deletion requires a separately named user confirmation
after discovery. The unit of authorization is `(branch, expected_sha)`, not a
repository count.

## Critical gotchas

- **Do not combine `gh api --slurp` with `--jq`.** `gh` rejects the pair
  outright (`the --slurp option is not supported with --jq or --template`) and
  exits non-zero. Piping to a separate `jq` is the only working form. This is
  not cosmetic: the failed command leaves `live.json` empty, `vetted-branches`
  then finds no candidates, and the whole axis reports **zero deletable
  branches in every repository** — a false all-clear indistinguishable from a
  genuinely clean fleet. Measured 2026-08-08: the broken form hid 10 real
  merged-and-stale branches across 5 repositories.
- **Do not treat an empty `vetted.json` as evidence of a clean repository.**
  Confirm `live.json` is non-empty first; a zero-length input is an instrument
  failure, not a measurement.

## Invariants

- Resolve the writable remote from `../_shared/repo-map.md`; it is not always
  `origin`.
- Discover squash-merged branches through merged-PR `headRefOid`, not commit
  ancestry.
- Exclude default, standing deployment, release, and merge-queue branches.
- Exclude every branch backing an OPEN PR.
- Preserve `branch expected_sha` unchanged through discovery, display,
  confirmation, and deletion.
- Delete only with an atomic expected-SHA lease. A moved branch is a SKIP.
- Never fall back to an unleased REST DELETE, `--delete`, or `--force`.

## 3-br-a: Build the vetted set

Capture live branches, merged PR heads, and open PR heads:

```bash
r=<org/repo>
STATE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/pr-fix-branches-XXXXXX")
DEFAULT_BRANCH=$(gh repo view "$r" \
  --json defaultBranchRef --jq '.defaultBranchRef.name')

# Keep the SEPARATE `jq`. `--slurp` and `--jq` are mutually exclusive: gh
# rejects the pair with a usage dump, exits 1, and leaves `live.json` EMPTY, so
# the vetted-branches helper dies on `TypeError: live and merged must be
# arrays`. `--paginate` also does not raise the page size, hence per_page=100.
gh api --paginate --slurp "repos/$r/branches?per_page=100" \
  | jq 'flatten | map({name:.name, sha:.commit.sha})' \
  > "$STATE_DIR/live.json"
test -s "$STATE_DIR/live.json"
# Join merged PRs PER LIVE BRANCH, not through a windowed bulk list. Any
# `--state merged --limit N` window is finite-depth (1000 ≈ 2.5 weeks on
# mcp-infra at 2026-08 velocity), so a branch whose PR merged before the
# window silently fell out as unvettable. Per-branch `--head` queries are
# exact for the entire live set and bounded by the branch count — this axis
# only fires above five branches (measured 2026-08-23: a windowed join
# returned vetted=0 on mcp-infra while the per-branch join proved two
# deletable branches existed).
: > "$STATE_DIR/merged-rows.jsonl"
jq -r '.[].name' "$STATE_DIR/live.json" | while IFS= read -r b; do
  gh pr list --repo "$r" --head "$b" --state merged --limit 20 \
    --json headRefName,headRefOid --jq '.[]' \
    >> "$STATE_DIR/merged-rows.jsonl"
done
jq -s '.' "$STATE_DIR/merged-rows.jsonl" > "$STATE_DIR/merged.json"
gh pr list --repo "$r" --state open --limit 300 \
  --json headRefName --jq '[.[].headRefName]' > "$STATE_DIR/open.json"

jq -n \
  --slurpfile live "$STATE_DIR/live.json" \
  --slurpfile merged "$STATE_DIR/merged.json" \
  --slurpfile open "$STATE_DIR/open.json" \
  --arg default_branch "$DEFAULT_BRANCH" \
  '{live:$live[0], merged:$merged[0], open:$open[0],
    default_branch:$default_branch}' \
  | python3 "$PR_FIX_DIR/scripts/pr_fix_state.py" vetted-branches \
  > "$STATE_DIR/vetted.json"

jq -r '.[] | "\(.branch) \(.expected_sha)"' \
  "$STATE_DIR/vetted.json" > "$STATE_DIR/vetted.txt"
```

The helper retains only a live tip whose `(name, SHA)` exactly matches a merged
PR head, whose name is not protected/standing, and which backs no open PR.
Flag accumulation when total non-standing branches exceeds five, but report
total and vetted counts separately. The per-branch join covers every live
branch exactly, so there is no unvettable window. A high total with vetted=0
is usually genuine (measured 2026-08-22/23 on mcp-infra: never-PR'd codex
branches, closed-not-merged PRs, and tips that moved after merge — all
correct conservative exclusions; also note repos with delete-on-merge clean
their own merged branches within minutes, emptying the vetted set).

## 3-br-b: Confirm the exact targets

Show every row, including the expected SHA, and ask a branch-deletion-specific
question. Do not execute deletion in the same message that first lists them.

```text
claude-config: 2 vetted branches
  fix/old-lint       71d90b6...
  chore/retired-job  a3f270c...

Delete exactly these two remote branch refs if each still has the shown SHA
and still backs no open PR?
```

A prior “proceed,” repository selection, or cleanup request that did not name
these targets is not confirmation.

## 3-br-c: Compare-and-delete

Use only the confirmed `vetted.txt`. A local clone is convenient but not
required: an empty session-owned bare repository can perform an explicit
expected-SHA leased push.

```bash
REMOTE=<writable-remote-or-repository-url>
LEASE_REPO=<mapped-local-clone>
# With no clone:
# LEASE_REPO=$(mktemp -d "${TMPDIR:-/tmp}/pr-fix-lease-XXXXXX")
# git -C "$LEASE_REPO" init --bare

while IFS=' ' read -r branch expected_sha; do
  current_sha=$(gh api "repos/$r/git/ref/heads/$branch" \
    --jq '.object.sha' 2>/dev/null || true)
  open_count=$(gh pr list --repo "$r" --head "$branch" --state open \
    --json number --jq 'length')

  if [ "$expected_sha" != "$current_sha" ] || [ "$open_count" != "0" ]; then
    echo "SKIP: $branch (moved, missing, or now backs an open PR)"
    continue
  fi

  git -C "$LEASE_REPO" push \
    --force-with-lease="refs/heads/${branch}:${expected_sha}" \
    "$REMOTE" ":refs/heads/${branch}" || {
      echo "SKIP: $branch (lease failed, already deleted, or protected)"
      continue
    }

  verify_rc=0
  git -C "$LEASE_REPO" ls-remote --exit-code \
    "$REMOTE" "refs/heads/$branch" >/dev/null 2>&1 || verify_rc=$?
  case "$verify_rc" in
    0) echo "VERIFY-FAILED: $branch still exists" ;;
    2) echo "DELETED: $branch at $expected_sha" ;;
    *) echo "VERIFY-UNKNOWN: $branch readback failed (rc=$verify_rc)" ;;
  esac
done < "$STATE_DIR/vetted.txt"
```

The preflight improves the report; the lease is the race-safe control. If the
remote ref changes after preflight, the push fails atomically. Never retry by
removing the lease.

## 3-br-d: Report

Report each branch as `DELETED`, `SKIP`, or `VERIFY-FAILED`, with its expected
SHA. `VERIFY-UNKNOWN` is not success. Read back the repository branch list and
state the remaining total. When no longer needed, remove only `$STATE_DIR` and
any empty bare repository created by this run.

## Guardrails

- Exact target confirmation is mandatory.
- A SHA mismatch, OPEN PR, API uncertainty, protected branch, or lease failure
  is a skip, not a reason to widen the operation.
- Never delete standing branches (`main`, `master`, `dev`, `develop`,
  `staging`, `stage`, `prod`, `production`, `release`, `preview`) or
  `gh-readonly-queue` refs.
- Remove only temporary state created by this run; never sweep sibling clones
  or worktrees.
