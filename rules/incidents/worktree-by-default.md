---
paths:
  - "**/rules/worktree-by-default.md"
  - "**/rules/incidents/worktree-by-default.md"
---

# worktree-by-default: Incident Narratives

Extracted from `rules/worktree-by-default.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## 2026-07-26-azure-automations-scripts-verify-deploy-readiness

```
INCIDENT 2026-07-26 azure-automations: `scripts/verify_deploy_readiness.py` — the
operator's PRE-MERGE readiness gate, shipped IN the PR — was authored in
~/worktrees/azure-automations-harden and hardcoded
  WORKFLOW = Path.home() / "worktrees/azure-automations-harden/.github/workflows/..."
That worktree is removed at the end of its session (this rule's own STEP_5), so the
script had only ever been runnable in its birthplace. Every later run died
`FileNotFoundError`, and the traceback names the WORKFLOW path — so it reads as "the
workflow is missing" rather than "the verifier is broken." It passed its authoring
run, which is exactly why nobody noticed: the gate was green once, in the one place
it worked. Caught only by running it from a different checkout at ship time.
A worktree is EPHEMERAL BY DESIGN, so any absolute path into one is a
time-bomb the moment the artifact outlives the session — and a tool is the most
likely artifact to outlive it.
```

## uncommitted-experimental-files-in-the-main-checkout-can-vanish

```
WHY: uncommitted experimental files in the main checkout can vanish
     from hook firings, post-merge cleanup, branch deletion side
     effects, gh pr merge --delete-branch, post-checkout hooks, and
     stash+checkout sequences. Worktrees isolate the experimental
     state under a separate path that is not touched by hooks
     operating on the main checkout. Setup cost is ~5 seconds;
     recovery cost from accidentally-wiped files is hours plus
     potentially-irreplaceable API spend.
```

## any-uncommitted-state-in-the-main-checkout-is-at

```
WHY: any uncommitted state in the main checkout is at risk of being
     cleaned up unexpectedly. The main checkout is for browsing
     committed history, not for editing.
```

## incident-2026-05-28-opus-4-8-doc-sync

```
WHY: INCIDENT 2026-05-28 opus-4.8-doc-sync — a parallel session had already
corrected the effort-row on origin/main with the better (max-persistence)
rationale; my stale-base edit would have reverted it. /ship's divergence
check caught it; a fetch+diff at EDIT time would have prevented 5 redos.
```

## 2026-05-04-a4-multi-query-experiment-in-example

```
INCIDENT 2026-05-04 A4 multi-query experiment in example-org/
code-search: three uncommitted files vanished mid-experiment —
a4_multiquery_rerank.py (the experiment script), _a4_work/ (paraphrase
generation results for 183 queries, ~$1 of API cost), a0c_threshold_sweep.py
(threshold sweep script). Working tree silently went clean after
PR #96 auto-merged with --delete-branch. Cause: still under
investigation, but suspected post-merge cleanup hook firing on the
main checkout. ~$1 lost, ~30 min compute lost, recovery overhead.
```

## 2026-07-01-claude-hud-profile-labels-to-compare

```
INCIDENT 2026-07-01 claude-hud profile-labels: to compare test failures on my
branch vs untouched origin/main, I ran `git stash push -u` (twice, on two
separate baseline checks) on uncommitted multi-file work. Both times the
follow-up `git checkout origin/main -- src/ tests/` overwrote the working tree,
so `git stash pop` could not cleanly reapply — it left the work IN the stash
while the tracked files sat reverted to HEAD (which had NO commit yet on the
new branch). Recovered both times (discard the ignored dist/ churn that blocked
the pop → `git stash pop` → verify every file per-`grep -c` → `git stash drop`),
but it cost ~2 recovery cycles and a real scare that the work was lost.
The tell each time: `git stash pop` printed the restored files but ended with
"The stash entry is kept in case you need it again" — a PARTIAL pop (a
gitignored dist/ conflict), NOT a clean restore. Untracked new files (backend.ts)
survived only because `-u` re-adds them; the tracked edits were the ones at risk.
ROOT CAUSE: using `git stash` as a "peek at main" tool on dirty multi-file work.
The correct baseline-comparison tool is a SEPARATE WORKTREE off origin/main
(`git -C <repo> worktree add ~/worktrees/<name>-baseline origin/main`) — it lets
you build/test main WITHOUT touching your working tree at all — OR commit first
(a WIP commit is trivially reversible: `git reset --soft HEAD~1`), THEN compare.
```

## 2026-07-26-claude-config-audit-pass-3-mutation

```
INCIDENT 2026-07-26 claude-config audit pass 3: mutation-testing a new gate
means breaking the tree, running the check, then restoring. I restored with
`git checkout -- <file>` — but the FIX ITSELF was still UNCOMMITTED, so
checkout reverted to HEAD and silently discarded it along with the mutation.
Caught only by re-grepping afterward (`persist-credentials` count went to 0)
and re-applying the edit. Every gate reported green during the window,
because mutation AND fix were both gone — the check "passed" against a tree
that no longer contained the change it was verifying.
SAME uncommitted-vanish class as the stash entry above, but the destroyer is
a deliberate restore step inside a VERIFICATION loop — the one place you are
actively trying to be careful.
```

## 2026-06-14-ran-git-worktree-add-worktrees-name

```
INCIDENT 2026-06-14: ran `git worktree add ~/worktrees/<name>` with the shell
cwd left in a SIBLING repo (had cd'd there to explore it). git resolved the
worktree + new branch against THAT repo, off its origin/main — HEAD showed the
sibling's commit and the expected files were absent. The STEP_2 example uses
`git -C <repo> worktree add` precisely to prevent this; bare `worktree add`
silently targets whatever repo the cwd is in.
```

## 2026-06-30-example-requirements-charset-regression-a-one

```
INCIDENT 2026-06-30 example-requirements charset regression: a one-line charset
fix (PR #14) was built in a THROWAWAY /tmp clone, so the main checkout never
received it. Building the NEXT feature (PR #15) I edited the generator in
that STALE main checkout, then COPIED the edited files into a fresh worktree
and shipped — the copy overwrote the worktree's clean origin/main base,
silently reverting PR #14's fix. My #15 edits didn't touch the reverted
lines, so the loss was invisible in the diff. Two more PRs (#16, #18) carried
the regression forward; the user caught the mojibake return and I spent a
whole PR (#19) re-fixing it + adding the test that should have existed.
ROOT CAUSE: two anti-patterns compounded — (1) a fix built in a location
that never reached the repo's real checkout, and (2) "edit in checkout A,
build/ship from worktree B" where B's fresh base got clobbered by A's stale
copy. The byte-identical output size was the tell I missed the first time.
```

## 2026-05-06-plan-file-vanish-in-retro-distill

```
INCIDENT 2026-05-06 plan-file-vanish (in /retro distill window):
During a session whose primary work was in
`worktrees/code-graph-cg-resolver-fixes-2026-05-06`, wrote a plan
file to `~/Documents/knowledge-base/plans/2026-05-06-...md` (a
different repo's main checkout). Write tool returned success.
Continued working in code-graph for ~30 min. User asked for the
plan URL. File had vanished — same uncommitted-vanish pattern as
the 2026-05-04 incident. Recreate cost: ~5 min recreation + 1 PR
to knowledge-base.
The worktree-by-default rule covered the PRIMARY work (in a
worktree) but did not explicitly cover side-artifact writes to a
SECOND repo's main checkout. The rule fired correctly for the
main work; the plan write fell outside the rule's scope.
```

## 2026-06-22-measurement-census-the-entire-multi-day

```
INCIDENT 2026-06-22 measurement-census: the ENTIRE multi-day oracle-cascade
measurement run (all panel-model output, the drops file, the run-log, the live
worker's working state) + the StepShield harness source were written to
`/tmp/claude/` and `/tmp/p8scratch/`. macOS's periodic /tmp cleanup wiped both
directories at the date rollover (2026-06-22) — destroying ~hours of
in-perimeter Bedrock spend (irreplaceable; the run can't be cheaply re-billed)
and ~7h of day-16 grinding. The harness's RESUME logic couldn't help because
its resume STATE was also in /tmp; a full re-run was required. SAME
uncommitted-vanish class as the 2026-05-04 incident, but the destroyer was the
OS /tmp purge, not a git hook — and `/tmp` was chosen precisely BECAUSE the
advice in this rule treated it as a safe scratch alternative.
```

## 2026-06-22-credential-census-a-multi-hour-athena

```
INCIDENT 2026-06-22 credential-census: a multi-hour Athena+Bedrock census ran in
the FOREGROUND (lifetime == the shell/session) and logged to /tmp. After ~6
restarts the process count silently went to 0 mid-run — S2_content at 47%,
S2_diff never started (~34,822 blobs unjudged) — and because /tmp was also wiped,
the orchestrator + every pipeline_*.log were gone too: "only my probe from 00:58
survives." THREE coupled lifetimes died together: run=shell, logs=/tmp,
code=uncommitted working tree. User: "This was unacceptable. No tmp storage where
we lose data. No un or non-commits." Distinct from the /tmp-purge FAILURE above
(that's WHERE output lives); this is WHAT OWNS THE RUN'S LIFETIME and HOW you
prove it's alive.
```

## 2026-07-05-compliance-access-framework-arc-a-python3

```
INCIDENT 2026-07-05 compliance-access-framework arc: a `python3 bin/pr-merge-verified.py`
merge/verify loop was launched with its CWD INSIDE `~/worktrees/cc-slack-idem`. When that
worktree was `git worktree remove --force`'d as "cleanup" while the loop was still running,
the loop's CWD vanished out from under it — the background process died and the PR's
auto-merge was left DISARMED (PR sat CLEAN + unqueued, un-merged). Recovery: re-run
`pr-merge-verified.py` from the MAIN checkout (CWD-stable), which merged it. Same
lifetime-coupling class as the long-run FAILURE above (run tied to a directory that got
deleted), but here the deleted thing is the WORKTREE the loop was invoked from, not /tmp.
```
