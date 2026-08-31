---
name: work
description: "Create a per-session git worktree with auto-prefixed branch to isolate concurrent sessions."
when_to_use: "Create a per-session git worktree with auto-prefixed branch and emit the cd command to enter it. Use when another Claude Code session may be writing to the same repo — isolates this session, eliminating shared-HEAD races and ref clobbers (see ~/.claude/rules/git-hygiene.md INCIDENT 2026-04-17 + 2026-05-04 Family C). Trigger phrases - \"work\", \"worktree\", \"isolate session\", \"/work [branch-name]\". Do NOT use for trivial single-session edits or for repos that don't accept feature-branch PRs."
argument-hint: "[branch-name]  (omit for auto-named session branch; e.g., \"feat-cache-headers\")"
allowed-tools: Bash Read
metadata:
  author: example-security-engineering
  version: "1.0"
effort: low
---

# Work — per-session git worktree

Empirical finding (2026-05-04 Family C reflog inspection): when two
Claude Code sessions share one git working tree, one session's silent
`git checkout` shifts HEAD without the other session noticing. The
unaware session then commits to the wrong branch — or pushes a branch
whose ref was never advanced. Worktree isolation gives each session its
own HEAD and its own working tree, eliminating this class of race.

This skill creates a per-session worktree at `~/.claude/worktrees/`
with a session-tagged branch name and prints the `cd` command for the
user to enter it. A claim file is written to
`~/.claude/state/worktree-claims/` so future tooling can check
ownership.

## When to use

- Starting work in a repo where another Claude Code session may also be
  active (any of the protected repos: `.claude`, `mcp-servers`,
  `mcp-infra`, `code-search`, `code-graph`, `knowledge-base`,
  `example-compliance-repo`, `example-sbom-tool`, `claude-knowledge-base`)
- After observing the empty-push warning from `git-empty-push-guard.py`
- Before starting any non-trivial multi-commit feature in a shared repo

## When NOT to use

- The repo only ever has one active session
- Read-only inspection (no commits expected)
- Inside an existing worktree (the skill detects this and refuses)

## Step 0 — Capture session and repo identity

```bash
SESSION_ID="${CLAUDE_SESSION_ID:-$CLAUDE_CODE_SESSION_ID}"
[ -z "$SESSION_ID" ] && SESSION_ID="$(date +%s)-$$"
SUFFIX="${SESSION_ID: -8}"  # Last 8 chars include PID, ensuring uniqueness

REPO_ROOT="$(git rev-parse --show-toplevel)"
REPO_NAME="$(basename "$REPO_ROOT")"
echo "Session $SUFFIX, repo $REPO_NAME at $REPO_ROOT"
```

## Step 1 — Refuse if already in a worktree

If `git rev-parse --git-common-dir` differs from `git rev-parse
--git-dir`, the cwd is already inside a worktree. Refuse — the user is
already isolated.

```bash
GD="$(git rev-parse --git-dir)"
GCD="$(git rev-parse --git-common-dir)"
if [ "$GD" != "$GCD" ]; then
  echo "Already inside a worktree at $REPO_ROOT — nothing to do."
  exit 0
fi
```

## Step 2 — Pick branch name

If the user passed `[branch-name]` as the skill argument, use
`<branch-name>-<SUFFIX>`. Otherwise default to `wt-<SUFFIX>`. The suffix
makes the branch name unique across concurrent sessions.

The branch is cut from `origin/<default-branch>`, refreshed via fetch.

```bash
BRANCH_BASE="${1:-wt}"
BRANCH="${BRANCH_BASE}-${SUFFIX}"

git fetch --quiet origin
DEFAULT_BRANCH="$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@refs/remotes/origin/@@')"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
BASE_REF="origin/$DEFAULT_BRANCH"
SESSION_START_OID="$(git rev-parse "$BASE_REF")"
echo "Will create branch '$BRANCH' from $BASE_REF at $SESSION_START_OID"
```

## Step 3 — Create the worktree

The worktree path is a POSIX absolute path under `$HOME/.claude/worktrees/`
(per `~/.claude/rules/platform-constraints.md`).

```bash
WT_DIR="$HOME/.claude/worktrees/${REPO_NAME}-${SUFFIX}"
git worktree add -b "$BRANCH" "$WT_DIR" "$BASE_REF"
```

If the worktree already exists at that path, `git worktree add` will
fail. That's fine — re-running the skill in the same session is a
no-op-equivalent and the user can `cd` into the existing path.

## Step 4 — Write the claim file

Record this session's claim for future tooling that may verify ownership and
commit provenance. `SESSION_START_OID` is captured from the fetched base before
the worktree can receive session writes; the later HEAD is not a substitute.

```bash
CLAIM_DIR="$HOME/.claude/state/worktree-claims"
mkdir -p "$CLAIM_DIR"
cat > "$CLAIM_DIR/$SUFFIX.json" <<JSON
{
  "session_id": "$SESSION_ID",
  "session_suffix": "$SUFFIX",
  "repo_name": "$REPO_NAME",
  "repo_root": "$REPO_ROOT",
  "worktree_path": "$WT_DIR",
  "branch": "$BRANCH",
  "base_ref": "$BASE_REF",
  "session_start_oid": "$SESSION_START_OID",
  "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON
echo "Claim written to $CLAIM_DIR/$SUFFIX.json"
```

## Step 5 — Emit the cd command for the user

A skill cannot persistently change the parent session's cwd (per
synthesis finding N1: PreToolUse hooks run as child processes). Print
the command the user needs to run in their next prompt:

```
NEXT STEP: copy and run this command in your next prompt to enter the worktree:

  cd "$WT_DIR"

Then start work. All commits will land on '$BRANCH' which is isolated
from any other Claude Code session in this repo.

When ready to ship, /ship will push '$BRANCH' and open a PR. After
merge, run `git worktree remove "$WT_DIR"` and `git branch -d "$BRANCH"`
to clean up.
```

## Examples

```
# Start a session-isolated worktree with default branch name (wt-<suffix>)
/work

# Start with a specific feature name
/work feat/measurement-family-d-extraction-rule

# Refuses if already in a worktree
cd ~/.claude/worktrees/code-graph-abc12345 && /work
# → "Already inside a worktree — nothing to do."
```

## Success Criteria

- A new worktree directory exists at `~/.claude/worktrees/<repo>-<suffix>`
- A new branch exists locally with name `<branch-base>-<suffix>` cut
  from `origin/<default-branch>`
- A claim file exists at `~/.claude/state/worktree-claims/<suffix>.json`
- The claim records the fetched `base_ref` and exact pre-write
  `session_start_oid` for `/retro` and `/ship` provenance checks
- The skill output ends with a `cd` command the user can copy-paste

## Related

- `git-empty-push-guard.py` (PreToolUse:Bash) — blocks a push with zero
  commits ahead of upstream, the typical Family C symptom
- `~/.claude/rules/git-hygiene.md` — INCIDENT 2026-04-17 +
  2026-05-04 Family C history
