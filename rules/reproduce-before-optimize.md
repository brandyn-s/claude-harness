@rule reproduce_before_optimize
@version 2026-07-07
@scope every EMPIRICAL task where (a) the deliverable is a MEASURED metric (a competition score, benchmark number, eval result, reproduction target) AND (b) a known-working REFERENCE exists (a public winning solution/notebook, a shipped baseline, published SOTA, a prior working run). Fires hardest when a scarce/irreversible resource (competition submission quota, paid eval run, deploy) is spent to "learn".

# Full rationale and incidents: `docs/rule-reference/reproduce-before-optimize.md`.

INVARIANT the_deliverable_is_a_reproduced_number_not_an_analysis
INVARIANT reproduce_the_reference_VERBATIM_before_building_your_own
INVARIANT reviewing_the_reference_is_not_running_the_reference
INVARIANT never_spend_a_scarce_or_irreversible_resource_on_an_unverified_premise
INVARIANT a_diagnosis_must_gate_the_next_action_or_it_is_theater

# Required empirical sequence
STEP_1 Name the deliverable metric and known-working reference.
STEP_2 Obtain the actual reference artifact—not a summary or reconstruction—and run it VERBATIM in the target environment. Record the reproduced number.
STEP_3 If it reproduces, optimize from that baseline one change at a time. Measure each
       delta and retain only demonstrated improvements.
STEP_4 If it does not reproduce, the environment/reference delta is the immediate
       finding. Debug that falsifiable gap before proposing another method.
STEP_5 Spend submission quota, paid evaluation, or deployment only on the verbatim
       reference or a candidate already validated by a cheaper local/offline check.
STEP_6 Before the next action, restate the current diagnosis and verify that the action
       obeys it.

# Hard guards
# Reproduce-first is not preference-based; NO EXCEPTIONS within scope.
GUARD pattern="I reviewed/decoded the reference; I understand it":
  REFUSE to build an approximation. Reviewing is not running. Reproduce first.
GUARD pattern="my approximation captures the key idea":
  REFUSE. Run the exact artifact, then diff measured behavior.
GUARD pattern="I understand the mechanism; build the improvement":
  REFUSE an improvement claim without a reproduced baseline.
GUARD pattern="submit/deploy to see what happens":
  REFUSE spending scarce or irreversible resources on an unverified premise.
GUARD pattern="here is what we're doing wrong" without a reproduced number:
  Label it HYPOTHESIS. After two conflicting theories, stop and reproduce.
GUARD pattern="we hit the ceiling/frontier/plateau/diminishing returns":
  REFUSE while a known-good reference remains unreproduced. A ceiling is measured;
  otherwise the state is UNCHARTED, not a wall.

# Exclusions
Novel work with no known-working reference, non-empirical work, and a small reference
that was actually executed use the normal effectiveness-measurement discipline instead.
