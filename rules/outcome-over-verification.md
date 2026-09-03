---
description: Verification is bounded evidence for the requested outcome; verification completeness is never the deliverable
---

@rule outcome_over_verification
@version 2026-08-22
@scope every implementation, deployment, review, investigation, plan, and verification task

# OUTCOME OVER VERIFICATION — STOP CONTRACT

Verification exists to support a user-visible outcome. Its job is to answer the
material decision with enough trustworthy evidence, then end. More verification
is not progress after that decision is sound.

## Invariants

INVARIANT the_requested_outcome_is_the_goal
INVARIANT verification_is_bounded_supporting_work
INVARIANT decisive_evidence_beats_exhaustive_evidence
INVARIANT verifier_complexity_must_not_exceed_the_change_or_claim_it_proves
INVARIANT no_verifier_of_verifier_chain

## Contract

BEFORE_VERIFY:
  DEFINE outcome = the observable state that completes the user's ask.
  DEFINE decisive_evidence = the smallest fresh evidence that can prove or falsify it.
  DEFINE first_falsifier = the first fact that would make proceeding incorrect.
  DEFINE budget = normally 5 minutes to establish facts, 15 to choose the path,
    and 45 minutes of active work to reach an outcome-bearing state change.

DURING_VERIFY:
  USE the native runtime, platform, repository, or direct readback surface first.
  ADD a custom harness only when native evidence cannot answer a material decision.
  KEEP one bounded terminal review by default. Add another only for a distinct trust
    boundary or an explicit external requirement, never to pursue reviewer unanimity.
  FIX a defect in the deliverable when evidence exposes one, then rerun the same gate.
  REPAIR a defective custom verifier at most once. On the second verifier defect,
    discard or reduce it, narrow the claim, and switch to simpler native evidence.
  COUNT waiting for a bounded external job separately from active work; do not fill
    that wait by inventing more checks.

ON decisive_evidence_passes:
  STOP verification. Ship or report the requested outcome and remaining material
  uncertainty. Do not add completeness work "while here."

ON first_falsifier:
  STOP the mutation path. Correct the actual defect or report the blocker; do not
  expand the verifier unless the existing evidence surface caused the false result.

ON active_work_without_outcome >= 45_minutes:
  ABANDON the current verification approach. State outcome, known facts, unknowns,
  and the shortest safe next path. Simplify before continuing.

FORBIDDEN:
  verification_completeness_as_a_metric
  repeated_reviewer_cycles_until_no_findings
  growing_a_harness_to_prove_its_own_correctness
  adding_checks_that_cannot_change_the_current_decision
  promoting_plumbing_green_to_outcome_green
  weakening_live_or_outcome_proof_in_the_name_of_speed

## Override guards

GUARD pattern="make the verifier perfect" or "cover every edge case" or "one more review":
  REFUSE unbounded completeness work. USE the predefined decisive evidence and stop
  when it answers the material decision. NO EXCEPTIONS.

GUARD pattern="more verification is safer" or "the reviewer found another harness issue":
  REFUSE recursive verifier growth. USE native evidence, reduce the claim, or replace
  the verifier after its first repair. NO EXCEPTIONS.

GUARD pattern="we are in a hurry" or "skip live proof" or "the tests already passed":
  REFUSE to confuse bounded verification with absent verification. USE the smallest
  fresh proof that exercises the real entry point AND observes the outcome. NO EXCEPTIONS.

GUARD pattern="it is only one more check" or "I already reviewed it" or "I prefer exhaustive proof":
  REFUSE checks that cannot change the decision and claimed-prior-review shortcuts.
  USE one material falsifier and one decisive terminal gate. NO EXCEPTIONS.

If a law, audit standard, or user request names a finite evidence set, that set defines
the outcome. Satisfy it exactly; do not extend it to every imaginable proof.
