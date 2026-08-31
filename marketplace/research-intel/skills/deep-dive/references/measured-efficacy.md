# Measured Efficacy (live arm)

(Extracted from SKILL.md 2026-07-24 to meet the 5000-word Q1 budget; content unchanged.)

**Verdict: `trim` — measured 2026-05-31, N=3, `claude-opus-4-8`, n=15 (vs fair baseline).**
The three-layer framework (HIGH/MED/LOW confidence + per-finding counterfactual) was
A/B'd vs a plain baseline (same model + web_search, also emits confidence) over 15
factual questions (incl. currency-twists + false-premise traps). Both arms hit
**ceiling accuracy 1.00** (Opus 4.8 + search aces it, incl. rejecting all 4 false
premises). The framework's confidence is **uninformative** — it marked 43/45 answers
HIGH and got ~all right, so calibration_discrimination = 0.0 (no spread to calibrate);
counterfactuals are delivered (1.00 substantive) but inert at ceiling accuracy → trim.
Caveat: the fixture is too easy to exercise calibration (no errors to assign LOW to);
a harder fixture is needed to test the confidence layer on the upside. (An initial
`fix`/anti-calibrated verdict was a grader-bug artifact, caught + corrected — see
`harness/PROBLEM.md` §6.) Harness + CI gate: `skills/deep-dive/harness/`,
`tests/test_deep_dive_efficacy.py`.

**Trim candidate (actionable — but the confidence layer is RULE-REQUIRED; do NOT remove it):**
the "uninformative confidence" result is NOT grounds to drop the confidence/provenance/
counterfactual layer: (1) `output-grounding.md` REQUIRES it for deep-dive — knowledge-asymmetric
users can't validate the output by reading it, so the labels tell them what to spot-check; (2)
the finding is an artifact of a ceiling-accuracy fixture with NO errors to assign LOW to, so
calibration is *untestable* here, not absent. The actionable path is a HARDER fixture (questions
where a strong searching model genuinely errs or is uncertain) to test whether the confidence
layer DISCRIMINATES correct from incorrect — the upside the rule bets on; real discrimination
there flips this to `keep`. The only safe de-ceremony is cosmetic (prose length) — never the
three-layer grounding mechanism.
