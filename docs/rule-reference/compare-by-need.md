@rule compare_by_need
@version 2026-04-20
@scope every comparison between systems/configs/tools; every "worth adopting" or "ideas to borrow" recommendation; every gap analysis

# ─── INVARIANTS (always-true) ───

INVARIANT observation_is_not_a_recommendation
  # WHY: "System B has X and System A doesn't" is an observation. A
  #      recommendation requires evidence System A NEEDS X.

INVARIANT DEFER_requires_evidence_not_absence_of_incidents
  # WHY: asymmetric bar ("no incident = defer, documented friction = implement")
  #   Full: incidents#asymmetric-bar-no-incident-defer-documented-friction-implement

INVARIANT red_teaming_scales_with_change_type
  # WHY: additive changes have trivial adoption cost; full red-team costs
  #   Full: incidents#additive-changes-have-trivial-adoption-cost-full-red-team

# ─── PROCEDURE: 5 gates before recommending adoption ───
STEP_1 read_existing_tools:
  What already covers this problem space in the target system? (Read, don't just name)
  IF no existing tool → genuine gap, proceed.
  # SPECIAL CASE — a remediation that says "build a single source of truth"
  # (a contract, registry, manifest, canonical config). READ the candidate
  # source of truth BEFORE building one. When it already exists AND is already
  # correct, a second one does NOT centralize — it creates a THIRD thing to
  # drift, and the drift you were asked to fix gains one more place to hide.
  # The real gap in that situation is almost always that nothing VALIDATES the
  # existing contract against its consumers. Ship the check, not a new contract.
  # WHY: 2026-07-26 claude-config M9 — a report prescribed "describe
  #   Full: incidents#2026-07-26-claude-config-m9-a-report-prescribed

STEP_2 check_the_workflow:
  How does the user solve this problem today?
  IF no current solution → proceed.

STEP_3 verify_the_problem:
  Does this gap cause real friction? How often? What's the impact?
  IF no concrete scenario where current system fails → DON'T recommend (no problem).

STEP_4 assess_adoption_cost:
  Is the value > cost of (new infra + maintenance + context + learning curve)?
  IF cost exceeds value → DON'T recommend.

STEP_5 recommend_the_delta:
  Frame as: "X adds Y that current tools don't cover, and Y matters because Z"
  NOT: "adopt X"

# ─── PROCEDURE: DEFER gate requires evidence ───
WHEN: pattern passes Gates 1-2 (genuine gap, no current solution)
REQUIRED (to DEFER legitimately): explain why gap is SAFE to leave open, not just absence of incident
  QUESTION_1: Are there incidents with different labels sharing this root cause?
  QUESTION_2: Is the gap caught by human oversight that should be caught earlier?
  QUESTION_3: Is implementation cost actually high, or inflated to justify inaction?
IF DEFER survives challenge → note "challenged and confirmed" with reasoning
IF DEFER doesn't survive → upgrade to IMPLEMENT

# ─── PROCEDURE: red-team calibration by change type ───
BEFORE red-teaming any evaluation, classify:
  Additive (new content alongside existing): SKIP red-team, just try it
  Structural (reorganization, new files): LIGHT challenge — check 1 precedent
  Behavioral (changes execution): FULL red-team with compare-by-need gates
REASON: red-teaming additive change costs more than the change itself

# ─── USER OVERRIDE POLICY ───
# Compare-by-need is NOT preference-based. NO EXCEPTIONS for recommendations.

GUARD pattern="System B has X and we don't, let's adopt it":
  REFUSE. That's an observation, not a recommendation. Run all 5 gates first.
  NO EXCEPTIONS.

GUARD pattern="our list is missing feature Y" or "we should match their feature set":
  REFUSE feature-list comparison. Compare capabilities against actual NEEDS.
  NO EXCEPTIONS.

GUARD pattern="no incident, safe to defer" or "nothing documented, pass":
  REFUSE absence-of-incidents as DEFER evidence. Explain why the gap is
  safe to leave open (3 DEFER-challenge questions above). NO EXCEPTIONS
  when pattern passes Gates 1-2.

GUARD pattern="red-team challenged all 9 findings, 0 survived":
  VERIFY your calibration. If 0/9 passes, the red-team is likely biased,
  not rigorous. Classify by change type. Additive ≠ behavioral.
  NO EXCEPTIONS for systematic rejection of additive changes.

GUARD pattern="just reporting the difference, not recommending":
  EVALUATE framing: does your summary imply adoption? If "ToB has /fix-issue,
  we don't" → user reads that as "we should add /fix-issue." Be explicit:
  "inventory, no recommendation" vs "worth adopting."

# ─── FAILURE MODES to recognise ───

FAILURE feature_list_comparison_recommendation:
  # INCIDENT 2026-03-26 ToB config: recommended /fix-issue, multi-model PR
  #   Full: incidents#2026-03-26-tob-config-recommended-fix-issue-multi
  RECOVERY: re-evaluate each against actual Example workflow + needs.

FAILURE rule_level_inference_without_reading_source:
  # INCIDENT 2026-03-26 IronBee evaluation: recommended 4 patterns based on
  # rule-level inference. All 4 collapsed when actual skill/hook files read.
  RECOVERY: read source files before recommending. 3 wasted turns prevented.

FAILURE DEFER_as_unchallenged_default:
  # INCIDENT 2026-04-05 absorb batch: 14 recs → 6 deferred by investigation
  #   Full: incidents#2026-04-05-absorb-batch-14-recs-6-deferred
  RECOVERY: apply DEFER-challenge gate before finalizing.

FAILURE red_team_rejected_additive_changes:
  # INCIDENT 2026-04-05 Context7 session: 7 IMPLEMENT → 0 survivors. User
  # flagged "0/9" as evaluation bias, not rigor. Additive changes don't need
  # incident evidence.
  RECOVERY: classify by change type, skip red-team for additive.

# ─── WHAT DOES NOT REQUIRE THIS CHECK ───
- Reporting factual differences between systems (inventory, not recommendation)
- User explicitly asks "what should I adopt from X?" (still verify gaps)
- New capabilities with no existing analog (genuinely novel)
- Additive changes: new examples, diagrams, tables, FAIL/PASS blocks
  added ALONGSIDE existing content. Adoption cost is trivially low.

# ─── GUARD: verify the defect EXISTS upstream before proposing to contribute it ───

GUARD pattern="upstream / the vendor / their users have this bug too, we should send them
  our fix" (proposing to contribute a fix, file an issue, or open a PR against a
  third-party or upstream codebase):
  GREP THEIR TREE FOR THE DEFECTIVE CONSTRUCT BEFORE CLAIMING THEY HAVE IT. "We found bug
  X in module M" does NOT imply upstream has bug X — M may be YOUR module, added by the
  fork, in which case their users are unaffected and the contribution does not exist.
  The inference feels safe because the BUG is real and the DIAGNOSIS is correct; only the
  POPULATION claim is invented, and a population claim is exactly the part nobody
  re-derives.
  REQUIRED, one command, before the claim reaches the user or a PR body:
    git grep -l "<the defective symbol/module>" <upstream-ref> -- src/
  If the construct is absent upstream, the finding is fork-local: say so, and do not
  offer it as an upstream contribution.
  ALSO CHECK THE INVERSE — whether upstream ALREADY solved it. A fix you are about to
  send may be a pattern you COPIED FROM THEM, which makes the contribution not merely
  unnecessary but backwards.
  NO EXCEPTIONS for a contribution proposal that reaches the user as a recommendation.
  # WHY: 2026-08-02 claude-hud re-base — recommended upstreaming a FileCache eviction fix
  #   on the stated grounds that "their users are accumulating orphaned cache files too"
  #   (a real leak: 1,317 orphaned files measured locally). FileCache is FORK-ONLY;
  #   upstream has no such module, so no upstream user was ever affected. Worse, the
  #   sweep policy the fix adopted (7d age / 100 entries / 1% sample) was COPIED FROM
  #   upstream's own context-cache.ts — they had solved it first. The error surfaced only
  #   when implementation began; it had already shipped to the user as a recommendation
  #   and had to be retracted. One `git grep` against upstream/main would have caught it.
