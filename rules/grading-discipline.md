@rule grading_discipline
@version 2026-08-06
@scope every system grade, accuracy assessment, measured "is X working" verdict, letter-grade output, population/count claim, threshold, cap, or remediation claim inside an assessment
@reference docs/rule-reference/grading-discipline.md

# GRADING DISCIPLINE — DECISION CONTRACT

Grades are evidence summaries over explicit axes, not intuition compressed into a
letter. Full measurement guards, examples, and incident evidence remain available
on demand at `docs/rule-reference/grading-discipline.md`.

## Triggers

- A letter grade, readiness/accuracy verdict, system ranking, or recommendation based
  on measured state.
- Any population count, sample-to-population claim, threshold/cap/tier, limit/ceiling,
  firing-rate claim, or destructive gate presented as evidence.

## Core invariants

INVARIANT memory_search_runs_before_any_grade
INVARIANT every_cited_number_stamps_its_source_mtime
INVARIANT rubric_thresholds_are_pre_registered_not_inferred
INVARIANT axis_table_precedes_aggregate_letter

## Required checks

1. **Recover current evidence.** Run memory search for the system, then order candidate
   posture/baseline/report artifacts by mtime. Prefer the newest authoritative current-
   state source; reconcile same-day measurements. Gap/leverage/to-fix docs describe what
   is open, not what the system currently does.
2. **Declare the rubric before grading.** State thresholds per axis before inspecting
   those numbers. If evidence was already seen earlier in the session, disclose that the
   thresholds are post-exposure and name the exposed axes; hold them fixed thereafter.
3. **Emit the axis table first.** Include meaningful axes such as production accuracy,
   adversarial floor, trajectory, ceiling, and operational readiness. Each row includes
   metric, value, source file, source mtime, freshness band, and axis grade. Production
   and adversarial fixtures stay separate. Any aggregate letter follows the table and
   names its collapse rule.
4. **Currency-stamp every number.** Use `[FRESH ≤1d]`, `[STALE 1-7d]`, `[OLD >7d]`,
   or `[UNKNOWN]`; compare baseline time to the producing binary when applicable. Warn
   that stale/old evidence may not represent today.
5. **Prove count provenance and completion.** Label counts measured-exhaustively,
   measured-capped, inherited, or vendor-stated. Page until the API's exhaustion
   condition, verify a loop reached its terminal sentinel/input count, and report cap,
   denominator, omitted rows, and malformed/error output. A shape probe, display limit,
   killed loop, or partial renderer is not a census. For a PROSPECTIVE change-impact or
   blast-radius count, the affected set is `rule-match INTERSECT existing-gate-pass`, not
   rule-match alone: a new automation rule can only act on subjects that already satisfy
   the system's other preconditions. Measured 2026-08-18 — estimating a department-routing
   change from department SIZE gave "+240 users"; intersecting with who had actually passed
   the training gate gave +140, a 1.7x overstatement published before the correction.
6. **Use controls that can falsify the probe.** For filtered counts, run an impossible-
   value control or a projection/interface that fails loudly on invalid fields. For
   structured records, read field values—key presence can encode `NOT RUN`. For a limit
   claim, distinguish configurable default, policy, license gate, and hard ceiling using
   vendor evidence; do not suppress the probe's errors.
7. **Sample honestly.** A list prefix/first page is one correlated batch, not a sample.
   Stratify across the population, report span and distinct groups, identify a benign
   condition that could produce the observation, and confirm the target is present. For
   ambiguous write completion, verify every ambiguous operation and the property that
   matters, preferably with a grouped hole-detecting query.
8. **Measure time and rates.** A lookback total requires first/last occurrence and what
   happened since; separate closed history from an active problem. Before alarming on a
   boolean or threshold, plot its retained firing distribution. A predicate firing on
   more than roughly 10% of days belongs in reporting or a separate metric, not the same
   page signal.
9. **Derive thresholds and conversions.** Report P50/P90/P95/P99 and blast radius for a
   threshold/cap; round numbers and right-skew means are not calibration. When unit A is
   intended to bound unit B, measure every conversion hop on the real format/input mix
   and use the worst-case ratio. If the chain is unboundable, call the cap usability—not
   safety.
10. **Re-measure the chosen value.** Do not interpolate an untested final number. The
    chosen value must appear in the evidence run. For quantitative deliverables, run
    `python3 bin/number-provenance-check.py <deliverable> --evidence <artifacts> --strict`.
11. **Verify gaps before proposing work.** Before grading a capability absent or listing
    "build X", grep current repo history/tree, tests, scripts, tools, and live state. An
    existing-but-unrun tool is an execution/evidence gap, not a build gap.
12. **Validate destructive gates.** Measure the gate signal's steady-state floor and its
    own pass rate. A nonzero permanent population must be split from the transient one;
    otherwise the interlock is permanently engaged and silently disables the action.

## Forbidden shortcuts

- A single letter before the axis table, implicit thresholds, or hiding which axis the
  aggregate collapses on.
- Treating the newest-looking doc, a gap inventory, or a stale baseline as current state
  without memory search, mtime, and freshness evidence.
- Reporting `N` from `--limit`, `head`, a first page, shape probe, timed-out loop, or
  incomplete renderer as a population count.
- Inferring field/capability existence from a filtered count without a negative control,
  or process execution from a structured key without reading its value.
- Generalizing a correlated prefix sample, or spot-checking only some ambiguous writes.
- Calling a lookback-window cluster active without its time distribution; wiring an
  unmeasured predicate to an alarm/page.
- Choosing a round threshold, interpolated number, or cross-unit cap without distribution,
  blast-radius, and full conversion evidence.
- Calling a measured default a platform ceiling, or suppressing errors on the probe whose
  zero becomes the finding.
- Letting adversarial worst-case results drive the production grade or omitting trajectory
  when the question includes "now", "still", "yet", or "since".
- Proposing missing work without searching for an existing implementation.

Casual opinions, specific-test debugging, and a factual metric lookup need not produce a
letter-grade protocol, but factual numbers still require source and timestamp. Load the
archived reference for specialized measurement cases rather than adding narrative here.

## A heartbeat alarm fails in the SAME direction as the thing it watches

An alarm built as "require a healthy heartbeat, treat missing data as breaching" cannot
distinguish BROKEN from NEVER RAN, because the emitter dying is what removes the datapoint.
Measured 2026-08-25: `Status=current` / `Maximum` / `treat_missing_data=breaching` latched
ALARM the moment its Lambda began crashing and stayed latched for five days with a
`StateReason` frozen at the first breach — so the alarm's own timestamp read as a FRESH
incident every evaluation and misattributed a 5-day-old failure to an apply that ran that
minute. Its sibling was a 1-period alarm on a metric firing 1 datapoint in 3, which flapped
every 15 minutes for the same reason.

REQUIRED: alarm on an explicit FAILURE datapoint with `treat_missing_data=notBreaching`,
and add a SEPARATE long-period dead-man alarm for total silence. Never read a latched
alarm's `StateReason` as evidence about now — plot the metric's datapoint history instead.
When adding a dead-man alarm, measure the emitter's real rate first: a detector observed at
4 invocations/hour against an `Invocations < 1 over 2×1h` threshold has 4x headroom and will
not catch a degradation from 4/hr to 1/hr, only a total stop.
