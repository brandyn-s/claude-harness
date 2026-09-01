---
name: ship
description: "Take pending changes through the full PR lifecycle — commit, push, branch, PR, auto-merge."
when_to_use: 'Commit, push, and merge pending changes through the full PR lifecycle — detects fork targeting and merge mode, branches, stages files explicitly, runs marketplace rebuild for claude-config source changes, invokes the security gate for sensitive repos, pushes, creates the PR, verifies merge state, and posts a Linear breadcrumb. Use when finished changes are ready to land on main. Trigger phrases: "ship", "ship it", "ship this", "commit and push", "commit and merge", "send it", "merge it". Do NOT use for fixing failing CI on existing PRs (use /pr-fix), creating drafts for review without merge intent (use plain git + gh manually), or installing staged hook specs (use /ship-hook).'
argument-hint: "[commit message] [--queue-only] [--session-start <oid>]"
effort: medium
allowed-tools: Bash Read Glob Grep Skill AskUserQuestion
metadata:
  author: example-security-engineering
  version: "1.2"
compatibility:
  requires:
    - cli: gh
    - cli: git
  optional:
    - skill: differential-review
      fallback: "differential-review unavailable — surface that via the Step 4 AskUserQuestion gate and let the user decide to push anyway; do not silently skip"
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


# Ship

Commit, push, and merge all pending changes. One command, no friction.

## Arguments

- *(none)* — auto-generate commit message from diff
- `{message}` — use as commit subject line
- `--queue-only` — return after auto-merge is durably armed or queued. The
  caller owns terminal verification; `/retro` uses this mode so it can launch
  detached verification without blocking the rest of the wrap-up.
- `--session-start <oid>` — provenance boundary supplied by `/retro`; classify
  older ahead commits separately instead of attributing the entire range to
  the current session. Invalid or non-ancestor OIDs fail closed as
  `session_provenance: UNVERIFIED`.

---

## Step 1: Detect Repo

```bash
git rev-parse --show-toplevel
git remote get-url origin
git fetch origin main --quiet
git status --short
git rev-list --count origin/main..HEAD

# SHIP_SKILL_ROOT is the directory containing the loaded ship/SKILL.md.
python3 "$SHIP_SKILL_ROOT/scripts/outgoing_payload.py" \
  --repo "$(git rev-parse --show-toplevel)" --base origin/main --pretty
# /retro callers add: --session-start <oid>
```

Treat the helper JSON as the authoritative candidate-payload inventory. It
unions `committed_paths` from the merge-base diff with staged, unstaged, and
untracked paths in `all_paths`; `git status` and the staged diff are supporting
views only. A clean working tree is not sufficient evidence that there is
nothing to ship. Stop only when `all_paths` is empty and `ahead_count` is zero.
Clean-but-ahead commits are payload: keep them in scope, inspect their full
reachable diff/history, and preserve the helper's `base_oid` as the test and
approval base before any push.

When `/retro` supplies `--session-start <oid>`, pass it through to the helper.
Use `session_commits` for current-session attribution and
`pre_session_ahead_commits` for older payload; do not collapse the two lists.
If provenance is `UNVERIFIED`, `/retro` must not call older ahead commits
session-produced.

Before the first push, resolve and report the exact destination repository,
branch, ahead-commit count, changed-file count, and scope/secret-scan result for
the full outgoing range. If that payload is anomalously large or the user's
authorization was not destination-specific, obtain explicit informed approval
with `AskUserQuestion`; a rejection means nothing is transmitted.

Extract repo name from remote URL. Determine flow:

| Repo | Flow | Notes |
|------|------|-------|
| `code-search` | Feature branch + PR with `--repo example-org/code-search` | Fork target |
| All others | Feature branch + PR | Merge behavior is discovered after PR creation |

Do not choose merge behavior from a hardcoded repository list. Step 5 delegates
queue-versus-standard handling to the verified merge helper.

---

## Step 2: Branch

All repos require feature branches. This is mandatory for all active repos.

```bash
git branch --show-current
git log --oneline origin/main..HEAD   # commits already on this branch
```

**`claude-config` / `~/.claude` contended-checkout guard — check this FIRST.**
`~/.claude` is the one live checkout every concurrent session runs from (single
working tree, single HEAD). When `git rev-parse --show-toplevel` is `$HOME/.claude`
(the shared main checkout, NOT a `~/worktrees/...` worktree) AND the current
branch is **not `main`**, a parallel session has left a feature branch checked
out — `git checkout -b` here moves the shared HEAD under them (the shared-HEAD
race, `git-hygiene.md` INCIDENT 2026-05-04, and the recurring "sessions
conflicting" symptom). In that case DO NOT branch in place; route the whole ship
through a worktree off `origin/main` so the shared HEAD is never touched:

```bash
git fetch origin main --quiet
WT=~/worktrees/cc-ship-<slug>
git worktree add "$WT" -b <type>/<slug> origin/main   # shared HEAD untouched
```

Transplant ONLY the files you will ship (Step 3 stages them by name). Per file F,
guard against clobbering an independent origin/main change, then copy:

```bash
git diff origin/main -- "F"   # in ~/.claude: should show only your own edit
# clean      → cp ~/.claude/F "$WT"/F   (mkdir -p parents for new files)
# F diverged → do NOT copy; re-apply your edit onto the worktree's origin/main
#              copy by hand (a blind copy would revert their change)
```

Run **Steps 2b–5 entirely from `$WT`** (marketplace rebuild, stage, commit, push,
PR, merge-queue). After `gh pr view <N> --json state` == `MERGED`, revert the
now-redundant working-tree edits in the shared checkout and remove the worktree —
**never switch the main checkout's HEAD**:

```bash
git -C ~/.claude checkout -- <tracked files you shipped>
rm -f ~/.claude/<untracked files you created>
git -C ~/.claude worktree remove "$WT"
```

Validated 2026-06-13 (PR #1252 shipped this way while a parallel session held
`~/.claude` on `chore/distill-inspector-ec2-gotchas`). If the branch IS `main`
(normal single-session case) or you are already in a worktree, skip this guard
and use the in-place classification below.

Classify the current branch by what's on it:

- **`main`** → create a new feature branch (see below)
- **Feature branch continuing YOUR pending work** (existing commits touch the
  same files or subsystem as `git status`) → stay on it
- **Stale / unrelated branch** (`checkpoint/*` auto-save, abandoned
  `chore/*`, or commits that touch files unrelated to `git status`) →
  create a fresh feature branch off `origin/main`. Do NOT pile your
  changes onto unrelated commits.

Checkpoint and chore branches mixing into ship PRs is a real repeat
mistake (2026-04-21 session hit it twice). The cost of one extra
`git stash` + `git checkout -b` beats the cost of reviewers untangling
three unrelated concerns in one PR.

If switching:

```bash
git stash push -m "ship-prep" -- <unrelated-tracked-files>  # only if needed
git fetch origin main --quiet
git checkout -b <type>/<short-description> origin/main
git branch --show-current  # verify switch worked
```

After branch classification, any checkout/worktree switch, and any transplant,
rerun `outgoing_payload.py` from the selected shipping worktree before Step 2b.
Never reuse an inventory captured against the prior branch or worktree.

---

## Step 2b: Marketplace Sync (claude-config only)

Skip for all other repos. Only fires when the repo is `claude-config` AND
`all_paths` in the candidate payload inventory touches any source file under
`skills/`, `hooks/`, `rules/`, or `agents/`. This includes source changes
already committed on a clean-ahead branch; never reduce this gate to
`git status` or the staged diff.

Marketplace plugin bundles under `marketplace/<plugin>/` are real file copies (not symlinks) of source skills under `skills/`. Source is the truth; marketplace is the publish target. Whenever you ship a source change, the marketplace copy needs to be re-synced in the same commit so the published baseline tracks reality. The validate CI workflow blocks PRs that diverge.

```bash
# Inspect all_paths in the outgoing_payload.py JSON. If any entry starts with
# skills/, hooks/, rules/, or agents/, rebuild before continuing.
python3 scripts/build-marketplace.py
```

If the build ran, stage the resulting marketplace changes alongside the source changes in Step 3:

```bash
git add marketplace/ .claude-plugin/
```

Rationale: a source edit without a marketplace rebuild publishes a stale plugin bundle; over time the marketplace diverges from what the user is actually running. Shipping both together keeps the two in lockstep.

**Then run the preflight aggregator before pushing** — ONE command that runs every
`tests.yml` gate a `skills/` change can break (~40s full tier, measured):

```bash
python3 bin/preflight-skill.py            # all current gates
python3 bin/preflight-skill.py --list     # what each gate is + the CI step it mirrors
python3 bin/preflight-skill.py --only <key>   # re-run just the one that failed
```

Fix any failure HERE, not after CI. Each failure that reaches CI costs a
~4-minute round-trip to learn something this answers in under a second.

Do NOT hand-pick a subset of the gates. That is precisely the failure mode:
- 2026-06-14 `/lab-review` #1276 — **3 CI cycles**; only `validate-skills` +
  `audit-skill` were run locally, and the drift gate + cross-chain validator are
  separate Matrix-validate steps.
- 2026-07-28 `/gather-claude-endpoints` #1740 — **2 CI cycles**; prose in a
  manifest *reference* field (`guardrails:` takes hook IDs, not sentences), then a
  stale skill count (adding a skill moves it in ARCHITECTURE.md **and** README.md).
  Both were catchable locally in under a second.

The `pre-push` hook runs `--fast` automatically (skips the two >10s gates), so a
push is already gated; the full tier above is the pre-PR check. See
`rules/skill-standards.md` "Pre-push validation for a new/changed skill".

**Base-change invalidation gate:** if a fetch, rebase, or branch update changes
the base after authoritative tests ran, rerun the broadest affected collection
on the new tree before push. Pre-update evidence and target-only reruns do not
prove cross-skill collection compatibility.

---

## Step 3: Stage and Commit

Stage in-scope files explicitly by name. Never `git add -A` or `git add .`.

Never stage: `__pycache__/`, `*.pyc`, `.env`, `*.pem`, `*.key`, `*.tmp`, `debug_*.py`

For `claude-config` repos where Step 2b ran, also stage the `marketplace/` and `.claude-plugin/` directories (see Step 2b).

If the inventory's `commit_required` field is true, select the authorized in-scope
members of `worktree_paths`, stage those exact names, and commit them. If it
says `commit_required` is false and `ahead_count` is nonzero, this is a
clean-ahead payload: skip `git commit` instead of attempting an empty commit.

```bash
git add -- <file1> <file2> ...
```

Analyze the staged diff and generate (or use provided) commit message:

```bash
git diff --cached --stat
git diff --cached
```

Format: `<type>: <description>` — conventional commit, under 72 chars.
Include a WHY line in the body for behavior changes.

Only when `commit_required` is true:

```bash
git branch --show-current && git commit -m "$(cat <<'EOF'
<commit message>
EOF
)"
```

After the commit-or-skip decision, rerun `outgoing_payload.py --base <base_oid>`
against the preserved fetched base. Require at least one ahead commit, and treat
`committed_paths` plus `origin/main..HEAD` history as the full committed
outgoing range that will be transmitted. Leftover excluded working-tree dirt
is not part of that range and must remain unstaged.

Run the repository's configured secret scanner across every commit and blob in
that full range. Record the exact command and result. A staged-only scan or a
scan of `HEAD` alone does not satisfy the pre-push secret-scan gate.

---

## Step 4: Security Gate (conditional — before push)

**Applies to `mcp-servers`, `mcp-infra`, AND `compliance-access-framework`**
(the repos that carry deployed security/service code). Skip for docs-only
repos (`claude-config`, `claude-knowledge-base`) and all others.

Trigger: the **full committed outgoing range** (`origin/main...HEAD` paths and
`origin/main..HEAD` commits), not merely the staged diff, includes
security-sensitive service code —
`*.py` (service, not test), `.github/workflows/*.yml` or
`.github/workflows/*.yaml`, `Dockerfile*`,
`*.rego`, or Terraform `*.tf` touching IAM / policy / KMS / bucket-policy.

```bash
git diff --name-only origin/main...HEAD
git log --oneline origin/main..HEAD
git diff origin/main...HEAD
```

When triggered, this is a **DECISION GATE, not a prose ask** — call the
`AskUserQuestion` tool (it is in `allowed-tools`) so the choice is an
auditable JSONL event, not a skippable inline question:

```
AskUserQuestion(questions=[{
  header: "Security gate",
  question: "Security-sensitive service-code in the full outgoing range for <repo>. Run /differential-review before push?",
  options: [
    {label: "Run review (Recommended)", description: "Invoke /differential-review on the full outgoing range; fix critical/high findings before push."},
    {label: "Skip", description: "Proceed to push without a differential review (you accept the risk on this diff)."}
  ]
}])
```

1. If "Run review": invoke `/differential-review` via the Skill tool against
   the full `origin/main...HEAD` diff and `origin/main..HEAD` commit history.
2. If critical/high findings: fix before proceeding to Step 5.
3. If "Skip": record the choice and proceed — the skip is now an explicit, logged decision.

**Routing note:** if you shipped eligible service code via direct `git`/`gh`
outside this skill, the gate never fired. Route security-sensitive infra
ships through `/ship` so this gate evaluates them (2026-07-24 retro P2:
0 ToB fires across 4+ windows because eligible diffs bypassed `/ship`).

If the repo is outside `mcp-servers`, `mcp-infra`, and
`compliance-access-framework`, or the full committed outgoing range contains none of the
sensitive patterns above, skip this step entirely.

---

## Step 5: Push, PR, and Merge

Push the verified branch, create the PR, establish the CI enforcement state,
then delegate merge behavior and remote-state recovery to the tested helper.

```bash
git push -u origin <branch>
```

Capture the PR URL from `gh pr create` so every later call identifies the new
PR explicitly:

```bash
# For fork repos (e.g., code-search), add `--repo <org>/<repo>` here.
# For all repos in a fork relationship, pass --repo so gh doesn't default
# to the upstream parent.
PR_URL=$(gh pr create --head <branch> --title "<subject>" --body "$(cat <<'EOF'
## Summary
- <1-3 bullets>
EOF
)")
echo "Created: $PR_URL"
```

The `--head` flag is required — hooks can switch branches between push and PR
creation. For a fork, pass `--repo example-org/code-search` to
`gh pr create`. Resolve `REPO_SLUG=<owner>/<repo>` from the selected target and
`PR_NUMBER="${PR_URL##*/}"`; do not infer either from the current branch later.

### Effective-check enforcement preflight

Before arming merge, inspect the actual required check contexts on the target
branch rather than treating the presence of a rule object as enforcement:

```bash
REQUIRED_CONTEXTS=$(gh api "repos/$REPO_SLUG/rules/branches/main" \
  --jq '[.[] | select(.type == "required_status_checks") | .parameters.required_status_checks[]?.context] | unique | .[]')
```

- **Non-empty context list:** record the names. GitHub has an explicit predicate
  to hold auto-merge while those checks run.
- **Empty list, API error, or ambiguous response:** auto-merge might land before
  CI. Allow a bounded registration window, inspect workflow runs for the PR head
  SHA, then run `gh pr checks "$PR_URL" --watch --interval 10` and require every
  applicable check to be terminal-green before continuing. An immediate empty
  list is not evidence that no workflow applies. Failed checks route to
  `/pr-fix`.

Before any rerun, queue refresh, or no-content commit for absent checks, reconcile GitHub's official Actions status/incident feed with the current PR or merge-group head SHA. An active webhook incident is a hold: make no PR or repository changes and retry later; never rerun a completed workflow ID from a retired merge-group SHA.

This preflight is mandatory even when the repository requires pull requests.
A PR-only rule without required checks does not prevent post-merge CI failures.

### Verified merge helper

Do not reimplement merge-queue detection, standard-merge fallback, silent-drop
re-arming, behind-branch repair, or terminal polling in prose. The repository
helper owns those transitions and never uses `--admin` or force-push.

```bash
# Default /ship: exits 0 only after terminal MERGED.
python3 "$CONFIG_ROOT/bin/pr-merge-verified.py" "$PR_NUMBER" --repo "$REPO_SLUG"

# /ship --queue-only: exits 0 after a durable arm/queue entry (or MERGED).
python3 "$CONFIG_ROOT/bin/pr-merge-verified.py" "$PR_NUMBER" --repo "$REPO_SLUG" --queue-only
```

The helper tries bare `--auto` first (merge queues own strategy) and falls back
to `--auto --squash` for standard PRs. Run it unpiped. For a detached run, use
`--status-file` and read that JSON; a pipeline can mask its nonzero timeout.

Default mode succeeds only when the helper reports terminal `MERGED` and
`gh pr view "$PR_URL" --json state,mergedAt,mergeCommit` confirms it. Queue-only
mode may report `QUEUED`; preserve the branch/worktree and state who owns the
terminal verification. Queue-only may instead report terminal `UNQUEUEABLE`
(exit 7): the repo cannot hold an auto-merge request at all (no
protected-branch rules — claude-config and the KB measured 2026-08-22), so a
durable queue handoff does not exist there. Valid follow-ups: merge directly
once checks are green (`gh pr merge <N> --repo <o/r> --squash --delete-branch`,
run UNPIPED — a `| tail` masked exactly this arm failure twice on 2026-08-22),
re-run the helper without `--queue-only` to poll to `MERGED`, or hand off
`OPEN + named owner` when checks are blocked by external breakage. `/retro` immediately launches the same helper without
`--queue-only` in detached mode. Clean a linked worktree only after remote
`MERGED` confirmation; branch-deletion failure cannot overturn remote state.

---

## Step 6: Linear Breadcrumb

Read `$CONFIG_ROOT/skills/_shared/linear-routing.md`. Look up repo name.

If mapped, post a status update:

```
save_status_update(
  type="project",
  project="<project name>",
  health="onTrack",
  body="**<plain-language summary>**\n\n<what changed, why it matters>\n\nPR: #<number>"
)
```

If unmapped or Linear unavailable: skip silently. Git is the record.

---

## Step 7: Report

```
Shipped: <commit subject>
PR: <url>
State: MERGED | QUEUED — terminal verification delegated to <owner/status file>
Linear: posted to <project> | repo not mapped | unavailable
```



---

## Examples

**Example 1: Merge-queue repo, one clean feature**
User says: `/ship fix: raise audit threshold`
Actions: Detect `claude-config`. Create feature branch `fix/raise-audit-threshold`. Stage specific files, commit, push, and create the PR with `--head`. Query effective required check contexts, then run `pr-merge-verified.py`; it selects bare queue auto-merge and handles silent drops. Confirm terminal `MERGED`. Post Linear breadcrumb.
Result: PR merged through the queue, confirmed by terminal state.

**Example 2: Fork repo**
User says: `/ship feat: add type annotation`
Actions: Detect `code-search` (fork). Branch, commit, push. Use `gh pr create --head feat/... --repo example-org/code-search`, then run the verified helper with `--repo example-org/code-search`. It falls back to the standard squash strategy and confirms terminal state.
Result: PR merged against the fork target (not upstream), confirmed by terminal state.

**Example 3: Retro queue-only handoff**
User says: `/ship --queue-only --session-start <verified-oid> distill: persist session lessons`
Actions: Separate current-session commits from older ahead history, complete the same branch, validation, push, PR, and enforcement preflight. Run the verified helper with `--queue-only`; require `QUEUED` or `MERGED`, then return the PR URL and state owner to `/retro`.
Result: Auto-merge is durably armed; retro launches detached terminal verification and preserves the worktree until `MERGED`.


## Success Criteria

- Every ship uses a feature branch and PR; fork targets use `--repo`
- Candidate scope unions committed, staged, unstaged, and untracked paths;
  clean-ahead payloads skip empty commits but retain every downstream gate
- Commit message follows `<type>: <description>` format under 72 chars; behavior changes include a WHY line
- Files staged explicitly by name — no `git add -A` or `.`
- `gh pr create` uses `--head <branch>` in a separate Bash call
- Effective required check contexts are inspected; absent or ambiguous enforcement takes the terminal-green fallback after a bounded registration window
- The verified helper owns queue-versus-standard merge behavior, silent-drop recovery, and behind-branch repair
- Default mode confirms terminal `MERGED`; `--queue-only` confirms `QUEUED` or `MERGED` and names the owner of terminal verification
- No `--admin`, no `--no-verify`, no `git push --force` on main
- Marketplace, secret-scan, and security-review decisions use the full
  outgoing payload/range rather than a staged-only view
- Linear breadcrumb posted when repo is mapped; silent skip otherwise
- Final report includes commit subject, PR URL, and verified remote state

## Failure Paths

Each step has a deterministic recovery action; **never silently abandon a
partially-shipped state**. Full per-step failure → recovery table and the
partial-state decision rule live in `references/failure-paths.md`.
