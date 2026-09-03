@rule red_team_rubric_discipline
@version 2026-04-30
@scope every red-team, critique, audit, severity assessment, or "what's wrong with this" review of an artifact (skill, plan, design, system, recommendation) that has multiple modes, goals, or use-cases

# ─── INVARIANTS (always-true) ───

INVARIANT severity_follows_goal_classification
  # WHY: severity is implicitly graded against an optimization target.
  #   Full: incidents#severity-is-implicitly-graded-against-an-optimization-target

INVARIANT classify_findings_by_affected_mode_before_grading
  # WHY: a multi-mode artifact has different success criteria per mode.
  #   Full: incidents#a-multi-mode-artifact-has-different-success-criteria-per

INVARIANT make_evaluation_framework_explicit_before_evaluating
  # WHY: implicit evaluation criteria are the parent failure mode behind
  #   Full: incidents#implicit-evaluation-criteria-are-the-parent-failure-mode-behind

# ─── PROCEDURE: before red-teaming a multi-mode/multi-goal artifact ───

STEP_1 enumerate the artifact's modes, goals, or use-cases:
         - For a skill: what modes does it support? what's the success
           criterion per mode? (e.g., /persona discovery-mode = breakthrough
           framings; rubric-mode = validated measurement)
         - For a plan: what does each phase optimize for?
         - For a system: what's the primary value-generating property,
           and what's the secondary infrastructure-quality property?

STEP_2 state the optimization target per mode EXPLICITLY:
         "Mode A optimizes for X. Mode B optimizes for Y. They are
          incompatible — fixes for X may damage Y."

STEP_3 classify each finding by which mode/goal it affects:
         - If the finding affects mode A only → grade by A's rubric
         - If the finding affects mode B only → grade by B's rubric
         - If the finding affects both → grade twice, report both severities
         - If the finding's relevance depends on mode → flag as MODE-DEPENDENT

STEP_4 BEFORE proposing fixes, run the pre-mortem:
         "If all findings were addressed, would the artifact still serve
          its primary value goal?"
         If the answer is "no" or "uncertain" — your severity calibration
         is wrong. Re-classify by mode before recommending fixes.

STEP_5 surface the framework in the output:
         "I'm grading against criterion X for mode A. Findings affecting
          mode B are listed separately and graded against criterion Y."

# ─── USER OVERRIDE POLICY ───
# Severity rubric discipline is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="just give me the severity scores, skip the framework":
  REFUSE. The severity score IS the framework's output. Without naming
  the framework, you're applying an implicit one — and implicit frameworks
  are the documented parent failure mode (3 incidents).
  STATE the framework. THEN grade. NO EXCEPTIONS.

GUARD pattern="all findings are severity X" (no mode breakdown):
  EVALUATE: did you classify by mode first? If the artifact is multi-mode
  and your output has no mode-breakdown, you graded implicitly. Re-classify.
  NO EXCEPTIONS for multi-mode artifacts.

GUARD pattern="my severity rubric is the obvious one" or "rigor is rigor":
  REFUSE the implicit-framework framing. "Rigor" against discovery-mode
  ≠ "rigor" against rubric-mode. /persona's discovery output should make
  WILD swings without confidence labels; rubric output should be falsifiable.
  Same artifact, opposite rubrics. State which one you're applying.
  NO EXCEPTIONS.

GUARD pattern="if all findings are HIGH severity, just fix them all":
  REFUSE blanket-fix recommendation. Run the pre-mortem first: would
  the artifact still serve its primary value goal after all fixes?
  If no, your severity calibration was wrong, not the artifact. NO EXCEPTIONS.

GUARD pattern="this isn't multi-mode, just one goal":
  EVALUATE seriously before proceeding. Most non-trivial artifacts have
  at least two goals (the primary deliverable + infrastructure quality).
  Most skills have at least two use-cases. If the artifact truly has one
  mode, this rule doesn't fire. But "just one goal" is the assumption
  that produces this rule's failure mode — verify before claiming it.

GUARD pattern="user already gave severity criteria, just apply them":
  EVALUATE: did the user's criteria specify which mode they apply to?
  If yes → apply. If no → ask before grading. The failure mode is
  applying a single rubric to a multi-mode artifact silently.

GUARD pattern="about to state a DETERMINATION ('X is/isn't the problem', 'this is
  a Y not a Z', 'this class is out of scope') or bake a CLASSIFICATION RULE into
  an analysis METHOD (an include/exclude table, a type filter, a dedup key)":
  NAME THE LOAD-BEARING ASSUMPTION IN THE SAME BREATH AS THE DETERMINATION, and
  state how it would be falsified. A determination survives review because its
  CONCLUSION is stated explicitly while its ASSUMPTION is not — reviewers check
  the reasoning they can see. This is worse inside a METHOD than inside a
  recommendation: an assumption encoded as a filter makes every instance it
  misclassifies invisible BY CONSTRUCTION, so the analysis can never surface its
  own error.
  IT FIRES IN BOTH DIRECTIONS. Assuming a signal IS the problem and assuming it
  is NOT are the same error; being burned by one direction does not inoculate
  you against the other. And "worth confirming with you rather than me deciding"
  written NEXT TO the assumption does not neutralise it — if the assumption is
  still doing work in the table, you decided.
  CHEAPEST TEST: for each determination, ask what one read would refute it. If
  that read is a single API call or grep, run it BEFORE publishing.
  NO EXCEPTIONS for a determination that will drive a write or shape a method.
  # WHY: 2026-07-30 Airlock — five instances, one session, both directions.
  #   Full: incidents#2026-07-30-airlock-five-instances-one-session-both

# ─── FAILURE MODES to recognise ───

FAILURE severity_against_implicit_single_mode_target:
  # INCIDENT 2026-04-30 /persona red-team: graded against falsifiability
  #   Full: incidents#2026-04-30-persona-red-team-graded-against-falsifiability
  RECOVERY: name the optimization target per mode explicitly. Re-classify
  findings by mode. Re-grade with mode-appropriate rubric. Run pre-mortem.

FAILURE softening_bias_via_implicit_evidence_threshold:
  # INCIDENT 2026-04-05 absorb v3 red-team: 14 → 6 deferred for "lack of
  #   Full: incidents#2026-04-05-absorb-v3-red-team-14-6
  RECOVERY: state the evidence framework. Make the bar symmetric
  (refutation needs the same source bar as proposal — see
  symmetric-evidentiary-burden.md).

FAILURE over_rejection_via_implicit_change_type:
  # INCIDENT 2026-04-19 sbom-rs CDX 1.7: red-team rejected 7/7 IMPLEMENTs
  #   Full: incidents#2026-04-19-sbom-rs-cdx-1-7-red
  RECOVERY: state change-type classification per finding. Apply red-team
  intensity by classified type.

FAILURE severity_claimed_from_observed_surface_not_enforcement_model:
  # INCIDENT 2026-06-12 CSOD assessment (shipped KB report PR #798): graded the
  #   Full: incidents#2026-06-12-csod-assessment-shipped-kb-report-pr
  RECOVERY: before publishing a security finding's severity/exploitability,
  verify the CAPABILITY against the system's actual ENFORCEMENT model (the authz
  layers: OAuth scope + RBAC permission, IAM + SCP, etc.) — not the observed
  surface (granted scope/role). Scope-granted != capability-exercisable.
  Untested write/exploit capability grades AMBIGUOUS, not HIGH.

# ─── HISTORY ───

This rule was promoted to T1 from `knowledge-base/topics/skill-red-teaming.md`
on 2026-04-30 after the third documented recurrence of the implicit-
evaluation-criteria pattern. The prior plan (in skill-red-teaming.md) was
to build a `/red-team` skill; a T1 rule was chosen instead because the
failure mode occurs in AD-HOC red-teaming where no skill is invoked. The
rule fires ambient. A `/red-team` skill remains a future option for cases
where a structured workflow is preferred over ambient guidance.

# ─── RELATION TO OTHER RULES ───

- `compare-by-need.md` — covers change-type classification (additive /
  structural / behavioral) for adoption decisions. This rule covers
  mode/goal classification for severity assessment of OUR OWN artifacts.
  Both are aspects of "make evaluation framework explicit."
- `symmetric-evidentiary-burden.md` — covers citation rigor (refutations
  need same source bar as claims). This rule covers severity rubric
  rigor (severity needs explicit goal-classification before assignment).
- `verify-effectiveness.md` — a validation reports what it measured and what remains unverified.
  This rule extends it: when validating a multi-mode artifact, run the
  6 questions per mode, not once aggregated.

# ─── WHAT DOES NOT REQUIRE THIS CHECK ───

- Single-mode artifacts (a script that does exactly one thing)
- Trivial fixes (one-line typo correction; severity is obvious)
- Operational issues with no creative/methodology dimension
- Cases where the user has explicitly stated which mode to grade against
