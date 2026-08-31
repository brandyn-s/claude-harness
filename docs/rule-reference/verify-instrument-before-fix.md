@rule verify_instrument_before_fix
@version 2026-05-02
@scope every contingency-table cell, every "dominant failure" finding, every metric-plateau diagnosis where a failure cell has been identified

# ─── INVARIANTS (always-true) ───

INVARIANT verify_failure_cell_edges_before_designing_a_fix
  # WHY: in three documented incidents the cell surfaced by per-cell
  #   Full: incidents#in-three-documented-incidents-the-cell-surfaced-by-per

INVARIANT three_to_five_sample_edges_is_the_minimum
  # WHY: one or two samples can be cherry-picked or accidentally
  #   Full: incidents#one-or-two-samples-can-be-cherry-picked-or

INVARIANT source_inspection_means_reading_the_actual_source
  # WHY: not the harness's report, not the LLM-judge's verdict, not the
  #   Full: incidents#not-the-harness-s-report-not-the-llm-judge

# ─── PROCEDURE: when a contingency-table failure cell surfaces ───

WHEN: per-cell precision/recall analysis identifies one combination
       (caller_kind × resolver_rule, request_type × payload_size, etc.)
       holding ≥30% of the failure mass

STEP_1 sample 3-5 edges from the cell at random
STEP_2 for EACH sampled edge, open the source code at the cited
        location and verify by direct inspection:
          - Is the predicted target/output what the source says it
            should be? (verify expected behavior)
          - Is the failure mode reproducible from the source alone, or
            does it depend on a transformation the harness applies?
          - Does the resolver/parser/scorer have access to the same
            information a human reading the source has?
STEP_3 classify each edge:
          REAL — the source confirms the failure mode the cell describes
          INSTRUMENT — the source looks correct; the harness mis-sees it
          UNCLEAR — needs further investigation
STEP_4 IF ≥3 of 5 sampled edges are INSTRUMENT → fix lives in the
        harness, not the system. Stop. File the harness bug and re-run.
STEP_5 IF ≥3 of 5 are REAL → the cell is a real failure mode. Proceed
        to fix design.
STEP_6 IF mixed → expand the sample. The cell may contain two distinct
        sub-modes that need separate fixes.

# ─── PROCEDURE: before promoting any "fix shipped +Xpp gain" claim ───

WHEN: a fix has been measured against a baseline and shows improvement
REQUIRED: confirm the baseline was generated with the same instrument
           version that produced the post-fix measurement. If any
           harness change shipped between measurements (resolver
           penalty, oracle rule, sampling default, refreshed index),
           re-baseline before claiming the gain.
SEE: `verify-effectiveness.md` invariant
      "shipped_wins_expire_when_the_underlying_instrument_changes"

# ─── USER OVERRIDE POLICY ───

GUARD pattern="the cell is obviously the right thing to fix":
  REFUSE skipping the source inspection. The 2026-05-02 THEME D incident
  was exactly this: cell looked obviously like "cross-package-heuristic
  threshold too loose"; it was actually an oracle drop. NO EXCEPTIONS
  for high-confidence cells.

GUARD pattern="we already know the system, source inspection is overhead":
  REFUSE. Three documented incidents in three sessions. The "we know
  the system" prior is exactly the cognition that misses instrument
  bugs. NO EXCEPTIONS.

GUARD pattern="just fix the cell, source inspection later":
  REFUSE. The fix is the most expensive step; verifying first is the
  cheap step. NO EXCEPTIONS.

GUARD pattern="the ALARM says detection missed / coverage is broken — start
  fixing the detector" (a firing alarm whose metric is computed by a VERIFIER
  we wrote, not read from the system under test):
  REFUSE fixing the subject before verifying the VERIFIER. An alarm is an
  instrument, and the same instrument-artifact logic applies: a
  "detection-efficacy failure" is indistinguishable from a verifier that read
  the wrong file, the wrong day, or read before the producer finished.
  REQUIRED, in order: (1) confirm the artifact the verifier reads EXISTS and
  contains the expected units — an absent evidence file and a real miss look
  identical from the metric; (2) re-run the verifier's EXACT logic against that
  EXACT artifact by hand — if it now reports success, the subject is healthy
  and the alarm is the defect; (3) compare the producer's write TIME against
  the verifier's run time before concluding anything (`aws s3api
  list-objects-v2` for UTC, never `s3 ls`) — a fixed-schedule verifier racing
  a variable-duration producer fails whenever the producer runs long, which
  drifts and so looks intermittent rather than systematic.
  THEN: a timing race is fixed with a READINESS GATE on a happens-before edge
  the producer emits, plus a retry window — NOT by moving the schedule later
  (a guess against an unbounded distribution) and NOT by widening the
  threshold (which hides real misses). Emit a distinct INCONCLUSIVE state
  ("the run has not finished") that publishes NO metric, so it can never be
  read as a miss; keep the alarm `treat_missing_data=breaching` over a long
  period so an all-day suppression still fires as a dead-man's-switch.
  NO EXCEPTIONS for an efficacy/coverage alarm whose metric a verifier of ours
  computes.
  # WHY: 2026-07-28 mcp-infra #719 — `otel-canary-missed` reported 0 of 4
  #   Full: incidents#2026-07-28-mcp-infra-719-otel-canary-missed

# ─── FAILURE MODES to recognise ───

FAILURE shipped_fix_targeting_instrument_artifact:
  # INCIDENT 2026-05-02 THEME D (PR #144 → PR #145): F1 0.890 plateau,
  #   Full: incidents#2026-05-02-theme-d-pr-144-pr-145
  RECOVERY: revert the fix, document the measurement-skew root cause,
  add freshness checks before re-measuring.

FAILURE four_in_a_row:
  # INCIDENTS (running tally, 2026-05-02 → 2026-05-04):
  #   1. cell "cross-package-heuristic threshold loose" → confidence
  #      labels uncalibrated, threshold killed 1063 TPs
  #   2. cell "same-package-shadow miss" → CBM definition-time QN
  #      format bug
  #   3. cell "runIncrementalPasses single-site explosion" → oracle
  #      drops `recv.method` calls
  #   4. cell "Loc-Bench class-accuracy gap vs LocAgent (-24pp)" →
  #      class_hit forced False for 34% of GTs (module-level functions,
  #      no `Class.` prefix); metric-definition mismatch with
  #      LocAgent's "module" Acc@10 column. After fix: class becomes
  #      module/scope, code-graph re-baselines from -24pp behind to
  #      +13.5pp ahead on same column (eval_locbench_compare.py PR #180,
  #      2026-05-04).
  #   5. (2026-06-12) cell "P1 arm-2 golden MRR collapse 0.634→0.276;
  #      nix + example-gateway cohorts exactly 0.000" → PARTIAL INDEX: a
  #      ~38-min network outage dropped 11 embedding batches (a
  #      contiguous alphabetical directory swath) while the indexing
  #      job still reported status=completed; the eval measured the
  #      missing files, not the chunking change. Exposed by per-cohort
  #      split + per-extension/per-directory chunk census; fixed
  #      upstream (code-search #243: success=False → status failed) +
  #      a completeness gate in the sweep tooling. A whole-cohort
  #      EXACT-0.000 is the strongest instrument-artifact signal yet
  #      observed — real chunking effects move points, not to zero.
  PATTERN: five instances across sessions, the per-cell or column-level
  analysis surfaced an instrument bug. This rule exists because the
  pattern recurs — the diagnostic surface that surfaces the cell ALSO
  has bugs that surface AS the cell. Also recurs at the metric-
  definition layer: comparing your column to a published external
  column without verifying the columns measure the same thing produces
  the same shape of false-failure as a per-cell instrument bug.

FAILURE plan_baselines_decay_between_authoring_and_execution:
  # INCIDENT 2026-05-10 production-readiness gaps plan: Phase A baseline
  #   Full: incidents#2026-05-10-production-readiness-gaps-plan-phase-a
  PATTERN: plans that cite specific numbers (precision rates, null
  counts, mode counts, error percentages) operate on instruments that
  decay between authoring and execution. /retro summaries quote the
  audit; the audit may have a typo or be stale. Source-of-truth docs
  may have been updated since the plan was written. Phase 0 preflight
  that verifies entities exist is NOT sufficient — it must also re-run
  the measurement that produced the cited number.
  RECOVERY: when executing a plan whose baseline numbers are >24h old,
  re-run the measurement before designing the fix. If the day-of-
  execution number diverges materially from the plan's number, treat the
  divergence as a Phase 5c terminal-doc trigger, document the
  instrument decay alongside the actual-vs-predicted lift, and proceed
  with the fix scoped to the corrected baseline.
  PREVENTION: /superplan Phase 0 preflight should explicitly include
  "re-run baseline measurements that are >24h old" as a step. Currently
  the preflight covers entity existence but not measurement freshness.

# ─── WHAT DOES NOT REQUIRE THIS RULE ───

- Fast-feedback metrics moving with each fix (the loop is short
  enough that errors self-correct)
- Single-axis bug fixes where cause is reproducible in isolation
- Fixes whose effect doesn't go through the same instrument that
  produced the failure-cell evidence (different metric, different
  measurement path)

# PROCEDURE: health-check the migration DESTINATION, not just the source
STEP_1 before proposing or executing a migration onto a live, running pipeline (not a
        static dataset), run a describe-alarms (or equivalent live health check) on that
        pipeline specifically — even when prior reconciliation data about it exists.
FORBIDDEN: treating a destination's correctness as established from an old reconciliation
  entry without checking its CURRENT live operational state.
# WHY: 2026-07-31 — a gold ETL Lambda was actively in CloudWatch ALARM (a non-atomic,
#   Full: incidents#2026-07-31-a-gold-etl-lambda-was-actively

GUARD pattern="I read the current source, found the mechanism, and built a fix for a failure I
  observed in a LOG / metric / alarm":
  DATE THE ARTIFACT AGAINST THE EVIDENCE BEFORE WRITING THE FIX. Read the log line's
  TIMESTAMP, then `git log -1 --format=%ci` the function you are blaming. If the code is
  YOUNGER than the failure, it cannot be the cause — and every hour spent after that point is
  spent on a mechanism that did not exist when the thing broke.
  THIS IS THE INSTRUMENT-BUG FAMILY WITH THE AXES SWAPPED. The rest of this rule covers a
  measurement whose VALUE is wrong; here the value is right and its DATE is mismatched to the
  code you read. Both present as "the cell obviously points at this defect", and both survive
  review because the reasoning ABOUT the current source is genuinely sound.
  THE TELL IS A MUTATION THAT PASSES ON THE OUTCOME AND FAILS ONLY ON YOUR OWN CHANGE. Revert
  the fix: if every OUTCOME assertion still passes and the only failure is an assertion you
  wrote about the new code's shape (a call count, a re-read, a flag), there is no defect
  underneath — the test is pinning an implementation detail, not a behavior. That is the
  cheapest available refutation and it costs one run.
  ALSO REQUIRED: if a repo doc (CLAUDE.md, a topic file, an entry) says "do not re-diagnose
  this, a fix exists", treat that as a HARD gate, not context. Re-read the entry's own
  if/then and answer IT — an entry that prescribes "if X is still null after date D, that is
  genuinely new work" is asking a dated question, and the honest answer may be NEITHER branch.
  NO EXCEPTIONS before shipping a fix whose whole premise is a mechanism you inferred from
  current source.
  # WHY: 2026-08-02 mcp-infra bearer rotation — diagnosed a stale-`versions`-snapshot bug in
  #   `handler()` and built the fix + a regression test, from a `finishSecret` log dated
  #   2026-07-25. `_clear_dangling_pending` (the function blamed) merged 2026-07-28 13:06 —
  #   THREE DAYS LATER, so it cannot have produced that error. CLAUDE.md's own entry said
  #   verbatim "Do not re-diagnose this and do not write a fix: one exists"; I did both.
  #   Mutation testing exposed it: reverting the fix left every outcome assertion PASSING and
  #   failed only my own `describe_calls >= 2`. Fix and test discarded. The real state was
  #   UNCHARTED (the Lambda is never INVOKED — a scheduling failure, not a code failure), which
  #   is what the entry's if/then would have surfaced had I answered it instead of theorising.

GUARD pattern="the AUTHORITATIVE instrument is unavailable (auth error, missing permission,
  tool absent), so I'll answer from a REACHABLE proxy signal instead":
  THE ANSWER IS UNKNOWN. A proxy's reading is not a fallback verdict, and reporting one as
  the answer is worse than reporting nothing, because it is indistinguishable from a measured
  result. Say which instrument you could not reach and stop.
  THE CAVEAT DOES NOT SAVE YOU. Writing "this signal isn't exclusively attributable" NEXT TO
  the verdict does not neutralise the verdict — the reader takes the headline, and so does
  future-you. If the attribution is unestablished, there is no headline to write. (Same
  mechanism as red-team-rubric-discipline's "worth confirming with you" GUARD: a hedge beside
  a determination leaves the determination doing the work.)
  REQUIRED before substituting any proxy: (a) confirm the authoritative instrument is REALLY
  blocked, not blocked-for-a-reason-you-misread — an authorization error frequently NAMES the
  principal it denied, and the wrong-identity reading is far more common than a missing grant;
  (b) if you proceed with the proxy anyway, state the verdict as UNKNOWN and the proxy as
  context, never the reverse.
  THE TELL IS AN INVERTED CONCLUSION ORDER: you reached for the proxy only because the real
  instrument failed, yet the write-up leads with the proxy's finding and buries the failure.
  NO EXCEPTIONS for a health/status verdict the user will act on.
  # WHY: 2026-08-04 netsuite-paycom-sync — `mcp__azure-automation__list_jobs` returned
  #   AuthorizationFailed, so I answered "is the sync working?" from NetSuite
  #   `lastmodifieddate` activity on sync-owned records and reported "healthy and ran today".
  #   The job history said the opposite: last success 07-30 06:00Z, then 10 consecutive
  #   failures over 5 days, 36 new hires and 23 updates unwritten. I had written the
  #   attribution caveat and led with the conclusion anyway. The 403 was ALSO misread — it
  #   named `security@example.com`, and the subscription is owned by `adm-you`; one
  #   re-auth made every "blocked" read work first try. Two instrument errors stacked, and the
  #   proxy made the stack invisible.
