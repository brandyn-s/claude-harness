@rule reproduce_before_optimize
@version 2026-07-07
@scope every EMPIRICAL task where (a) the deliverable is a MEASURED metric (a competition
       score, benchmark number, eval result, reproduction target) AND (b) a known-working
       REFERENCE exists (a public winning solution/notebook, a shipped baseline, published
       SOTA, a prior working run). Fires hardest when a scarce/irreversible resource
       (competition submission quota, paid eval run, deploy) is spent to "learn".

# ─── WHY THIS RULE EXISTS (the incident) ───
# 2026-07-05..07 Kaggle JED (attack comp, ~/kaggle_jed_build): stuck at 7.5 while the public
# top scored ~95-100 and a PUBLIC winning method (pilkwang, 56.6) with a full working note was
# in hand. Instead of RUNNING pilkwang's method, I "decoded" it into my OWN ~10-line
# approximation (`dense-exfil`, blind N=600) — pilkwang's actual attack.py is 80,089 chars /
# 2,152 lines (profiles, dynamic sizing, verification, ~15 rotated benign-diagnostic exfil
# framings). My decode dropped ~99.9% of the machinery that makes 620 candidates fit+fire, and
# I never noticed because I never ran theirs → it timed out. Then, ONE TURN after writing
# "don't copy the number, size to budget", I submitted `cd-667` (blind N=667 extrapolated from
# pilkwang's env) → timed out. Across the arc: 3 different confident "the answer is X" theories
# (exfil-count → sizing → injection-surface), ZERO reproduced results above 7.5, multiple burned
# submissions. Root cause: on an EMPIRICAL task I operated in ANALYSIS mode (read/decode/theorize)
# and treated a compelling explanation as the deliverable — when the deliverable is a MEASURED
# number. With no reproduced baseline, every claim was unfalsifiable in the moment, so bad
# theories survived and I spent scarce submissions on guesses.

# ─── INVARIANTS (always-true) ───

INVARIANT the_deliverable_is_a_reproduced_number_not_an_analysis
  # WHY: on an empirical task the output is a measured metric. An analysis that is not anchored
  #   Full: incidents#on-an-empirical-task-the-output-is-a-measured

INVARIANT reproduce_the_reference_VERBATIM_before_building_your_own
  # WHY: when a reference is known to achieve the metric, running it verbatim (a) confirms your
  #   Full: incidents#when-a-reference-is-known-to-achieve-the-metric

INVARIANT reviewing_the_reference_is_not_running_the_reference
  # WHY: "I read/decoded the winning notebook" is not "I ran it and got the number". Reading
  #   Full: incidents#i-read-decoded-the-winning-notebook-is-not-i

INVARIANT never_spend_a_scarce_or_irreversible_resource_on_an_unverified_premise
  # WHY: competition submissions, paid eval runs, and deploys are the resources most tempting to
  #   Full: incidents#competition-submissions-paid-eval-runs-and-deploys-are-the

INVARIANT a_diagnosis_must_gate_the_next_action_or_it_is_theater
  # WHY: JED — I wrote "don't blind-N, size to budget" and blind-N'd the very next submission.
  #   Full: incidents#jed-i-wrote-don-t-blind-n-size-to

# ─── PROCEDURE: starting any empirical task with a known reference ───
STEP_1 identify the deliverable METRIC and the known-working REFERENCE (public solution, shipped
        baseline, published number, prior working run).
STEP_2 obtain the reference's ACTUAL artifact (pull the notebook/code, not a summary), run it
        VERBATIM, and confirm it reproduces the metric in YOUR environment. This is deliverable #1.
STEP_3 IF it reproduces → you now have a working baseline. Optimize from it with MEASURED deltas
        (change one thing, re-measure, keep if it beat the baseline).
STEP_4 IF it does NOT reproduce → the delta between your env and the reference IS the finding.
        Debug THAT (it is falsifiable and concrete) before proposing any new method.
STEP_5 only spend a scarce/irreversible resource on (a) the verbatim reference, or (b) a candidate
        you validated cheaply (local harness, offline check) first.

# ─── USER OVERRIDE POLICY — NOT preference-based. NO EXCEPTIONS. ───

GUARD pattern="I reviewed/decoded the reference, I get the idea" or "I know what they do":
  REFUSE to build your own version yet. Reviewing ≠ running. RUN the reference verbatim, confirm
  the number. The idea is not the machinery. NO EXCEPTIONS.

GUARD pattern="my approximation captures the key idea" or "close enough to their method":
  REFUSE. Reproduce the EXACT reference, THEN diff. Approximations diverge silently — a 10-line
  decode of an 80K-line engine looks close and scores zero. NO EXCEPTIONS.

GUARD pattern="I understand the mechanism, let me build the improvement":
  REFUSE without a reproduced baseline. Without one there is nothing to measure the improvement
  against, and "improvement" is an unfalsifiable guess. Reproduce first, optimize second. NO EXCEPTIONS.

GUARD pattern="I'll submit/deploy this to see what happens" or "let's just test it live":
  REFUSE spending the scarce/irreversible resource to learn. Submit only a replication of
  known-good OR a cheaply pre-validated candidate. NO EXCEPTIONS for submission quota / paid runs / deploys.

GUARD pattern="here's what we're doing wrong: <theory>" (with no reproduced number behind it):
  LABEL it a HYPOTHESIS, not a diagnosis. If you have flip-flopped ≥2 times on "the answer",
  STOP theorizing and go reproduce the reference — the flip-flopping IS the signal that you have
  no anchor. NO EXCEPTIONS.

GUARD pattern="we've hit the ceiling" or "this is the reachable frontier" or "diminishing
  returns" or "this is as good as it gets" or "we've plateaued" (on an empirical task where
  a known-good reference exists and has NOT been reproduced):
  REFUSE the ceiling claim. A ceiling is a MEASURED result, not a felt one — and it is only
  credible AFTER the known-good reference has been reproduced (so you know the gap is real,
  not an artifact of your own approach). At the FIRST plateau, the move is to reproduce the
  reference and diff, NOT to declare the frontier. "Ceiling at the slightest inconvenience"
  is the exact 2026-07-24 user correction ("Stop immediately assuming that you are reaching a
  ceiling or reachable frontier at the slightest inconvenience. In fact, I never want you to
  assume that") — the fortnight's most-repeated frustration, corrected ~4x across 3 sessions.
  UNCHARTED (see symmetric-evidentiary-burden.md), not a wall, is the honest tag when the experiment
  hasn't been run. NO EXCEPTIONS on an empirical task with an unreproduced reference.

# ─── FAILURE MODES ───

FAILURE decoded_instead_of_reproduced (JED 2026-07-05..07):
  RECOVERY: pull the reference's actual artifact, run it verbatim, get the number, THEN diff your
  version against it. Never present a decode as a reproduction.

FAILURE spent_scarce_resource_on_a_guess:
  RECOVERY: stop. Reproduce known-good or pre-validate cheaply. Treat every burned submission as
  evidence the premise was unverified.

FAILURE diagnosis_did_not_gate_next_action:
  RECOVERY: before the next action, restate the just-made diagnosis and confirm the action obeys it.

# ─── RELATION TO OTHER RULES (and why they did not catch this) ───
# - diagnose-before-fix.md ALREADY had a 2026-07-05 JED entry ("don't derive a submission CONTRACT
#   from framework-source inference when a validator/known-good example exists") — SAME failure
#   mode, same competition, and it did NOT fire. This rule BROADENS it from "contract/format" to
#   "the whole METHOD/strategy", and states it as the general reproduce-first gate.
# - feedback skills-over-rules: an ambient rule already existed and was violated under load. So the
#   durable fix is a GATE/skill-step (reproduce-first as a hard first step for empirical tasks),
#   not only this prose. Treat this rule as the statement; escalate to a hook/skill-step if it
#   recurs.
# - verify-effectiveness.md / eval-shipping-discipline.md: those govern OUR-OWN changes/metrics.
#   This governs reproducing an EXTERNAL known-working reference before building or spending.

# ─── WHAT DOES NOT REQUIRE THIS RULE ───
# - Genuinely novel work with NO known-working reference (nothing to reproduce; then verify-
#   effectiveness / measure-before-threshold apply instead).
# - Non-empirical tasks (no measured-metric deliverable).
# - The reference is trivially small AND you actually ran it (not decoded it).
