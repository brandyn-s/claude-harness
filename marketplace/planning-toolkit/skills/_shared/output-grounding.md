« Output-grounding contract — REQUIRED READ for /scout-frontier, /brainstorm, /deep-dive, /refine »

**Relocated from `rules/output-grounding.md` (ambient) on 2026-08-26.** It was measured
`SAFE` to relocate by `bin/rule_relocation_pilot.py` over 438 local transcripts:
corpus-wide, the rule's activity appeared in **19 sessions and all 19 were invocations of
one of its four owner skills** — coverage 100.0%, **EXPOSED=0**. Its `@scope` is literally
those four skills, so nothing outside them ever needed it in context. Instrument was
validated the same run (known-positive 4/4 expected skills, known-negative 0 sessions).

The four skills now carry a REQUIRED-READ pointer rather than a citation. That distinction
is load-bearing: while the contract was ambient, a citation sufficed because the text was
already in context. On demand, a citation that does not instruct a read is a silent
weakening — so read this file before drafting recommendations, not after.

Full rationale and incidents: `docs/rule-reference/output-grounding.md`.
Failure-mode narratives: `rules/incidents/output-grounding.md`.

---

@rule output_grounding
@version 2026-08-26
@scope every output from creative-discovery skills (/scout-frontier, /brainstorm,
       /deep-dive, /refine) where the user is not the domain expert and cannot
       validate output by reading it

INVARIANT every_load_bearing_claim_carries_confidence_label
INVARIANT every_load_bearing_claim_traces_to_source_or_INFERRED_tag
INVARIANT counterfactual_offered_for_at_least_one_recommendation_per_output

# Required three-layer output contract

For recommendations from `/scout-frontier`, `/brainstorm`, `/deep-dive`, or `/refine`:

1. Confidence per load-bearing claim:
   - HIGH: production case study plus reproducible benchmark.
   - MEDIUM: comparable paper benchmark, or vendor claim without case study.
   - LOW: analogy, incumbent-profile inference, or unmeasured derivation.
2. Provenance inline with each claim: source URL/DOI, `[INFERRED]` when unsourced,
   or `[DISPUTED]` when credible sources conflict. A bibliography alone is insufficient.
3. Counterfactual for at least one recommendation per output and every cross-domain
   analogy: state the causal property, invert it, and test whether the recommendation
   SURVIVES (likely recombination; downgrade LOW), COLLAPSES (maintain confidence), or
   is AMBIGUOUS (tag DISPUTED).

State assumptions explicitly. Confidence, provenance, and counterfactual signals must
remain visible in the user-facing artifact; do not strip them for brevity or polish.

# Hard guards

GUARD pattern="trust the output" or "verify later":
  REFUSE to remove any layer. NO EXCEPTIONS for the four scoped skills.
GUARD pattern="user knows the context":
  Refuse implicit load-bearing assumptions; outputs outlive conversational context.
GUARD pattern="small/quick output needs no grounding":
  REFUSE. Output size is not a bypass.
GUARD pattern="creative work should not need verification":
  REFUSE the dichotomy; these outputs are drafts whose grounding tells the user what
  to verify.
GUARD pattern="the model self-verified":
  REFUSE internal self-check as a substitute for externally auditable grounding.
GUARD pattern="this contract is no longer ambient, so it is advisory":
  REFUSE. Relocation changed WHERE the contract lives, not whether it binds. The
  measurement that authorised the move showed zero sessions outside these four skills
  needed it — it said nothing about the four skills needing it less.

# Scope and enforcement

This contract applies only to the four named creative-discovery skills in
knowledge-asymmetric collaboration. It excludes compiler/proof-oracle engineering,
fail-loud operational work, expert-readable outputs, and internal reasoning.

Enforce through skill instructions, deterministic fixtures, transcript replay, and
final-output evaluation. The configured `creative-output-grounding-check` PostToolUse
hook is an advisory payload diagnostic only: it can warn when a substantive Skill tool
response is present, but the payload normally contains launcher metadata rather than the
later user-facing answer. Hook silence is not evidence that the final answer met this
contract.
