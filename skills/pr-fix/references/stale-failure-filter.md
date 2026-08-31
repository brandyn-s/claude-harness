# Stale-Failure Filter — the two checks, and why neither alone works

Read this when a `[CI]` candidate is a **`main`-branch** failure. Both checks run;
they cover disjoint blind spots.

## Critical gotchas

- **Do not report a `main` CI failure actionable on the strength of its log alone.**
  A log can be entirely genuine and still describe a problem fixed hours ago. Log
  correctness and log *currency* are separate questions.
- **Do not use a bare `headSha != main-HEAD` test.** On a fast-moving repo a
  12-minute-old, genuinely-current failure already has a superseded sha. That rule
  produces false all-clears, which are worse than the stale reports it prevents.
- **Do not trust workflow-recency alone.** It is blind when *no newer run of that
  workflow has completed* — the normal state on a repo where rapid pushes cancel
  in-flight CI.

## Check 1 — workflow recency

Did a newer **completed** run of the same workflow succeed?

```bash
gh run list --repo <org/repo> --branch main --workflow "<workflow_name>" --limit 3 \
  --json name,conclusion,status,createdAt,headSha
```

Only compare runs returned for the failing workflow; success from an unrelated
workflow is not recovery evidence. `success` on a newer completed run →
**DROP**. A `null`/absent conclusion is
`in_progress`/`queued` → pending, re-poll; never a failure.

Blind spot: if every later run is `cancelled` / `pending` / `waiting`, the newest
*completed* run stays the old failure forever.

## Stalled approval gates

That blind spot has a second, worse face: a run parked in `waiting` is invisible to **both** discovery axes, so it is not merely mis-aged — it is never reported at all.

- the failure scan filters `--status failure`; `waiting` is not a failure
- this filter reads the latest **completed** run; `waiting` is not completed

So a deploy held at an environment approval gate produces no signal in either place, and on a merge-triggers-apply repo that means `main` is merged-but-undeployed with nothing saying so. This is the `git-hygiene` "a MERGED PR is not a DEPLOYED change" invariant, reached from the discovery side.

**Measured 2026-08-01 (mcp-infra):** Terraform run `30695266494` (sha `f204529`) sat `status=waiting` for **7+ hours** with `tflint`, `protected-plan` and `lambda-tests` all `success` and only the `apply` job held on the `production` gate — with a second run queued behind it. Neither axis surfaced it; a human reading the run list did. Two more gates fired the same day, so this is a recurring steady-state condition, not a one-off.

SKILL.md's **Stalled Approval-Gate Discovery** is the query that acts on this. It is REPORT-ONLY (`[GATE]`): the skill never approves a deployment gate — see `security-confirmations.md`, whose `self_approved_production_environment_gate_on_a_generic_proceed` failure mode is precisely the shape an automated cleanup pass would walk into.

## Check 2 — commit supersession

How far has `main` advanced past the failing run's head commit?

```bash
python3 $HOME/.claude/bin/ci-failure-superseded.py --repo <org/repo> --run-id <id>
```

| `ahead_by` | Newer completed run? | Verdict |
|---|---|---|
| `0` | — | **CURRENT** — the run's sha *is* main HEAD |
| `1-2` | no | **CURRENT** — normal churn |
| `≥3` | no | **SUPERSEDED** — read the source before reporting |
| any | `success` | **DROP_SUCCEEDED** |

`SUPERSEDED` is **not** "drop it silently" — it means *go read the source at current
`main`* and grep for the specific fix (the IAM action, the guarded call, the changed
default). If present, the failure is closed history: report it as closed, never as a
live gap. If absent, it is still actionable.

The helper's `classify()` is pure and unit-tested
(`hooks/test-hooks/test_ci_failure_superseded.py`, 12 cases, mutation-verified
5/5) — including a boundary test at the threshold and the false-drop control below.

## Measured evidence (2026-07-28)

Three live cases, which together fix the threshold and rule out the naive rule:

| Repo / workflow | `ahead_by` | Newer run | Verdict | Ground truth |
|---|---|---|---|---|
| mcp-infra `Terraform` | 20 | none completed (all cancelled) | SUPERSEDED | the `s3:PutInventoryConfiguration` grant it failed on was **already in `ci.tf:715`** |
| code-search `Unit Tests` | 3 | `success` ×2 | DROP_SUCCEEDED | fixed by #261 **8 minutes** after the failure |
| mcp-servers `Dependency Update` | 1 | none | **CURRENT** | a genuine 12-minute-old failure — a bare sha test would have dropped it |

Cost of skipping check 2: both superseded items were diagnosed from real logs and
reported as actionable work. `--limit 3` passed mcp-infra through because it had
**zero** completed `Terraform` runs since the failure.

## Relation to other rules

This is `grading-discipline`'s window-total rule applied to CI: a state drawn from a
lookback window cannot distinguish an ongoing fault from a closed cluster, and the
closed cluster is common (a deploy day, a since-fixed bug). It is also
`check-before-change` STEP_1 — verify current state before acting on a stale read.

## The retired `mirror` exclusion

Phase 1's commit-CI query carried a hardcoded `select(.name | test("^mirror$";"i") | not)`
from **2026-07-29 to 2026-08-02**. It is gone. Do not re-add it.

**Why it existed.** `mirror` was failing on every push and flooding discovery: on 2026-07-29,
~10 of ~40 raw failing runs across 6 repos were `Mirror` while only **2** were live failures.

**Why it was always provisional.** `mirror` was *broken*, not *retired*. What retired
2026-06-12 was the org-wide `enforce-mirror.yml` controller; the per-repo `mirror.yml`
workflows remain (`_shared/repo-map.md` says exactly this). The original entry therefore
shipped with an explicit removal condition rather than as a standing rule.

**Why it was removed.** claude-config **#1774** (merged 2026-07-29) credentialed the tag fetch
that had broken mirroring since 07-27. Measured 2026-08-02, the latest `Mirror` run was
`success` in **6 of 6** repos sampled — mcp-servers, mcp-infra, claude-config, code-search,
code-graph, claude-knowledge-base.

**Why removal is strictly better than keeping it.** The two stale-failure checks above already
suppress a fixed workflow's old failures — the latest completed run succeeds, so the failure
is dropped automatically. A name-exclusion adds nothing on top of that, and it *subtracts*
something important: it cannot distinguish "noisy" from "newly broken", so a genuine future
`mirror` regression would be silently invisible. Noise-suppression past its condition is
blindness.

**Generalisation.** An unconditional workflow-name exclusion is defensible only for a
**permanently** dead workflow — verify with `gh api repos/<r>/actions/workflows` (file deleted,
or `state: disabled_manually`). Anything broken-but-fixable gets a removal condition and a
date, the same discipline `check-before-change.md` requires of a version pin. Prefer the stale
filter over a name match whenever the workflow could plausibly be fixed.
