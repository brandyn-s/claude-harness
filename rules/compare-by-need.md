@rule compare_by_need
@version 2026-04-20
@scope every comparison between systems/configs/tools; every "worth adopting" or "ideas to borrow" recommendation; every gap analysis

# Full rationale, examples, and incident history: `docs/rule-reference/compare-by-need.md`.

INVARIANT observation_is_not_a_recommendation
INVARIANT DEFER_requires_evidence_not_absence_of_incidents
INVARIANT red_teaming_scales_with_change_type

# REQUIRED: five gates before recommending adoption
STEP_1 read_existing_tools: Read what already covers the problem. If a proposed
       remediation is a new contract/registry/manifest, inspect the existing source
       of truth and its consumers first. If the contract is already correct, add a
       validator; do not create another source that can drift.
STEP_2 check_the_workflow: Establish how the user solves the problem today.
STEP_3 verify_the_problem: Name a concrete failing scenario, frequency, and impact.
       If no scenario exists, report the difference as inventory, not a recommendation.
STEP_4 assess_adoption_cost: Include infrastructure, maintenance, context, migration,
       and learning cost. Recommend only when expected value exceeds total cost.
STEP_5 recommend_the_delta: State "X adds Y that current tools do not cover, and Y
       matters because Z"; never stop at "adopt X."

# DEFER gate
WHEN a real gap with no current solution is deferred, explain why it is safe to
leave open. Check for differently named incidents with the same root cause, work
currently caught only by humans, and inflated implementation cost. Record
"challenged and confirmed" only if the defer survives; otherwise IMPLEMENT.

# Review depth follows change type
- Additive (content alongside existing): try it; no full red-team required.
- Structural (reorganization/new files): light challenge and one precedent.
- Behavioral (execution changes): full five-gate review.

# Hard guards
GUARD pattern="System B has X and we don't, let's adopt it":
  REFUSE. That is an observation. Run all five gates. NO EXCEPTIONS.
GUARD pattern="our list is missing feature Y" or "match their feature set":
  REFUSE feature-list comparison; compare actual capabilities to actual needs.
GUARD pattern="no incident, safe to defer":
  REFUSE absence-of-incidents as evidence; apply the DEFER gate.
GUARD pattern="red-team rejected every additive finding":
  Recalibrate by change type; systematic rejection is not rigor.

GUARD pattern="upstream says they fixed X, so our analogous component has X":
  REFUSE the population inference. Probe our component with the vendor's attack
  shape, record BLOCKED/ALLOWED per shape, and prove any allowed shape is
  runtime-reachable before proposing a local fix. NO EXCEPTIONS for changes to
  a security control.

# Upstream-contribution gate
Before claiming an upstream/vendor project shares a locally found defect, grep the upstream ref for the defective symbol/module and check whether upstream already
solved it. If absent, label the defect fork-local and do not propose an upstream
issue/PR. Required evidence is the upstream ref and matching source path.

# Exclusions
Pure factual inventories are allowed when explicitly labeled "no recommendation."
Novel capabilities still require the workflow/problem/cost gates before adoption.
