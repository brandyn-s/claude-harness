@rule worktree_by_default
FAILURE shipped_a_script_hardcoding_the_absolute_path_of_its_authoring_worktree:
  # INCIDENT 2026-07-26 azure-automations: `scripts/verify_deploy_readiness.py` — the
  #   Full: incidents#2026-07-26-azure-automations-scripts-verify-deploy-readiness
  RECOVERY/PREVENTION: a shipped script resolves its repo-relative inputs from its OWN
  location — `Path(__file__).resolve().parent.parent / "<repo-relative path>"` (plus an
  env override for odd layouts) — NEVER from `Path.home() / "worktrees/..."` or any
  absolute path containing `worktrees/`. Grep before shipping any script written in a
  worktree: `grep -n 'worktrees/\|Path.home() /' <script>`. Verification bar: run it
  from a DIFFERENT checkout than the one it was authored in before calling it working —
  an authoring-worktree pass proves nothing about portability. Sibling of the
  verify-effectiveness "a verifier must distinguish UNKNOWN from ABSENT" guard: both are
  cases where the VERIFIER's own defect is reported as a defect of the thing under test.

@version 2026-05-04
@scope every non-trivial coding or experimentation task in a git repo

# ─── INVARIANTS (always-true) ───

INVARIANT non_trivial_work_runs_in_a_dedicated_worktree
  # WHY: uncommitted experimental files in the main checkout can vanish
  #   Full: incidents#uncommitted-experimental-files-in-the-main-checkout-can-vanish

INVARIANT worktree_paths_use_home_or_absolute_macos_form
  # macOS: use `~/worktrees/...` or an absolute `/Users/<user>/worktrees/...`
  #        path. zsh expands `~`/`$HOME` correctly before git sees it — the
  #        Windows MSYS mangling does not occur on this host.
  # [WINDOWS-ONLY — inactive on macOS]: prior host required the explicit
  #   "C:/Users/..." form because Git Bash expanded ~/$HOME to MSYS-style
  #   paths (e.g. /c/Users/...) that git resolved to "C:/c/Users/..."
  #   (a literal "c" subdir).

INVARIANT main_checkout_is_for_committed_work_only
  # WHY: any uncommitted state in the main checkout is at risk of being
  #   Full: incidents#any-uncommitted-state-in-the-main-checkout-is-at

# ─── PROCEDURE: starting any non-trivial work ───

STEP_1 evaluate the task:
        - Will it modify multiple files?
        - Will it produce intermediate artifacts (eval outputs, generated
          data, work-in-progress files)?
        - Will it run scripts longer than 60 seconds?
        - Will it span multiple commits?
       IF any of the above → use a worktree.

STEP_2 create the worktree with a home or absolute macOS path:
        git -C <repo> worktree add \
          ~/worktrees/<repo-name>-<topic> \
          -b <type>/<short-desc>
        # (or the EnterWorktree tool, which places it under .claude/worktrees/)

STEP_3 cd into the worktree and do all work there. Edits, scripts,
       intermediate data files, everything.

STEP_3b RUN THE PROJECT'S INSTALL STEP BEFORE THE FIRST BUILD OR TEST. A fresh
       worktree contains only TRACKED files, and every language ecosystem
       gitignores its dependency dir — so `node_modules/`, `.venv/`,
       `vendor/`, `target/` are ABSENT even though the parent clone has them.
       The failure surfaces as the BUILD TOOL missing, not as a missing
       dependency (`sh: tsc: command not found`, `ModuleNotFoundError` on a
       package you can see in package.json/requirements.txt), which reads like
       a broken toolchain or a PATH problem rather than an empty worktree.
       `npm ci` / `uv sync` / `pip install -r` / `bundle install` first.
       Do NOT symlink or copy the parent's dependency dir: it defeats the
       isolation the worktree exists for, and a lockfile-mismatched
       `node_modules` fails in ways that look like source bugs.
  # WHY 2026-08-03 claude-hud: `npm test` in a new worktree died
  #   `sh: tsc: command not found`. Read as a toolchain fault; the real cause
  #   was that `node_modules/` is gitignored so the worktree had none. Two
  #   turns to `npm ci`. Cheap to prevent, and it fires on EVERY first
  #   worktree of a JS/Python/Go/Rust repo.

STEP_4 commit + push from the worktree. PR + auto-merge as usual.

STEP_5 after the PR merges, remove the worktree:
        git -C <main-checkout> worktree remove ~/worktrees/<repo-name>-<topic>
        # [WINDOWS-ONLY — inactive on macOS] FILE-LOCK (2026-05-31, recurred
        # 3× in one session): `worktree remove --force` often failed
        # "Permission denied" even when cwd was the main checkout — a process
        # (Defender / Search indexer / a lingering handle) held a file in the
        # just-created 700-2000-file worktree. `git -C <main> worktree prune`
        # STILL reconciles git's metadata (worktree list goes clean), so git
        # stays consistent; the orphan directory is cosmetic — rmdir later.
        # Don't block on the removal. Pre-empt where possible: `cd` OUT of
        # the worktree before removing, and reuse ONE worktree per arc.
        # SCOPE: remove ONLY the worktree(s) YOU created this session — never
        # bulk `git worktree remove --force` a whole glob (e.g. all
        # `<repo>-*` worktrees). `--force` discards uncommitted changes, and a
        # stale-LOOKING sibling worktree may belong to a CONCURRENT session
        # with in-flight work — bulk-forcing it destroys their uncommitted
        # state silently. (2026-06-27: bulk-`--force`-removed all `mcp-servers-*`
        # worktrees; harmless that time only because they were all stale-merged.)
        # Leftover OTHER-session worktrees are /pr-fix's job, not retro cleanup.

# ─── WHAT IS "NON-TRIVIAL" ───
- multi-step refactors
- experiments with intermediate artifacts (eval runs, batch API jobs,
  generated data, work-in-progress files)
- long-running scripts that produce in-progress state
- any work spanning more than ~5 file edits
- any work that will accumulate uncommitted files for more than ~5 minutes
- any work where re-running has real cost (API spend, multi-minute compute)
- ANY edit — even a single-file doc/typo — in a CONTENDED or BEHIND
  checkout: the repo has other active worktrees, concurrent-session
  dirty files, OR local HEAD is behind/diverged from origin/main.
  Contention and staleness — not edit size — make it non-trivial.

# ─── WHAT IS TRIVIAL (skip worktree, edit in main) ───
# ONLY when the repo is NOT contended (no other worktrees, no concurrent-
# session dirty files, local HEAD current with origin/main). In a contended
# repo even these are non-trivial — see the non-trivial list above and the
# fetch-before-edit procedure below.
- single-file typo fix
- one-line config change with immediate commit
- read-only investigations (Read, Grep, Glob, no edits)
- aborting/reverting a previous change

# ─── PROCEDURE: before editing a tracked file in a possibly-behind checkout ───
# Contended repos (concurrent sessions, many worktrees) drift: origin/main
# may be ahead of your local HEAD, so your edit is built on a stale base.
STEP_1 git -C <repo> fetch origin main --quiet
STEP_2 git -C <repo> diff HEAD origin/main -- <file>   # is THIS file diverged?
STEP_3 IF the file (or repo) is behind/diverged → edit in a worktree cut from
        origin/main, NOT in the stale checkout. A stale-base edit reverts or
        conflicts with parallel work and is usually caught only at ship time.
FORBIDDEN: editing a tracked file in a checkout not confirmed current with
           origin/main when the repo shows concurrent activity.
# WHY: INCIDENT 2026-05-28 opus-4.8-doc-sync — a parallel session had already
#   Full: incidents#incident-2026-05-28-opus-4-8-doc-sync

# ─── USER OVERRIDE POLICY ───
# Worktree-by-default is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="just edit in main, it's faster" or "worktree is overkill":
  REFUSE for non-trivial work. Worktree setup takes ~5 seconds.
  Recovery from accidentally-wiped uncommitted files takes hours plus
  potentially-irreplaceable API/compute cost.
  NO EXCEPTIONS for multi-step or long-running work.

GUARD pattern="it's just a doc edit, I'll edit in the main checkout":
  EVALUATE contention FIRST, before deciding it's trivial. Check
  `git -C <repo> worktree list` (other worktrees?), `git status`
  (concurrent dirty files?), and `git log origin/main..HEAD` +
  `git diff HEAD origin/main` (behind/diverged?). If ANY is true → NOT
  trivial → worktree off origin/main and edit there. Edit size is not
  the criterion in a contended repo. NO EXCEPTIONS.

GUARD pattern="I'll commit before any cleanup runs":
  REFUSE. You do not know when hooks fire. PR auto-merge with
  --delete-branch may trigger post-checkout / post-merge hooks that
  wipe uncommitted files. Use a worktree so the question doesn't matter.
  NO EXCEPTIONS.

GUARD pattern="this experiment is small enough" (when API spend or
  multi-minute compute is involved):
  REFUSE. Re-running a $1 paraphrase batch is cheap once but expensive
  in aggregate when it happens repeatedly. Worktree is permanent
  insurance. NO EXCEPTIONS for any work with API spend or >60s compute.

GUARD pattern="I'm only running for a minute, no risk":
  EVALUATE: is the script truly bounded to a minute, or could it run
  longer if it succeeds? Most "1 minute" scripts that produce useful
  output extend to follow-on phases. If the work is genuinely a
  one-shot probe with no follow-up, OK to skip. If there's any chance
  of follow-on phases or accumulated state, use a worktree.

GUARD pattern="remove these N stale worktrees" / any loop over `~/worktrees/*`
  (cleanup sweeps, /pr-fix [WT], end-of-session tidy):
  A DIRECTORY UNDER ~/worktrees IS NOT NECESSARILY A WORKTREE. Some are STANDALONE
  CLONES with their own `.git` DIRECTORY. The distinction is load-bearing and
  invisible from the path: `git worktree remove` CANNOT remove a clone (it errors),
  so "removing" one means `rm -rf` — a materially different authorization than the
  one a worktree-cleanup approval covers. Two cheap discriminators, either suffices:
    test -f "$p/.git"                                  # FILE  -> linked worktree
    git -C "$p" rev-parse --git-common-dir             # == "$p/.git" -> CLONE
  AND CHECK `git stash list` PER DIRECTORY. Measured 2026-08-01: stashes are scoped
  to the OWNING git dir, so a clone's stash is INVISIBLE from the sibling main
  checkout — `~/Documents/GitHub/mcp-servers` reported 0 stashes while the
  `mcp-servers-det` clone held WIP on a branch that existed nowhere else. A clean
  tree + a MERGED PR says nothing about the stash; deleting the dir destroys it with
  no reflog and no remote copy.
  THEREFORE the two-factor check (clean + merged/deleted) is NECESSARY BUT NOT
  SUFFICIENT for a bulk sweep. Add: kind (worktree vs clone) and stash count. Drop
  every clone from the batch and name it back to the user rather than widening the
  approved operation.
  FORBIDDEN: an automatic `--force` fallback inside a bulk loop. Force is a per-item
  fallback for a directory that ALREADY passed every factor; in a loop it silently
  force-removes whatever the classification got wrong. Refuse, SKIP, and report.
  NO EXCEPTIONS for a sweep over a directory you did not create this session.
  # WHY: 2026-08-01 /pr-fix — classified 25 dirs "safe worktrees"; 9 were standalone
  # clones and one (`mcp-servers-det`) held a unique stash. The loop carried an
  # auto-`--force`. Caught by the PERMISSION CLASSIFIER, not by my own review. The
  # corrected set was 16, all removed cleanly with no force. Sibling of the SCOPE
  # note in STEP_5 (never bulk-force a glob) — that one warns about a concurrent
  # session's dirt; this one is about the dirs not being worktrees at all.

# ─── FAILURE MODES to recognise ───

FAILURE uncommitted_experiment_wiped_by_unknown_hook:
  # INCIDENT 2026-05-04 A4 multi-query experiment in example-org/
  #   Full: incidents#2026-05-04-a4-multi-query-experiment-in-example
  RECOVERY: re-create work in C:/Users/.../worktrees/ via
  `git worktree add`, redo experiment phases. Going forward: every
  non-trivial task starts with `git worktree add`.

FAILURE forgot_to_use_worktree_for_long_experiment:
  RECOVERY: stop the experiment, `git worktree add` a new worktree,
  copy the in-progress files into it, resume from there.

FAILURE git_stash_for_baseline_comparison_stranded_uncommitted_multi_file_work:
  # INCIDENT 2026-07-01 claude-hud profile-labels: to compare test failures on my
  #   Full: incidents#2026-07-01-claude-hud-profile-labels-to-compare
  RECOVERY: discard any gitignored build churn blocking the pop
  (`git checkout -- dist/`), `git stash pop`, then VERIFY every expected change is
  present (`grep -c <marker> <each file>`) BEFORE `git stash drop`. If the pop
  reports "stash entry is kept", the restore was partial — do not drop until verified.
  PREVENTION: never `git stash` to compare against another ref on uncommitted
  multi-file work. Cut a baseline worktree off origin/main, or commit-then-compare.
  Same uncommitted-vanish class as the wiped-experiment and stash+checkout entries
  above — stash is the blunt instrument this rule exists to route around.

FAILURE mutation_test_restore_via_git_checkout_discarded_the_uncommitted_fix:
  # INCIDENT 2026-07-26 claude-config audit pass 3: mutation-testing a new gate
  #   Full: incidents#2026-07-26-claude-config-audit-pass-3-mutation
  RECOVERY: re-apply the edit, then re-verify with a CONTENT grep — never trust
  the gate's exit code alone after a restore (it can pass for the wrong reason).
  PREVENTION, in preference order:
    1. **Commit the fix BEFORE mutation-testing it.** Then `git checkout --` is
       exactly right: it restores the fix instead of deleting it. Cheapest fix,
       and it makes the whole loop safe.
    2. If it must stay uncommitted, mutate a COPY (`cp file /tmp/x.SAFE`, edit,
       restore with `cp /tmp/x.SAFE file`) — never route the restore through
       git, which knows only about HEAD.
    3. `git stash push -- <file>` + `pop` works for one file but inherits the
       partial-pop hazard above; prefer 1 or 2.
  FORBIDDEN: `git checkout -- <path>` as the restore step of a mutation test on
  a file whose change is not yet committed.

FAILURE worktree_created_in_wrong_repo_from_sibling_cwd:
  # INCIDENT 2026-06-14: ran `git worktree add ~/worktrees/<name>` with the shell
  #   Full: incidents#2026-06-14-ran-git-worktree-add-worktrees-name
  RECOVERY: `git -C <wrong-repo> worktree remove <path> --force` +
  `git -C <wrong-repo> branch -D <stray-branch>`, then recreate with explicit
  `git -C <intended-repo> worktree add ...`.
  PREVENTION: ALWAYS `git -C <intended-repo> worktree add` — never rely on cwd,
  especially after exploring a sibling repo earlier in the session.

FAILURE edited_main_checkout_then_built_from_worktree_reverted_a_prior_fix:
  # INCIDENT 2026-06-30 example-requirements charset regression: a one-line charset
  #   Full: incidents#2026-06-30-example-requirements-charset-regression-a-one
  RECOVERY: re-apply the fix IN the worktree (the shipping tree), regenerate
  there, and add a regression test so the revert can't recur silently.
  PREVENTION:
    1. Build EVERY fix in a worktree cut from origin/main — never in a
       throwaway /tmp clone (its changes never reach the tracked checkout) and
       never in the main checkout you then copy OUT of.
    2. NEVER `cp` edited files from one checkout into a worktree to "move" work.
       If work landed in the wrong tree, `git stash` + `git stash apply` in the
       worktree, or cherry-pick a commit — a raw cp overwrites the worktree's
       base (incl. commits it already had) with no merge.
    3. A one-line fix inside a large generated artifact MUST ship with a
       regression test (see verify-effectiveness.md) — an untested one-liner in
       a 6MB-generating template is one stale-base edit from silent reversion.

FAILURE cross_repo_single_file_write_uncommitted_for_session_duration:
  # INCIDENT 2026-05-06 plan-file-vanish (in /retro distill window):
  #   Full: incidents#2026-05-06-plan-file-vanish-in-retro-distill
  RECOVERY: when writing a plan, report, or any output file to a
  DIFFERENT repo's main checkout from the active worktree, treat it
  as if it were committed-required-immediately:
    1. Write the file
    2. In the SAME turn, `cd` to the other repo, create a feature
       branch, commit, push, open a PR, merge.
    3. If the file is too small or experimental to ship, do NOT write
       it to the other repo at all — write to a temp location ONLY IF it
       is truly disposable (no API/compute cost, no future value); else
       a durable repo path (see the /tmp FAILURE below).
  Equivalent rule: cross-repo writes that aren't worth a PR aren't
  worth writing.

FAILURE expensive_run_output_written_to_tmp_purged_at_rollover:
  # INCIDENT 2026-06-22 measurement-census: the ENTIRE multi-day oracle-cascade
  #   Full: incidents#2026-06-22-measurement-census-the-entire-multi-day
  RECOVERY: re-run from a durable path. PREVENTION: any run with API spend,
  multi-minute compute, or a result you'd want to read TOMORROW writes to a durable
  repo-relative path (e.g. `<repo>/bench/.../runs/`), gitignored if the content is
  sensitive (`runs/*` ignored, `!baselines/*.json` negated for a content-free
  metric summary) so the value survives BOTH git cleanup AND the /tmp purge. Commit
  the harness too, so even uncommitted in-progress work can be regenerated. /tmp is
  for TRULY disposable scratch ONLY — a one-shot probe whose output you read THIS
  turn and never again. The moment a file represents real cost or future value, it
  is NOT /tmp-eligible.
  # RECURRED 2026-07-31 in `~/claude-scratch/`, which this FAILURE did not name —
  # and that omission is why nothing fired. A 90-day Anthropic cost/usage pull
  # (6 feeds, 39,368 records, 27.9 MB) plus its 489-line harness sat in
  # `~/claude-scratch/pull90/` while the pipeline that consumes it read from a
  # data dir containing ONLY a freeze file. `~/claude-scratch` is NOT OS-purged,
  # so it reads as "not /tmp, therefore safe" — but it is untracked, outside every
  # repo, and invisible to `git status`, so it fails the SAME durability test for a
  # DIFFERENT reason: nothing will ever tell you the file is unbacked. The tell was
  # that the pipeline could not find its own inputs.
  # THE TEST IS NOT "IS IT /tmp?" — it is: would a `git status` anywhere show this
  # file as at-risk, and can it be REGENERATED? A path failing both is disqualified
  # whatever it is called. Named non-durable locations on this host: `/tmp/**`
  # (OS-purged at rollover), `~/claude-scratch/**` (untracked, no repo), any
  # `$TMPDIR` path, and a worktree that will be removed at session end
  # (worktree-by-default STEP_5).

FAILURE long_run_tied_to_shell_lifetime_died_silently_with_no_forensic_trail:
  # INCIDENT 2026-06-22 credential-census: a multi-hour Athena+Bedrock census ran in
  #   Full: incidents#2026-06-22-credential-census-a-multi-hour-athena
  RECOVERY/PREVENTION: any run longer than ~a few minutes or with real cost gets the
  durability triad: (1) DETACH from the shell so it survives the session — `nohup
  <cmd> >runs/<id>/run.log 2>&1 &` (or a background Bash task), with `mkdir -p
  runs/<id>/` in the SAME shell FIRST (a redirect into a not-yet-created dir no-ops
  the launch — see platform-constraints `nohup_redirect_to_a_dir_the_launched_process_creates_itself`);
  (2) write a `.done`/`.fail` MARKER on completion so status is a file-read, not a
  guess; (3) MONITOR by OUTPUT GROWTH (findings/log advancing), NOT pid-liveness — a
  hung run keeps its pid but stops producing, and a finished run's pid is gone though
  the work succeeded, so pid-presence answers neither "done?" nor "hung?". Code +
  resume-state on a durable committed path so a kill is resumable, never a full re-run.

FAILURE removed_a_worktree_while_a_background_loop_ran_FROM_it:
  # INCIDENT 2026-07-05 compliance-access-framework arc: a `python3 bin/pr-merge-verified.py`
  #   Full: incidents#2026-07-05-compliance-access-framework-arc-a-python3
  RECOVERY/PREVENTION: run a background merge/verify/poll loop from a CWD that OUTLIVES the
  work — the MAIN checkout (`cd <main> && python3 bin/pr-merge-verified.py <N>`), NOT the
  feature worktree it merges. Never `worktree remove` a worktree while a process you launched
  from it is still running: confirm the loop reported terminal `state == MERGED` (or kill it)
  BEFORE removing the worktree. A background task's own completion notification is the safe
  signal to clean up; a still-running loop is not.

# ─── PROCEDURE: writing output artifacts (plans, reports, evidence) to
#                another repo from inside a worktree ───
WHEN: I'm working in worktree of repo A and want to write a plan,
      report, or other output file into repo B's working tree (a
      different checkout — typically knowledge-base, claude-config,
      or a docs repo).
REQUIRED: the write and the commit/push to repo B must happen in the
       SAME turn. Acceptable patterns:
         - Write file → cd repo B → git checkout -b → git add → git
           commit → git push → gh pr create → gh pr merge --auto.
           ~5 sequential commands; one turn.
         - OR write file to a temp location (`/tmp/...`) instead of
           the destination repo ONLY IF it is truly disposable (no
           API/compute cost, no future value). /tmp is purged at the
           macOS date rollover — a result with real cost goes to a
           durable repo path, never /tmp (see the FAILURE above).
FORBIDDEN: writing to repo B's working tree and then continuing the
       primary work in repo A's worktree without committing repo B's
       file in the same turn. Repo B's working tree is at risk of
       cleanup hooks firing between turns.

# ─── RELATIONSHIP TO OTHER RULES ───
- subagent-verification.md: requires worktree isolation for subagent
  writes in protected repos. THIS rule extends that requirement to
  ALL non-trivial work, regardless of whether it's done by main session
  or subagent.
- git-hygiene.md: covers feature branches and PRs. Worktree-by-default
  is the implementation choice for HOW to manage feature branches —
  via worktrees, not via in-place checkout-and-edit on main.
- check-before-change.md: read-before-edit. Compatible: read in main
  is fine; edit in worktree.

# ─── WHAT DOES NOT NEED THIS RULE ───
- Trivial fixes (one-line, immediate commit)
- Read-only investigations
- Operations on repos outside our protected orgs (where the cleanup
  hooks aren't configured)
- **Writing a GITIGNORED runtime artifact under `~/.claude`** (e.g.
  `retrospectives/`, `projects/*/memory/`, `last-distill.json`). These never
  enter a commit, so the shared-HEAD race cannot occur — no worktree needed.
  The `write-edit-dispatcher` guard still blocks the **Write/Edit tool** by
  path-prefix (it cannot see gitignore status), so route the write through
  **Bash** (`cp` from `/tmp`, or a `python3` script). SCOPED EXEMPTION: this is
  ONLY for gitignored paths — TRACKED files on a feature branch still require
  `/work`; never Bash-write a tracked file to bypass the guard (that
  reintroduces the shared-HEAD race the guard exists to prevent).
  (2026-06-30: hit twice writing a retro report + an auto-memory anchor.)

## Recovered 2026-08-08 — verification tree and isolated cleanup

An evidence-producing command must identify the worktree it measured in the
same invocation. Claude Code's Bash working directory can return to the primary
checkout between calls, so a relative test path can run the unchanged main tree
and produce a convincing green result. In the observed case, 1,515 tests was the
main baseline while the treatment worktree collected 1,524. Absolute paths (or
an explicit `cd`) plus the collection count expose that substitution.

Worktree removal belongs in a non-isolated main session. Claude Code 2.1.222
expanded worktree isolation to Bash, and an upstream report described even
read-only `git -C <main>` being rejected from an isolated session. Treat the
report as a requalification trigger, not local fact, but do not design cleanup
that requires crossing the isolation fence from inside the worktree session.
