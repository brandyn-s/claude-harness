@rule validate_to_improve
@version 2026-04-20
@scope every test, validation, review, or "done" claim; every batch of changes; every function touching shared state

# Full rationale, examples, and incident history: `docs/rule-reference/validate-to-improve.md`.

INVARIANT validation_produces_fix_list_not_pass_fail
INVARIANT metadata_and_behavior_changes_never_mix_in_same_PR
INVARIANT interruption_safety_is_documented_on_stateful_functions

# After every validation
Before declaring done, answer and report:
1. Correctness: failures, fragility, and the nearest edge case.
2. Test quality: untested behavior and dependencies on live DB/network/credentials.
3. Thresholds: calibrated values versus guesses and unsafe defaults.
4. Consistency: counts and schemas across related stores.
5. Resilience: crash/kill/power-loss behavior, atomic writes, locks, and recovery.
6. Doc drift: misreads, stale documentation, and mismatched docstrings.

REQUIRED: present a ranked fix list alongside results and ask, "Want me to fix
all of these?" Never publish PASS while withholding known issues.

# Validation must exercise the product
- Visual artifact: run declarative checks, render it, inspect pixels/data regions,
  detect clipping from real document height, and render every theme.
- Scheduled/headless job: inspect its workflow for human gates before scheduling;
  verify output mtime and size, not exit code or log existence. Compare an ungated
  sibling on the same scheduler when diagnosing. A gate nobody can answer terminates.
- Wrapper/migration/deploy: state the intended behavior first and assert that
  behavior. Liveness, 200 responses, and config readback are not substitutes.
  Exercise rollback on a throwaway target. Non-deterministic identical calls require
  stopping and restoring the last definitively known-good state.
- Control fixture: prove the instrument fires on a known-positive constructed the
  same way as the negative. Do not use famous vendor example secrets or repeated
  filler as realistic controls; scanners allowlist the former and compression makes
  the latter non-representative.
- Multi-component feature: list every seam and name its owning file. Read both sides
  for mutual disclaimers. Trace each "pinned" value to a real consumer, using a wired
  sibling as a control. Execute every prescribed runbook path at least once.

# Change and interruption discipline
CLASSIFY each change as METADATA (descriptions, hints, docs, comments, examples) or
BEHAVIOR (model/context/tool grants, invocation, flags, hooks, permissions, error
paths). Batch metadata. Ship behavior alone or in groups of 2-3. Never mix them.

Every non-trivial function touching files, DB, git, or network must document:
`// INTERRUPTION: [safe|unsafe] — [mid-execution state and recovery]`.
Unsafe behavior must state why it is acceptable.

# Hard guards
GUARD pattern="tests pass, we're done":
  REFUSE. Run the six-question assessment and publish the fix list.
GUARD pattern="metadata + behavior can ship together, they're small":
  REFUSE. Split by risk. NO EXCEPTIONS.
GUARD pattern="scheduled job exits cleanly, so it is running":
  REFUSE. Verify the product advanced and that no unanswered human gate stopped it.
GUARD pattern="config applied and readback matches, so it works":
  REFUSE. CONFIG-VERIFIED IS NOT BEHAVIOUR-VERIFIED; assert intended output.
GUARD pattern="negative control returned zero, so the scanner broke":
  Verify a same-shape known-positive before judging either scanner or filter.
GUARD pattern="all component tests are green, so the integration works":
  REFUSE. Cross every named seam to the real sink in one run.

# User-facing copy is part of the contract
When a change adds a capability, grep the product's own text for statements the new
capability FALSIFIES — "cannot be changed", "not supported", "read-only", "ask an
admin" — and fix them in the SAME change. Convert every prose tripwire into an executable
assertion: a test that fails when the copy and the shipped capability disagree.

GUARD pattern="the copy is cosmetic, ship the feature now":
  REFUSE. False capability copy is a defect the user hits BEFORE the feature.
  Grep the contradicted claims and fix them in the same change. NO EXCEPTIONS.
GUARD pattern="I left a comment so the next person updates it":
  REFUSE a comment as a drift control. Write the test.

# Never promote a side effect of your own design into a benefit

Report an unrequested consequence AS a consequence. Reframing it as a feature removes
the user's ability to reject the tradeoff. A justification that occurred to you only
AFTER choosing the implementation is a tradeoff, not a rationale.

GUARD pattern="this side effect is actually desirable because <compliance word>":
  REFUSE. Report it as a consequence and let the user judge it. NO EXCEPTIONS.
GUARD pattern="the isolation is a feature, not a regression":
  Check whether the isolation was REQUIRED by the goal. If not, it is a cost.

Narrative: `rules/incidents/validate-to-improve.md`.
