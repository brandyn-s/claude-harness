# Root-cause analysis — why 38% of fix-batch dispatches hit stale findings

In the May 2026 fix campaign (8 batches A–H dispatched against
``AUDIT-TRACKERS/05-phase2-findings.md``), **13 of 34 attempted
fixes (38%) turned out to be on findings that had already been
resolved by other work**. The fix-agents diagnosed correctly, opened
the right file, and found nothing to fix.

This document names the six root causes and the mitigation each
maps to. The mitigations are implemented as of commit (this commit);
the empirical 38% number is the calibration baseline. If a future
campaign exceeds it, one of the mitigations has regressed.

## The six root causes

### 1. Static-tracker, live-tree mismatch

`AUDIT-TRACKERS/05-phase2-findings.md` was written ONCE, as a
snapshot of what the 89-agent Phase 2 audit found at that moment.
Between that moment and the first fix-batch dispatch, dozens of
unrelated commits landed. Some resolved the very findings the
tracker still listed. The tracker had no way to know.

**Mitigation**: `oracle.act_on()` (CLI: `audit-skill-oracle.py act-on`)
is the mandatory pre-action gate. Every fix-batch dispatch must run
it first, treating the tracker as input and a filtered
"worklist.yaml" as output. The tracker is preserved as historical
record; the worklist is the live state.

### 2. Parallel-batch overlap

Batches A, B, C, D were dispatched simultaneously (parallel Agent
invocations). Each fix-agent edited files. There was overlap:
`skills/_shared/repo-map.md`, `audit-context.md`, manifest YAML
formats, and several SKILL.md files were touched by more than one
batch. The first batch to land would resolve a finding that later
batches were still queued to fix.

Concretely, the `security-alerts` finding "`_shared/repo-map.md`
missing" was stale by the time batch H ran because batch B (running
in parallel) had created the file as part of an unrelated fix.

**Mitigation**: same as #1 — `act_on` re-checks against the live
tree at dispatch time, so prior parallel work shows up as STALE
verdicts. The mitigation is the same gate; the failure mode is
distinct.

### 3. Oracle was downstream of dispatch, not upstream

The Phase 3 oracle gate I added in commit f97e0f7 sat between
Phase 2 (finding discovery) and the SKILL.md output report. But the
fix-orchestrator workflow has its own implicit downstream step —
"agents act on the report" — that the gate didn't cover. The
oracle's reverify ran once at discovery time, but every later
batch dispatched against the same stale list.

**Mitigation**: SKILL.md now adds **Phase 3.5: Pre-action gate**.
The gate runs before every fix-batch dispatch, not just once at
discovery. Tests pin the "must run act_on" requirement
(`tests/test_audit_skill_helpers.py::test_skill_md_enforces_all_phases_as_mandatory`).

### 4. Long-running session accumulates state churn

This session ran for many hours and dozens of turns. The original
Phase 2 audit ran against the tree at one specific snapshot. By
the time the last fix-batch dispatched, the tree had moved
substantially: marketplace rebuilds, ~10 commits of unrelated
fixes, several rename-operations.

**Mitigation**: structural — `act_on` queries the *current* tree,
not the tree-at-discovery. The latency between discovery and
action is permitted to be arbitrary as long as the gate runs.

### 5. False positives from Phase 2 itself

A subset of "stale" findings were false positives in the original
Phase 2 audit — the agent asserted a bug that wasn't real (LLM
hallucination, mis-identified pattern, mis-read context). Reverify
correctly returns STALE on those, but they consumed audit budget
upstream.

**Mitigation** (two layers):
- Layer A's calibration set (`tests/golden-findings/calibration/`)
  measures TNR; the documented floor is 0.80. The current
  calibration shows TNR=1.0 on N=30, meaning the oracle won't
  re-promote a known-stale finding.
- Layer B (`oracle.ensemble`) reduces single-agent hallucinations
  via N-agent agreement. Documented as Tier 3 (NOT decorrelated
  from the proposer) per SPEC.md §"Layer B" — the gain is modest
  but real for high-stakes findings.

### 6. Findings stored as prose, not predicates

The original Phase 2 agents emitted prose findings. Many had a
"Reproducer:" sentence, but most didn't include a machine-checkable
predicate. Without a predicate, the oracle can't reverify — those
findings flow through as `type: manual` and bypass the staleness
check.

**Mitigation**:
- Going forward, Phase 2 agents emit YAML with structured Reproducer
  (SKILL.md §"Phase 2: Agent checks" — Reproducer schema). Manual
  findings are tagged as such, not silently bypassed.
- The back-catalog converter (`oracle.tracker.parse_tracker` /
  `bin/audit-skill-oracle.py convert-tracker`) does best-effort
  predicate inference from the prose. For findings whose prose
  doesn't yield a deterministic check, the converter emits
  `type: manual` so the caller knows the oracle has not made a
  verdict — a more honest failure than silently classifying as
  STILL-FIRES.

## How to read this number going forward

The 38% stale rate is the **uncontrolled baseline** — what happens
when the pre-action gate is NOT used. After enabling `act_on`:

- Stale findings drop OUT of the worklist before dispatch. The
  fix-batch never sees them, never wastes budget on them.
- The stale-rate metric in `format_act_on_summary()` becomes a
  *diagnostic*: high stale-rate means the upstream Phase 2 audit
  was run too long ago, or parallel work resolved findings
  out-of-band — either way, the gate caught it.

If the stale rate ever drops to 0 across a campaign, the gate has
become unnecessary (the upstream tracker is being refreshed often
enough that everything fires). That's the optimal end-state.

## Calibration regression set

`tests/golden-findings/calibration/findings.yaml` pins 30 labeled
findings (15 known-true, 15 known-false). Layer A must classify
true findings as STILL-FIRES (TPR ≥ 0.95) and known-false as STALE
(TNR ≥ 0.80) — the documented floors. Current measured: TPR=1.0,
TNR=1.0.

The 13 specific stale findings observed in this campaign are
captured per-skill in commit messages and in the
`AUDIT-TRACKERS/05-phase2-findings.md` notes — they're available
for future regression-set expansion if a new audit-skill version
risks regressing on them.

## Root-fix status (May 2026 campaign close)

| Cause | Mitigation | Root fix | Module / file |
|---|---|---|---|
| 1. Static tracker | act_on | `oracle/discover.py` — one-shot Phase 1 + Layer A reverify; no static tracker | `oracle.discover` |
| 2. Parallel batch overlap | act_on catches side effects | `oracle/claim.py` — per-skill claim locks | `oracle.claim` |
| 3. Skippable gate | Phase 3.5 in SKILL.md | `oracle/validate.py` REJECT_NOT_REVERIFIED + REJECT_PROSE_INPUT | `oracle.validate` |
| 4. State churn | act_on returns fresh verdict | `oracle/validate.py` REJECT_STALE_RECORD (30-min TTL) | `oracle.validate` |
| 5. Phase 2 false positives | Layer B ensemble (modest) | `oracle/templates/phase2-prompt.md` — agents MUST run Reproducer before emitting; orchestrator rejects findings without `verified_at` + `observed_evidence` | `oracle/templates/` |
| 6. Prose findings | best-effort converter | `oracle/validate.py` REJECT_NO_REPRODUCER (manual findings can't enter dispatch path) | `oracle.validate` |

All 6 root causes now have a structural fix in addition to the
runtime mitigation. The campaign's 38% stale-rate is the empirical
calibration baseline — future campaigns measure against it.

Tests pinning the gates:
- `tests/test_oracle_validate.py` — 6 tests (REJECT_PROSE_INPUT,
  REJECT_NO_REPRODUCER, REJECT_NOT_REVERIFIED, REJECT_STALE_RECORD,
  fresh-record accept, format_rejections shape).
- `tests/test_oracle_discover.py` — 7 tests (Reproducer inference
  per Phase 1 code, manual fallback, end-to-end against real tree).
- `tests/test_oracle_act_on.py` — 5 tests (already landed).
- `tests/test_oracle_calibration.py` — 4 tests (TPR=TNR=1.0 on
  N=30 labeled set; trace contract; SPEC sections present;
  Layer B honest framing).
- `tests/test_oracle_fix_loop.py` — 4 tests.
- `tests/test_oracle_corpus.py` — 3 tests.

Total: 87 tests across the oracle + skill suite.

## What this analysis is NOT claiming

- It is not claiming Phase 2 itself is broken. The 89-agent audit
  found 206 real findings; 38% being stale by dispatch time is
  not the same as 38% being wrong-at-discovery-time.
- It is not claiming agents are unreliable. The fix-agents A–H all
  reached correct verdicts (including correctly identifying stale
  findings as not needing action) — but they did so AFTER
  consuming dispatch budget. The cost lives in the dispatch, not
  the agent.
- It is not claiming the oracle is now complete. SPEC.md §"Out of
  scope" enumerates real limitations. The act_on gate addresses
  ONE specific failure mode (stale findings) — not all the
  others.
