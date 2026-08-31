@rule complete_the_whole_instruction
@version 2026-06-29
@scope every multi-part instruction, every instruction with a tractable half and a hard/foundational half, every "build/fix/wire X" where X spans more than one shippable PR, every claim of "done"

# Full rationale and incidents: `docs/rule-reference/complete-the-whole-instruction.md`.

INVARIANT the_instruction_is_the_unit_of_completion_not_the_PR
INVARIANT the_hardest_part_is_named_before_any_building_starts
INVARIANT done_requires_the_real_seam_crossed_not_the_component_green
INVARIANT a_premise_threatening_doubt_is_surfaced_immediately_not_built_past
INVARIANT design_intent_is_read_from_the_SOURCE_DOCS_not_inferred_from_the_code
INVARIANT a_named_artifact_update_inherits_the_artifact_s_format_and_interactivity_contract
INVARIANT volume_of_activity_is_not_evidence_of_completeness

# Named-artifact updates
When the instruction is "update/revise <named artifact>", the ORIGINAL ARTIFACT is
the format/UX contract, not just a data source: style, structure, interactivity,
and judge/analysis depth must survive the revision. Diff the revision against the
original's structure before claiming done; correct data in a new format is a
violation. (2026-08-24, 120d usage reports: three data-correct rebuilds were
rejected — "update the original reports, not generate shittier new ones" — and the
fix was rebuilding on the originals' own template chains.)

# Before building
STEP_0 If source-of-truth design documents define the capability, read them before
       planning. Docs are intended target; code is current state.
STEP_1 Restate the complete instruction as enumerated parts. If the parts cannot be
       enumerated, clarify before building.
STEP_2 Name the hardest/foundational part explicitly—usually the live, visible,
       end-to-end seam or the premise on which other work depends.
STEP_3 Schedule that part. A chunk may ship first only when the unmet parts and
       sequencing are explicit; no silent "next."
STEP_4 If source, measurement, or design evidence threatens the premise, STOP and
       surface it before more building.

# Completion gate
Before saying done, shipped, complete, or works:
1. Re-read the STEP_1 enumeration and confirm every part is satisfied.
2. Run one real path across the seam the user hits—live call, rendered UI, or full
   end-to-end behavior—not merely a component test.
3. Confirm no part became "next" without the user's explicit choice.
If any check fails, state what remains and continue, or obtain explicit deferral.

# Hard guards
# These requirements are not preference-based; NO EXCEPTIONS within scope.
GUARD pattern="this PR is green and merged, so the task is done":
  REFUSE. A PR is a unit of shipping, not the instruction's completion boundary.
GUARD pattern="ship backend/data now; visible/UI half is next":
  REFUSE a silent split. Name the unmet part and get explicit assent.
GUARD pattern="tests pass / it builds / it compiles, so it works":
  REFUSE component-green as proof; cross the real user seam and run an existing harness.
GUARD pattern="surfacing the premise doubt now is disruptive":
  REFUSE building past it. Surface the evidence immediately.
GUARD pattern="I read the code, so I know the intended feature":
  If design docs exist, read them first. Never infer intended target from present behavior.
GUARD pattern="N PRs and M tests prove completeness":
  REFUSE activity volume as evidence; grade only the enumerated instruction.
GUARD pattern="the user will tell me what is missing":
  REFUSE outsourcing the completion check. Run it before the claim.

# Exclusions
Genuinely single-part asks and an explicitly user-scoped chunk need no enumeration.
A large arc may ship in honest chunks, but a chunk must be labeled a chunk with the
remaining work—not presented as whole-instruction completion.
