---
paths:
  - "**/rules/git-hygiene.md"
  - "**/rules/incidents/git-hygiene.md"
---

# Git Hygiene: Incident Narratives

Extracted from `rules/git-hygiene.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
keys and lessons as one-liners; full narratives live here.

---

## 2026-03-04 rogue-subagent-self-merge
**Key:** `subagent_did_git_ops_directly`

A `bypassPermissions` subagent committed, pushed, opened a PR, and
`--admin`-merged 7 files autonomously, with no human approval.

**Lesson.** Subagents must edit files only; the main session does all
git ops (commit, push, PR, merge). Worktree isolation is the only
defense against rogue writes — `bypassPermissions` subagents ignore
`PreToolUse` hooks. `--admin` was retired across Example repos as a
direct result of this incident (2026-03-13).

---

## 2026-03-29 PR-421 lost-commits
**Key:** `queued_auto_then_added_commits_to_branch`

Queued `gh pr merge --auto` after the first commit, then pushed 6
more commits to the same branch. Auto-merge fired on the first
commit's passing checks and squash-merged *only that commit*. The
other 6 commits (9 files, 400+ lines) were lost.

**Recovery:** PR #422 re-applied the missing commits.

**Lesson.** ONE commit per PR when you queue `--auto`. If you need
more commits on the same branch, cancel auto-merge first
(`gh pr merge --disable-auto`), push the additional commits, then
re-queue.

---

## 2026-05-17 squash-merge-of-sync-PR-broke-ancestry
**Key:** `squash_merged_a_sync_pr_and_broke_ancestry`

ExampleApp session. `dev` was 14 commits behind `main` on infra.
Opened PR #32 "chore: merge main into dev — sync S3+OAC + L@E SSO
topology" targeting `dev`. Auto-merged with `--auto --squash
--delete-branch` (the standard flow per STEP_7 of this rule). Then
opened PR #33 (`dev` → `main`) to ship the backend feature additions.

**Symptom.** PR #33 reported `mergeable: CONFLICTING` despite `dev`'s
tip containing `main`'s content. `git merge-base --is-ancestor
origin/main origin/dev` returned NO. The squash commit on `dev` had
ONE parent (the previous `dev` tip), not two — so `main`'s commits
were FLATTENED out of `dev`'s ancestry. A subsequent `dev → main` PR
sees the same files appear "changed" on both sides and conflicts.

**Recovery.** Created `chore/repair-history` from `dev`'s tip,
`git merge origin/main` with the default `--merge` strategy (NOT
squash), accepted `--ours` on the two re-conflicted files
(already-resolved content), committed the merge, pushed, opened PR
#34 from `chore/repair-history` → `main`. PR #34 was MERGEABLE
because the new commit had `main`'s tip as a direct ancestor.

**Rule.** For "sync upstream into branch" PRs (sync main into dev,
fork sync, release branch back-merges), use `gh pr merge --auto
--merge` NOT `--squash`. Squash collapses the merge into a single new
commit with ONE parent; the upstream's commits stop being ancestors
of your branch. For regular feature PRs (single-purpose change,
`dev → main` feature ship), `--squash` is still correct.

**Heuristic.** If the PR title starts with `chore: merge`,
`chore: sync`, `sync:`, or the PR's purpose is "bring this branch
current with another branch," use `--merge`. Otherwise `--squash`.

---

## 2026-03-13 IAM-gaps-invisible
**Key:** `skipped_full_deploy_verification_after_infra_change`

Skipped full deploy verification after merging IAM changes.
`iam:PassRole` was missing for months with no alerting.

**Lesson.** After infra changes, re-run the FULL workflow, not just
the build step.

---

## 2026-04-17 cross-session-git-index-race (commit-time)
**Key:** `concurrent_session_staged_files_into_my_commit`

Two concurrent Claude sessions doing git ops in the same repo. The
second session's commit captured files staged by the first.

**Lesson.** Run `git diff --cached --stat` immediately before every
commit; don't run concurrent sessions with git ops in the same repo.

---

## 2026-05-04 cross-session-git-index-race (push-time + automated prevention)
**Key:** `concurrent_session_reset_my_branch_label`

**Context.** Prior session shipped 4 measurement-discipline PRs
against `example-apps-org/code-graph` and
`brandyn-s/claude-harness`. Each ship-cycle (commit → push
→ PR → auto-merge) hit a variant of the race FOUR times in the same
session. Recoveries took ~5-10 min each via reflog cherry-pick to a
`*-clean` branch.

**Recurrences.**
1. B1 design ship — local branch reset, pushed empty-equivalent
2. Family C ship (PR #184) — recovered via cherry-pick to `feat/family-c-clean`
3. Family B ship — local main lag
4. ACC-013 ship (PR #188) — branch label commandeered by parallel session

**Root cause.** Shared-HEAD confusion in concurrent worktrees
(verified via reflog inspection 2026-05-04). The local branch label
(`refs/heads/<name>`) gets reset by the OTHER session's checkout
between this session's commit and push; the commit itself still
exists in reflog but the LABEL points elsewhere.

**Visible symptom.** `git push` uploads 0 commits (label == upstream);
`gh pr create` rejects with "No commits between main and ...".

**Automated prevention.** `~/.claude/hooks/git-empty-push-guard.py`
upgraded from advisory WARN to hard BLOCK on 2026-05-04 (Phase A of
the post-measurement-discipline plan, PR #416). Hook fires on the
0-commits-ahead state at push-time, surfaces the recovery procedure
(reflog cherry-pick to `*-clean` branch), and provides a bypass env
var (`CLAUDE_GIT_PUSH_ALLOW_EMPTY=1`) for the rare legitimate
empty-equivalent push case.

**Lesson.** The root cause (shared HEAD in concurrent worktrees) is
upstream of the hook; the hook only catches the visible symptom. Use
`/work` to create per-session worktrees with auto-prefixed branches
when running multiple sessions on the same repo. The hook is
defense-in-depth, not the primary fix.

**Diagnostic.** When investigating a "branch was reset by another
session" claim, consult the HEAD reflog (`git reflog --date=iso`),
NOT just the branch reflog (`git reflog show refs/heads/<branch>`).
The branch reflog only shows direct ref-mutation history; the HEAD
reflog shows the silent `checkout`/`switch` that shifted HEAD without
moving the branch — which is the actual mechanism in shared-worktree
races. Family C (PR #184) reflog showed only two branch entries
(created from main, then reset --hard 0df346b for recovery), making
the branch look fine. The HEAD reflog showed the real story:

```
07:35:36 checkout: family-c → ship/n200-iter2
07:40:44 commit on ship/n200-iter2 ("Family C" message — intent vs branch mismatch)
07:45:13 checkout: ship/n200-iter2 → family-c (5069e22)
```

The branch was never clobbered; HEAD was silently shifted between
the user's intent-state and their next commit.

---

## 2026-04-29 synced-template-revert
**Key:** `shipped_per_repo_fix_to_template_managed_file`

`fxhoudinimcp` security audit. PR #1 added a `permissions:
contents: read` block to `.github/workflows/ci.yml` in
`example-apps-org/fxhoudinimcp`. File header read
`# Managed by example-org/.github — do not edit directly`. PR
merged. Within hours, the cross-org sync workflow ran and commit
`d73f772` reverted the file back to the template content,
overwriting the security fix.

**Observation.** Per-repo edits to a `# Managed by ...` file are
never durable. The upstream template
(`example-org/.github`) is the only source of truth; Sync
Workflows to All Orgs reapplies it on a cron + push trigger.

**Rule.** When fixing or editing a file whose first non-shebang line
says `# Managed by <org>/<repo> — do not edit directly`, EITHER:
- (a) open a PR against the upstream template repo (durable fix), OR
- (b) make the per-repo edit AND immediately open the upstream PR
  with a note that the per-repo edit is interim and will be reverted
  on next sync.

FORBIDDEN: shipping a per-repo fix to a template-managed file
without opening the upstream PR. The fix will silently revert.

**Recovery.** After a revert, the per-repo PR's intent is preserved
in git history but the file content is gone. Re-land the fix only
after the upstream template ships, OR ship a one-off commit that you
accept will revert.

---

## 2026-04-19 example-technologies-absolute-block
**Key:** `absolute_block_prevented_legitimate_security_fix`

`/vendor-breach` smoke test found real exposure (tag-pinned
trivy-action) in `example-technologies/trident` during CVE-2026-33634
response.

**Previous rule.** Absolute block on `example-technologies` writes
with "NO EXCEPTIONS."

**Problem.** Blocked legitimate cross-team security-fix path with no
approved override, forcing the user to choose between policy
violation and workaround (Linear ticket + wait for trident owner).

**Fix.** Introduced `EXPLICIT_APPROVAL_OVERRIDE` in the parent rule —
per-operation user approval for `example-technologies` writes. Still
refuses on first mention, still surfaces rule WHY, still offers
alternatives; the override only activates on an explicit
authorization that names the target repo or PR.

**Lesson.** Absolute blocks on cross-domain operations should have a
narrow, auditable approval path when the cost of refusal becomes real
blocking of legitimate work. Do not dilute the approval to
session-wide or implicit consent — per-operation keeps the audit
trail.

---

## 2026-05-14 staged-only-additions-dropped-modifications
**Key:** `git_add_specific_paths_dropped_unstaged_modifications`

Phase C of the grade-lift roadmap (PR #317). Working tree had 6 new
files (`A`) + 4 modifications (`M`). Ran:

```
git add bench/accuracy/cache/
git add bench/accuracy/check_adversarial_f1.py
git commit -m "..."
```

Only the explicitly-named paths were staged. The 4 `M` files
(`.github/workflows/accuracy-regression.yml`, `.gitignore`,
`bench/accuracy/.gitignore`, `bench/accuracy/common.py`) stayed
unstaged and were silently dropped from the commit. PR #317 shipped:
oracle caches + gate script landed, but the workflow steps +
env-override + `.gitignore` weren't there. The gate script was dead
code in main until follow-up PR #318 shipped the missing 4 files.

**Recovery cost:** ~10 min. Same-session follow-up PR with the
missing files. Tag the PR description with "follow-up to PR #N
missing M-files".

**Root cause.** Solo-session shape of the same "staged ≠ intended"
failure the 2026-04-17 incident covered for multi-session races. The
`git diff --cached --stat` lesson exists in this rule but was framed
as a race-condition guard. Read as "only matters under concurrency"
and skipped for solo-session work.

**Lesson.** ALWAYS run `git diff --cached --stat` immediately before
`git commit`, regardless of concurrency context. When the working
tree has BOTH `M` and `??` files, `git add <specific paths>` only
stages the explicit names — unstaged `M` files are silently
excluded. This is a single-session failure mode, not just a
race-condition one.

---

## 2026-06-07 contended-repo-reverted-working-tree-post-commit
**Key:** `concurrent_sync_reverted_working_tree_after_commit_verify_pushed_sha`

During the GPT-debug / roundtable-fix arc, a concurrent process in `~/.claude`
(a session-start repo-sync auto-checkpoint, with a second session's worktree
also active — `git worktree list` showed `claude-config-jamf-fix`) raced this
session's worktrees **twice**: it moved a dedicated worktree's HEAD onto `main`
and reverted edited files in the working tree **after** they were
committed+pushed, and stranded the main checkout on `checkpoint/<ts>`. Each
time, `git show HEAD:<file>` and the working tree showed the ORIGINAL (unfixed)
content — looking exactly like the fix had been lost.

**Why the existing race incidents (2026-04-17, 2026-05-04, 2026-05-29) didn't
cover it.** Those cover the 0-commits-ahead symptom (push uploads nothing) and
the worktree-strands-main case. This is the inverse: the commit + push
SUCCEEDED (origin had the fix), but the LOCAL working tree/HEAD was reverted
afterward, so local inspection lied. `git-empty-push-guard.py` doesn't fire
(the push wasn't empty); `git diff --cached --stat` (commit-time) doesn't help
(the revert is post-commit).

**Lesson / recovery.** In a contended repo (multiple active worktrees OR a
concurrent session-sync — check `git worktree list`), the local working tree
and HEAD are unreliable AFTER commit. The authoritative state is the PUSHED
artifact:
- commit → push immediately, then **verify the pushed SHA equals your commit**:
  `gh pr view <N> --json headRefOid` and/or `git ls-remote origin <branch>`.
  If they match, the PR is correct regardless of what local HEAD shows.
- Do NOT re-apply edits or panic when local HEAD shows the original — confirm
  via the HEAD reflog (`git reflog --date=iso`, which shows the silent
  checkout/rebase) and the pushed SHA first.
- Worked twice this session: PR #1130 head=`ccc1eea`, #1131 head=`b09b6fa`,
  both verified on the remote; the fixes survived only because they were
  committed+pushed before the race and then verified on origin.

**Root cause (upstream).** The session-start repo-sync resets/moves worktrees
in `~/.claude` while another session has live worktrees. The durable fix is not
running the resetting sync against a repo with live worktrees; until then, the
verify-pushed-SHA discipline is the defense.

---

## org-and-ruleset-history
**Extracted from the parent rule's ORG CONSTRAINTS + ORG-RULESET AWARENESS
sections (2026-06-10 descope). The parent keeps the constants; history and
per-org ruleset detail live here.**

ALLOWED_ORGS history:
- 2026-04-26: 8 personal/director-managed repos transferred from
  example-org to example-org (mcp-servers, mcp-infra,
  claude-config, claude-knowledge-base, example-sbom-tool, example-compliance-repo,
  claude-code-architecture, obsidian-infra). GitHub redirects from old
  URLs are active. example-org and example-apps-org remain the
  team-shared repo orgs (GHOST-SHIP, code-graph, code-search, etc.).
- 2026-04-26b: example-labs-org added. Personal/director-managed
  prototype-maturation org for Claude-artifact-derived internal tools
  (ExampleApp, ExampleService, ExampleUI). Org has 2FA enforced, "PR Security
  Review" ruleset active on default branches. Same write-policy as the
  other allowed orgs: feature branch + PR + auto-merge.

EXPLICITLY_UNPROTECTED_REPOS history:
- 2026-04-26: obsidian-infra was previously the only direct-push-to-main
  exception. After transfer to example-org, it now has the
  repo-level "Repo Protection" ruleset (PR + status checks). All repos in
  our 3 active orgs require feature branch + PR. The parent's procedure
  block for explicitly-unprotected repos is kept for shape; no repos
  currently match.

EXAMPLE-SECURITY-DEV rulesets = {
  # 2026-04-26: NO org-level rulesets configured. Each transferred repo
  # carries a repo-level "Repo Protection" ruleset:
  "Repo Protection" (per-repo, active) : pull_request + required_status_checks on default branch
}
  # NOT replicated from example-org: gitleaks-as-merge-gate,
  # required code-owner review, required thread resolution, CoPilot review.
  # 2FA enforcement is also not on at the org level (likely enterprise-locked).

EXAMPLE-SECURITY rulesets = {
  "Branch Protection" (active, blocking)    : deletion + non_fast_forward on default branches
  "CoPilot Code Review" (evaluate, non-blocking) : AI code review on push only
  "PR Security Review" (active, blocking)    : gitleaks + 1 approval + code owner + thread resolution
    # excludes (legacy, mostly stale post-2026-04-26 transfer): aws-commercial-security-infra,
    #          Example-CTI, skills (deleted 2026-04-12).
    # The transferred repos (claude-config, mcp-servers, mcp-infra, claude-knowledge-base,
    # obsidian-infra, example-compliance-repo, example-sbom-tool, claude-code-architecture) no longer
    # live in this org.
}

EXAMPLE-INTERNAL-APPS rulesets = {
  "PR Security Review" (active)  : gitleaks / gitleaks, 0 approvals, Repository Role 5 bypass
  "Restrict-Visibility" (active) : all repos private or internal
}

INTERNAL-EXAMPLE-LABS rulesets = {
  "PR Security Review" (active, org-level) : applies to default branch on every repo (ExampleService, ExampleApp, ExampleUI)
}
  # 2FA enforced at org level. Default repo permission: read.
  # Repos here are Claude-artifact-derived prototypes maturing toward
  # internal tools, AWS account 123456789012.

---

## 2026-05-31 merge-queue-bare-auto
**Key:** invariant `merge_queue_repos_use_bare_--auto`

claude-config has a GitHub MERGE QUEUE on main. On a merge-queue repo:
- `gh pr merge <N> --auto --squash --delete-branch` FAILS:
  "Cannot use -d/--delete-branch when merge queue enabled" (hard error),
  and "merge strategy for main is set by the merge queue" (--squash
  rejected) — the command no-ops on queuing, PR stays unqueued.
- CORRECT: `gh pr merge <N> --repo <org/repo> --auto` (bare; the queue
  dictates strategy + branch deletion).
- VERIFY queued by the "is already queued to merge" message — NOT by the
  `autoMergeRequest` JSON field, which reads null for merge-queue PRs
  (merge queue ≠ legacy auto-merge; different mechanism).

knowledge-base + the other allowed orgs have NO merge queue — there
`--auto --squash --delete-branch` is still correct.

**WHY:** 2026-05-31 distill — 3 failed merge attempts on PR #1105 before
switching to bare --auto. The --delete-branch hard-error + the null
autoMergeRequest both misled the verify step.

---

## 2026-05-17 committed-on-main recovery — hook-compatible cherry-pick
**Key:** FAILURE `committed_on_main_accidentally`

`git reset --hard origin/main` is blocked by ~/.claude/hooks/
bash-security-guard.py (dangerous-command-guard) without explicit user
approval. Cherry-pick-to-clean-branch achieves the same outcome (commit
reaches its intended branch) without the destructive op. Verified
2026-05-17: this exact pattern recovered two HEAD-race incidents in one
session via PR #389 (cherry-pick to *-clean branch) and PR #393 (branch
directly off origin/main carrying working tree).

INCIDENT 2026-05-17: the prior recovery line (`git reset --hard
origin/main`) was correct in spirit but blocked by the security hook on
first contact. Removed the inconsistency; matches the
cross-session-git-index-race incident's recovery pattern (Family C,
2026-05-04). Local main keeping an orphan commit ahead of origin/main is
harmless until you push main (which is blocked by branch protection
anyway); optionally ask user authorization for `git reset --hard
origin/main` to clean local main.

---

## 2026-05-12 post-merge-sync-conflicts
**Key:** GUARD "multiple back-to-back PRs in the same session"

2026-05-12 session: 5 consecutive PRs (#503, #879, #882, #883, plus one
earlier merge) all hit merge conflicts at the same point. Same root cause
every time: after `gh pr merge --auto --squash --delete-branch`, the
branch deletion checks you out to local main, which is now BEHIND
origin/main by the just-squashed commit. Any subsequent commit creates
divergence requiring merge conflict resolution. Step 8 of the
protected-repo procedure already says to sync, but the sequence "merge →
start next PR" without an explicit sync step between them is the
recurring trap. REQUIRED after EVERY `gh pr merge --delete-branch`:
`git fetch origin main && git rebase origin/main` (stash first if the
working tree is dirty), even when "the next PR is small".

---

## 2026-05-25 long-lived-branch-inflated-diff-display
**Key:** GUARD "reuse the same long-lived feature branch across multiple squash-merge cycles"

After a squash-merge of `<branch>` into main, the branch's commits live
on main under a NEW SHA; the original branch tip is now an orphan
ancestor. Resuming work on the same branch makes its merge-base on main
walk back to BEFORE the squashes, so every subsequent PR's display diff
shows the cumulative historical diff (often thousands of lines /
hundreds of files) rather than the actual net delta. Squash-merge
collapses this to the real delta, so the merge itself is safe — but the
pre-merge display spooks reviewers and makes reviewable diffs nearly
unusable.

INCIDENT: PR #972 (claude/beautiful-cori-7VuP9) showed an 11,298-line /
285-file diff pre-merge against a 76-line intended delta. Branch had
absorbed PRs #968-971 via squash-merge (different SHAs each time).
GitHub's merge-base computation walked back to before all four squashes
and surfaced the cumulative historical diff. Squash-merge resolved
correctly to the real delta (76 lines), so the merge was safe — but the
display made review hard and could mask a genuine accidental diff
inflation in a future cycle.

REQUIRED after every squash-merge that lands a long-lived branch's
content: EITHER cut a fresh branch from origin/main for the next arc
(`git fetch origin main && git checkout -b <new-branch> origin/main`),
OR reset the existing branch to origin/main (user-confirmed, hook may
prompt: `git fetch origin main && git checkout <branch> && git reset
--hard origin/main`). Don't assume "fresh off the merged main" without
verifying with `git log origin/main..HEAD` (should be empty or only the
new delta).

---

## 2026-05-27 pr-body-inline-code-blocked-by-hook
**Key:** GUARD "gh pr create --body with literal code examples inline"

The bash-security-guard's inline-encoding check fires on the literal
`open('foo.json')` inside `gh pr create --body "$(cat <<'EOF' ... EOF)"`
because the hook scans the bash command string and can't distinguish
prose (PR body content) from execution (an actual `python -c`
invocation). Same applies to long inline-python-c bodies, literal CRLF
replace patterns, etc.

INCIDENT 2026-05-27 distill: A2 PR (#1016) was blocked twice on first
`gh pr create --body` attempt because the body explained that
bash-security-guard fires on `open('settings.json')` literals — and
contained that exact literal as an example. Switched to `--body-file
pr-body.md` and the create succeeded. The hook is correctly enforcing;
the fix is workflow, not bypass. Equivalent for commit messages with
code examples: `git commit -F message.txt`. Bodies with no
shell-detectable patterns (the common case) can stay inline.

---

## 2026-05-29 chained-git-commands-tripped-pretooluse-guards
**Key:** GUARD "chaining git checkout -b && git commit / git push -u && gh pr create"

The PreToolUse git guards (commit-guard, pr-guard, bash-security-guard)
evaluate the ENTIRE command string against the CURRENT branch/upstream
state BEFORE the command runs — so the `checkout -b` (still on main when
evaluated) trips commit-guard, and the `push -u` (no upstream yet when
evaluated) trips pr-guard. 2026-05-29 compliance arc hit this 3× (one
commit-guard, two pr-guard blocks) — each a wasted cycle. The guards are
PreToolUse: they see the pre-command state, not the
post-`&&`-checkout/push state. Run branch-switch and push as SEPARATE
bash calls FIRST, then commit / `gh pr create` in a following call.

---

## 2026-05-29 worktree-holding-main-strands-session
**Key:** INCIDENT `worktree-holding-main-strands-session`

git forbids two worktrees on the same branch. A stale worktree left on
`main` (e.g. an old claude-config-fork-pr9) blocks the main checkout AND
every other worktree from `git checkout main` ("'main' is already used
by worktree at ..."). session-start repo_sync's auto-checkpoint then
fails its return-to-main and STRANDS the session on checkpoint/<ts>
(2026-05-29: ~/.claude stuck on checkpoint/20260527000921 ~2 days,
behind origin/main). Don't assume "Windows file lock" for a failed
checkout-back — run `git worktree list` to find what holds the branch,
`git worktree remove <stale-path>` to free it, THEN `git checkout main`.
Keep worktrees on feature branches, never leave one parked on main.

---

## 2026-05-29 gitignore-coverage-and-tracked-intent-need-git-not-grep
**Key:** INCIDENT `gitignore-coverage-and-tracked-intent-need-git-not-grep`

To decide whether a path is ignored, use `git check-ignore -v <path>`
(real glob semantics), NOT a substring grep of .gitignore — grep gives
FALSE NEGATIVES on globs (`.last-*` covers
`.last-mcp-zombie-cleanup.json`, but a grep for the literal name finds
nothing). To decide whether an untracked file is runtime junk vs
intended-tracked state, use `git ls-files <dir>` + `git log -- <dir>`,
NOT a path-name guess. Both misfired in one session: nearly shipped a
redundant gitignore PR (the glob already covered the file) and nearly
ignored audit/*.jsonl + agent-memory/sentinel/*.yaml that are a tracked
audit trail (7 committed daily logs).

---

## 2026-06-07 reused-worktree-local-ref-behind-remote
**Key:** INCIDENT `reused-worktree-local-ref-behind-remote`

A REUSED prior-session worktree's LOCAL branch ref can be far behind its
REMOTE branch — another session pushed to that branch after this
worktree last synced. 2026-06-07: cc-tavily-prune's local tip was the
2026-05-31 prune commit, but origin/<branch> had a 2026-06-05 "merge
main" + ~20 more commits; building the #1098 fix on the stale local base
made `git push` reject "non-fast-forward". BEFORE building on a worktree
you did NOT create this session: `git fetch origin <branch>` then
`git checkout -B <branch> origin/<branch>` to reset to the true remote
tip, THEN merge origin/main + make changes. Recover a stale-base
push-rejection the SAME way — `checkout -B` to origin/<branch>, NOT
`reset --hard` (bash-security-guard blocks reset --hard; checkout -B
reaches the same state and is hook-allowed; same pattern as the
committed_on_main recovery). Also: `git worktree add <path> <branch>`
FAILS "already used by worktree at <other>" when a prior-session
worktree still holds that branch — `git worktree list` to find it and
reuse it, don't add a second.

---

## 2026-06-07 merge-queue-silent-drops-and-head-vs-queue-matrix
**Key:** INCIDENT `merge-queue-silent-drops-and-head-vs-queue-matrix`

GitHub merge-queue gotchas (claude-config), one session:

1. HEAD-vs-QUEUE matrix divergence — a PR's `pull_request` checks and
   the queue's `merge_group` checks can run DIFFERENT matrices. #1120
   was green on the ubuntu `pull_request` leg but its windows-2022 leg
   ran ONLY in the queue (`merge_group`), where a real Windows bug
   failed it. A green PR-head badge is NOT proof of mergeability on a
   merge-queue repo. Confirm a PR LANDED by `state == MERGED` (or
   origin/main contains its SHA), never by the PR's own check badges.
2. SILENT QUEUE DROPS — when a queued PR merges, trailing PRs go
   BEHIND, get removed, and return to `mergeStateStatus=CLEAN` but
   `queue=not-queued` (NOT re-queued). They sit un-merged silently.
   After a multi-PR cascade re-verify EVERY PR's `mergeQueueEntry`
   (`gh api graphql ... mergeQueueEntry{state}`), not just
   `mergeStateStatus`. #1124 dropped once (re-queued, merged); #1120
   dropped repeatedly because its `merge_group` checks genuinely failed.
3. --auto on a PR whose `merge_group` check FAILS loops forever
   (added->fail->removed->re-added; 4 cycles/~45min on #1120, each a
   full matrix run). When a queued PR's `merge_group` check fails
   systematically, `gh pr merge <N> --disable-auto`, FIX the failing
   check, THEN re-queue — don't just re-queue a systematically-failing
   PR.

**Addendum 2026-06-11 (PR #1176): drops need NO cascade, and bare --auto
arms LEGACY auto-merge first.** A single queued PR with nothing else
merging dropped silently: `mergeStateStatus=CLEAN`, `state=OPEN`, BOTH
`autoMergeRequest` and `mergeQueueEntry` null. Re-running bare `--auto`
merged it within seconds (checks were green). Two refinements to the
2026-05-31 note: (a) on this repo `gh pr merge --auto` returns silently
(exit 0, NO output, no "queued to merge" message) having armed LEGACY
auto-merge — `autoMergeRequest` reads NON-null in that pre-queue window,
so the old "null for merge-queue PRs" claim only describes the
post-queue-entry state; (b) verify terminal success ONLY by
`state == MERGED`, and treat CLEAN-but-OPEN with both fields null as a
drop → re-run bare `--auto`. Queue confirmed still active same day
(`mergeQueue` non-null via GraphQL; branch deletion comes from
`deleteBranchOnMerge: true`, not the queue).

---

## 2026-06-11 untracking-pr-deletes-working-copies
**Key:** GUARD "ship a `git rm --cached` untracking PR"

Two untracking PRs shipped back-to-back from the live `~/.claude`
checkout: #1175 untracked 5 `audit/*.jsonl` runtime logs, #1176
untracked 47 auto-memory entry files under `projects/*/memory/`. Both
times, syncing local main across the untracking commit DELETED the
on-disk copies of exactly the files the PRs were declaring
"machine-local state to preserve":

- **Mechanism.** `git rm --cached` keeps working copies at commit time,
  but any checkout/rebase/fast-forward that moves a TRACKING checkout
  from old-tree (has files) to new-tree (lacks files) removes the
  working copies. The post-merge-sync hook's auto-fast-forward does
  this WITHOUT asking — after #1176 merged, the hook had already
  fast-forwarded main before the manual rebase ran.
- **Dir-level deletion.** A directory left with ZERO untracked
  survivors is removed entirely: `projects/-Users-you-Documents/memory/`
  vanished (all 6 files were tracked). The sibling main-dir survived
  only because the untracked `MEMORY.md` index lived there.
- **Hook-append interaction.** Hook-appended tracked files (audit logs)
  re-dirty between commit and sync, BLOCKING the rebase ("Please commit
  or stash"). Revert them to HEAD (`git checkout -- <paths>`) before
  the sync — the appended content is preserved by the snapshot.
- **Recovery that worked, both times.** Snapshot the affected files to
  `/tmp/claude/<name>-backup/` BEFORE any sync that crosses the
  commit; after the sync, `mkdir -p` any deleted dirs and restore with
  `cp -n` (never overwrites a live file the deletion missed, e.g. the
  untracked MEMORY.md). Verified byte-identical against the snapshot.

**Lesson.** The snapshot step is not optional cleanup hygiene — without
it, the untracking PR destroys the state it was written to protect, and
only the last-committed version is recoverable from history (live drift
since the final commit is gone).

## guard-override-examples
**Extracted Example lines from the parent rule's GUARD blocks (2026-06-10 descope).**

- "it's a small change": User says "commit this typo fix directly to main, it's one
  character." You MUST create a feature branch (e.g. fix/typo-in-comment) and open a PR.
- "force push to clean up": User says "git push --force to fix the merge commit mess."
  You MUST refuse and suggest git rebase + --force-with-lease on the feature branch,
  or reverting via a new commit instead.
- "--admin merge": User says "Merge PR #500 with --admin, it's just a dependabot bump."
  You MUST use --auto instead. GitHub merges when CI passes (usually <2 min).
- "reset --hard": User says "reset --hard, I don't care about the local edits."
  You SHOULD run git_status to enumerate local changes, then offer stash + checkout
  as the safer path.
- "I'm in the right repo, I checked": User says "Create a PR for my code-search
  changes." You MUST pass repo="example-apps-org/code-search" to gh_pr_create.
- "amend the merge commit": User says "Amend the last commit on main to fix the typo."
  You MUST refuse — create a new commit (via feature branch + PR).

---

## 2026-06-12 generated-file-conflicts-and-rearm-helper
**Key:** INVARIANT `merge_queue_repos_use_bare_--auto` (AUTOMATED + CONFLICTS lines)

One session (healthcheck-findings arc) shipped three PRs (#1194, #1196,
#1198) through the claude-config merge queue and hit BOTH known queue
frictions repeatedly:

1. **Silent drops ×3** — each PR reached `mergeStateStatus=CLEAN`,
   `state=OPEN`, auto-merge gone (the 2026-06-11 PR #1176 no-cascade
   signature), and needed a manual bare `--auto` re-arm before the queue
   took it. Three manual recoveries in one session crossed the 3+
   friction threshold (scope-discipline), so the inline poll loops were
   promoted to `bin/pr-merge-verified.py`: arm → poll → re-arm on the
   CLEAN-but-unqueued signature → exit 0 only on `state == MERGED`
   (exit 3 on DIRTY, 2 on timeout, 4 on CLOSED). Idempotent and
   interruption-safe; replaces ad-hoc session poll loops.

2. **Generated-file conflicts ×2** — while each PR sat in CI, a
   concurrent session's PR merged first and both times the conflict set
   was exactly the build-generated files: `.claude-plugin/marketplace.json`,
   `.claude-plugin/plugin-versions.json`, `marketplace/*/.claude-plugin/plugin.json`.
   The canonical resolution (worked both times): `git merge origin/main`
   (leave the conflicted generated files alone), run
   `python3 scripts/build-marketplace.py` (regenerates all three
   deterministically from the merged source tree), `git add` the
   regenerated files, commit the merge. Never hand-edit the conflicted
   JSON — the builder is the only correct author. Sequencing PRs that
   both rebuild the marketplace (land one, merge main into the next,
   rebuild, then queue) avoids the conflict entirely.

## 2026-07-20-anthropic-retired-admin-across-example-repos-use
<a id="2026-07-20-anthropic-retired-admin-across-example-repos-use"></a>

  # WHY: Anthropic retired --admin across Example repos. Use --auto --squash
  #      --delete-branch — EXCEPT on merge-queue repos (next).
  # OWNER-BYPASS EXCEPTION (2026-07-20, standing user directive "I'm an owner,
  # let my bypass by default"): on example-labs-org/* repos ONLY,
  # `gh pr merge <N> --repo example-labs-org/<repo> --merge|--squash --admin`
  # IS allowed when ALL THREE hold:
  #   (a) every CI check is green (bypassing failing/pending checks stays FORBIDDEN),
  #   (b) the ONLY unmet requirement is review approval, AND
  #   (c) self-approval is impossible (the PR was authored under the user's own
  #       gh identity, you-s).
  # This exercises the USER'S OWN ruleset bypass (you-s holds
  # bypass_mode=always on the org "PR Security Review" ruleset + repo rulesets)
  # and matches their established UI pattern (ExampleApp promotions #121, #129).
  # bash-security-guard.py admin-merge-guard enforces the same shape: it blocks
  # --admin EXCEPT with an explicit `--repo example-labs-org/*` flag. The --repo flag
  # is REQUIRED on the command or the hook blocks it.

## 2026-06-18-fires-contended-checkout-claude-concurrent-sessi
<a id="2026-06-18-fires-contended-checkout-claude-concurrent-sessi"></a>

# Fires when a contended checkout (~/.claude with concurrent sessions) must
# move to origin/main THROUGH dirty files, OR when a branch-switch/reconcile
# is contemplated while other sessions share the checkout.
# PREVENTION (do this so you never need the recovery below): NEVER edit the
# shared ~/.claude MAIN checkout while it is on a feature branch, and NEVER
# `git checkout -b` in it — run /work (EnterWorktree) and edit in a per-session
# worktree instead; the main checkout stays on main, clean, read-only.
# `worktree-enforcement.py` (PreToolUse:Write|Edit) HARD-BLOCKS content edits to
# the ~/.claude main checkout when it is on a non-main branch (2026-06-18, after
# this exact reconcile reverted 3 live sessions' in-flight work) — the block
# names /work as the fix. Also NEVER run this reconcile while OTHER sessions are
# live (STEP_0): isolate into your own worktree instead of moving the shared tree.

## 2026-06-13-reconciling-claude-origin-main-2-live-concurrent
<a id="2026-06-13-reconciling-claude-origin-main-2-live-concurrent"></a>

  # WHY 2026-06-13: reconciling ~/.claude to origin/main with 2 live concurrent
  # sessions — markers were ~40 min old (looked stale) but ps -p showed both
  # session_pids alive; switching the shared tree would have moved it under them.
  # Resolved via AskUserQuestion; a concurrent session reconciled to main first,
  # making the switch a no-op. Marker mtime alone would have mis-read "safe".

## 2026-06-12-three-reconciliation-rounds-session-preserved
<a id="2026-06-12-three-reconciliation-rounds-session-preserved"></a>

  # WHY 2026-06-12: three reconciliation rounds in one session preserved a
  # concurrent session's in-flight files; the cmp step caught an uncommitted
  # settings.json matcher improvement a blind revert would have clobbered.
  # Snapshot-first per the untracking GUARD below; blind stash-pop is the
  # blunt fallback (pop conflicts where cmp would have classified).

## 2026-07-05-claude-sync-across-1531-settings-json-dirty-iden
<a id="2026-07-05-claude-sync-across-1531-settings-json-dirty-iden"></a>

  # WHY: 2026-07-05 ~/.claude sync across #1531 — settings.json was dirty-identical
  # to origin/main, ff-merge refused, and a reset-based ref-advance left the
  # commit's 3 OTHER files (ARCHITECTURE.md, docs/PLATFORM_NOTES.md,
  # settings.example.json) stale as phantom `M`s; caught by post-sync status,
  # fixed via `git restore` after `git diff <old-HEAD> -- <files>` proved
  # zero user edits. The STEP_4 path updates the WHOLE tree atomically.

## 2026-06-23-platform-double-gate-cc-v2-1-183-gather-claude-v
<a id="2026-06-23-platform-double-gate-cc-v2-1-183-gather-claude-v"></a>

  # PLATFORM DOUBLE-GATE (CC v2.1.183, gather-claude-verified 2026-06-23): auto-mode now
  # ALSO blocks `git reset --hard`, `git checkout -- .`, `git clean -fd`, `git stash drop`
  # (when you didn't ask to discard), `git commit --amend` (commit not made this session),
  # and `terraform/pulumi/cdk destroy` (unless the stack was named). So these are gated by
  # BOTH our bash-security-guard AND the platform classifier — recovery flows MUST use the
  # cherry-pick path (FAILURE committed_on_main_accidentally), never reset --hard.

## 2026-07-29-documents-github-claude-config-hookspath-unset
<a id="2026-07-29-documents-github-claude-config-hookspath-unset"></a>

  # WHY: 2026-07-29 — ~/Documents/GitHub/claude-config had hooksPath UNSET, so
  # every push from its worktrees skipped BOTH pre-push checks (marketplace sync
  # AND preflight). PR #1780 passed all 16 gates locally and failed CI on
  # marketplace drift. Do NOT hunt `ensure_repo_hooks_path()` — no such function
  # exists; the KB entry naming it is stale. The wiring is inline in
  # session_start_modules/repo_sync.py.

## 2026-06-11-auto-asynchronous-design-polling-gh-pr-checks-wa
<a id="2026-06-11-auto-asynchronous-design-polling-gh-pr-checks-wa"></a>

  # WHY: --auto is asynchronous by design; polling `gh pr checks --watch` returns
  #      non-zero if ANY check (including non-required) fails, which misleads.
  # KNOWN ERROR: if checks already finished by the time --auto is queued (fast
  # CI, or any delay between create and merge), GitHub rejects with
  # `GraphQL: Pull request is in clean status (enablePullRequestAutoMerge)`.
  # That error means the PR is READY — retry the same command WITHOUT --auto
  # (plain `gh pr merge <N> --squash --delete-branch`). Not a failure of the
  # flow; do not treat it as a blocked merge. (Observed 2026-06-11, code-graph
  # PR #380.)

## 2026-07-29-contains-reported-both-feat-editable-news-querie
<a id="2026-07-29-contains-reported-both-feat-editable-news-querie"></a>

  # WHY: 2026-07-29 — `--contains` reported both feat/editable-news-queries-v2 and
  # feat/overview-obligations-first as NOT merged minutes after `gh pr view` said
  # MERGED for both; nearly re-shipped landed work. `pr-fix/references/branch-cleanup.md`
  # already documents the `--merged` half for CLEANUP; this is the same blindness
  # reached from the opposite direction (deciding whether work still needs shipping).

## 2026-06-19-committed-detector-env-iam-wiring-onto-465-s-bra
<a id="2026-06-19-committed-detector-env-iam-wiring-onto-465-s-bra"></a>

  # WHY: 2026-06-19 — committed detector env/IAM wiring onto #465's branch after #465
  # squash-merged; push re-created an orphan branch with no PR. Cherry-pick to a fresh
  # branch off origin/main (#466) recovered it. Distinct from the long-lived-branch
  # GUARD below (that's diff-inflation across reuse; this is a single armed-PR race).

## 2026-07-26-audit-h3-repo-sync-prune-gone-branches
<a id="2026-07-26-audit-h3-repo-sync-prune-gone-branches"></a>

  # WHY: 2026-07-26 audit H3 — `repo_sync._prune_gone_branches` and
  # `post-merge-sync.py` both ran `branch -D` on every `[gone]` branch, justified
  # in-code by "gone-upstream means GitHub already accepted and removed the remote
  # — local-only divergent history is not possible". Disproven on a disposable
  # repo: `[gone]` + `is-ancestor`=False, and `-D` destroyed the only named ref to
  # a never-pushed commit (`git branch --contains <sha>` came back EMPTY). Fixed
  # with the three guards above; recover via `git for-each-ref refs/gone-recovery/`.

---

## 2026-07-31-reconcile-two-conditions
<a id="2026-07-31-reconcile-two-conditions"></a>

Reconciling the shared `~/.claude` checkout (4 OTHER live sessions, verified live by
`ps -p <session_pid> -o comm=`) so an advisory-hook revert would actually deploy. 15
dirty files; local `main` 10 commits behind `origin/main`.

**The false blocker.** The first classifier scored each dirty file by "is the local
diff vs HEAD purely additive, and is every added line already on main?" That flagged
`hooks/bash-security-guard.py` as an unshippable FF blocker on "20 removed lines".
It was in fact byte-identical to `origin/main` — **staged** with main's content, so
its diff-vs-HEAD showed MAIN's deletions relative to the older HEAD. The additive
test is structurally wrong for a staged file. Byte-equality and additive-and-upstream
are INDEPENDENT sufficient conditions; each alone false-blocks a real shape.

**Caught by a negative control, not by review.** The dry run was executed first with
a known-unshipped blocker present, expecting exit 2 / STOP. It reported 4 blockers
where 3 were expected — the 4th was the instrument's own bug. Had the script been run
straight to `--apply`, the extra blocker would have read as a legitimate stop and the
sync would have been abandoned as impossible.

**Two mechanics the procedure did not state.**
1. `git checkout -- <f>` restores from the INDEX. For a file staged with main's
   content that is a NO-OP, so the ff stays blocked; `git checkout HEAD -- <f>`
   resets index and worktree together.
2. git refuses `merge --ff-only` even for files whose worktree content ALREADY equals
   the incoming content — empirically confirmed here: 4 byte-equal MATCH files were
   listed in "would be overwritten". Consequence: hand-placing main's content into a
   contended tree to "pre-deploy" a fix ADDS blockers for whoever syncs next. Also,
   reverting the MATCH set is only a round trip if the ff then runs — with local main
   behind, `checkout HEAD --` moves those files BACKWARD, and only the ff restores
   them. Reverting without completing the ff ships a regression.

**Outcome.** 3 of the blockers were another session's unshipped distill batch, which
was landed as its own PR (#1821) rather than discarded — extracted as a patch against
the old HEAD and 3-way applied onto current main, since a blind copy would have
reverted main's own changes to those same files. The reconcile then ran: 10 files
reverted and verified identical to `origin/main` after the ff (lossless round trip),
5 preserved and verified byte-identical to the STEP_1 snapshot, zero in-flight work
lost across 4 live sessions.

**Rule tension worth knowing.** Ambient STEP_0 permits the reconcile after verifying
liveness ("verify both, or ASK"); `incidents#2026-06-18` says NEVER reconcile while
other sessions are live, after it reverted 3 sessions' work. Both are correct for
their case. The per-file-verified path is the narrow exception and is ONLY valid when
the snapshot and the STEP_5 comparison are actually performed — the 2026-06-18
failure had no per-file proof, which is exactly what made it destructive.


<!-- extracted 2026-08-01: ambient-context reduction -->

## 2026-07-30-pr-1785-resolving-a-conflict-by

```
WHY: 2026-07-30 PR #1785 — resolving a conflict by regenerating flattened
all SIX plugins to their floor (planning-toolkit 1.1.13→1.1.0,
knowledge-ops 1.1.8→1.1.0, code-intelligence 1.1.6→1.1.0), destroying up
to 13 real bumps. Caught only because the pre-push hook re-flagged 4 more
generated files and the diff showed versions decreasing. Generalises: when
a conflict set contains a generated artifact AND the state file its
generator reads, the state file must be resolved before the generator runs.
BEHIND-RACE (2026-06-12 PR #1224): under heavy concurrent merging, a
legacy-armed pre-queue PR sits BEHIND+armed+unqueued indefinitely —
classic auto-merge never updates branches (github.md [confirmed]
strict-checks gotcha). REMEDY: `gh pr update-branch <N>` (server-side)
then re-arm bare --auto. AFTERWARDS the REMOTE branch carries a merge
commit your local lacks — `git pull --rebase origin <branch>` before
any further local commit/push, or the push rejects (hit live same day).
Non-queue repos: --auto --squash --delete-branch — but DROP --delete-branch when
merging FROM A WORKTREE: the merge/queue succeeds, then gh's local cleanup
(checkout default branch + delete local branch) fails — main is held by the main
checkout and the worktree sits on the branch — so the error MASKS the success.
Verify `gh pr view <N> --json state` == MERGED; org repos auto-delete the remote
head branch. Both facets (worktree-side failure; queue-time checkout switch in a
normal clone) in agent-memory/topics/github.md (2026-06-12).
```

## 2026-07-31-a-reconcile-classifier-using-b-alone

```
WHY 2026-07-31: a reconcile classifier using (b) alone flagged a staged
  hooks/bash-security-guard.py as an unshippable FF blocker; caught only by running
  the dry run as a NEGATIVE CONTROL first (it must report STOP while a known blocker
  is unshipped). The ambient STEP_0 above says "verify both, or ASK before
  switching"; incidents#2026-06-18 says NEVER reconcile with live sessions. Both are
  right for their case — the per-file-verified path here is the narrow exception, and
  it is only valid with the snapshot + STEP_5 comparison actually performed.
  Full: incidents#2026-07-31-reconcile-two-conditions
```

## 2026-07-31-914-f3-recorder-sat-open-across

```
WHY: 2026-07-31 — #914 (F3 recorder) sat OPEN across ~5 "what is left to do?" turns; I
reported "merge-queue latency" each time. Its `validate` was RED the whole time on my
own skipped-local-ruff (E702/E731). One `--json mergeStateStatus,statusCheckRollup`
read at the 2nd OPEN check would have found it immediately. The repeated identical
user status-question was the tell that a blocker existed, not that I was idling —
sibling of diagnose-before-fix's "worth watching" defer applied to a stuck PR.
```

## local-main-left-behind-next-commit-conflicts-5-prs

```
WHY: local main left BEHIND → next commit conflicts (5 PRs hit it 2026-05-12).
Full: incidents#2026-05-12-post-merge-sync-conflicts
DEPLOY VARIANT (2026-07-20): the same stale-ref failure bites DEPLOY-FROM-REF
flows, not just commits. `git checkout --detach origin/<branch>` for a
terraform/build/deploy step uses the LOCAL remote-tracking ref — if the fetch
ran BEFORE the PR merged, you deploy the PRE-merge tree with NO error (git
checks out exactly what you asked for). ALWAYS `git fetch origin <branch>`
AFTER the merge event and BEFORE the checkout; then review the deploy plan for
the PRESENCE of the shipped change (ExampleApp prod plan 2026-07-20 showed
none of the new resources — only the contains-my-change review caught it;
an absence-of-scary-changes review would have applied the old tree).
SAME-SESSION SECOND SHAPE: a ~/.claude working-copy edit based on a stale
local main, cp'd into a fresh ship worktree, REVERTS commits origin/main
gained meanwhile (here: nearly reverted #1632 + a concurrent session's
entry). Before transplanting a file into a worktree, diff it against
origin/main and check the DELETION side, not just the additions.
```

## orphan-ancestor-tip-inflates-pr-diffs-pr-972-11

```
WHY: orphan-ancestor tip inflates PR diffs (PR #972: 11,298 lines vs 76 real).
Full: incidents#2026-05-25-long-lived-branch-inflated-diff-display
RECURRENCE 2026-07-29 (corpdev-dashboard), a NEW shape — not branch REUSE but a
branch cut BEFORE the squash and never rebased: dd-019 work sat on the local
pre-squash commit while origin/main held its squash, so `git diff main...HEAD`
showed 34 files / 3,620 lines against a real 13 / 1,301. Caught by eyeballing the
stat, not by any check. STARTING a branch from a stale local main has the same
effect as reusing one — `git fetch origin main` FIRST, then branch from
origin/main (never from local main) whenever a PR of yours merged recently.
RECOVERY is the same as the post-squash case: fresh branch off origin/main +
`git cherry-pick` only the new commits (NOT rebase — rebase tries to replay the
pre-squash commit whose content is already in main).
```

## hit-3-2026-05-29-missing-heredoc-variant-2

```
WHY: hit 3× 2026-05-29; missing-heredoc variant 2× 2026-06-12 (pr-body file
"no such file" after a blocked `cat <<EOF && gh pr create`).
Full: incidents#2026-05-29-chained-git-commands-tripped-pretooluse-guards
NOT GIT-ONLY (2026-07-28): the same mechanism fires on ANY command pair — a
`python3 - <<'PY'` scripted edit bundled with `pytest | tail` was blocked by
bash-tail-buffering-guard, so the heredoc never ran and 6 str.replace anchors
"missed" with a ZERO diff and no error, reading as an anchor bug in the edit
logic. The guard's message names only the guard, never the skipped side effect.
So: any side-effecting script gets its OWN Bash call, and after ANY guard block
treat every earlier segment as NOT RUN and re-verify (`git diff` / re-read the
file) rather than retrying the tail. ALSO `assert old in s` PER replacement in
scripted edits — a no-match replace and a blocked script are indistinguishable
(both: empty diff, exit 0). Nearly shipped a silently-unmodified test suite.
```

## hit-twice-in-one-session-2026-06-11-audit

```
WHY: hit twice in one session (2026-06-11: audit/*.jsonl after #1175, 47
memory files + whole -Documents dir after #1176). Snapshot+restore was the
only thing that preserved them. Full: incidents#2026-06-11-untracking-pr-deletes-working-copies
```

## 2026-07-30-mcp-infra-757-merged-and-verified

```
WHY: 2026-07-30 mcp-infra #757 — merged and verified MERGED via pr-merge-verified.py,
exactly the documented contract. Its apply then FAILED at `protected-plan` ("Block
Terraform deletes, replacements, and forgets": the PR removed two alarms and that gate
blocks bare deletes with no override). Unnoticed for HOURS — the live false alarm #757
existed to fix stayed live, and it surfaced only while grading something unrelated.
PROMOTED from T4 on recurrence: already `[confirmed]` in
agent-memory/topics/aws-infra-s3.md (2026-05-29, "a MERGED PR is not a DEPLOYED
change") and knowledge-base/topics/terraform-ci-workflow-gating.md ("Blind spot 2").
It recurred anyway, because a topic file loads on worker dispatch while this decision
is made in the MAIN thread seconds after a merge. Ambient is the correct tier.
```

## additional-failure-shape-2026-07-31-gh-run-list

```
WHY (additional failure shape, 2026-07-31): `gh run list ... conclusion` catches a FAILED
apply but not a WAITING one. PR #777 merged; its apply sat `waiting` at the `production`
environment gate ~8h. A second merged PR (#779) queued BEHIND it because the workflow's
concurrency group runs `cancel-in-progress: false` — #779's apply could not even START.
`state == MERGED` was checked and reported as shipped for #777; the RUN's status
(`waiting`, not `completed`) was never checked. REQUIRED: after confirming MERGED on a
gated-apply repo, check `gh run list --workflow terraform.yml --branch main` for
waiting/queued state — a still-waiting prior run silently blocks every later one on the
same concurrency group.
```


## 2026-08-01 classifier-outage hand-off script omitted a per-repo step

When the safety classifier became temporarily unavailable and blocked further Bash calls, a
multi-repo shell script was authored for the user to paste and run (knowledge-base:
commit+push+PR+merge; claude-config: commit+push). The script completed the full flow for one repo
and stopped at push for the other, omitting `gh pr create`. Nothing forced a per-repo completeness
check before hand-off, and the omission is invisible in a script that reads as complete.

FIX: when authoring a hand-off script covering MULTIPLE repos, enumerate each repo against the
required step list (branch/commit -> push -> PR create -> auto-merge) BEFORE presenting it, and
state per-repo which steps are included. A script handed to a user is a deliverable; the per-repo
step matrix is its verification.

EVIDENCE (verbatim): "Both pushed. KB is PR #1328 with auto-merge armed; claude-config pushed and
pre-push gates passed... but has no PR yet — my command omitted it."
