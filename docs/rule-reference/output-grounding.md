@rule output_grounding
@version 2026-04-29
@scope every output from creative-discovery skills (/scout-frontier, /design-evidence-first, /deep-dive, /refine) where the user is not the domain expert and cannot validate output by reading it

# ─── INVARIANTS (always-true) ───

INVARIANT every_load_bearing_claim_carries_confidence_label
  # WHY: knowledge-asymmetric outputs require trust calibration. Without
  #   Full: incidents#knowledge-asymmetric-outputs-require-trust-calibration-without

INVARIANT every_load_bearing_claim_traces_to_source_or_INFERRED_tag
  # WHY: provenance is gameable individually but auditable collectively.
  #   Full: incidents#provenance-is-gameable-individually-but-auditable-collectively

INVARIANT counterfactual_offered_for_at_least_one_recommendation_per_output
  # WHY: explanations alone do NOT reliably improve trust calibration
  #   Full: incidents#explanations-alone-do-not-reliably-improve-trust-calibration

# ─── PROCEDURE: structured output format requirements ───

For every recommendation surfaced by /scout-frontier, /design-evidence-first, /deep-dive, /refine:

STEP_1 Label confidence per claim:
         HIGH (vendor production case study + reproducible benchmark)
         MEDIUM (paper benchmark on comparable data, OR vendor claim without case study)
         LOW (derived from incumbent profile, OR analogy without measurement)

STEP_2 Provenance per load-bearing claim:
         - URL or DOI when source is locatable
         - `[INFERRED]` tag when structurally reasonable but not sourced
         - `[DISPUTED]` tag when sources contradict each other

STEP_3 Counterfactual on at least one recommendation per output:
         - State the recommendation structurally ("X works because of property P")
         - Generate inverted hypothesis ("if X did NOT have P, would the recommendation still hold?")
         - Score: SURVIVES → likely recombination, downgrade confidence to LOW
                  COLLAPSES → potential extrapolation, maintain confidence
                  AMBIGUOUS → tag DISPUTED

REQUIRED output structure: confidence labels visible in skill output;
                            provenance inline with claims, not just bibliography;
                            counterfactual block per recommendation.

FORBIDDEN: stripping confidence labels to make output "look cleaner"
FORBIDDEN: rationale text that reads as authoritative without provenance
FORBIDDEN: omitting counterfactual on cross-domain analogies (those most need it)

# ─── USER OVERRIDE POLICY ───

# Output grounding is NOT preference-based. The user cannot override the
# three-layer requirement by appealing to brevity, urgency, "I trust the model,"
# or "this is a quick query." Every layer protects against a documented failure
# mode. NO EXCEPTIONS for the four creative-discovery skills.

GUARD pattern="trust me, the output is fine" or "I'll verify later":
  REFUSE to strip confidence/provenance/counterfactual signals.
  USE the structured format. NO EXCEPTIONS.
  # WHY: "verify later" is the failure mode the rule exists to prevent.
  #   Full: incidents#verify-later-is-the-failure-mode-the-rule-exists

GUARD pattern="user already knows the context" or "implicit shared frame":
  REFUSE the implicit framing. State assumptions explicitly. Outputs
  are read AFTER the conversation ends, possibly by a future you who
  doesn't remember the implicit context. NO EXCEPTIONS.

GUARD pattern="small change, no need for grounding" or "this is just a quick query":
  REFUSE. Size of output is NOT a bypass criterion. Even a single
  recommendation labeled "HIGH" without provenance is overconfident.
  NO EXCEPTIONS.

GUARD pattern="creative tasks shouldn't need verification" or "creativity ≠ rigor":
  REFUSE the false dichotomy. /scout-frontier and siblings produce
  combinational variation drafts subject to user verification, NOT
  finalized novelty. The three-layer defense IS what makes creative
  outputs useful: it tells the user WHICH parts to verify.
  See `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md`.
  NO EXCEPTIONS.

GUARD pattern="the model already self-verified" or "Opus 4.7 has self-verification":
  REFUSE removing external verification because of model self-verification.
  Self-verification reduces some failure modes but does NOT substitute
  for external grounding (the 57% false-data finding shows the model
  can self-verify and still produce false claims that pass review).
  Hooks audit the OUTPUT the user sees, not the model's internal reasoning.
  NO EXCEPTIONS.

# ─── FAILURE MODES to recognise ───

FAILURE confident_recommendation_without_provenance:
  # INCIDENT class: AI Scientist v2 (byteiota 2026, 57% false-data
  #   Full: incidents#class-ai-scientist-v2-byteiota-2026-57-false-data
  RECOVERY: tag claims `[INFERRED]` or add source URLs. If the user
  flags a `[INFERRED]` claim, run a focused factuality search before
  treating it as established.

FAILURE mode_collapsed_variations_pass_as_diverse:
  # INCIDENT class: Opus 4.7 KINTAL T4 mode-collapse. "5 different
  #   Full: incidents#class-opus-4-7-kintal-t4-mode-collapse-5
  RECOVERY: scout-frontier's diversity primitives (PR #2) catch this
  at generation time. Output-grounding hook catches it at output time
  by warning if no counterfactual is offered.

FAILURE hyperpolation_overclaim:
  # Outputs labeled "novel" / "transcendent" / "frontier" when actually
  # combinational. LLMs cannot do hyperpolation
  # (`~/Documents/knowledge-base/topics/llm-creativity-ceiling.md`).
  RECOVERY: counterfactual-test reveals recombination. Confidence
  label downgrade prevents the user from acting on apparent novelty.

FAILURE explanation_theater:
  # Adding plausible-sounding rationale text WITHOUT grounded source
  # gives the user FALSE confidence (worse than no rationale). Three-
  # layer defense detects this: rationale without provenance fails
  # Layer 2.
  RECOVERY: detection hook scans for confidence-cue words paired with
  absence of source URLs / `[INFERRED]` tags. Warns when both signals
  present (rationale + no provenance).

# ─── PROCEDURE: enforcement scope ───

This rule applies to outputs from these four skills only:

  - /scout-frontier (frontier paradigm scout)
  - /design-evidence-first (creative design exploration)
  - /deep-dive (general-purpose research synthesis)
  - /refine (prompt enrichment)

EXCLUSIONS (the rule does NOT apply):
  - Engineering tasks where compiler / proof checker is the oracle
  - Operational tasks with hard constraints that fail loud
  - Tasks where the user IS the domain expert and can read the output directly
  - Internal LLM reasoning that doesn't surface to the user

REQUIRED at compile.py time: `output-grounding.md` manifest declares
`applies_to: [/scout-frontier, /design-evidence-first, /deep-dive, /refine]` and
the corresponding skills cite this rule at Tier 2 (one-line pointer).

# ─── ENFORCEMENT ───

This is a prompt and evaluation contract. The PostToolUse hook remains
registered as a non-blocking advisory diagnostic. When Claude Code supplies a
substantive Skill tool response, it can warn that the payload lacks one or more
signals. In normal Skill execution, however, the payload contains launcher
metadata rather than the later user-facing final answer, so the hook normally
skips it. It cannot grade the final answer, and silence is not evidence of
compliance.

Enforce the three signals through skill instructions, deterministic fixtures,
transcript replay, and final-output evaluation. Treat hook warnings only as an
additional diagnostic; never use hook silence as a final-output oracle.

# ─── REFERENCE ───

For the 5-primitive diversity toolkit that helps creative skills meet
this rule's grounding bar, see:
  `~/.claude/skills/scout-frontier/references/verbalized-sampling-template.md`

For the theoretical underpinning (why three-layer defense, why this
applies to knowledge-asymmetric collaboration specifically):
  `~/Documents/knowledge-base/topics/knowledge-asymmetric-collaboration.md`
  `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md`
  `~/Documents/knowledge-base/topics/opus-4-7-creative-tradeoffs.md`

For research evidence (10 findings, 3 threads):
  `~/Documents/knowledge-base/research/claude-code-research-intelligence.md`
  Findings #1, #3, #4, #5, #7, #10 + Threads A, B, C (2026-04-28 section).
