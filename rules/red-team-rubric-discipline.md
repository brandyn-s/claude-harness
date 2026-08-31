@rule red_team_rubric_discipline
@version 2026-04-30
@scope every red-team, critique, audit, severity assessment, or "what's wrong with this" review of an artifact (skill, plan, design, system, recommendation) that has multiple modes, goals, or use-cases

# Full rationale and incidents: `docs/rule-reference/red-team-rubric-discipline.md`.

INVARIANT severity_follows_goal_classification
INVARIANT classify_findings_by_affected_mode_before_grading
INVARIANT make_evaluation_framework_explicit_before_evaluating

# Required review procedure
STEP_1 Enumerate the artifact's modes, goals, and use cases. State the success
       criterion and primary value-producing property for each.
STEP_2 State the optimization target per mode explicitly, including incompatible
       tradeoffs where a fix for one mode may damage another.
STEP_3 Tag every finding with affected mode/goal before severity:
- one mode -> that mode's rubric;
- multiple modes -> grade separately and report each severity;
- relevance depends on mode -> MODE-DEPENDENT.
STEP_4 Before fixes, ask: "If every finding were fixed, would the artifact still
       serve its primary value goal?" If no or uncertain, recalibrate findings.
STEP_5 Surface the framework in the result: name the criterion used for each mode.

# Determinations and method design
Whenever stating a determination ("X is/isn't the problem," "Y not Z," "out of
scope") or encoding a classification/filter/dedup rule, state the load-bearing assumption and its falsifier in the same passage. Run the cheapest source/API/grep
that could refute it before the determination drives a write or hides data. A hedge
beside an assumption does not stop the assumption from doing work.

A PROPOSED REMEDIATION IS A DETERMINATION. A published fix asserts that the fix is
possible, so its data/API precondition needs the same cheapest-refuting-read before
it ships — verifying that the PROBLEM is real does not verify that the FIX is
available. Measured 2026-08-20: a review correctly measured that 86 calendar items
were being dropped, then prescribed "parse them into the same schema with a
participants field." The user approved it. The fix was impossible — 0 of the 86
files carried `ORGANIZER` or `ATTENDEE`, a one-command check that was never run
because the five refuting reads that WERE run all tested the problem's existence,
never the remedy's feasibility. Recoverable here only because the precondition was
checked before implementation; the cost of finding out later is a retracted plan.

GUARD pattern="the finding is measured, so the fix is sound":
  REFUSE. Name the field, endpoint, permission, or capability the fix consumes and
  read it before publishing. An unverified remedy is a hypothesis wearing a
  recommendation's clothes.

# Security severity
Grade effective capability against the actual enforcement model—such as OAuth scope
plus RBAC, or IAM plus SCP—not the observed surface, granted role, or prose. Untested
write/exploit capability is AMBIGUOUS, not HIGH.

# Hard guards
# Rubric discipline is not preference-based; NO EXCEPTIONS within scope.
GUARD pattern="just give severity scores; skip the framework":
  REFUSE. Severity is an output of the named framework. State it, then grade.
GUARD pattern="all findings have one severity" with no mode breakdown:
  Reclassify a multi-mode artifact by mode before grading.
GUARD pattern="the rubric is obvious" or "rigor is rigor":
  REFUSE implicit criteria; discovery and validation modes may require opposite behavior.
GUARD pattern="all findings are HIGH; fix them all":
  REFUSE until the primary-value pre-mortem passes.
GUARD pattern="user supplied severity criteria":
  Apply them only to the modes they cover; clarify missing mode mapping.
GUARD pattern="this determination is probably right":
  State its assumption/falsifier and run the cheapest refuting read.

# Exclusions
Truly single-mode artifacts, trivial typo fixes, and cases where the user explicitly
selects the mode/rubric need no mode decomposition. Verify that they are actually
single-mode before taking the exclusion.
