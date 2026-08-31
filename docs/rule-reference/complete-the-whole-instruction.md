@rule complete_the_whole_instruction
@version 2026-06-29
@scope every multi-part instruction, every instruction with a tractable half and a hard/foundational half, every "build/fix/wire X" where X spans more than one shippable PR, every claim of "done"

# ─── WHY THIS RULE EXISTS (the diagnosed mechanism, not a vibe) ───
# 2026-06-29 Claudinator session, user feedback (verbatim): "It seems to me
# that you aren't really fully executing my instructions. There are multiple
# examples throughout this session." Three documented instances in ONE session:
#   1. prompt/skill separation — shipped the DATA-layer tag as "done"; the
#      VISIBLE UI + skill-refine loop (the actual point) waited until the user
#      said "it doesn't look like that's been done."
#   2. judge fix — called assistant-prefill "the canonical Bedrock technique"
#      and shipped WITHOUT one live call; a smoke harness built to catch exactly
#      this was not run; it failed EVERY call.
#   3. golden sets — shipped 4 PRs of golden-set machinery while the repo's OWN
#      design doc (TASK_UNIT.md) said the unit was wrong and named the
#      replacement; built ON the questioned premise instead of surfacing it.
# COMMON ROOT: the boundary of a clean, mergeable PR was allowed to become the
# boundary of the instruction. The tractable half ships green+tested+merged,
# which FEELS like completion, so the hard/foundational half silently becomes
# "next." Volume of activity (worktrees, tests, PRs) masks that the instruction
# was half-met. Building is the path of least resistance; a merged PR is a clean
# stopping point; crossing a real seam / fully satisfying a multi-part ask /
# surfacing a doubt that threatens the work are all harder and get deferred.

# ─── INVARIANTS (always-true) ───

INVARIANT the_instruction_is_the_unit_of_completion_not_the_PR
  # WHY: a PR is a unit of SHIPPING, not a unit of DONE. An instruction is
  #   Full: incidents#a-pr-is-a-unit-of-shipping-not-a

INVARIANT the_hardest_part_is_named_before_any_building_starts
  # WHY: the failure is silent BECAUSE the hard part is never named out loud —
  #   Full: incidents#the-failure-is-silent-because-the-hard-part-is

INVARIANT done_requires_the_real_seam_crossed_not_the_component_green
  # WHY: "tests pass / it builds / the PR merged" is component-green. The user
  #   Full: incidents#tests-pass-it-builds-the-pr-merged-is-component

INVARIANT a_premise_threatening_doubt_is_surfaced_immediately_not_built_past
  # WHY: if evidence (a design doc, a measurement, the code) says the thing
  #   Full: incidents#if-evidence-a-design-doc-a-measurement-the-code

INVARIANT design_intent_is_read_from_the_SOURCE_DOCS_not_inferred_from_the_code
  # WHY: what the code DOES is not what it was SUPPOSED to do. Inferring the
  #   Full: incidents#what-the-code-does-is-not-what-it-was

INVARIANT volume_of_activity_is_not_evidence_of_completeness
  # WHY: many PRs / many tests / many worktrees read as thoroughness and HIDE
  #   Full: incidents#many-prs-many-tests-many-worktrees-read-as-thoroughness

# ─── PROCEDURE: before building anything for a multi-part instruction ───

STEP_0 IF the repo has source-of-truth design docs (SPEC.md, a design doc, an
        original brief / tarball, an ADR) AND the task is about a capability
        those docs define → READ THEM FIRST, before forming the plan. Learn the
        INTENDED design from the docs; use the code only to learn the current
        STATE. Never infer the goal from what the code currently does — that
        re-implements the present (possibly broken) behavior as if it were the
        target. (2026-06-29: inferred "Experiments = findings" from the code,
        renamed the tab, moved away from the SPEC's actual intent.)

STEP_1 RESTATE the full instruction in your own words, enumerated as parts.
        If you can't list the parts, you don't understand the ask yet — ask.

STEP_2 NAME the hardest / most-foundational part explicitly, out loud, in the
        response. This is usually: a real-world seam (live call, visible UI,
        end-to-end behavior), a foundational premise, or the integration that
        makes the pieces actually work for the user.

STEP_3 DECIDE the build order with the hard part scheduled, not deferred. If
        you genuinely must ship a piece first, say WHICH part you are NOT yet
        completing and WHEN it lands — make the deferral an explicit,
        user-visible choice, never a silent drift.

STEP_4 IF any evidence (a design doc, a measurement, the source) suggests the
        instruction's PREMISE is wrong or under question → STOP and surface it
        BEFORE building. Do not build polished work on a questioned premise.

STEP_5 build — but DONE is gated by STEP_6, not by "the PR merged."

STEP_6 COMPLETION GATE — before saying "done" / "shipped" / "complete":
         (a) re-read the STEP_1 enumeration; is EVERY part satisfied?
         (b) did ONE real run cross the seam the USER will hit (live call,
             rendered screen, full multi-part behavior) — not just a unit test?
         (c) is there a part that "became next" without the user choosing that?
         If any answer is no → it is NOT done. Say what remains, in the same
         response, and either do it now or get an explicit deferral.

# ─── USER OVERRIDE POLICY ───
# This is NOT preference-based. The user asked for this rule to STOP the
# half-assing pattern — so the model does not get to relax it for convenience,
# speed, or a clean stopping point. NO EXCEPTIONS.

GUARD pattern="this PR is green + merged, the task is done" (when the instruction had more parts):
  REFUSE the completion claim. A merged PR is shipping, not done. Re-read the
  STEP_1 enumeration; if a part is unmet, name it and continue. NO EXCEPTIONS.

GUARD pattern="I'll ship the data/backend half now, the visible/UI half is next"
  (without the user choosing that split):
  REFUSE the silent split. The half the user can SEE/USE is usually the point.
  If you must sequence, make the deferral explicit + dated in the response and
  get assent — do not let "next" be a default. NO EXCEPTIONS.
  # WHY: the 2026-06-29 prompt/skill incident — data tag shipped as "done,"
  #      the visible separation only built after the user noticed it missing.

GUARD pattern="tests pass / it builds / it compiles, so it works":
  REFUSE "works" from component-green. Cross the REAL seam the user hits — a
  live call, the rendered screen, the end-to-end multi-part run — before
  claiming it works. If a harness exists to cross that seam, RUN IT. NO
  EXCEPTIONS.
  # WHY: the 2026-06-29 judge incident — "canonical technique" shipped without
  #   Full: incidents#the-2026-06-29-judge-incident-canonical-technique-shipped

GUARD pattern="I'm already building on this premise, surfacing the doubt now is disruptive":
  REFUSE building past it. A premise-threatening doubt (a design doc, a
  measurement, the code contradicts the ask) is surfaced IMMEDIATELY, before
  the next build — even mid-arc, even when it threatens shipped work. Polished
  work on a wrong premise is the most expensive half-assing. NO EXCEPTIONS.
  # WHY: the 2026-06-29 golden-set incident — 4 PRs built on a premise the
  #      repo's own TASK_UNIT.md had already concluded was the wrong unit.

GUARD pattern="I read the code, I know what this feature is / does" (when design docs exist):
  REFUSE forming the plan from the code's CURRENT behavior. The code is the
  present state (possibly the bug); the SPEC / design doc / original brief is the
  INTENDED target. Read the source-of-truth docs FIRST (STEP_0), then plan. NO
  EXCEPTIONS when the repo has design docs for the capability in question.
  # WHY: 2026-06-29 — inferred "Experiments = findings" from the rendered code,
  #   Full: incidents#2026-06-29-inferred-experiments-findings-from-the-rendered

GUARD pattern="look how much I shipped — N PRs, M tests, all green":
  REFUSE volume as a completeness proxy. The only completeness question is "is
  the USER'S whole instruction satisfied end to end." Re-run STEP_6 against the
  enumerated parts, not against the activity count. NO EXCEPTIONS.

GUARD pattern="the user will tell me if a part is missing":
  REFUSE outsourcing the completeness check to the user. The user asking "why
  isn't X done" is the FAILURE this rule prevents, not the safety net. YOU run
  STEP_6 before claiming done. NO EXCEPTIONS.

GUARD pattern="the hard part is a multi-day arc, this PR is a reasonable chunk":
  EVALUATE honestly: chunking a genuinely large arc is fine — IF you (a) named
  the whole arc, (b) said which chunk this is and what remains, and (c) did not
  imply the instruction is complete. A chunk presented AS completion is the
  violation; a chunk presented AS a chunk is fine.

# ─── FAILURE MODES to recognise ───

FAILURE shipped_tractable_half_as_completion:
  # The data layer / the backend / the easy mechanism ships green; the visible,
  # integrated, or user-facing half silently becomes "next."
  RECOVERY: re-read the original instruction, enumerate the unmet parts, name
  them to the user, and complete them (or get an explicit deferral) NOW.

FAILURE claimed_done_without_crossing_the_user_seam:
  # "Tests pass" / "merged" stood in for "the live behavior works."
  RECOVERY: cross the real seam (live call, rendered UI, end-to-end run); if a
  harness exists, run it; report the actual result, not the inference.

FAILURE built_past_a_questioned_premise:
  # Kept building on a foundation the evidence (doc/measurement/code) had
  # already put in question, instead of surfacing it.
  RECOVERY: stop, surface the premise tension with the evidence, let the user
  re-decide before more building.

FAILURE volume_masked_a_half_met_instruction:
  # Many PRs/tests read as thoroughness; the actual ask was half-done.
  RECOVERY: ignore the activity count; grade only against the enumerated parts.

FAILURE deferred_ungated_deliverable_behind_self_justifying_prerequisites:
  # INCIDENT 2026-07-31 CloudTrail/Athena bandwidth: the user's literal, REPEATED ask was
  #   Full: incidents#2026-07-31-cloudtrail-athena-bandwidth-the-user-s
  RECOVERY: when the plan's own text marks an item already-unblocked or ship-independently,
  ship THAT before any further prerequisite work -- or say explicitly, in the turn where you
  choose otherwise, that you are deferring an already-designed ungated deliverable and why.
  A prerequisite being real is not evidence it is GATING.

# ─── RELATION TO OTHER RULES ───
- never-stop-early.md — that rule says don't STOP before the task is done
  (don't punt to a new session). THIS rule says don't redefine DONE down to a
  shippable slice. Siblings: one guards against quitting, one against
  truncating the definition of complete.
- verify-effectiveness.md — its multi-seam invariant ("a multi-seam feature is
  not done until one real run crosses every seam to the real sink") is the
  verification spine of STEP_6(b). This rule generalizes it from features to
  whole instructions.
- scope-discipline.md — that rule stops OVER-building (infra nobody asked for).
  This rule stops UNDER-completing (shipping less than the ask). They are the
  two sides of "build exactly the instruction": not more, not less.

# ─── WHAT DOES NOT REQUIRE THIS RULE ───
- Genuinely single-part instructions (one file, one fix, one answer) — DONE is
  obvious; no enumeration needed.
- Conversational turns / questions (no deliverable to complete).
- An explicit chunk the user themselves scoped ("just do part 1 today").
