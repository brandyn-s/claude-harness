# Multi-Axis Discovery

Read this for Phase 1. Discovery is read-only. Run independent axes in parallel,
then present one deduplicated report before changing code or remote state.

Set `PR_FIX_DIR` to the directory containing the loaded `pr-fix/SKILL.md` so the
same commands work from a source checkout, `~/.claude`, or `~/.agents`.

## An axis that returns zero is UNKNOWN until a control says otherwise

A discovery axis reporting no findings and a discovery axis whose command never
ran produce **identical output**. Zero is a detector result, not an observation
about the world, and it fails in the direction that ends the search.

Before reporting any axis as empty, run a known-positive control: the same query
with the discriminating filter relaxed, against a repository where a hit is
expected. If the control also returns zero, the instrument is broken — fix it
before reporting the axis. Never suppress the axis command's stderr, and check
its exit status; a zero produced alongside a non-zero exit is never an all-clear.

Two shapes cause this on this host specifically, both measured 2026-08-15:

- **zsh does not word-split unquoted variables.** `for r in $REPOS` over a
  newline-joined list runs **once**, with the entire blob as a single bogus repo
  name. Drive every multi-item loop from `while IFS= read -r r; do … done <
  file`. The commit-CI axis reported `0` failures this way while 33 existed.
- **`--jq` takes the jq program as its value.** Writing
  `gh run list --jq --arg r "$r" '…'` makes the program the literal string
  `--arg`. With stderr discarded the axis reported `0` stalled gates while 9
  existed. Pass `--arg` to a separate piped `jq`, never after `--jq`.

Both are silent, both look exactly like a clean queue, and neither is caught by
any downstream check in this skill — the report is simply short.

## Repository scope

Use `../_shared/repo-map.md` only to resolve local paths, writable remotes, and
fork-specific `--repo` flags. It is not the discovery allowlist. PR discovery is
involvement-based across the managed organizations; commit-CI also scans every
non-archived repository in the wholly owned organization. Dirty-tree and
worktree discovery are the only clone-local axes.

## Pull requests

Run all three searches:

```bash
DISCOVERY_DIR=$(mktemp -d "${TMPDIR:-/tmp}/pr-fix-discovery-XXXXXX")
ORGS=(--owner example-org --owner example-org \
  --owner example-apps-org --owner example-labs-org)

gh search prs --author @me --state open "${ORGS[@]}" --limit 200 \
  --json number,title,repository,author,isDraft,createdAt \
  > "$DISCOVERY_DIR/authored.json"
gh search prs --review-requested @me --state open "${ORGS[@]}" --limit 200 \
  --json number,title,repository,author,isDraft,createdAt \
  > "$DISCOVERY_DIR/review.json"
gh search prs --owner example-org --state open --limit 200 \
  --json number,title,repository,author,isDraft,createdAt \
  > "$DISCOVERY_DIR/owned-org.json"
```

Do not sweep every PR in the team organizations; author/reviewer involvement is
the scope boundary there. Combine the arrays and deduplicate on
`(repository.nameWithOwner, number)`, never the basename:

```bash
jq -s 'add' "$DISCOVERY_DIR/authored.json" "$DISCOVERY_DIR/review.json" \
  "$DISCOVERY_DIR/owned-org.json" \
  | python3 "$PR_FIX_DIR/scripts/pr_fix_state.py" dedupe \
  > "$DISCOVERY_DIR/candidates.json"
```

The helper rejects candidates without an owner-qualified repository identity;
silently falling back to `repository.name` can collapse two organizations.

### Real-time hydration and merge-queue state

Search results are lagging and omit classification fields. Hydrate PER
REPOSITORY, not per PR: `gh pr list --json` returns the same field shapes as
`gh pr view` for every open PR in one call (verified live 2026-08-22 —
`author.login`, `mergeStateStatus`, `statusCheckRollup`, `autoMergeRequest`
all match), so 63 candidates across 15 repos cost ~15 calls instead of 63.
Include `headRefOid` for later push leases and `reviewRequests` for the
review axis:

```bash
# one call per candidate repository; then join to the candidate numbers
gh pr list --repo "$repo" --state open --limit 300 \
  --json number,title,author,headRefName,headRefOid,state,mergeable,mergeStateStatus,isDraft,autoMergeRequest,statusCheckRollup,reviewDecision,reviewRequests,createdAt \
  > "$DISCOVERY_DIR/list_${repo_safe}.json"
jq --argjson nums "$candidate_numbers_json" --arg repo "$repo" \
  '[.[] | select(.number as $n | $nums | index($n)) | . + {repo: $repo}]' \
  "$DISCOVERY_DIR/list_${repo_safe}.json" > "$DISCOVERY_DIR/hyd_${repo_safe}.json"
```

The injected owner-qualified `repo` field is load-bearing: the batch
classifier refuses elements without it, and every later phase keys on it.

A candidate absent from its repo's open-PR list was merged or closed since
the search index snapshot — drop it (the same index-lag drop as
`state != OPEN`). Fall back to per-PR `gh pr view` only for a repo whose
open-PR count exceeds the list limit.

#### `UNKNOWN` mergeability is not a state — re-poll it

GitHub computes mergeability **lazily**. The first `gh pr view` of a PR whose
base moved only *enqueues* that computation and returns
`mergeable: "UNKNOWN"` with `mergeStateStatus: "UNKNOWN"`. `UNKNOWN` therefore
means "not yet computed", never "fine".

A single hydration pass silently under-reports conflicts, because `UNKNOWN`
matches no classifier branch and falls through to No action. Check for
`UNKNOWN` first — sleep only when at least one exists — then re-hydrate just
those candidates (per-PR `gh pr view` is fine for the stragglers):

```bash
unknown=$(jq -r '.[] | select(.mergeStateStatus == "UNKNOWN") | "\(.repo) \(.number)"' \
  "$DISCOVERY_DIR"/hyd_*.json 2>/dev/null)
if [ -n "$unknown" ]; then
  sleep 6
  # re-hydrate each listed (repo, number) with gh pr view, updating its record
fi
```

Measured 2026-08-08: 20 of 36 hydrated PRs returned `UNKNOWN`; one re-poll
resolved all 20 and reclassified **7** of them from No action to
`[PR-CONFLICT]`. If a candidate is still `UNKNOWN` after the re-poll, report it
as indeterminate — do not record it as clean.

Neither `gh pr list` nor `gh pr view --json` exposes merge-queue membership.
Query it in ONE aliased GraphQL call per repository, covering every candidate
number (verified live 2026-08-22):

```bash
owner=${repo%%/*}; name=${repo#*/}
aliases=$(printf 'pr%s: pullRequest(number:%s){number mergeQueueEntry{state}}\n' \
  $(jq -r '.[] | "\(.number) \(.number)"' "$DISCOVERY_DIR/hyd_${repo_safe}.json"))
if QUEUE_RESPONSE=$(gh api graphql -f query="query{repository(owner:\"$owner\",name:\"$name\"){$aliases}}")
then
  jq --argjson q "$QUEUE_RESPONSE" \
    '[.[] | . + {mergeQueueEntry: $q.data.repository["pr\(.number)"].mergeQueueEntry}]' \
    "$DISCOVERY_DIR/hyd_${repo_safe}.json" > "$DISCOVERY_DIR/hyd_${repo_safe}.tmp" \
    && mv "$DISCOVERY_DIR/hyd_${repo_safe}.tmp" "$DISCOVERY_DIR/hyd_${repo_safe}.json"
fi
# on GraphQL failure the records simply lack mergeQueueEntry — see below
```

An explicit JSON `null` means the PR is not queued. A GraphQL error means queue
state is unknown: retain the candidate but do not add `mergeQueueEntry`, and do
not classify CLEAN + unarmed as ready. This distinction prevents an API failure
from becoming a duplicate merge action.

### Do not hand-roll a rollup bucket test

Use the provided classifier. An ad-hoc probe written mid-run will not encode the
conclusion taxonomy, and the failure is silent: it reports PR states that look
actionable and are not. Measured 2026-08-25 — a one-line jq filter treating
anything outside `SUCCESS|NEUTRAL|SKIPPED` as a failure reported 7 to 14
"failing" checks on three Dependabot PRs whose real state was `CANCELLED`
(superseded runs) plus `null` (still running). Zero were failures, and the wrong
reading was published to the user before a re-probe corrected it. SKILL.md's
"empty, cancelled, skipped-only, pending... are never green" rule and
`classify_checks` both exist to prevent exactly this; writing a fresh probe
walked past both.

`CANCELLED` is neither a failure nor green. A `null` conclusion is in-progress.
Enumerate conclusions explicitly and treat only `FAILURE`, `TIMED_OUT`,
`STARTUP_FAILURE`, and `ACTION_REQUIRED` as failures.

### Deterministic classification

Use the deterministic classifier for the safety-sensitive ordering. Classify
the whole batch in ONE process — `classify-prs` emits identity-bound JSONL
(`{"bucket":…, "repo":…, "number":…}`), so no output is ever paired to its
PR by loop position (the single-PR `classify-pr` form remains for one-off
re-checks):

```bash
ACTOR=$(gh api user --jq .login)
jq -s 'add' "$DISCOVERY_DIR"/hyd_*.json \
  | python3 "$PR_FIX_DIR/scripts/pr_fix_state.py" classify-prs --actor "$ACTOR" \
  > "$DISCOVERY_DIR/classified.jsonl"
```

Buckets, in priority order:

| Condition | Bucket | Action |
|---|---|---|
| hydrated `state != OPEN` | drop | Search-index lag; no action |
| `mergeQueueEntry != null` | `[PR-QUEUED]` | Report queued; do not re-arm |
| any check conclusion is null | `[PR-PENDING]` | Re-poll once; then report pending |
| required failure, authored by the actor | `[PR-FAIL]` | Diagnose and repair |
| `mergeStateStatus == DIRTY`, authored by the actor | `[PR-CONFLICT]` | Rebase workflow |
| CLEAN + MERGEABLE + unarmed + explicitly unqueued, authored by actor or Dependabot | `[PR-READY]` | Queue using repository merge mode |
| another author requested the actor's review | `[PR-REVIEW]` | Summarize only |
| authored PR is review-blocked or changes-requested | `[PR-BLOCKED]` | Report only |
| verified non-required/cosmetic failure | `[PR-COSMETIC]` | Only after log evidence |

`UNSTABLE` means a non-required check is failing or pending; do not promote it
to `[PR-FAIL]`. Never infer cosmetic status from a job name alone. Drafts and
unclassified items go under No action.

Annotate every `[PR-FAIL]` and `[PR-CONFLICT]` row with its age. Before any
Phase 2 diagnosis or Phase 3-conflict rebase of an item older than ~3 days on
a high-velocity repo, run the supersession triage in
[`diagnose.md`](diagnose.md) §2a-pre first — measured 2026-08-22, it resolved
8 of 9 such items without a repair worktree.

## A check can report `pass` while annotating that it failed

PROMOTED here 2026-08-15 on recurrence. This was already `[confirmed]` in
`agent-memory/topics/github.md` as *"example-labs-org org-synced baseline Python
Test check is ADVISORY — green ≠ tests pass"* (2026-07-20), and again in
`memory/continue-on-error-masks-failure.md`. It recurred anyway, because a
topic file loads on worker dispatch while THIS decision is made in the main
thread mid-`/pr-fix`. The knowledge existed; the delivery did not. It lives in
the consuming skill now for that reason — do not "simplify" it back out.

`classify_checks` requires "affirmative pass evidence", and a masked check
SATISFIES that bar: its bucket really is `pass`. The failure lives in the
check's ANNOTATIONS, which the rollup does not carry. So the classifier is
correct and the input is a lie, and no amount of bucket logic detects it.

A workflow that captures its own exit code and re-exits 0 produces this —
`pytest -v; code=$?; … echo "::warning::Tests failed (exit code $code)"; exit 0`
is the exact shape. Before treating a green `Python Test`, `Validate`, or any
other suite-runner check as evidence that a suite passed, read its annotations:

```bash
head=$(gh pr view "$N" --repo "$repo" --json headRefOid --jq .headRefOid)
id=$(gh api "repos/$repo/commits/$head/check-runs?per_page=100" \
  --jq '.check_runs[] | select(.name|test("Test")) | .id' | head -1)
gh api "repos/$repo/check-runs/$id/annotations" --jq '[.[].message] | join(" | ")'
```

A `Tests failed` string there means the check is green and wrong. Report it as
`[PR-COSMETIC]`-adjacent only with that evidence; never silently upgrade it to
"tests pass".

Measured 2026-08-15: 4 of 19 example-labs-org repos on the shared `baseline-ci.yml`
were masking failures this way, every one a pytest exit 2 (collection error).
It is not a reporting nit — it corrupts decisions. `fxhoudinimcp#67` was merged
partly BECAUSE the green check was read as "no test signal", while that check
had been annotating `ModuleNotFoundError: mcp.server.fastmcp` on every run. The
broken gate did not merely hide a defect; it hid the evidence that would have
stopped the merge.

## Commit CI

Build the repository set from every non-archived repository in
`example-org` plus the local team-organization clones in the repo map.
For each repository, scan non-PR failures from the last seven days:

```bash
DEFAULT_BRANCH=$(gh repo view <org/repo> \
  --json defaultBranchRef --jq '.defaultBranchRef.name')
gh run list --repo <org/repo> --status failure --limit 20 \
  --created ">$(date -d '7 days ago' +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d)" \
  --json databaseId,headBranch,event,name,headSha,createdAt \
  | jq --arg default_branch "$DEFAULT_BRANCH" \
    '[.[]
      | select(.event | IN("pull_request", "pull_request_target", "dynamic") | not)
      | select(.event != "push" or .headBranch == $default_branch)]
    | group_by(.headSha)
    | map({sha:.[0].headSha,branch:.[0].headBranch,event:.[0].event,
           created:.[0].createdAt,failing:[.[].name],run_ids:[.[].databaseId]})
    | sort_by(.created) | reverse | .[0:5]'
```

The EVENT filter is deliberately wider than `!= "pull_request"`:
`pull_request_target` runs are PR-driven (trusted-compat checks on
Dependabot branches), `dynamic` runs are Dependabot alert auto-scans, and a
`push` failure on a feature branch is that branch's own in-progress work —
measured 2026-08-22, these three shapes were ~60% of raw candidates and none
was actionable commit CI. Schedule and `workflow_dispatch` events stay
unscoped by branch because release/canary dispatches legitimately target
non-default refs. Do not add a workflow-name exclusion. For every candidate, apply both checks in
[`stale-failure-filter.md`](stale-failure-filter.md): latest completed run of the
same workflow and commit supersession. Pending is not failure; `SUPERSEDED`
requires a source check rather than a silent drop.

## Stalled approval gates

For every commit-CI repository, also list `waiting` and `action_required` runs
on `main`. Report anything older than 30 minutes as `[GATE]` with its URL.

```bash
gh run list --repo <org/repo> --status waiting --limit 10 \
  --json databaseId,headBranch,workflowName,createdAt,headSha
gh run list --repo <org/repo> --status action_required --limit 10 \
  --json databaseId,headBranch,workflowName,createdAt,headSha
```

`[GATE]` is report-only. Never approve an environment gate from this skill.

## Branch hygiene

Use Step `3-br-a` in [`branch-cleanup.md`](branch-cleanup.md) as the single
candidate-selection algorithm. It resolves the repository's actual default
branch, excludes protected and open-PR branches, handles squash merges, and
emits an immutable `branch expected_sha` pair for each candidate. Keep its JSON
inputs and candidate output under the run state directory, never in the
repository checkout. Preserve each pair through display, branch-specific
confirmation, and the leased deletion. Flag accumulation when the repository
has more than five non-standing branches, but report total and deletable counts
separately.

## Dirty trees and worktrees

- Run [`dirty-tree-discovery.md`](dirty-tree-discovery.md) for each mapped local
  clone. Exclude transients, auto-ship only when every real file is a recognized
  prior-session artifact, and ask before in-progress or mixed work.
- The worktree axis reports COUNTS in Phase 1, never full listings. A repo
  can carry 100+ registered worktrees (mcp-infra measured ~180 on
  2026-08-22, mostly Codex-managed), so a porcelain dump blows the output
  budget while adding nothing to the selection decision:

  ```bash
  porcelain=$(git -C "$repo" worktree list --porcelain)
  total=$(printf '%s\n' "$porcelain" | grep -c '^worktree ')
  prunable=$(printf '%s\n' "$porcelain" | grep -c '^prunable' || true)
  ```

  Report `<repo>: N worktrees (M prunable)` and defer per-path listing and
  classification to Phase 3-wt after the user selects `worktrees`. In
  Phase 3-wt, `prunable` entries (gitdir already gone) can go through
  `git worktree prune --dry-run` first — pruning a dead registration
  removes no working tree. Worktrees under Codex-managed roots
  (`~/.Codex`, `~/.codex`, `~/Documents/Codex`) and `/tmp` belong to other
  tools' lifecycles: count them, but exclude them from removal candidates
  unless the user names them. Follow
  [`worktree-cleanup.md`](worktree-cleanup.md) for everything else.
  Worktree cleanup is never a global directory sweep and never treats a
  standalone clone as a worktree.

## Discovery output

Present one table with explicit labels: `[PR-FAIL]`, `[PR-QUEUED]`,
`[PR-READY]`, `[PR-CONFLICT]`, `[PR-COSMETIC]`, `[PR-REVIEW]`,
`[PR-BLOCKED]`, `[PR-PENDING]`, `[CI]`, `[CI-PENDING]`, `[GATE]`, `[BR]`,
`[DIRTY]`, and `[WT]`. Keep destructive targets separate and require their own
named confirmation at the phase that performs the operation.

After the report no longer needs its snapshots, remove only
`$DISCOVERY_DIR`. Never create discovery artifacts in a repository checkout.
