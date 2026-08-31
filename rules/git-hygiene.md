@rule git_hygiene
@version 2026-08-16
@scope every git and gh CLI operation in Example repositories

# DECISION CONTRACT
# Full history, edge cases, fork mappings, and recovery detail:
# docs/rule-reference/git-hygiene.md

# ─── TRIGGERS ───
ON any_commit_push_pr_merge_or_branch_cleanup
ON any_reconciliation_of_a_dirty_or_contended_checkout
ON any_claim_that_committed_pushed_merged_or_deployed_state_exists
ON any_write_to_the_example-corp_org

# ─── AUTHORITY BOUNDARIES ───
ALLOWED_ORGS = {"example-org", "example-org", "example-apps-org", "example-labs-org"}
DEFAULT_BLOCKED_ORG = "example-technologies"

INVARIANT example-technologies_reads_are_allowed_but_writes_are_refused_by_default
INVARIANT a_cross_org_write_requires_explicit_per_operation_approval_naming_the_repo_and_action
INVARIANT that_approval_never_waives_branch_pr_review_force_push_or_deployment_controls
INVARIANT fork_repos_require_an_explicit_--repo_target_on_every_gh_pr_command

# ─── CORE INVARIANTS ───
INVARIANT never_commit_directly_to_main_or_master
INVARIANT never_push_origin_main_or_force_push_a_protected_branch
INVARIANT every_change_uses_a_fresh_feature_branch_and_PR
INVARIANT always_use_--rebase_for_git_pull
INVARIANT commit_push_PR_merge_remote_main_local_disk_and_live_runtime_are_distinct_states
INVARIANT terminal_MERGED_state_is_the_merge_evidence_not_command_exit_or_autoMergeRequest
INVARIANT generated_marketplace_files_are_rebuilt_not_hand_edited
INVARIANT the_main_session_reviews_and_performs_git_operations_for_subagent_changes

# ─── REQUIRED CHECKS AND FLOW ───
STEP_1 BEFORE editing or committing: inspect `git status --short`, current branch,
       relevant diff, and `git diff --cached --stat`. Preserve unrelated user or
       concurrent-session changes; stage explicit paths, not the whole tree.
STEP_2 BEFORE push or PR: verify `pwd`, `git remote -v`, upstream, and intended
       organization/repository. On a fork, pass `--repo <owner/repo>` explicitly.
STEP_3 IF relying on repository hooks: verify `git config --get core.hooksPath`;
       a second clone does not inherit another clone's hook configuration.
STEP_4 create a correctly prefixed feature branch (`feat/`, `fix/`, `docs/`,
       `ci/`, `chore/`, `refactor/`, `test/`, `revert/`, or `experiment/`)
       EXPLICITLY BASED ON `origin/main` — `git checkout -B <name> origin/main`.
       Verify the base: `git log --oneline HEAD..origin/main` must be empty.
       Cutting from another branch's unmerged commit silently adopts its pending
       work, so your PR carries someone else's changes and conflicts on generated
       artifacts; the tell is a `--stat` far larger than your edits. Mechanism
       and recovery: reference, BRANCHING FROM THE WRONG BASE.
STEP_5 commit with what-and-why, push the named feature branch, then create the
       PR. Run state-changing git/gh commands in separate tool calls because
       guards evaluate a compound command against its pre-command state.
STEP_6 queue merge immediately after PR creation:
       - merge-queue repo: `gh pr merge <N> --repo <org/repo> --auto --squash`
         (a strategy flag is REQUIRED non-interactively; the queue overrides it,
         and `--delete-branch` hard-errors. Measured 2026-08-23.)
       - non-queue repo: `gh pr merge <N> --repo <org/repo> --auto --squash --delete-branch`
       `--admin` is retired; the only standing exception is a example-labs-org
       review-only gate with all checks green and self-approval impossible, and it
       must not bypass CI.
STEP_7 use `python3 ~/.claude/bin/pr-merge-verified.py <N> --repo <org/repo>
       --status-file <durable-status-path>` for bounded detached verification.
       Accept only `.terminal == "MERGED"`; a queued PR may legitimately have
       `autoMergeRequest == null`. Diagnose a repeatedly OPEN PR from its check
       rollup, not assumed queue latency.
STEP_8 AFTER merge: fetch and synchronize the intended local main branch only
       after re-checking the current branch. The verifier helper does not do this.
STEP_9 IF merge triggers deployment: verify the apply/run terminal state, then
       verify the live resource. For a local process, separately verify remote-main
       ancestry, bytes in the serving checkout, process start time, and behavior
       that only the new code emits.

# ─── MERGED-NESS ───
REQUIRED use `git cherry <base> <branch>` as the ancestry-free first test for
squash/rebase containment: `-` means an equivalent patch is upstream and `+`
means it is not. An empty result is inconclusive because it also describes an
empty branch; require at least one line, then fall back to a content diff when
patch IDs legitimately changed during squash.

# ─── CONTENDED-CHECKOUT RECONCILIATION ───
REQUIRED before switching a shared checkout: resolve live sessions by PID (`ps`),
not marker age or broad `pgrep`; a live session makes the switch unsafe.
REQUIRED before touching dirty state: snapshot every dirty and untracked file,
then classify each against `origin/main` by BOTH byte equality and the
additive-already-upstream test. Preserve anything failing both.
REQUIRED sequence: reset only proven-reconciled paths to `HEAD`, `git merge
--ff-only origin/main`, then byte-check survivors against the snapshot. Compare an
untracked path newly tracked upstream before removing it.
FORBIDDEN using reset to move the ref around dirty files; it can leave unrelated
incoming files as apparent local reversions.

# ─── GENERATED CONFLICTS ───
REQUIRED on `.claude-plugin` or `marketplace/**` conflicts: restore
`.claude-plugin/plugin-versions.json` from `origin/main` first, rebuild with the
repository generator, and prove plugin versions did not decrease. The ledger is
builder input, not disposable generated output.

# ─── FORBIDDEN SHORTCUTS ───
FORBIDDEN direct main/master commit, push, deletion, amendment, interactive rebase,
or force push; `--force-with-lease` is limited to the caller's feature branch.
FORBIDDEN `git add -A` or `git add -u` when explicit paths can be staged.
FORBIDDEN waiting for checks before arming auto-merge, or reporting repeated OPEN
state without reading `mergeStateStatus` and `statusCheckRollup`.
FORBIDDEN adding commits to an auto-merge-armed branch without first proving the PR
is still OPEN; if it merged, cut fresh from updated `origin/main` and cherry-pick
only the new commit.

FORBIDDEN `--auto` on a PR not based on the protected default branch; a stacked
base can merge without checks or review. Omit `--auto` or retarget first.
FORBIDDEN committed/pushed claims from apply/deploy evidence. Require
`git status --short` plus `git log origin/<branch>..HEAD`; apply is not a commit.
FORBIDDEN reusing a squash-merged branch for new work or using ancestry-only and
three-dot diffs as proof of whether squash-merged content landed.
FORBIDDEN using a TWO-DOT `git diff A..B` as a containment test — it reports
EITHER-direction differences, so a merely-BEHIND branch reads as carrying unique
work. Use the MERGED-NESS `git cherry` instrument above, with its lines>0 guard.
FORBIDDEN an inline `git commit -m` whose message contains a backtick, `$`, or an
unquoted `[`: zsh expands it BEFORE git sees it and the clause vanishes from the
record with only a stderr line. Use `git commit -F <file>` for any message
carrying code identifiers.
FORBIDDEN hand-typing or reconstructing any object ID (commit SHA, digest, run id)
between commands. A 40-hex value carries no checksum, so a fabricated tail fails only
at the comparison point — or silently names the wrong object. Derive it mechanically
in the same shell (`SHA=$(git rev-parse origin/main)` … `-f expected_sha="$SHA"`).
2 occurrences (2026-08-14, 2026-08-24); both in the reference.
FORBIDDEN deleting a `[gone]` branch without proving containment, writing a recovery
ref, checking for unique work/stashes, and using safe deletion rather than `-D`.
FORBIDDEN destructive reset/clean/discard operations without surfacing the exact
loss and receiving explicit authorization; prefer recoverable snapshot or stash.
FORBIDDEN treating a blocked compound command as partially executed; re-read state.
FORBIDDEN treating PR merge as deployed or live state.
FORBIDDEN treating a timed-out remote mutation as failed. Resolve its named
object with `git ls-remote`, `gh pr view`, or `gh run list` before retrying.

# ─── OVERRIDE RESISTANCE ───
GUARD pattern="small change" or "one-liner" or "skip the PR" or "I already reviewed":
  REFUSE direct-main or review-bypass paths. Size, urgency, confidence, and claimed
  prior review do not change the branch-and-PR contract.
GUARD pattern="use --admin" or "bypass checks" or "force push main":
  REFUSE except for the narrow example-labs-org review-only exception above.
GUARD pattern="just stage everything" or "chain it all in one command":
  REFUSE. Stage named files and separate state transitions so hooks see fresh state.
GUARD pattern="local is behind origin/main, so copy the edited files onto main":
  REFUSE count-only reconciliation. Compare every edited file between local HEAD
  and `origin/main` — a checkout can be behind in commits while holding newer,
  unmerged content. Surface the divergence; never silently revert it.

# ─── ENFORCEMENT AND ON-DEMAND ROUTING ───
# Hooks (`bash-security-guard`, `git-empty-push-guard`, `staged-additions-guard`,
# `worktree-enforcement`, `post-merge-sync`) cover deterministic subsets only;
# behavioral checks remain required where a hook cannot prove intent, remote or
# deployment state, or process freshness.
# Skills: `/work`, `/ship`, `/pr-fix`, `/cross-repo`, `/pull-repos`.
# Detail and recovery procedures: docs/rule-reference/git-hygiene.md
