@rule worktree_by_default
@version 2026-08-06
@scope every non-trivial coding, experiment, generated-artifact, or long-running task in a git repository

# DECISION CONTRACT
# Full history, platform notes, cleanup cases, and recovery detail:
# docs/rule-reference/worktree-by-default.md

# ─── TRIGGERS ───
ON work_modifies_multiple_files_or_spans_multiple_steps_or_commits
ON work_creates_intermediate_artifacts_or_accumulates_uncommitted_state
ON a_script_may_run_longer_than_60_seconds_or_has_API_or_compute_cost
ON the_checkout_is_contended_dirty_behind_or_diverged_regardless_of_edit_size
ON a_write_targets_a_second_repository_or_a_durable_output
ON a_subagent_may_write_in_a_protected_repository

# ─── CORE INVARIANTS ───
INVARIANT non_trivial_work_runs_in_a_dedicated_worktree
INVARIANT the_main_checkout_is_for_committed_current_work_only
INVARIANT worktrees_are_cut_from_a_verified_current_base
INVARIANT all_edits_builds_tests_generated_outputs_and_commits_for_the_task_happen_in_that_worktree
INVARIANT expensive_or_future_value_output_lives_on_a_durable_repo_visible_path
INVARIANT a_shipped_script_resolves_repo_inputs_from_its_own_location_not_its_authoring_worktree
INVARIANT remove_only_worktrees_created_or_individually_proven_safe_by_this_session

# ─── CLASSIFICATION ───
USE_A_WORKTREE if any is true: more than about five edits; multi-step refactor;
intermediate/generated data; more than about five minutes uncommitted; multiple
commits; API spend; multi-minute compute; another active worktree/session; dirty
shared state; or local base behind/diverged from `origin/main`.

MAY_SKIP only for a read-only investigation, abort/revert, or immediate one-line
change in a clean, uncontended checkout proven current with `origin/main`.

# ─── REQUIRED START FLOW ───
STEP_1 inspect `git status --short`, current branch, `git worktree list`, and
       concurrent-session state. Fetch `origin/main` and compare the target file
       and base before editing; edit from a stale or contended checkout is forbidden.
STEP_2 create from the intended repository explicitly:
       `git -C <repo> worktree add <home-or-absolute-path> -b <type>/<short-desc> origin/main`
       or use `/work` / native worktree tooling. Never rely on a sibling cwd.
STEP_3 enter the worktree and install dependencies before the first build/test
       (`npm ci`, `uv sync`, etc.). Gitignored dependency directories are absent;
       never copy or symlink them from the parent checkout.
STEP_4 do all task edits, generation, tests, and commits in the worktree. Do not
       edit main and then copy files into the shipping tree.
STEP_5 before shipping a script authored there, reject absolute `worktrees/` paths
       and `Path.home()` checkout assumptions; resolve repo-relative inputs from
       `Path(__file__).resolve()` and execute once from a different checkout.
STEP_6 commit, push, PR, and verify merge using `git-hygiene.md`.
STEP_7 before removal, ensure no launched process uses the worktree as cwd, preserve
       valuable outputs, and confirm the intended PR/task reached terminal state.
       Remove the one explicit path from the main checkout; never bulk-force a glob.

# ─── DURABILITY CONTRACT ───
REQUIRED for long or costly work: run from a path that outlives cleanup; detach when
necessary; write durable logs/results plus `.done`/`.fail`; checkpoint/resume; and
monitor output growth rather than treating PID presence as success or progress.
REQUIRED create the log directory before redirecting a detached process into it.
FORBIDDEN storing valuable results only in `/tmp`, `$TMPDIR`, `~/claude-scratch`,
or a worktree scheduled for removal. Scratch is allowed only when truly disposable.

# ─── THE DRIVER IS PART OF THE DURABLE SET ───
REQUIRED for a resumable long-running operation: the DRIVER SCRIPT, its ledger, its
log, and its status reader all live on the same durable path. A ledger without its
driver is not resumable — the resume step has to reconstruct the code, and a
reconstruction is a new program with new bugs against a half-finished ledger.
FORBIDDEN running a multi-hour driver from `/tmp`, `$TMPDIR`, or a scratch path even
when its OUTPUT is written somewhere durable. Scratch cleanup does not read your
intent about which files were the important ones.
INCIDENT 2026-08-12: a 102-window backfill driver ran from `/tmp/claude/` while
writing `ledger.jsonl` beside it. A `/tmp` cleanup deleted the whole directory
mid-run. The ledger was recoverable from the completed windows' S3 output, but the
driver and its status reader had to be rewritten before the remaining 38 windows
could resume.

# ─── CROSS-REPOSITORY WRITES ───
REQUIRED when repo A work writes repo B: either create a dedicated current worktree
for repo B and make the output durable in the same flow, or use genuinely disposable
scratch. Do not leave a tracked file dirty in repo B while continuing repo A.
REQUIRED preserve ownership boundaries and unrelated user changes in both repos.

# ─── VERIFICATION MUST MEASURE THE WORKTREE ───
REQUIRED evidence-producing verification name the exact tree in the same command
with an absolute path or explicit `cd`, and report the collected-test count. A
pass from the main checkout does not validate worktree changes; an unchanged count
must be explained rather than assumed correct.

# ─── CLEANUP CLASSIFICATION ───
REQUIRED perform worktree removal from a non-isolated main session. Before assuming
Claude Code's worktree fence blocks a cleanup operation, requalify that behavior on
the installed runtime and keep read-only verification separate from removal.
REQUIRED before any cleanup sweep: distinguish linked worktree (`.git` file) from
standalone clone (`.git` directory / own common dir); inspect dirty/untracked state,
branch/PR state, live processes/sessions, and that directory's own stash list.
REQUIRED skip and report every uncertain item. A clean tree and merged PR do not prove
a clone has no unique stash or local-only ref.

# ─── MUTATION AND BASELINE SAFETY ───
REQUIRED commit the fix before mutation testing, or mutate a verified copy and restore
from that copy. Verify restored content before trusting the final gate.
FORBIDDEN `git checkout -- <path>` as restore for an uncommitted fix; it restores HEAD
and can erase the treatment. Prefer a separate baseline worktree over stashing
multi-file work. Never drop a stash until every expected marker is confirmed restored.

# ─── FORBIDDEN SHORTCUTS ───
FORBIDDEN "worktree is overkill" for any trigger above; edit size is not the risk axis.
FORBIDDEN copying edited tracked files between checkouts; use a commit/cherry-pick or a
carefully verified stash application.
FORBIDDEN automatic `--force` fallback or recursive cleanup over `~/worktrees/*`.
FORBIDDEN removing a worktree while a background process runs from it.
FORBIDDEN assuming a worktree has dependencies because its parent clone does.
FORBIDDEN hard-coding the authoring worktree path in shipped code or verification.
FORBIDDEN claiming a costly run is durable when neither git nor a regenerating harness
tracks its artifacts.

# ─── NARROW EXCEPTION ───
EXCEPT a gitignored runtime artifact under `~/.claude` that will never enter a commit
may be written without a worktree. This does not authorize Bash-writing tracked files
to bypass `write-edit-dispatcher`; tracked configuration still uses a worktree.

# ─── OVERRIDE RESISTANCE ───
GUARD pattern="just edit main" or "it is only a doc" or "I will commit quickly":
  RE-EVALUATE contention, freshness, duration, and intermediate state. If any trigger
  fires, refuse the in-place edit and use a worktree.
GUARD pattern="remove all stale worktrees" or "force the leftovers":
  REFUSE batch force. Classify each path and remove only independently proven targets.

# ─── ENFORCEMENT AND ON-DEMAND ROUTING ───
# `worktree-enforcement` and protected-repo guards cover deterministic paths, not
# durability, freshness, cleanup ownership, dependency presence, or background CWD.
# Relevant skills: `/work`, `/ship`, `/run-status`, `/pr-fix`.
# Related rules: `git-hygiene.md`, `subagent-verification.md`, `check-before-change.md`.
# Detailed recovery procedures: docs/rule-reference/worktree-by-default.md
