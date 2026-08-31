@rule best_in_class_for_cross_model
@version 2026-06-29
@scope every CROSS-MODEL task — cross-provider validation, second-rater / independence checks, multi-model panels, A/B between model families, any task whose VALIDITY depends on comparing or corroborating across models

# ─── WHY THIS RULE EXISTS (the incident) ───
# 2026-06-29 Claudinator task-unit validation: the Phase B grouping coherence (87%
# same-work, judged by Sonnet) was firm-up-checked with a CROSS-PROVIDER second
# rater — but the second rater chosen was Amazon Nova PRO (mid-tier), selected only
# because the flagship Nova PREMIER was access-blocked. Nova Pro returned 26%
# same-work vs Sonnet's 87% (κ=0.10). That result was shipped (PR #67) as
# "grouping is rater-dependent" — but it is CONFOUNDED: a strong judge vs a
# mid-tier judge cannot distinguish "the grouping is noisy" from "the weaker judge
# is simply wrong more often." A cross-model finding is only as trustworthy as the
# WEAKEST model in it. User directive: "Use only the best-in-class models for
# cross-model tasks."

# ─── INVARIANTS (always-true) ───

INVARIANT a_cross_model_result_is_only_as_valid_as_its_weakest_model
  # WHY: the entire value of a cross-provider / second-rater / panel task is
  #   Full: incidents#the-entire-value-of-a-cross-provider-second-rater

INVARIANT best_in_class_means_each_vendor_s_FLAGSHIP_not_its_mid_tier
  # WHY: "cross-provider" is satisfied by vendor diversity, but VALIDITY needs
  #   Full: incidents#cross-provider-is-satisfied-by-vendor-diversity-but-validity

INVARIANT model_availability_does_NOT_silently_lower_the_bar
  # WHY: when the best-in-class model is blocked (no key, Legacy/30-day lock,
  #   Full: incidents#when-the-best-in-class-model-is-blocked-no

# ─── PROCEDURE: before running any cross-model task ───

STEP_1 name each arm's intended model AND its tier (flagship vs mid/fast/mini).
STEP_2 confirm EVERY arm is its vendor's best-in-class generally-available
        reasoning model. If any arm is mid-tier, STOP.
STEP_3 probe reachability LIVE (one cheap call) before the full run — a flagship
        can be key-less, Legacy-locked, provisioned-only, or schema-divergent.
STEP_4 IF a best-in-class arm is unreachable:
         (a) substitute ANOTHER best-in-class vendor's flagship (e.g. swap a
             blocked Amazon flagship for OpenAI/Google flagship), OR
         (b) if NO best-in-class cross-vendor model is reachable, SURFACE the
             block to the user and ask: provision a key / unblock the model, or
             explicitly accept a single-rater (non-cross) result labeled as such.
        NEVER silently run with a mid-tier arm and present it as a cross-model
        validation.
STEP_5 in the output, state each arm's exact model id + tier, so the reader can
        see the comparison was best-in-class on both sides.

# ─── USER OVERRIDE POLICY ───
# NOT preference-based. "Best-in-class for cross-model" is a standing directive.
# NO EXCEPTIONS via convenience or reachability.

GUARD pattern="the flagship is blocked, this mid-tier one is available, use it":
  REFUSE the silent downgrade. A mid-tier arm confounds the cross-model result.
  Substitute another vendor's FLAGSHIP, or surface the block and ask. NO
  EXCEPTIONS. (This is the exact 2026-06-29 Nova-Pro substitution that shipped a
  confounded κ=0.10.)

GUARD pattern="it's a different vendor, so cross-provider independence is satisfied":
  REFUSE. Vendor diversity satisfies INDEPENDENCE; it does NOT satisfy VALIDITY.
  A disagreement between a strong and a weak model is uninterpretable. Both arms
  must be best-in-class. NO EXCEPTIONS.

GUARD pattern="a cheaper/faster model is good enough for the second opinion":
  REFUSE for cross-model VALIDATION tasks. The second opinion is the whole point;
  a weak second opinion is not a validation, it's noise. NO EXCEPTIONS.
  # EXCEPTION (narrow, must be deliberate): a MEASURED A/B showing the cheaper
  # model ties the flagship on THIS task's exact metric — then it is, by
  # measurement, best-in-class for this task. Absent that evidence, flagship.

GUARD pattern="re-running with the flagship costs more tokens/time":
  IGNORE cost/speed framing for cross-model validity — same basis as
  decisive-model-choice (capability IS the result; cost is not the constraint
  on judge/eval/validation work). NO EXCEPTIONS.

# ─── FAILURE MODES to recognise ───

FAILURE confounded_cross_model_finding_from_a_mid_tier_arm:
  # 2026-06-29: Sonnet(87%) vs Nova-Pro(26%) shipped as "rater-dependent." The
  # weak arm makes the disagreement uninterpretable.
  RECOVERY: re-run the cross-model comparison with a best-in-class arm on BOTH
  sides; re-grade the finding; correct any decision record that cited the
  confounded result (here: ADR 0008's contested-coherence note).

FAILURE silent_downgrade_on_availability_block:
  RECOVERY: surface the block, get a best-in-class path (provision a key /
  unblock / swap vendor flagship) or an explicit user decision to accept a
  single-rater result LABELED as non-cross-validated.

# ─── RELATION TO OTHER RULES / MEMORY ───
# - eval-shipping-discipline.md (llm_judge + cross-PROVIDER rater): that rule
#   requires a DIFFERENT VENDOR for independence. THIS rule adds the tier
#   requirement: the different-vendor arm must also be best-in-class, or the
#   independence is bought at the cost of validity.
# - [[decisive-model-choice]] (auto-memory): capability-first, never default to
#   the weakest. THIS rule is its cross-model specialization — for cross-model
#   tasks, "capability-appropriate" hardens to "each vendor's flagship."
# - llm-as-judge-validity-2026 (KB topic) — IMPORTANT NUANCE: "best model is not
#   always the best JUDGE" (a conservative flagship can UNDER-recall vs a diverse
#   panel). This rule does NOT override that: when the task has a MEASURED target
#   metric (recall@k, etc.), pick by the measurement (decisive-model-choice's A/B
#   exception). The flagship mandate here governs cross-model VALIDATION /
#   corroboration tasks where no such measurement exists yet — the default is the
#   flagship, and a measured A/B is the only thing that licenses a smaller model.
# - no-chinese-based-models (auto-memory): provenance EXCLUSION, orthogonal —
#   best-in-class is chosen from the US/allied set only.

# ─── WHAT DOES NOT REQUIRE THIS RULE ───
- Single-model tasks (no cross-model comparison; decisive-model-choice governs).
- Tasks with a MEASURED metric where a smaller model is proven to tie/win
  (then the measurement defines best-in-class for that task).
- Cheap mechanical sub-steps inside a larger task (extraction, formatting) that
  do not themselves carry the cross-model validity claim.
