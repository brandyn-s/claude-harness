---
name: pr-fix
description: "Clear the PR queue — failing CI, stuck auto-merge, conflicts, stale branches, dirty trees, orphaned worktrees."
when_to_use: "Use when PRs are stuck across the board: failing CI, stuck auto-merge, merge conflicts from drift, others' PRs needing review, commits with broken CI on main, stale merged branches, uncommitted work in dirty trees, or orphaned worktree directories left by prior sessions. Multi-axis discovery across all repos — surfaces PRs the daily digest flags, not just the ones with red checks. Trigger phrases: \"pr-fix\", \"fix CI\", \"stuck PRs\", \"stale PRs\", \"failing checks\", \"address my PRs\", \"clear my PR queue\", \"PR digest\", \"stale branches\", \"clean up branches\", \"clean up worktrees\", \"orphaned worktrees\", \"stale worktrees\", \"what PRs are broken\", \"rebase my conflicts\", \"review queue\", \"broken CI on main\", \"failed workflows\", \"dirty repos\", \"uncommitted changes\", \"ship pending artifacts\". Do NOT use for creating new PRs (use /ship) or initial code writing."
argument-hint: "[optional: org/repo#number for direct fix, --iterate to loop until green, --axis [name] for single-axis fast-path (e.g. failing), or omit for discovery]"
effort: high
metadata:
  author: example-security-engineering
  version: "1.3"
compatibility:
  # Requires gh CLI for PR status and workflow run queries.
  requires:
    - cli: gh
allowed-tools: AskUserQuestion Bash Edit Glob Grep Read Write mcp__codebase-memory-mcp__trace_call_path mcp__codebase-memory-mcp__index_status mcp__codebase-memory-mcp__search_code
---

## pr-fix

# PR Fix - CI Failure Discovery and Repair

Find failing CI across all repos: open PRs with broken checks, commits with failed workflow runs (push to main, scheduled jobs, manual dispatches), and stale merged branches. Diagnose from logs, fix code, push to the right branch, and clean up branch accumulation.

---

## Phase 0: Skill freshness (always first)

This skill's own procedure files can be STALE on the host running it, and a
stale reference produces confidently wrong counts with no error. `~/.claude` is
the live checkout and its `main` is permanently content-diverged from
`origin/main`, so a merged fix to this skill does NOT reach the host.

```bash
git -C "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" fetch origin main --quiet
python3 - <<'PY'
import subprocess
R = "$HOME/.claude"
ls = subprocess.run(["git","-C",R,"ls-tree","-r","--name-only",
                     "origin/main","skills/pr-fix/"],
                    capture_output=True,text=True).stdout.split()
stale = []
for p in ls:
    want = subprocess.run(["git","-C",R,"rev-parse",f"origin/main:{p}"],
                          capture_output=True,text=True).stdout.strip()
    got = subprocess.run(["git","-C",R,"hash-object","--path",p,"--",p],
                         capture_output=True,text=True).stdout.strip()
    if want != got: stale.append(p)
print(f"STALE {len(stale)}/{len(ls)}")
for p in stale: print("  ", p)
PY
```

If any reference is stale, read the `origin/main` copy
(`git show origin/main:<path>`) for every procedure you are about to follow,
and say in the report which files were stale. A stale `SKILL.md` cannot be
repaired mid-run — its body is already in context — so re-invoke after
deploying. Ported from the equivalent gates in `/healthcheck` (Check 0),
`/audit-architecture` (Phase 0), and `/software-security-review`
(`preflight.py` check 0).

Measured 2026-08-25: 8 of 20 `skills/pr-fix/` files were stale on this host
(local `main` 278 ahead / 216 behind). Following them reported **85** worktree
candidates instead of 21 (the stale copy lacked the managed-root exclusion for
`~/.Codex` / `~/Documents/Codex`, 120 of 165 registrations) and **13**
deletable branches instead of 2 (the stale copy lacked the >5-branch gate).
Both were published to the user before the staleness was noticed.

## Phase 1: Discovery (multi-axis)

Discovery is read-only and parallel across PRs, commit CI, approval gates,
branches, dirty trees, and worktrees. Read
[`references/discovery.md`](references/discovery.md) and follow it as the
authoritative Phase 1 procedure. Its core boundaries are:

- Search PRs by involvement across the managed organizations; use the repo map
  only for local-path and writable-remote resolution.
- Deduplicate by `(repository.nameWithOwner, number)` through
  `scripts/pr_fix_state.py`; a repository basename is not globally unique.
- Hydrate every PR in real time and query GraphQL `mergeQueueEntry` separately.
  `[PR-READY]` requires CLEAN + unarmed + an explicit null queue entry.
  A non-null entry is `[PR-QUEUED]`; a failed queue query is unknown, not ready.
- A passing check is affirmative evidence. Empty, cancelled, skipped-only,
  pending, and unknown snapshots are never green.
- Filter commit failures by both same-workflow recency and commit supersession.
  Report stalled approval gates but never approve them.
- Carry branch `name expected_sha` records from the merged-PR SHA join through
  confirmation and leased deletion. Never recompute with ancestry.
- Dirty-tree and worktree axes are clone-local and retain their own explicit
  scope and confirmation gates.

Present one deduplicated report before any fix or destructive action. A generic
selection of the report does not authorize branch deletion, worktree removal,
deployment approval, or a repository-wide policy change.

---

## Phase 2: Diagnose

For the selected item. **[PR]** items run 2a-pre first (supersession triage — cheap main-state reads that answer "did main move past this PR?" before any worktree; measured 2026-08-22 it resolved 8 of 9 stale items with no code fix), then 2a-2e (PR context, failing checks, CI logs by run ID, classification flowchart code-vs-infra-vs-unknown, cosmetic-failure reclassification). **[CI]** items use 2a-ci which reuses the same classification flowchart on commit-CI logs.

Detailed gh commands, the classification flowchart, the cosmetic-failure pattern table (dependabot workflow-permission, pre-existing main breakage, non-required checks), and reusable-workflow / gitleaks SARIF caveats live in `references/diagnose.md`. Read that for any [PR] or [CI] item.

---

## Phase 3: Fix

For `[PR-FAIL]`, first read
[`references/repair-worktree.md`](references/repair-worktree.md). Every repair
runs in a dedicated worktree cut at the hydrated `headRefOid`; never stash,
switch, reset, or edit an existing shared checkout.

1. Resolve the source clone and writable remote. Clone on demand only when no
   mapped clone exists.
2. Fetch the exact `headRefName`, verify it still equals `headRefOid`, and add a
   detached dedicated worktree at that SHA.
3. Read `gh pr diff` and the failing logs. If the repo is indexed, search for
   variants and trace affected callers before editing.
4. Apply the smallest complete fix inside the repair worktree and run targeted
   tests plus repository-required validation.
5. Commit specific files and push `HEAD:refs/heads/<headRefName>` with
   `--force-with-lease=refs/heads/<headRefName>:<headRefOid>`. A lease failure
   means the branch moved; stop and rehydrate rather than overwriting it.
6. Verify the remote head, then remove only the clean worktree created by this
   run. Do not touch sibling worktrees or the shared clone's current branch.

Report the original CI error, fix, commit, remote branch, tests, and cleanup
state. Unless iterate mode was requested, do not wait for CI after the push.

---

## Phase 3-ci: Fix Commit CI Failures

For **[CI]** items (failed workflow runs on commits, not PRs). Unlike PR fixes, there's no existing PR branch — create a `fix/` branch, push, open a PR, queue auto-merge.

Detailed step-by-step procedure lives in `references/commit-ci-fix.md`. Read
that when processing any `[CI]` item—it covers isolated base hydration, branch
creation, commit and push, PR creation, auto-merge, and cleanup.

---

## Phase 3-ready: Merge [PR-READY] and [PR-COSMETIC]

For PRs with green required checks and no auto-merge queued. Queue auto-merge in batches.

### A merge is not always a merge — check for a deploy trigger FIRST

Before merging ANY `[PR-READY]`, check whether the base repo has a
`push`-triggered workflow that matches the PR's diff **and declares a GitHub
`environment:`**. If one does, merging is a DEPLOY, and a queue-cleanup selection
is not authorization for it. Report it and stop; get named authorization.

**`environment:` is the discriminator — a bare push+paths match is not.** Almost
every repo has push-to-main CI (secret scanning, mirrors, validate), and those
match any diff, so matching alone flags everything and the gate gets ignored. A
deploy declares an environment, because that is where approval gates and deploy
secrets live. Measured over 5 real PRs, this separates cleanly:

| PR | diff | DEPLOY | ci-only |
|---|---|---:|---:|
| mcp-infra #1492 | `govcloud/mcp-outlook/variables.tf` | **3** | 3 |
| claude-config #2145 | skill + marketplace files | 0 | 3 |
| example-labs-org/.github #81 | `.github/workflows/baseline-ci.yml` | 0 | 3 |
| example-labs-infra #343 | `scripts/paved_road.py` | 0 | 4 |
| cloud-self-service #16 | `CODEOWNERS` | 0 | 2 |

Run it with `scripts/deploy_trigger_probe.py` (a FILE, not inline — an earlier
inline-in-a-shell-loop version failed silently under `2>/dev/null` and reported
zero findings for the known positive):

```bash
python3 "$PR_FIX_DIR/scripts/deploy_trigger_probe.py" <org/repo> <N>
```

It prints BOTH classes and any parse errors. Do not filter the `ci-only` rows
away — an unreadable workflow is unknown coverage, not a clean result. `DEPLOY`
rows carry the environment name so a non-deployment environment (a read-scoped
one, `deployment: False`) can be told apart from a real gate by eye.

Measured 2026-08-26 (mcp-infra #1471/#1477/#1492): three PRs classified
`[PR-READY]` — green, unarmed, unqueued, one-line diffs — each changed
`govcloud/mcp-outlook/variables.tf`. `outlook-production-release.yml` triggers on
`push` to `main` with `paths: govcloud/mcp-outlook/**`, reads `IMAGE_TAG` from
exactly the changed line, and runs in `environment: production` against a service
serving 914 users. A user selection of "merge the ready items" would have fired a
GovCloud production release. Nothing in this skill asked the question; the only
thing that caught it was checking the deploy path by hand.

Two corollaries worth applying without re-deriving them:

- **Mutually exclusive PRs look like a stack.** Those three all rewrote the SAME
  line from the SAME base value to three different SHAs. Merging any one makes the
  other two conflict, and merging them in listed order promotes the OLDEST
  artifact last. Diff them against each other before batching.
- **Repos may carry their own release contract.** mcp-infra's `CLAUDE.md` requires
  `scripts/release-domain status <exact-registered-domain>` before crossing a
  protected production boundary. Read the target repo's `CLAUDE.md` before merging
  anything that deploys.

### `BLOCKED` with green checks and no review requirement usually means UNSIGNED

A PR can be `mergeStateStatus == BLOCKED` with every required check green,
`reviewDecision` empty, and `required_approving_review_count == 0`. That is not
"awaiting review" — check the commit signature before reporting it as such:

```bash
head=$(gh pr view <N> --repo <org/repo> --json headRefOid --jq .headRefOid)
gh api "repos/<org/repo>/commits/$head" --jq '.commit.verification | "\(.verified) \(.reason)"'
gh api "repos/<org/repo>/rulesets" --jq '.[].id' \
  | xargs -I{} gh api "repos/<org/repo>/rulesets/{}" --jq '.rules[].type' | grep required_signatures
```

`verified=false` + a `required_signatures` rule is the blocker. Measured
2026-08-26: four PRs were reported to the user as "awaiting review, all green"
when all four were blocked by unsigned commits — three of them in repos requiring
ZERO approvals. Recovery is `git commit --amend -S --no-edit` plus an
expected-SHA leased force-push; verify the tree hash is unchanged so the amend
carries no content.

**Do not gate the local re-sign check on `%G?`.** It reports local
*verifiability* and needs `gpg.ssh.allowedSignersFile`, which is commonly absent —
it returns `N` for a correctly signed commit. Check the commit object's header
instead, and let GitHub do the verifying:

```bash
git cat-file commit HEAD | sed -n '/^$/q;p' | grep -c '^gpgsig'   # >=1 = signed
```

**Probe merge-queue state live — never from a remembered repo list.** Queue
status changes over time: claude-config WAS documented here as a merge-queue
repo, and by 2026-08-22 its live `mergeQueue` was `null` with no required
checks, so the prescribed bare `--auto` failed outright. One call answers it
for the repo at hand:

```bash
gh api graphql -f query='query{repository(owner:"<org>",name:"<repo>"){mergeQueue{id}}}' \
  --jq '.data.repository.mergeQueue'
```

**Merge-queue repos (non-null probe) use bare `--auto`** (git-hygiene
invariant `merge_queue_repos_use_bare_--auto`): `--delete-branch` hard-errors
and `--squash` is rejected (the queue dictates strategy and branch deletion).
Queue with `gh pr merge <pr> --repo <org/repo> --auto` (bare), or run
`python3 bin/pr-merge-verified.py <pr>` from the claude-config checkout
(arms, polls, re-arms on silent queue drops). Verify landing by
`state == MERGED`, never by `--auto`'s output or the PR's check badges.

```bash
# Non-merge-queue repos:
for pr in <numbers>; do
  gh pr merge $pr --repo <org/repo> --auto --squash --delete-branch
done
```

Handle three GraphQL responses to a queued `--auto` — the first two mean "there is nothing for `--auto` to wait on" (drop `--auto`, merge directly); the third means the repo has the auto-merge feature OFF:

- `Pull request is in clean status (enablePullRequestAutoMerge)` — all required checks are already green at queue time.
- `Branch does not have required protected branch rules (enablePullRequestAutoMerge)` — the repo's `main` has **no branch protection / required checks** (e.g. `example-labs-org/fxhoudinimcp`, 2026-06-16), so auto-merge is invalid. This is **NOT** a merge-queue repo: do NOT retry bare `--auto` (it errors `--merge, --rebase, or --squash required when not running interactively`). Merge directly with an explicit method.
- `Auto merge is not allowed for this repository (enablePullRequestAutoMerge)` — `allow_auto_merge=false`. Default to the **one-off** action already in scope: direct-merge only this PR with `--squash --delete-branch`. Changing `allow_auto_merge` or `delete_branch_on_merge` changes policy for every future PR and requires a separate `AskUserQuestion` that names the exact repository, both fields, and their new values. Only after that target-specific answer may you run `gh api -X PATCH repos/<org>/<repo> -F allow_auto_merge=true -F delete_branch_on_merge=true`; read the repository settings back before reporting success. A prior request to fix or merge a PR is not that policy authorization.

```bash
gh pr merge <pr> --repo <org/repo> --squash --delete-branch
```

After the batch, poll state once to report merged vs still-open. Do NOT wait for every PR to land — some will merge later when required checks finish.

---

## Phase 3-conflict: Rebase [PR-CONFLICT]

For PRs where you are the author and `mergeStateStatus == "DIRTY"` (armed
auto-merge is not required). After the rebase, rehydrate both auto-merge and
GraphQL queue state: arm only when both are explicitly absent.

**Triage by staleness first** (2026-05-17 calibration: 4/4 rebases on PRs >7d stale hit real conflicts and were closed; 2026-08-22: 5/5 at 4-6d conflicted too, and supersession triage closed 4 of them without a worktree):

| PR age (since createdAt) | Default action |
|---|---|
| <3 days | Auto-rebase per procedure |
| 3-7 days | Run `diagnose.md` §2a-pre supersession triage first; auto-rebase survivors with "X-day stale, conflict probable" warning |
| >7 days | `AskUserQuestion` (close vs rebase) BEFORE touching the branch |

The dedicated-worktree procedure, checkpoint-commit handling via `git rebase --onto`, and expected-SHA leased push live in `references/conflict-rebase.md`. Read it before touching any conflicted PR.

**Hard rule**: never rebase a PR you did not author. Force-pushing someone else's branch destroys their work in progress.

---

## Phase 3-review: Triage [PR-REVIEW]

For PRs authored by others that are queued for your review. NEVER auto-merge — the point is the review itself, not the merge. Produce a per-PR summary with the diff scope, touched files, and any obvious blockers (failing CI, conflicts, draft). Then flag to the user for manual review.

Detailed per-PR summary format lives in `references/review-triage.md`.

---

## Phase 3-dirty: Ship Pending Artifacts

For **[DIRTY]** items or when the user selects 'dirty'. Categorize each repo's dirty files using the bucket table from Discovery, then act per repo:

- **Prior-session-artifact bucket → auto-ship:** if ALL non-transient dirty files match (agent-memory/topics, hooks, topics, research, plans), transfer only those reviewed paths into a dedicated worktree, commit specific files, and create a PR. Leave the dirty source checkout unchanged.
- **In-progress-feature bucket → ask first:** new service files, Terraform, large refactors. **Default to skip** on no response.
- **Transients only → report excluded**, no action.
- **Mixed buckets → treat as in-progress-feature** (ask first).

The isolated transfer, merge variants, and report contract live in `references/dirty-ship.md`. Read it before shipping any `[DIRTY]` item.

---

## Phase 3-br: Clean Up Stale Branches

For **[BR]** items or when the user selects 'branches'. Deletes exact remote
refs whose live tips still match merged-PR head SHAs, after user confirmation.

The exact-target confirmation, OPEN-PR recheck, and expected-SHA leased deletion live in `references/branch-cleanup.md`. Read it before deleting anything.

---

## Phase 3-wt: Clean Up Orphaned Worktrees

For **[WT]** items or when the user selects 'worktrees'. Removes linked
worktrees only when the tree is clean and an exact merged-head match or a
zero-unique-commit comparison proves no work will be lost, after user
confirmation.

Detailed procedure (two-factor safety check, confirmation prompt,
removal, report) lives in `references/worktree-cleanup.md`. Read that
before removing anything.

---

## Phase 4: Sequential Multi-Fix

If the user chose 'all' in discovery, process each item sequentially through the appropriate Phase 2/3 path. Report a combined summary at the end:

```
=== CI Fix Report ===

| # | Type | Repo | Ref | Error | Action | Result |
|---|------|------|-----|-------|--------|--------|
| 1 | PR | claude-config | #285 | JSON parse | Code fix | Pushed to branch |
| 2 | PR | mcp-servers | #201 | Import error | Code fix | Pushed to branch |
| 3 | CI | mcp-servers | main@b942dd3 | Missing env var | Code fix | PR #305 created |
| 4 | CI | code-graph | main@abc1234 | Runner timeout | Rerun | Triggered |
| 5 | BR | claude-config | 52 branches | Merged, stale | Cleanup | 52 deleted |
| 6 | BR | mcp-servers | 22 branches | Merged, stale | Cleanup | 22 deleted |
| 7 | WT | claude-config | 2 worktrees | Branch merged, clean | Cleanup | 2 removed |
```

---

## Direct Mode

Direct mode (`/pr-fix <PR-number-or-URL>`) skips discovery and goes straight to diagnose+fix for one PR. Full semantics: `references/direct-mode.md`.

## Guardrails

- **Read before fix**: ALWAYS read CI logs before touching code (diagnose-before-fix rule)
- **A merge that fires a deploy is not queue cleanup**: before merging any `[PR-READY]`, check for a `push`-triggered workflow whose `paths` match the diff (Phase 3-ready). If one matches, report it and stop — a selection of "merge the ready items" is NOT named authorization for a production release, and the PR can look trivially safe (one line, all green). 2026-08-26: three one-line `[PR-READY]` PRs would each have fired a GovCloud `environment: production` release.
- **`BLOCKED` + green required checks + no review requirement = check the signature**: `verified=false` against a `required_signatures` ruleset blocks a PR that otherwise looks ready, and it reads exactly like "awaiting review". Never report a BLOCKED PR as awaiting review without reading `commit.verification` first (Phase 3-ready). 2026-08-26: four PRs misreported this way.
- **Never suppress commit signing**: do NOT pass `-c commit.gpgsign=false` (or otherwise disable signing) on any commit. Repos here carry `required_signatures`, so an unsigned commit is an unmergeable commit. If signing appears to fail, verify with the `gpgsig` header — not `%G?`, which needs an allowed-signers file that is usually absent and returns `N` for correctly signed commits.
- **PR repair stops after push**: A `[PR-FAIL]` code repair does not merge the PR after pushing. Phase 3-ready and commit-CI-created PRs use their explicit queue procedures.
- **PR fixes → existing branch**: Push to the existing PR branch. No new PRs for PR fixes.
- **Commit CI fixes → new fix/ branch + PR**: Create a `fix/` branch from main and open a PR.
- **Iterate mode**: When invoked with `--iterate` (or user says "keep going until green"), after pushing a fix, wait 90 seconds, check CI status, and if still failing, loop back to Phase 2 with the new error. Max 3 cycles per item. Report each cycle. Stop on green or after 3 attempts.
- **Repair isolation**: Never stash or switch a shared checkout. `[PR-FAIL]`, `[PR-CONFLICT]`, `[CI]`, and `[DIRTY]` changes run in a dedicated worktree; updates to existing remote branches use an explicit expected-SHA push lease.
- **Fork repos**: Always pass the `--repo` flag noted in `_shared/repo-map.md` Notes column (e.g., code-search needs `--repo example-org/code-search` on all `gh pr` commands)
- **7-day window**: Commit CI discovery only surfaces failures from the last 7 days to avoid noise.
- **A `main` CI failure `ahead_by ≥ 3` commits is presumptively superseded**: read the source at current `main` for the specific fix BEFORE reporting it actionable. `--limit 3` recency cannot catch this — on a repo whose rapid pushes cancel in-flight CI there may be *no* newer completed run, so "latest completed run is a failure" stays true while the cause is long fixed. Never use a bare `headSha != main-HEAD` test: `ahead_by=1` with no re-run is a genuinely current failure (measured 2026-07-28), and dropping it produces a false all-clear.
- **Branch cleanup confirmation**: ALWAYS confirm with user before deleting branches, and NAME the exact branches in the confirmation itself — not a count, and not in a message that also executes the deletion. A general "proceed" earlier in the session does not authorize a destructive remote write it never named. (2026-08-01: the permission classifier blocked a deletion for exactly this, correctly — the branches had been listed, but in the same turn as the delete.)
- **Leased branch deletion**: Carry the confirmed `(branch, expected_sha)` pair into deletion, recheck OPEN PRs, and use an atomic expected-SHA lease. A mismatch is a SKIP; never fall back to an unleased delete.
- **Threshold**: Only flag repos with >5 branches. Small branch counts are normal.
- **`[GATE]` is never actioned**: stalled approval gates are reported and handed to the user. The skill does not approve deployment gates — see `security-confirmations.md`.
- **Never rebase others' PRs**: `[PR-CONFLICT]` rebase path applies only when `author.login == @me`. Force-pushing someone else's branch destroys in-progress work.
- **Never auto-merge others' PRs**: `[PR-REVIEW]` items are summarized and flagged to the user. The skill never approves or merges on their behalf.
- **Cosmetic-only reclassification requires log evidence**: `[PR-COSMETIC]` label requires the specific error string in the failing job's log (see Phase 2e table). Do not guess a failure is cosmetic from the job name alone.
- **Clean-status merge fallback**: If `gh pr merge --auto` returns `Pull request is in clean status`, drop `--auto` and merge directly. This happens when all required checks are already green at queue time.
- **Merge-queue repos take bare `--auto` only — and merge-queue-ness is probed live, never recalled**: on a repo whose GraphQL `mergeQueue` probe is non-null, `--squash`/`--delete-branch` error, and the queue can silently drop an armed PR (CLEAN-but-OPEN, auto-merge gone). Queue `gh pr merge <N> --repo <org/repo> --auto` or `python3 bin/pr-merge-verified.py <N>`, and confirm `state == MERGED` before reporting merged. (claude-config was hardcoded here as merge-queue; measured 2026-08-22 it no longer is — hardcoded repo facts rot, same class as the retired `mirror` exclusion.)
- **Unprotected repos merge directly**: if `--auto` errors `Branch does not have required protected branch rules`, the repo's `main` has no required checks — merge with `--squash --delete-branch` (no `--auto`). Do NOT retry bare `--auto`; that path is only for merge-queue repos, and on an unprotected repo it errors `--merge/--rebase/--squash required`. (example-labs-org/fxhoudinimcp, 2026-06-16 — 5 PRs failed a first-pass `--auto` before the direct merge. Protection state rots BOTH ways: by 2026-08-22 fxhoudinimcp HAD gained protection and `--auto` queued fine — probe, don't remember.)
- **Mid-CI snapshots are not failures**: a `statusCheckRollup` entry with a **null** conclusion is `in_progress`/`queued` → classify `[PR-PENDING]` and re-poll; never `[PR-FAIL]` (and never diagnose) off a transient mid-run snapshot. Also drop any candidate whose live `state == MERGED` — `gh search prs`' index lag re-lists just-merged PRs as open (2026-06-16: #536).
- **Dirty-tree auto-ship requires bucket match**: Only auto-ship when ALL non-transient dirty files in a repo match the prior-session-artifact bucket (agent-memory/topics, hooks, topics, research, plans). Mixed buckets → ask user.
- **Never auto-ship in-progress feature work**: New service files, Terraform changes, and large refactors require explicit user confirmation. Default action when the user does not respond is **skip**.
- **Dirty discovery never uses `git add -A`**: Stage specific files by name. Transients (`settings.json`, `last-distill.json`, `mcp-needs-auth-cache.json`, `session-friction-patterns.md`, `knowledge-base/README.md`) must never be committed.
- **Dirty-tree tempo signals priority**: Dormant repos (0-4 commits/90d) with dirty work flagged HIGH; active repos (15+) flagged LOW. Sort the [DIRTY] block by tempo when presenting.
- **Worktree removal requires affirmative no-loss proof**: clean status plus either an exact merged-PR-head SHA match or zero commits beyond the verified remote default branch. Remote branch absence alone is not proof, standalone clones are out of scope, and removal is never retried with `--force`.
- **Worktree cleanup confirmation**: ALWAYS confirm with user before removing worktrees. List worktree paths, branches, and PR states first.

---

## Examples

Common entrypoints:

- `/pr-fix` — run read-only multi-axis discovery, then present a selection.
- `/pr-fix example-org/mcp-servers#201` — hydrate and diagnose one PR.
- `/pr-fix --axis failing` — scan only the failing-PR classifier path.

Seven worked examples (stale PRs, direct fix, infrastructure failure, commit CI
failure, branch cleanup, iterate mode, mixed multi-fix) live in
`references/examples.md`.

---

## Phase 5: Iterate Until Green (--iterate mode)

When `--iterate` flag is set or the user requests continuous fixing ("keep going until green"), the skill loops diagnose → fix → wait → re-check up to 3 times per item.

Detailed iteration procedure (90s initial wait, 30s poll cadence, 10-poll cap, 3-cycle limit, per-cycle reporting) lives in `references/iterate-mode.md`. Read that when `--iterate` is set.

---

## Success Criteria

- Owner-qualified involvement discovery covers authored, review-requested, and
  wholly-owned-organization PRs without a hardcoded repository cap.
- Queue state is explicitly observed; `[PR-QUEUED]` and unknown queue state are
  never treated as ready.
- Empty, cancelled, skipped-only, pending, and indeterminate check snapshots
  are never green.
- Repeated-failure detection includes normalized current log evidence, so a
  different error under the same check name remains actionable.
- CI logs and current-state filters are read before code changes.
- Every code fix, rebase, and dirty-artifact shipment uses a dedicated
  worktree; shared checkouts remain unchanged.
- Existing branch updates use expected-SHA leases.
- Branch cleanup carries the confirmed SHA, rechecks OPEN PRs, and uses an
  atomic expected-SHA delete lease.
- Repository-wide settings changes receive their own target-specific
  confirmation and post-write readback.
- Deployment gates and other authors' PRs remain report-only.
- Worktree removal retains kind, clean-state, branch-state, and confirmation
  gates; ambiguous targets are skipped.
- Same-workflow recency and commit supersession both gate commit-CI findings.
- Reports distinguish staged, committed, pushed, queued, merged, cleaned, and
  unverifiable states rather than collapsing them into “fixed.”
