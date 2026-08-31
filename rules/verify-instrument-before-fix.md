@rule verify_instrument_before_fix
@version 2026-05-02
@scope every contingency-table cell, every "dominant failure" finding, every metric-plateau diagnosis where a failure cell has been identified

# Full rationale, examples, and incident history: `docs/rule-reference/verify-instrument-before-fix.md`.

INVARIANT verify_failure_cell_edges_before_designing_a_fix
INVARIANT three_to_five_sample_edges_is_the_minimum
INVARIANT source_inspection_means_reading_the_actual_source

# Dominant-cell gate
WHEN one contingency-table combination holds >=30% of failure mass:
STEP_1 randomly sample 3-5 edges from the cell.
STEP_2 open the cited source for every sample. Verify expected behavior, whether
       the failure exists without harness transformation, and whether the instrument
       sees the same information as a source reader.
STEP_3 classify each sample REAL, INSTRUMENT, or UNCLEAR.
STEP_4 if >=3 of 5 are INSTRUMENT, STOP: fix the harness and re-run.
STEP_5 if >=3 of 5 are REAL, design the system fix.
STEP_6 if mixed, expand and split the cell into distinct modes.

# Comparable measurement gate
Before claiming "fix shipped +Xpp," prove baseline and treatment used the same
instrument version, resolver/oracle rules, sampling defaults, and index. Re-baseline
after any instrument change. Re-run plan baselines older than 24 hours; report material
divergence and scope the fix to current measurements.

# Alarm/verifier gate
For an alarm whose metric is produced by a verifier we wrote, verify the verifier
before changing the subject:
1. Confirm its exact input artifact exists and contains expected units.
2. Re-run its exact logic manually against that artifact.
3. Compare producer completion time to verifier run time.
A race requires a producer-emitted readiness/happens-before gate plus retries, not a
later guessed schedule or wider threshold. Emit INCONCLUSIVE and no metric while the
producer is unfinished; retain a long-period missing-data dead-man alarm.

# Temporal and live-state gates
- Before migrating to a live pipeline, check that destination's current alarms/health;
  old reconciliation does not establish present health.
- Date logs/metrics/alarms against the blamed code's commit. Code younger than the
  failure cannot be its cause.
- Mutation check: revert the proposed fix. If outcome assertions still pass and only
  new implementation-shape assertions fail, no demonstrated defect underlies the fix.
- Treat a repository instruction such as "do not re-diagnose; a fix exists" as a hard
  gate: answer its dated if/then before starting new work.

# Authoritative-instrument failure
If the authoritative instrument is unavailable, the verdict is UNKNOWN. First verify
the actual failing identity/principal and authorization error. A reachable proxy may
be reported only as context after UNKNOWN, never as the headline or substitute verdict.
A caveat beside a proxy determination does not make the determination measured.

# Hard guards
GUARD pattern="the cell is obviously the right thing to fix":
  REFUSE source-free diagnosis. Sample and inspect first. NO EXCEPTIONS.
GUARD pattern="just fix the cell, verify later":
  REFUSE. Verification is the cheaper step and gates the fix.
GUARD pattern="the alarm fired, start fixing the detector":
  Verify artifact, verifier logic, and producer/verifier ordering first.
GUARD pattern="authoritative instrument is blocked, use a proxy":
  Report UNKNOWN and the blocked instrument; do not promote the proxy.

# Exclusions
Fast-feedback loops that self-correct, isolated reproducible single-axis defects, and
fixes measured through an independent instrument do not require the dominant-cell gate.


# Gate-plumbing-first (2026-08-24)
WHEN a quality GATE (provenance checker, linter, validator) reports failure —
or an implausibly clean pass — verify the gate's OWN CALL PLUMBING before
touching the deliverable: argument shapes (file list vs directory), exit-code
capture (`rc=$?` BEFORE any `$(...)` on the same line — command substitution
resets `$?`), and shell splitting (zsh does not word-split unquoted vars; an
unsplit list arrives as ONE filename). Measured 2026-08-24: THREE consecutive
call-plumbing defects on one gate each masqueraded as deliverable verdicts —
two false passes, one false failure — on the same session's exec reports.
The tell: a gate header that does not change when the inputs should have
(e.g. "evidence files: 1" across different call shapes).
GUARD pattern="the gate failed, fix the document":
  Verify arg shape + rc capture + splitting first; a gate mis-called is an
  instrumentation error (exit 2 class), not a deliverable finding.
