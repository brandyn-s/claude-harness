---
paths:
  - "**/rules/grading-discipline.md"
  - "**/rules/incidents/grading-discipline.md"
---

# grading-discipline: Incident Narratives

Extracted from `rules/grading-discipline.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## 2026-05-10-incident-graded-code-graph-against-an

```
WHY: 2026-05-10 incident — graded code-graph against an "accuracy
     gap inventory" doc that was authored hours before a "posture
     snapshot" superseded it. Both files dated 2026-05-10; the gap
     inventory's HTTP_CALLS precision (17.6%) and IMPLEMENTS recall
     (27.3%) were obsolete by ~6 hours when I cited them. One
     memory_search query would have surfaced the posture snapshot
     in the top-3 results. The cost of the memory_search is one
     tool call; the cost of skipping it is publishing an 80%-stale
     grade.
```

## a-grade-table-without-per-row-mtime-is-indistinguishable

```
WHY: a grade table without per-row mtime is indistinguishable from
     a grade table whose rows came from different time points.
     Currency stamps make staleness visible at-a-glance instead of
     buried in a closing footnote. Same logic as
     verify-instrument-before-fix.md "baselines decay between
     authoring and execution."
```

## without-explicit-a-if-f1-0-95-b-if

```
WHY: without explicit "A− if F1 >= 0.95, B+ if 0.85-0.95, D if <0.5"
     thresholds, the grader picks the most pessimistic anchor by
     default. 2026-05-10 incident: Flask adversarial F1=0.49 was
     allowed to drive "Python D+" while mcp-servers production F1=
     0.989 sat in the same file unweighted. With pre-registered
     thresholds + production-vs-adversarial axis split, the grade
     would have been "Python A on production, D on adversarial
     stress-test."
```

## a-single-letter-grade-collapses-4-meaningful-axes-absolute

```
WHY: a single-letter grade collapses 4+ meaningful axes (absolute
     accuracy, worst-case floor, trajectory, architectural ceiling)
     into one number. When the user disagrees with the letter, the
     disagreement is unresolvable without re-deriving the axes.
     Output the axis table first; let the user pick which axis to
     collapse on.
```

## 2026-07-28-govslack-user-deprovision-reported-35-of

```
WHY: 2026-07-28 govslack-user-deprovision — reported "35 of 59 failed,
unexplained, not yet root-caused" from a 15-day window total. ALL 35
fell inside a single 19-hour build window ending 2026-07-14, 28 of them
under one since-DISABLED 30-min schedule, followed by 14 consecutive
daily successes. The runbook was healthy; the aggregate made closed
history look like an open incident. Same session, same shape: the
retention window itself (15d) was the floor, so "never succeeded in
window" was reported without noting it was not a proven start date.
```

## 2026-08-01-atlassian-token-inventory-the-org-count

```
WHY: 2026-08-01 Atlassian token inventory — the org count moved 17 -> 18 while a
previously-unrenderable token simultaneously became visible, and I reported it as
"created during this session — the control caught it," a tidy narrative that fit. Its
`createdAt` was 2025-08-05, ~11 months earlier; the +1 was never explained at all.
Sibling of the prefix GUARD below: there the partial view is a contiguous slice, here
it is a renderer silently dropping records from an otherwise complete-looking list.
```

## 2026-07-29-hologram-fleet-census-the-same-error

```
WHY: 2026-07-29 Hologram fleet census — the SAME error twice in one session, both
times producing a confident wrong population claim. (1) A paginated pull capped at 20
pages landed entirely inside one homogeneous TEST-ACTIVATE batch and reported
"uniform fleet-wide sg.hologram" as a finding; the SIM under investigation was absent
from all 2000 rows, which was the unheeded tell. (2) `sg_live[:12]` was one contiguous
KTAC provisioning batch showing 10 of 12 with only zero-byte sessions — nearly
reported to the user as a 399-SIM outage. A stratified resample (every 16th, id span
4905598-6806304, 23 distinct name groups) found 0 of 24 with that symptom: 13 had
passed data, and 11 had NO session records at all because they were undeployed spares
(`ExampleTarget spare1`, `shepherd-buoy`, `GPS Tracker`).
```

## 2026-07-31-gold-table-principal-backfill-aws-lambda

```
WHY: 2026-07-31 gold-table `principal` backfill — `aws lambda invoke` (default 60s CLI
read timeout) reported "Read timeout" on most chunks of a 2-month backfill while the
Lambda ran on server-side. I checked S3 object mtimes for the timed-out JUNE chunks,
found fresh objects, and concluded all timed-out chunks had landed. The JULY chunks had
NOT: days 07-05..07-17 sat at principal=0. Caught only by a per-DAY
`count_if(principal IS NOT NULL)` query, which is also the check that would have
replaced the whole sampling exercise. Then the failure mode CHANGED under re-run (S3
SlowDown on DeleteObjects, not timeouts), so the first diagnosis had also expired —
a second reason to re-measure rather than extrapolate.
```

## 2026-07-28-mcp-infra-737-739-sibling-mcp

```
WHY: 2026-07-28 mcp-infra #737 → #739 (+ sibling mcp-servers #891) — a shipped
detector alarmed on "a (principal, server) pair never seen in the retained
history." Measured AFTER merge: non-empty on 19 of 20 days (median ~40, peak 206).
With `ChannelFindings > 0` it enters ALARM on day one and never leaves, muting the
ONE shape with a real zero baseline (bypassPermissions escalation on an MDM-managed
host: 0 of 13,651 managed transitions in 60d). It passed its own review because the
detector's stated contract — "only discrete state changes alarm" — was checked
against the predicate's WORDING, never against its rate; the same morning a sibling
detector was RETIRED for a 7.6x swing. Only the production deploy gate (declined
self-approval) kept it from deploying, making it a fix-forward not a rollback.
```

## 2026-07-28-my-own-differential-review-of-737

```
WHY: 2026-07-28 — my own differential review of #737 named "materialise the
baseline" as the MEDIUM's real fix and explicitly warned off the cheap
date-window fix (measured 0.45%). Materialising would have made a
permanently-firing alarm ~500x cheaper while leaving it permanently firing. The
cost finding was correct and the recommendation was aimed at the wrong defect.
```

## 2026-05-10-code-graph-grade-cited-accuracy-gap

```
INCIDENT 2026-05-10 code-graph grade: cited accuracy-gap-inventory.md
(a leverage doc) for "HTTP_CALLS precision 17.6%, D−" when
accuracy-posture-snapshot.md (the state doc, same date, written
hours later) reported "113 edges, ~0% misresolution" after PRs
#280+#281 shipped between the two docs. Net: D− grade was 80%
stale within hours of being written.
```

## 2026-07-31-purview-audit-retention-measured-0-aad

```
WHY: 2026-07-31 Purview audit retention — measured "0 AAD records past ~366 days" with
-ErrorAction SilentlyContinue and shipped "366d is the limit / 01-01-2025 is definitively
unreachable / no extended-retention policy exists." All three were REFUTED by one doc read:
1 year is Audit (Premium)'s DEFAULT policy, Purview supports 10 YEARS, and a custom policy
(RET001-AllUsers, Priority 2) had existed all along at 1 Year. The measurement survived an
adversarial re-run (zeros were clean); only the inference was wrong. 366 ~= the documented
1-year default was the tell, ignored. Five turns of probing preceded any doc read; the user
supplied the correction three times. Sibling of measure_distributions_before_setting_
thresholds in verify-effectiveness.md — that one governs setting a threshold, this one
governs REPORTING an observed one as a boundary.
```

## 2026-07-30-detection-accuracy-grade-graded-c

```
WHY: 2026-07-30 detection-accuracy grade — graded it C ("UNCHARTED;
only oracle-relative 0.87 exists") and made "build an engine-independent candidate
pool" the #1 recommendation. `bench/recall-census/` already existed, tested and
documented, its README opening by naming the exact three confounds I cited, ONE
command from the number — unrun for 26 days. memory_search returned topic files;
`git ls-tree | grep -iE 'oracle|recall'` found it instantly. Running it produced
combined system recall 0.779 -> 0.810: the axis graded C was measurable that
afternoon.
Distinct from scope-discipline's existing_tooling_is_always_the_first_option (governs
BUILDING) and compare-by-need STEP_1 (governs ADOPTING). This governs GRADING, where
the cost is a wrong recommendation rather than wasted construction.
RECURRED 2026-07-31, ONE DAY LATER, which is why the trigger above was broadened from
"grade a capability absent" to include ANY remediation proposal. Diagnosed three
firing detector alarms as a no-tolerance-band defect and proposed a 4-item fix list
("give the judge a tolerance band", "split didn't-run from ran-degraded", "fix the
description"). All three ALREADY EXISTED in the daily detector module — `COV_MIN_FRAC,
COV_MIN_ABS = 0.01, 20`, `judge_loss_is_material()`, and a
`DETECTOR_BEACON_MINOR_LOSS` token deliberately chosen not to collide with the metric
filters — merged as #900 and DEPLOYED. Worse, the code comment narrated the exact
2026-07-28 incident I had just re-derived from scratch. The alarms were still lit only
because the fix merged 02:38 and the run fired 03:00, 22 min before the image was
pushed at 20:11.
```

## the-trigger-missed-the-framing-was-what-should-we

```
WHY THE TRIGGER MISSED: the framing was "what should we fix?", not "grade this
absent" — so a guard keyed on the word ABSENT read as inapplicable while the identical
error was in flight. A proposal to BUILD is a claim that the thing does not exist,
whatever verb introduces it. One `grep -n "tolerance\|material" <detector>.py` would
have collapsed the entire 4-item list.
```

## 2026-07-31-azure-automations-cui-entra-sync-daily

```
WHY: 2026-07-31 azure-automations `cui-entra-sync-daily` — group removals were hard-blocked
on `unmatched > 0`, which conflated a Graph 404 (PERMANENT: 15 of 1,893 CSOD users have no
Entra identity, 11 of them Cornerstone vendor built-ins dating to 2018) with a transient
read failure. ONE deleted employee held the interlock open, so flipping
REMOVE_STALE_MEMBERS=true would have removed nobody while the variable read as enabled —
and `reconciliation_status=FAILED` on every otherwise-clean run muted the job status too.
Fixed by splitting `absent` from `unresolvable` (PRs #47/#48, mutation-verified 4/4).
INVERSE of destructive-automation-safety's shape (a counter incremented but never reaching
the exit code); here it reaches a gate whose floor was never measured.
```

## 2026-08-01-gateway-assessment-144-personal-api-keys

```
WHY: 2026-08-01 gateway assessment — "144 personal API keys" was carried from stale
memory, never measured, and repeated across ~8 turns, four comparison tables, and BOTH
formats of a shipped report as the load-bearing security argument ("the gateway
eliminates all 144 personal API keys"). The only api_keys call that session was
`get("/v1/organizations/api_keys", {"limit": 3})` — written under a comment reading
"What does an api_key object actually expose? (is there a limit field?)", i.e. a SHAPE
probe. It answered the field question correctly and was never a count.

The real inventory, measured only when a later user turn ("replace the unmanageable
Claude Code keys") forced a census: **1,143 keys, 320 active** — 250 active
CLI-generated `claude_code_key_<user>_<4char>` (the actual migration set, held by 161
humans, 54 of them holding more than one and one holding 11) plus 70 active
service/integration keys. So the figure was wrong by ~8x on the total and ~1.7x on the
number that mattered, and it under-stated the credential sprawl the recommendation
rested on.

Two aggravating details worth keeping:
- The census CHANGED THE ARCHITECTURE, not just a number. The 250/70 split fell exactly
  on the lane boundary the user had proposed (all 250 CLI keys in the `Claude Code`
  workspace = 92.2% of spend; all 70 service keys in the default workspace = 6.9%), so
  the measurement supplied the strongest evidence for the plan — evidence that sat
  unmeasured for the entire preceding arc.
- Nothing in the session challenged it. Each restatement inherited authority from the
  last, and the number appeared beside genuinely measured figures ($465,016.75 from
  `cost_report`, 92.2% share) which lent it their credibility.

Distinct from the partial-enumerator and prefix-sample GUARDs: both of those describe a
census that was ATTEMPTED and fell short. This one describes a census that was never
attempted, where a shape-inspection call's presence in the transcript made a remembered
number look measured.
```
