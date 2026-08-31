# Failure Paths

Each step has a deterministic recovery action. **Never silently abandon a
partially-shipped state** — either drive the failure to resolution or report
the partial state to the user.

| Failure point | Symptom | Recovery |
|---|---|---|
| Step 2 branch creation | `git checkout -b` exits 0 but `git branch --show-current` still on main (Git Bash quirk) | Abort. Re-run `git checkout -b <name>` then verify before any `git commit`. |
| Step 2 contended checkout | `git worktree add` or guarded transplant fails | Leave the shared checkout's HEAD and edits untouched. Report the worktree path and failed file; do not clean either tree until terminal merge state is known. |
| Step 2b marketplace sync | `build-marketplace.py` fails or marketplace bundle drifts from canonical | Resolve drift before commit. Do NOT commit canonical-only changes if a marketplace skill was touched — the bundle gate in CI will fail. |
| Step 2b full preflight aggregator | `bin/preflight-skill.py` reports a failed gate | Fix that gate, re-run it with `--only <key>`, then re-run the full aggregator. Do not commit or push until the full tier exits 0. |
| Step 3 pre-commit hook | Hook exits non-zero | Fix the underlying issue, re-stage, create a **new** commit. NEVER `--amend` (the failed commit didn't happen; amend would mutate the previous one). NEVER `--no-verify`. |
| Step 4 security gate | Policy denies the change | Stop. Address the policy finding before retrying. Do not bypass with `--admin`. |
| Step 5a push | Network error | Retry with exponential backoff (2s, 4s, 8s, 16s) up to 4 times. Permanent failure → report to user with the error; do not force-push. |
| Step 5b PR creation | `gh pr create` fails after push succeeded | Branch is live but unmerged. Re-run `gh pr create` once. If still failing, report PR-creation failure with branch name so the user can open it manually. |
| Step 5c effective required-status rules query | Rules endpoint errors, returns malformed data, or required check contexts are ambiguous | Enter the terminal-green fallback. Do not infer enforcement from repository visibility or PR-only rules. |
| Step 5d bounded registration window | No checks appear before the registration deadline | Inspect workflow runs for the current PR/merge-group head SHA and reconcile GitHub's official Actions status plus incident feed. During an active webhook incident, make no PR/repository changes and retry later. Never rerun a completed run from a retired merge-group SHA; if applicability remains ambiguous, leave the PR open and report rather than merging an empty check list. |
| Step 5e required checks | A registered or required check fails | Use `/pr-fix` on the PR. Do not arm or re-arm merge and never retry with `--admin`. |
| Step 5f merge-queue silent drop | PR is `OPEN` and `CLEAN`, `autoMergeRequest` is null, and no `mergeQueueEntry` exists | Let `pr-merge-verified.py` re-arm. `autoMergeRequest` null alone is not a drop; never hand-diagnose in parallel with the helper. |
| Step 5g verified-merge timeout | Helper exits 2 or the PR remains `OPEN` at the bounded deadline | Report the exact remote state and keep the branch/worktree intact. Do not treat quiet output or a filter pipeline's exit code as success. |
| Step 5h Linked-worktree cleanup | Cleanup or branch deletion fails because another worktree owns the branch | Verify remote `MERGED` state, then remove the worktree separately. Remote state is authoritative; do not unwind a landed PR. |
| Step 6 Linear breadcrumb | Linear API error | PR is already merged — the breadcrumb is best-effort. Log the failure in the report and continue. Do not retry indefinitely. |

**Decision rule for partial state**: if Step N succeeded but Step N+1 cannot
recover, surface the partial state and **stop**. Specifically: a pushed branch
without a PR is recoverable by the user; an opened PR without auto-merge is
recoverable; a queue-only handoff is recoverable when it names the terminal
verification owner; a merged PR without a Linear breadcrumb is recoverable.
Do not attempt to unwind successful steps.
