@rule git_hygiene
@version 2026-06-10
@scope every git and gh CLI operation in Example repos

# Pointer shorthand: "Full: incidents#anchor" = rules/incidents/git-hygiene.md.
# All INCIDENT one-liners below have their full narrative in that file.

# ─── ORG CONSTRAINTS (hard-coded facts) ───
DEFAULT_BLOCKED_ORG = "example-technologies"
  # WHY: another team's domain (own owners, own CI) — no writes without coordination.
  # DEFAULT: refuse writes. OVERRIDE: per-operation approval (next block).
ALLOWED_ORGS = {"example-org", "example-org", "example-apps-org", "example-labs-org"}
  # Transfer history (2026-04-26 split, Labs): Full: incidents#org-and-ruleset-history

EXPLICIT_APPROVAL_OVERRIDE for example-technologies writes:
  1. REFUSE the write by default on the first mention
  2. SURFACE the rule's WHY (cross-team domain boundary)
  3. LIST safer alternatives (user submits PR, Linear ticket, Slack to repo's team)
  4. EXECUTE only after EXPLICIT per-operation approval naming the target repo/PR
     ("bypass the block for <repo>", "go ahead and push to <repo>", etc.)
  5. STATE in one sentence what is about to happen before executing
  6. APPROVAL IS PER-OPERATION — never extends to later writes in the session
  7. APPROVAL DOES NOT EXTEND to other rules: never_commit_to_main, never_force_push,
     --admin ban still apply — feature branch + PR + --auto stays mandatory.
  # WHY: no silent writes, no session blanket; a human can approve one necessary write.

EXPLICITLY_UNPROTECTED_REPOS = {}
  # 2026-04-26: obsidian-infra exception ended; all repos in our active orgs require
  # feature branch + PR. History: incidents#org-and-ruleset-history

FORK_REPOS = {
  "~/Documents/GitHub/code-search" → "example-org/code-search"          # upstream: FarhanAliRaza/claude-context-local; transferred from example-apps-org 2026-04-26; path updated 2026-05-07 (was ~/code/code-search)
  "~/Documents/GitHub/claude-hud" → "you-s/claude-hud"                 # upstream: jarrodwatts/claude-hud, and an `upstream` REMOTE is configured here (2026-08-02 re-base) so gh targets jarrodwatts without --repo. Path corrected 2026-08-02: the marketplace path is Windows-era and absent; ~/.claude/plugins/claude-hud/ is the runtime CACHE dir, not a clone
  "~/code/SBOM-Visualization" → "you-s/SBOM-Visualization"             # upstream: CycloneDX/Sunshine
    # WHY: gh CLI defaults to upstream fork; need --repo flag on every PR operation
}

# ─── INVARIANTS (always-true) ───
INVARIANT never_commit_to_main
  # WHY: org ruleset blocks non-fast-forward/deletion on main; feature branch + PR only.

INVARIANT never_push_origin_main
  # WHY: same — all changes go through feature branches and PRs.

INVARIANT never_force_push_to_main_or_master
  # WHY: destroys history; blocked by org ruleset.

INVARIANT --admin_flag_is_RETIRED as of 2026-03-13
  # WHY: Anthropic retired --admin across Example repos. Use --auto --squash
  #   Full: incidents#2026-07-20-anthropic-retired-admin-across-example-repos-use

INVARIANT merge_queue_repos_use_bare_--auto (claude-config 2026-05-31; mcp-servers + mcp-infra also queue-enabled, verified 2026-07-22)
  # On a merge-queue repo --delete-branch HARD-ERRORS. --squash is NOT rejected —
  # it is SILENTLY IGNORED: warns "! The merge strategy for main is set by the
  # merge queue", exits 0, and stores mergeMethod=MERGE anyway (MEASURED
  # 2026-08-02 on claude-config #1882). So `--auto --squash` and bare `--auto` are
  # EQUIVALENT there. CORRECT: `gh pr merge <N> --repo <org/repo> --auto`.
  # COROLLARY — a stored `autoMergeRequest.mergeMethod == "MERGE"` is NORMAL on
  # these repos and is NOT a defect, even though allow_merge_commit=false and the
  # queue's merge_method=SQUASH. NEVER diagnose a stuck queue PR from it: measured
  # 2026-08-02, mcp-servers #902/#903/#905/#906 all merged fine with MERGE stored
  # while same-batch #904/#907 stalled — a 4-of-6 split refutes any deterministic
  # method incompatibility and points at the intermittent silent drop below.
  # VERIFY by terminal state (`state == MERGED`), NOT by --auto's output or
  # autoMergeRequest: bare --auto can return SILENTLY (exit 0, no output) having
  # armed LEGACY auto-merge first (autoMergeRequest NON-null pre-queue — the old
  # "null for merge-queue PRs" claim doesn't hold in that window), and that armed
  # request can vanish without a cascade (2026-06-11 PR #1176: CLEAN + both
  # autoMergeRequest and mergeQueueEntry null, PR sitting un-merged). RECOVERY:
  # re-run bare --auto — on green checks it merges immediately.
  # AUTOMATED: `python3 ~/.claude/bin/pr-merge-verified.py <N> --repo <org/repo>`
  # (ABSOLUTE path — the script lives in claude-config/bin, NOT the target repo;
  # a repo-relative invocation from another repo fails file-not-found, 2026-07-09).
  # RUN IT DETACHED, ALWAYS — `nohup ... --status-file /tmp/claude/merge-<N>.json &`
  # then read `.terminal == "MERGED"` from that file when the task notification
  # arrives. The script's own docstring says "Prefer --status-file for ANY
  # backgrounded or redirected invocation"; its default timeout is 20 min, so a
  # FOREGROUND run holds the turn doing nothing but polling and then times out
  # exit 2 on a perfectly healthy queued PR. DO NOT hand-roll a `sleep`+poll loop
  # after it times out. 2026-08-03: foreground run timed out on a QUEUED PR, and
  # the manual recovery cost 19 tool calls + 32.5 min of foreground `sleep`.
  # AND: `armed: False` / `autoMergeRequest: null` is NORMAL for a QUEUED pr —
  # the queue REPLACES the legacy auto-merge request. The drop signature needs
  # `mergeQueueEntry` null TOO (the script's own check is `CLEAN and not armed
  # and not queued`), and only GraphQL can see it — `gh pr view --json` errors on
  # that field. Re-arming a queued PR just returns "already queued to merge".
  # Works on non-queue repos too (2026-07-09 fix): gh REJECTS bare --auto there
  # (demands an explicit strategy), which previously failed SILENTLY — KB #1118 sat
  # CLEAN+unarmed to a blind 20-min timeout; arm() now falls back to --auto --squash
  # and logs arm failures. The script arms, polls, re-arms on
  # the CLEAN-but-unqueued drop signature, and exits 0 ONLY on state==MERGED
  # (3 manual re-arms in one session, 2026-06-12, promoted the loop to a script).
  # SYNC GAP: the script does NOT trigger post-merge-sync.py (the hook's `if`
  # matches `Bash(gh pr merge*)`, not `python3 bin/...`) — after it reports
  # MERGED, sync local main yourself: stash-if-dirty → checkout main → fetch →
  # ff/rebase. Deliberate non-fix: auto-sync inside the script would checkout
  # main under the invoker's feet (same hazard the hook's CWD-switch caution
  # covers). Observed 2026-06-12 PR #1209: local main sat 4 behind on the
  # feature branch after the script exited MERGED.
  # BREADCRUMB GAP (same root cause, 2026-07-24): because the script's merge
  # is `python3 bin/...` and NOT `Bash(gh pr merge*)`, it ALSO skips any
  # PostToolUse hook keyed on the merge command — including a /ship-style
  # project-breadcrumb post. A PR merged via pr-merge-verified.py therefore
  # lands with NO Linear project-timeline breadcrumb; post it manually
  # (save_status_update type=project) if the timeline record is wanted.
  # CONFLICTS in .claude-plugin/*.json + marketplace/** are build-generated:
  # resolve by `git merge origin/main` + `python3 scripts/build-marketplace.py`
  # + stage regenerated files + commit — never hand-edit the JSON.
  # BUT FIRST — RESTORE THE LEDGER. One of those conflicted files,
  # `.claude-plugin/plugin-versions.json`, is not merely OUTPUT: it is the
  # content-hash LEDGER the builder READS to compute the next version, and
  # `plugin_def["version"]` is only the initial FLOOR. So regenerating while
  # the ledger is still conflicted makes the builder parse a conflicted file,
  # lose the version history, and silently emit the FLOOR for EVERY plugin —
  # a version DOWNGRADE that reverts real bumps already on main. REQUIRED
  # order: `git checkout origin/main -- .claude-plugin/plugin-versions.json`
  # FIRST, then build, then verify versions are MONOTONIC vs origin/main
  # (`git show origin/main:.claude-plugin/plugin-versions.json`) before
  # committing. A regenerated version that went DOWN is the tell.
  # WHY: 2026-07-30 PR #1785 — resolving a conflict by regenerating flattened
  #   Full: incidents#2026-07-30-pr-1785-resolving-a-conflict-by
  # WHY: 3 failed merges on PR #1105; silent no-cascade drop on PR #1176.
  # Full: incidents#2026-05-31-merge-queue-bare-auto, incidents#2026-06-07-merge-queue-silent-drops-and-head-vs-queue-matrix, incidents#2026-06-12-generated-file-conflicts-and-rearm-helper

INVARIANT fork_repos_require_--repo_flag on every gh pr command
  # WHY: without --repo, gh targets upstream and fails ("Head sha can't be blank").

INVARIANT always_--rebase on git pull
  # WHY: merge commits clutter history; can be rejected by branch protection.

# ─── PROCEDURE for ANY change ───
ON user_requests_change_to_protected_repo:
  STEP_1 git_status()                                # verify state
  STEP_2 git_branch_current()                        # verify not on main
  STEP_3 IF on main → git_create_feature_branch(name="<type>/<desc>")
  STEP_4 git_commit_on_branch(message=<what + why>)
  STEP_5 git_push_feature_branch(branch=<name>)
  STEP_6 gh_pr_create(title, body, repo=<for forks only>)
  STEP_7 gh_pr_merge_auto(pr_number, repo=<for forks only>)
  STEP_8 git_fetch_and_rebase_main()                 # sync local main
  # WHY: the ONLY safe path; skipping a step diverges state or bypasses review.

ON user_requests_change_to_explicitly_unprotected_repo:
  # Set is empty (2026-04-26). Block kept for shape; no repos match.

# ─── PROCEDURE: reconciling a dirty contended checkout to origin/main ───
# Fires when a contended checkout (~/.claude with concurrent sessions) must
#   Full: incidents#2026-06-18-fires-contended-checkout-claude-concurrent-sessi
STEP_0 verify which concurrent sessions are LIVE before switching the branch:
        `.session-active/<uuid>.json` markers carry `session_pid` but are written
        ONCE at start (mtime ≈ start time, NOT heartbeated) — marker file age does
        NOT prove a session is alive. Liveness = `ps -p <session_pid> -o comm=`
        returns `claude`. Dead pid → stale marker → safe to switch. Live pid →
        switching the SHARED working tree moves it under that session: data-safe
        ONLY if that session's tree is clean AND its branch work is pushed (verify
        both, or ASK before switching). `pgrep -f claude` OVER-counts (matches
        every ~/.claude-pathed helper/MCP/hook); confirm each pid with `ps -p`.
  # WHY 2026-06-13: reconciling ~/.claude to origin/main with 2 live concurrent
  #   Full: incidents#2026-06-13-reconciling-claude-origin-main-2-live-concurrent
STEP_1 snapshot every dirty + untracked file to /tmp/claude/ FIRST
STEP_2 per dirty file, TWO INDEPENDENT sufficient conditions for "safe to revert" —
        test BOTH, because each alone yields a false verdict on a real shape:
        (a) BYTE-EQUAL to origin/main (`git show origin/main:<f> | cmp -s - <f>`)
        (b) the local diff vs HEAD is PURELY ADDITIVE **and** every added line is
            already present in origin/main
        SAFE if (a) OR (b). DIFFERS on both → in-flight work (yours or a concurrent
        session's) → keep it; if the FF path also touches it, STOP and resolve
        ownership first.
        WHY BOTH: (b) alone FALSE-BLOCKS a file STAGED with main's content — its
        diff-vs-HEAD shows MAIN's own deletions, so the additive test fails on a file
        that is byte-identical to the target. (a) alone FALSE-BLOCKS a file whose
        local edit is additive-and-already-upstream while main carries FURTHER content
        the local copy lacks — safe to revert, not byte-equal.
        REVERT WITH `git checkout HEAD -- <f>`, NOT `git checkout -- <f>`: the latter
        restores from the INDEX, which for a STAGED file already holds the new content,
        so it is a NO-OP and the ff stays blocked. HEAD resets index AND worktree.
        A MATCH-revert is only a round trip IF the STEP_4 ff actually follows — local
        main is behind, so `checkout HEAD --` sets the file to the OLDER HEAD content
        and only the ff restores it. Never revert the reconciled set without completing
        the ff, or you ship a REGRESSION.
        git REFUSES the ff even for files whose worktree content already equals
        origin/main, so a "helpful" pre-deploy of target content ADDS blockers for the
        next session — never hand-place main's content into a contended tree.
  # WHY 2026-07-31: a reconcile classifier using (b) alone flagged a staged
  #   Full: incidents#2026-07-31-a-reconcile-classifier-using-b-alone
STEP_3 untracked file at a path origin/main now TRACKS: byte-compare; equal →
        rm before FF (FF restores it tracked); different → stop, investigate
STEP_4 revert ONLY the reconciled files, then `git merge --ff-only origin/main`
STEP_5 verify survivors against the STEP_1 snapshot, never against HEAD
  # WHY 2026-06-12: three reconciliation rounds in one session preserved a
  #   Full: incidents#2026-06-12-three-reconciliation-rounds-session-preserved
FORBIDDEN: "advancing" the ref past a dirty-but-identical file with `git reset --soft
           origin/main` + mixed reset instead of STEP_4's checkout+ff-merge. reset
           moves HEAD/index but NOT the worktree: every OTHER file the incoming
           commits changed is left at OLD content, reading as spurious local
           modifications that would silently REVERT those commits if ever committed.
  # WHY: 2026-07-05 ~/.claude sync across #1531 — settings.json was dirty-identical
  #   Full: incidents#2026-07-05-claude-sync-across-1531-settings-json-dirty-iden

# ─── BRANCH NAMING (required) ───
BRANCH_PREFIXES = {feat/, fix/, docs/, ci/, chore/, refactor/, test/, revert/, experiment/}
  # WHY: consistent prefix enables automation (stale-branch detection, release notes)

# ─── BRANCHING FROM THE WRONG BASE: mechanism and recovery ───
# Relocated from the ambient rule's STEP_4 (2026-08-24) to hold that file under
# its 10,000-byte contract cap. The STEP_4 imperative and its tell stay ambient;
# this is the mechanism and the recovery procedure.
#
# MECHANISM: a checkout left on ANOTHER BRANCH'S UNMERGED COMMIT silently adopts
# that branch's pending work as your base. Your PR then carries someone else's
# changes, and on any repo with generated build products (marketplace files,
# compiled catalogs, `generated/*.json`) it conflicts on artifacts you never
# edited. Nothing errors -- the branch is created successfully from a real commit.
#
# THE TELL: `git diff --stat` against the base is far larger than your own edits.
# Verify the base BEFORE editing: `git log --oneline -1` plus
# `git log --oneline HEAD..origin/main` (the second must be empty on a fresh cut).
#
# RECOVERY: do NOT hand-merge the generated files -- that is how a wrong-base PR
# becomes a wrong-content PR.
#   1. Extract only YOUR source files (copy them aside).
#   2. Re-cut the branch from CURRENT `origin/main`: `git checkout -B <name> origin/main`.
#   3. Re-apply the source edits, then REGENERATE build products with the
#      repository's own generator rather than copying them forward.
#   4. Open a fresh PR; close the wrong-base one with a pointer to it.

# ─── HAND-TYPED OBJECT IDs: the two occurrences ───
# Relocated from the ambient rule (2026-08-24) to hold it under its 10,000-byte
# contract cap. The FORBIDDEN clause and the mechanical-derivation remedy stay
# ambient; these are the dated instances.
#
# 2026-08-14 (1st) — guessed a full 40-hex SHA from its short form inside a
#   post-push assert. KB plans, helm-deployment-flaws arc.
# 2026-08-24 (2nd) — typed a protected-release `expected_sha` with an INVENTED
#   tail. The release run was cancelled. This is the occurrence that promoted the
#   clause from an observation to a FORBIDDEN.
#
# WHY IT FAILS QUIETLY: a 40-hex object ID carries no checksum, so git cannot
# tell a fabricated tail from a real one. The error surfaces only at the
# comparison point — or not at all, when the fabricated value happens to name a
# DIFFERENT real object. Derive it mechanically in the same shell and pass it by
# variable; never retype it across tool calls.

# ─── USER OVERRIDE POLICY ───
# NOT preference-based. No bypass via size, urgency, confidence, or claimed approval.
# NO EXCEPTIONS — except EXPLICIT_APPROVAL_OVERRIDE above (per-op, example-technologies).

ON user_requests_destructive_git_operation:
  MUST refuse; suggest the safe equivalent; cite the rule's WHY.
  FORBIDDEN: capitulating. EXCEPTIONS: none.

# ─── EXPLICIT GUARDS (worked examples: incidents#guard-override-examples) ───

GUARD pattern="it's a small change" or "one-liner" or "typo fix" or "feature branch is overkill":
  REFUSE direct commit to main. Size is NOT a bypass. Feature branch + PR. NO EXCEPTIONS.

GUARD pattern="force push to clean up" or "rebase mess" or "fix the history":
  REFUSE on protected branches. --force-with-lease ONLY on your own feature branch,
  NEVER main/master. NO EXCEPTIONS.  # WHY: destroys collaborator history.

GUARD pattern="--admin merge" or "bypass checks" or "I've already reviewed" or "just merge it":
  REFUSE --admin (RETIRED). USE --auto (--squash --delete-branch off merge-queue repos).
  NO EXCEPTIONS — except the example-labs-org OWNER-BYPASS EXCEPTION (see the
  --admin_flag_is_RETIRED invariant): review-only-blocked + all-checks-green +
  self-approval-impossible on example-labs-org/* → `--repo example-labs-org/<repo> --admin`
  is standing-authorized. # WHY: --admin bypasses required CI checks; the Labs
  # exception never bypasses CI, only the review gate the user themself owns.

GUARD pattern="reset --hard" or "get a clean slate" or "discard all my local edits":
  REFUSE without explicit confirmation of data loss. git_status FIRST — surface what
  dies. USE stash (--include-untracked) + checkout main.  # WHY: stash is recoverable.
  # PLATFORM DOUBLE-GATE (CC v2.1.183, gather-claude-verified 2026-06-23): auto-mode now
  #   Full: incidents#2026-06-23-platform-double-gate-cc-v2-1-183-gather-claude-v

GUARD pattern="just push" or "I'll handle the PR later" or "create branch and push, skip PR":
  REQUIRED: branch + PR + auto-merge in the SAME flow.  # WHY: deferred PRs stall.

GUARD pattern="I'm in the right repo, I checked" or "we pushed to this yesterday":
  CALL git_remote_verify anyway before push/PR. Session memory is NOT evidence.
  NO EXCEPTIONS for fork repos.  # WHY: gh defaults to upstream without --repo.

GUARD pattern="amend the merge commit" or "rebase and force push main":
  ABSOLUTELY FORBIDDEN on main/master in protected repos.  # WHY: rewrites shared history.

GUARD pattern="my local gates passed, so the push is gated" (pushing from a
  worktree of a SECOND clone of a repo that ships `.githooks`):
  VERIFY `git config --get core.hooksPath` FIRST. That wiring is ONE-TIME PER
  CLONE and a worktree INHERITS its parent clone's config — so an unwired clone
  pushes with ZERO pre-push gating, silently: no error, no skipped-hook notice,
  just an ordinary-looking push. repo_sync.py sets it opportunistically, but ONLY
  for the repos it manages (code-search, mcp-infra, mcp-servers) — claude-config
  and claude-knowledge-base ship `.githooks` and are NOT in that set, so their
  wiring is incidental, not maintained. Fix: `git config core.hooksPath .githooks`
  in the clone. NO EXCEPTIONS before trusting "pre-push already checked this".
  # WHY: 2026-07-29 — ~/Documents/GitHub/claude-config had hooksPath UNSET, so
  #   Full: incidents#2026-07-29-documents-github-claude-config-hookspath-unset

GUARD pattern="wait for checks" or "check before queuing --auto":
  DO NOT wait. Queue --auto immediately after gh pr create. GitHub merges when
  checks pass. Waiting blocks your next task for no benefit.
  # WHY: --auto is asynchronous by design; polling `gh pr checks --watch` returns
  #   Full: incidents#2026-06-11-auto-asynchronous-design-polling-gh-pr-checks-wa

GUARD pattern="the PR is still OPEN, must be queue latency" or "just waiting on the
  merge queue" (a merge-queue PR that has stayed OPEN across MORE THAN ONE status check):
  REFUSE the latency assumption. A merge queue normally clears in minutes; an OPEN PR
  that persists is a FAILING CHECK far more often than a slow queue. READ the rollup
  BEFORE reporting "waiting": `gh pr view <N> --repo <org/repo> --json
  mergeStateStatus,statusCheckRollup` — a red required check (commonly `validate` on your
  OWN just-pushed lint you skipped locally) is the real blocker, and auto-merge will never
  fire while it is red. Fix the check forward (push to the same branch — auto-merge stays
  armed and cannot merge out from under a red check). Do NOT re-report "waiting on the
  queue" to the user a second time without having read the rollup. NO EXCEPTIONS after the
  2nd OPEN check.
  # WHY: 2026-07-31 — #914 (F3 recorder) sat OPEN across ~5 "what is left to do?" turns; I
  #   Full: incidents#2026-07-31-914-f3-recorder-sat-open-across

GUARD pattern="use git add -A" or "stage everything" or "-u flag":
  PREFER staging specific files by name.
  # WHY: -A/-u can stage sensitive files/binaries (2026-03-04 PR #130: 7 files vs 1).

GUARD pattern="multiple back-to-back PRs in the same session, just queue --auto and move to next":
  REFUSE skipping post-merge sync. After EVERY `gh pr merge --delete-branch`:
  git fetch origin main && git rebase origin/main (stash first if dirty). NO EXCEPTIONS.
  # WHY: local main left BEHIND → next commit conflicts (5 PRs hit it 2026-05-12).
  #   Full: incidents#local-main-left-behind-next-commit-conflicts-5-prs

GUARD pattern="reuse the same long-lived feature branch across multiple squash-merge cycles":
  REFUSE. After every squash-merge landing that branch: fresh branch from origin/main
  OR reset branch to origin/main (user-confirmed). Verify `git log origin/main..HEAD`.
  # WHY: orphan-ancestor tip inflates PR diffs (PR #972: 11,298 lines vs 76 real).
  #   Full: incidents#orphan-ancestor-tip-inflates-pr-diffs-pr-972-11

GUARD pattern="git branch --contains / --merged / `git log branch..main` says a branch is NOT merged":
  DO NOT conclude unmerged. On a SQUASH-merge repo (all of ours) the branch's content
  lands on main under a NEW SHA, so the branch tip is never an ancestor of main and
  every ancestry-based check reports not-merged — structurally, for a fully merged
  branch. Deleting on that signal is safe; KEEPING work on it, or re-shipping it,
  is the error.
  AUTHORITATIVE instead: `gh pr view <N> --json state,mergedAt` (`MERGED` is the
  answer), or verify the CONTENT is on main by reading the merged tree
  (`git show origin/main:<file> | grep <marker>`).
  ALSO FORBIDDEN: reading three-dot `git diff origin/main...HEAD` as "what is missing
  from main" — three-dot shows the branch's own commits since the merge base, which
  for two parallel merged branches shows each lacking the OTHER's work and looks like
  neither landed.
  # WHY: 2026-07-29 — `--contains` reported both feat/editable-news-queries-v2 and
  #   Full: incidents#2026-07-29-contains-reported-both-feat-editable-news-querie

GUARD pattern="gh pr create --body with literal code examples (open(...), python -c, etc.) inline":
  REFUSE inline body containing shell-detectable patterns (hook fires on the literal).
  REQUIRED: --body-file pr-body.md (commit msgs: git commit -F message.txt).
  EXCEPTIONS: bodies with no shell-detectable patterns stay inline.
  # WHY: PR #1016 blocked twice. Full: incidents#2026-05-27-pr-body-inline-code-blocked-by-hook

GUARD pattern="chaining `git checkout -b X && git commit`, or `git push -u && gh pr create`, in one bash call":
  REFUSE. PreToolUse guards evaluate the WHOLE string against PRE-command state —
  checkout -b trips commit-guard; push -u trips pr-guard. SEPARATE bash calls.
  ALSO: a BLOCKED compound ran NOTHING — earlier segments (heredoc-written body
  files, mkdir, git add) never executed. Re-run them before retrying the tail;
  retrying only the final command fails on the missing side effects.
  AND DO NOT REPORT the earlier segments' effects as DONE. Writing the command is
  not running it: a denial makes the whole string a no-op, so a status line like
  "remote added" sourced from your own un-run command is a false report the user
  then acts on. Re-READ the state (`git remote -v`) before claiming any segment
  landed. Corollary: put the CONTENTIOUS command in its own call so a denial
  cannot take out benign setup. (2026-07-29: reported "remote origin added" after
  a denied `cd && git remote add && git push`; the user's retry failed with
  "'origin' does not appear to be a git repository".)
  # WHY: hit 3× 2026-05-29; missing-heredoc variant 2× 2026-06-12 (pr-body file
  #   Full: incidents#hit-3-2026-05-29-missing-heredoc-variant-2

GUARD pattern="committing MORE changes onto a feature branch after its auto-merge was armed (gh pr merge --auto)":
  REFUSE. On a squash-merge repo an armed --auto PR can LAND between your edit and your
  `git push` — the remote branch is then DELETED on merge, so your push RE-CREATES an
  orphan branch carrying both the already-merged squash AND your new commit, attached to
  NO PR (silent: push succeeds, nothing merges the new work). Before adding a commit to
  an --auto-armed branch: `gh pr view <N> --json state` — if MERGED, do NOT push here.
  RECOVER: cut a FRESH branch from the updated origin/main and `git cherry-pick` ONLY
  the new commit (verify `git diff origin/main --stat` shows just your delta, not the
  already-merged content), open a new PR, delete the orphan branch. NO EXCEPTIONS.
  # WHY: 2026-06-19 — committed detector env/IAM wiring onto #465's branch after #465
  #   Full: incidents#2026-06-19-committed-detector-env-iam-wiring-onto-465-s-bra

GUARD pattern="it's a protected repo but I have admin" or "my permissions override the rule":
  REFUSE. The rule applies regardless of permissions. example-technologies only:
  EXPLICIT_APPROVAL_OVERRIDE (still feature branch + PR).
  # WHY: rulesets bind at the API layer; individual admin rights don't bypass.

GUARD pattern="ship a `git rm --cached` untracking PR" (runtime logs, memory files, any tracked→local migration):
  REQUIRED: BEFORE any checkout/rebase/pull that crosses the untracking commit —
  including the post-merge-sync hook's auto-fast-forward, which fires without
  asking — snapshot the affected on-disk files (`cp` to /tmp/claude/), then
  restore with `cp -n` after the sync. Crossing the commit DELETES the working
  copies on every other checkout (tracked-in-old-tree → absent-in-new-tree),
  and a directory left with ZERO untracked survivors is removed entirely.
  If the files are hook-appended (audit logs), the dirty copy also BLOCKS the
  rebase ("Please commit or stash") — revert to HEAD first, sync, then restore.
  NO EXCEPTIONS: the untracked files are usually the "machine-local state" the
  PR was written to protect; skipping the snapshot deletes exactly that state.
  # WHY: hit twice in one session (2026-06-11: audit/*.jsonl after #1175, 47
  #   Full: incidents#hit-twice-in-one-session-2026-06-11-audit

GUARD pattern="this branch's upstream is `[gone]`, so it's merged — safe to `git branch -D`"
  (automated branch cleanup, squash-merge tidy-up, stale-branch pruning):
  REFUSE `-D` on the strength of `[gone]` alone. `[gone]` is a fact about the
  UPSTREAM REF (the remote branch disappeared), NOT about local history — every
  commit made after the last push is invisible to it, which is routine. REQUIRED
  before deleting: (a) prove the tip is already contained in an accepted base
  (`git merge-base --is-ancestor <branch> origin/main`), (b) write a recovery ref
  (`git update-ref refs/gone-recovery/<branch> <branch>`), and (c) use `-d` not
  `-D` so git independently refuses an unmerged branch. A branch failing (a) is
  LEFT ALONE — a stale branch is cosmetic, destroying the only reference to
  unpushed work is not. Reflog is an accident, not a safety mechanism. NO
  EXCEPTIONS for automated cleanup.
  # WHY: 2026-07-26 audit H3 — `repo_sync._prune_gone_branches` and
  #   Full: incidents#2026-07-26-audit-h3-repo-sync-prune-gone-branches

# ─── FAILURE MODES to recognise ───
FAILURE committed_on_main_accidentally:
  RECOVERY (non-destructive — hook-compatible):
    git reflog HEAD | head -5; git checkout -b <feature> origin/main;
    git cherry-pick <orphan-sha>
  # WHY: reset --hard is hook-blocked; cherry-pick reaches the same outcome (verified
  # 2026-05-17, PRs #389/#393). Full: incidents#2026-05-17-committed-on-main-recovery--hook-compatible-cherry-pick

FAILURE pushed_to_wrong_remote (fork targeting upstream):
  SYMPTOM: "Head sha can't be blank". RECOVERY: add --repo <Org/RepoName>, retry.

FAILURE force_pushed_to_main:
  IMMEDIATE: contact collaborators (shared history rewritten).
  RECOVERY: may require reflog from a collaborator with a fresher clone.

# ─── ORG-RULESET AWARENESS ───
# Per-org ruleset tables: incidents#org-and-ruleset-history. Summary: every active org
# enforces PR-based merges on default branches (Repo Protection / Branch Protection /
# PR Security Review); no org allows direct main pushes.

# ─── PROTECTED BRANCH RESTRICTIONS SUMMARY ───
main/master on protected repo:
  FORBIDDEN: direct commit; direct push; force push (only --force-with-lease on a
             feature branch); deletion; amending merged commits; interactive rebase
             on committed history
  REQUIRED: feature branch + PR + auto-merge path

# ─── SUBAGENT + WORKTREE AWARENESS ───
ON subagent_writes_in_protected_repo:
  REQUIRED: isolation="worktree" on Agent tool call
  # WHY: bypassPermissions subagents ignore PreToolUse hooks; worktree isolation is
  #      the ONLY defense against rogue writes.

ON worktree_isolated_subagent_returns:
  MAIN session handles all git ops (commit, push, PR, merge) itself.
  REQUIRED: git -C <worktree-path> diff main BEFORE cherry-picking
  # WHY: review worktree changes in the main session before integration.

# ─── DISTILLED INCIDENTS (one-liners; full narratives in incidents file) ───

INCIDENT 2026-03-04 rogue-subagent-self-merge:
  lesson: subagents edit only — main session does ALL git ops; worktree isolation mandatory.

INCIDENT 2026-03-29 PR-421 lost-commits:
  lesson: ONE commit per PR with --auto; cancel auto-merge before adding commits.

INCIDENT 2026-05-17 squash-merge-of-sync-PR-broke-ancestry:
  lesson: "sync upstream into branch" PRs (chore: merge / sync:) use --merge NOT
          --squash — squash collapses ancestry; the next dev→main PR conflicts.

INCIDENT 2026-03-13 IAM-gaps-invisible:
  lesson: after infra changes, re-run the FULL workflow, not just the build step.

INCIDENT 2026-04-17 cross-session-git-index-race (commit-time):
  lesson: git diff --cached --stat before EVERY commit; no concurrent git ops in one repo.

INCIDENT 2026-05-04 cross-session-git-index-race (push-time):
  lesson: shared HEAD in concurrent worktrees can reset your branch label; use /work
          worktrees; investigate via HEAD reflog (git reflog --date=iso), not branch reflog.

INCIDENT 2026-04-29 synced-template-revert:
  lesson: per-repo edits to "# Managed by <org>/<repo>" files revert on next sync —
          open the upstream-template PR (or both together).

INCIDENT 2026-04-19 example-technologies-absolute-block:
  lesson: absolute cross-org blocks need a narrow, auditable approval path (above).

INCIDENT 2026-05-14 staged-only-additions-dropped-modifications:
  lesson: with both M and ?? files, `git add <paths>` silently excludes unstaged M
          files — diff --cached --stat is a solo-session need, not just a race guard.

INCIDENT 2026-05-25 long-lived-branch-inflated-diff-display:
  lesson: after a squash-merge, cut fresh from origin/main or reset the branch (GUARD above).

INCIDENT 2026-05-29 worktree-holding-main-strands-session:
  lesson: a stale worktree parked on main blocks all main checkouts and strands
          session-start sync; `git worktree list` → remove → checkout main.

INCIDENT 2026-05-29 gitignore-coverage-and-tracked-intent-need-git-not-grep:
  lesson: ignore-coverage via `git check-ignore -v` (grep false-negatives on globs);
          junk-vs-tracked via `git ls-files` + `git log`.

INCIDENT 2026-06-12 git-pathspec-star-is-not-shell-glob:
  lesson: git pathspec `*` crosses `/` — `git ls-files 'rules/*.md'` ALSO matches
          rules/incidents/*.md, unlike Python glob / zsh. Comparing pathspec counts
          to glob counts produces phantom mismatches; use `:(glob)` magic
          (`git ls-files ':(glob)rules/*.md'`) when shell-glob semantics are meant.

INCIDENT 2026-06-07 reused-worktree-local-ref-behind-remote:
  lesson: on a worktree you did NOT create this session: git fetch origin <branch> &&
          git checkout -B <branch> origin/<branch> (hook-allowed) BEFORE building.

INCIDENT 2026-06-07 merge-queue-silent-drops-and-head-vs-queue-matrix:
  lesson: green PR-head badges ≠ merged (merge_group runs a different matrix); confirm
          state==MERGED; re-verify every PR's mergeQueueEntry after a cascade (query via
          `gh api graphql ...mergeQueueEntry{state}` — `gh pr view --json` does NOT expose
          mergeQueueEntry and errors "Unknown JSON field"; for gh --json use
          state / mergeStateStatus / autoMergeRequest);
          --disable-auto + fix before re-queueing a failing merge_group PR.

INCIDENT 2026-06-14 post-merge-sync-ff-landed-on-wrong-branch (contended checkout):
  lesson: in a contended checkout (concurrent sessions sharing ONE tree), a post-merge
          `git merge --ff-only origin/dev` SILENTLY ff'd local MAIN — a parallel session
          had switched the shared HEAD dev→main between my fetch and merge, so the sync
          retargeted main with NO error and advanced it to the dev tip (origin/main /
          prod untouched; local-ref only). ff-only does not fail on the wrong branch —
          it ff's whatever branch you're on. PREVENT: before any post-merge ff/rebase in
          a contended checkout, verify `git branch --show-current`; BETTER, sync ref-only
          with `git fetch origin <branch>:<branch>` (branch-independent — cannot retarget
          the checked-out branch, fails loudly if you're on it). RECOVER: HEAD reflog +
          `git checkout -B main origin/main` (reset --hard is hook-blocked).

GUARD pattern="the PR is MERGED, so the change is live" (on a repo whose merge TRIGGERS
  an apply/deploy — mcp-infra terraform, any auto-deploy pipeline):
  VERIFY THE APPLY'S TERMINAL STATE, not the merge's. `state == MERGED` satisfies this
  rule's merge-queue invariant and is the correct contract FOR THE MERGE — but the apply
  runs afterward in a separate job and can FAIL (a gate, an SCP deny, a state lock, a
  broken `validate` from an unrelated file) while the PR shows merged + squashed + branch
  deleted. Nothing pages on a failed post-merge apply.
  REQUIRED once the merge verifies:
    gh run list --repo <org/repo> --workflow terraform.yml --branch main --limit 2 \
      --json databaseId,status,conclusion
  confirm `completed/success`, and for a CONTROL change also read the live resource (an
  alarm's StateValue, a Glue column count) — a green apply that applied the wrong thing
  still reads green.
  NO EXCEPTIONS when the merge is the deploy trigger.
  # WHY: 2026-07-30 mcp-infra #757 — merged and verified MERGED via pr-merge-verified.py,
  #   Full: incidents#2026-07-30-mcp-infra-757-merged-and-verified

# Extend the existing GUARD "the PR is MERGED, so the change is live":
# THIRD FAILURE SHAPE (2026-08-02) -- A LONG-LIVED LOCAL PROCESS. The two shapes above are
#   cloud deploys (a triggered apply that fails; a green apply that applied the wrong thing).
#   The commonest shape has no pipeline at all: a dev server, preview build, watcher, or MCP
#   stdio process that LOADED ITS MODULES BEFORE THE MERGE. Nothing restarts it, nothing warns,
#   and the files on disk can be byte-identical to origin/main while the RUNNING process serves
#   pre-merge behaviour. "Merged" is THREE independent claims and a PR state answers only the
#   first: (1) the commit is on origin/main; (2) the bytes are on THIS host's disk; (3) the
#   running process holds them.
# (2) IS NOT FREE EITHER, and this is the half that gets skipped: a checkout parked on a
#   FEATURE BRANCH serves its WORKING TREE, so for anything read from disk at runtime --
#   ambient rules in ~/.claude, a hook, a config -- merged-to-main does NOT mean loaded.
#   Measured 2026-08-02: ~/.claude sat on `chore/glob-guard-replay-measurement` while 5
#   just-merged rule files needed to be live; they happened to be byte-identical, which is
#   luck, not verification.
# REQUIRED for (2): diff the working-tree file against origin/main, per file, not per repo
#   (`git show origin/main:<path>` vs the local bytes).
# REQUIRED for (3): compare the PROCESS START TIME to the file mtime (`ps -p <pid> -o lstart=`),
#   then exercise the real endpoint and assert on a value only the NEW code emits (a version
#   field, a new refusal message) -- not merely that it responds 200.
# ALSO: `git branch --contains` / `git log origin/main..HEAD` report a merged branch as
#   UNMERGED on a squash-merge repo (the tip is never an ancestor). The honest signal is the
#   CONTENT diff: `git diff origin/main..HEAD --stat` EMPTY means nothing is missing upstream,
#   whatever ancestry says. 2026-08-02: two checkouts read "1 commit ahead"; both PRs were
#   already MERGED (#1872, #1368) and both content diffs were empty.

# Extend the existing GUARD "the PR is MERGED, so the change is live":
# WHY (additional failure shape, 2026-07-31): `gh run list ... conclusion` catches a FAILED
#   Full: incidents#additional-failure-shape-2026-07-31-gh-run-list

## Recovered 2026-08-08 — squash containment and count-only transplant traps

`git cherry <base> <branch>` compares patch IDs, so it can show equivalent
content after squash or rebase when ancestry cannot. A `-` line means an
equivalent patch is upstream and `+` means it is not. An empty result is not a
verdict: both a merged branch with no unique patches and a newly created empty
branch produce no lines. Require at least one line and use a content diff when
squashing legitimately changed patch IDs.

Commit counts are also not file freshness. A checkout can be behind
`origin/main` while containing newer, unmerged versions of the files being
shipped. Before transplanting onto a fresh branch, compare every edited file
between local HEAD and the remote base and inspect version/header provenance.
The 2026-08-07 live configuration held a newer rule-descope refactor while
origin/main still held the expanded text; blind copy-to-main would have silently
reverted roughly a thousand lines without a merge conflict.

## Recovered 2026-08-16 — stacked auto-merge and applied-without-commit traps

Auto-merge is safe only when the PR targets the protected default branch. A
feature-branch base has no default-branch required checks or review gate, so
`gh pr merge --auto` can merge immediately instead of entering the expected
queue. An organization auto-merge workflow may do the same even without the CLI
flag. This was measured on three stacked PRs: two merged branch-to-branch with
zero review time, and the third merged through the organization workflow. One
was the riskiest change in the stack and its content briefly had no open PR to
the default branch. For stacked work, omit auto-merge or retarget to the
protected default branch before arming it.

Apply/deploy evidence cannot establish committed or pushed state. A Terraform
apply from a dirty working tree can make the live change real while leaving it
in no commit; the next source-driven apply can then revert production. In the
measured incident, a CloudWatch repair had been applied but not committed, and
`gh pr create` exposed the discrepancy with `No commits between main and
<branch>`. Before claiming a change is committed or pushed, inspect both
`git status --short` and `git log origin/<branch>..HEAD`. Treat deployment,
source, and remote-branch state as separate receipts.

A tool timeout bounds the observation window, not the remote mutation. In a
measured 2026-08-15 case, `git push -u origin <branch>` timed out after the
transfer had already completed; `git ls-remote --heads origin <branch>` returned
the exact local SHA. Repeating that push was harmless, but repeating PR
creation, a merge, or a tag push can duplicate a mutation whose first attempt
landed. Read the expected named remote object first, then retry only when the
read proves it absent.

## Merge coherence — a merge that raised no conflict is not a merge that succeeded

Measured 2026-08-21 reconciling a 278-commit local backlog (dated 2026-08-05..06,
unpushed 15 days) against 127 upstream commits, with 336 of the backlog's 522 files
changed on both sides.

### The loud conflicts were never the risk

167 files conflicted and every one resolved correctly. Meanwhile **20 files were
silently synthesised** — content identical to NEITHER branch, no conflict raised,
because the two sides edited different regions of the same file. Exactly ONE had a
contract test to catch it: `rules/eval-shipping-discipline.md` came out carrying the
backlog's `paths:` frontmatter grafted onto upstream's compacted body, which violates
upstream's own "this rule must be global" test. The other 19 were invisible.

Detection, cheap and exhaustive:

```bash
# for every contested file, compare the merged blob against BOTH parents
git diff --name-only "$BASE" "$OURS"   | sort > /tmp/ours.txt
git diff --name-only "$BASE" "$THEIRS" | sort > /tmp/theirs.txt
comm -12 /tmp/ours.txt /tmp/theirs.txt | while read -r p; do
  [ -f "$p" ] || continue
  d=$(git hash-object "$p")
  o=$(git rev-parse "$OURS:$p"   2>/dev/null)
  t=$(git rev-parse "$THEIRS:$p" 2>/dev/null)
  [ "$d" = "$o" ] || [ "$d" = "$t" ] || echo "SYNTHESISED: $p"
done
```

Resolve at FILE granularity, not hunk granularity. `-X theirs` / `-X ours` does not
avoid this class — it leaves the other side's non-conflicting deletions in place and
produces the same never-tested hybrid.

### The source/contract split, and why it recurs

One side deletes a file the other never touched, so the deletion applies with NO
conflict — while a file that references it arrives from the other side. Five separate
instances in one merge, each surfaced by a more expensive symptom than the last:

| # | surfaced by | files |
|---|---|---|
| 1 | marketplace generator crash | `hooks/context-monitor.py`, `hooks/precompact-checkpoint.py` |
| 2 | `manifest-refs` gate | a separate skill (not included in this export) (9 files) |
| 3 | `hook-paths` gate | `hooks/skill-routing-hint.py` |
| 4 | `pytest skills/` (15 min) | 5 hooks named by `classify_rules.py` HOOK_RULE_MAP |
| 5 | **the sweep below** (seconds) | 8 remaining dangling references |

```bash
# every path upstream has that the merged tree lacks and something still names
git ls-tree -r --name-only "$THEIRS" | while read -r p; do
  [ -e "$p" ] && continue
  b=$(basename "$p"); [ ${#b} -ge 6 ] || continue
  grep -rl --exclude-dir=.git --exclude-dir=marketplace -F "$b" . >/dev/null 2>&1 \
    && echo "DANGLING: $p"
done
```

Plus the inverse pairing rule: **if a source is now one side's, its contract must be
too.** Instances found this way — a skill whose eval fixture came from the other side
(mega-distill asserted text upstream's SKILL.md never contains), a hook whose test
asserted a `systemMessage` the other side's entry script never emits, and four
retirement contract tests asserting the absence of files the merge had restored.

That last group is the irreducible case: upstream's `classify_rules.py` REQUIRES
`verify-before-assuming.py` and `skill-alias.py`; the backlog's
`tests/test_compare_advisory_hooks.py` asserts both are ABSENT. Both cannot hold
inside one merge. The retirement — its deletions AND its contract tests — is a
coherent unit that ships separately.

### Economics

Instances 1-4 cost a generator crash, two gate failures and a 15-minute test run,
discovered serially. Instance 5 found eight more in seconds because it searched for
the CLASS rather than waiting for the next symptom. Run the sweep once, early —
before the expensive suites, not after each of their failures.
