# Interpreting roundtable results

How to read the META_SYNTHESIS.md output, pre-reg deltas, convergence signals, and Agent D detection.

## Convergent findings (3-of-3 HIGH confidence)

These are the most reliable. All three agents independently held the position through R5, with calibrated confidence. Treat as actionable unless you have specific reason to doubt.

**Failure mode to watch for**: convergence on a finding that was *seeded* in the original Round 1 by one agent and propagated through cross-talk. The pre-reg → main delta in R3 is the signal — if positions stabilized at R3 with low revision rate, convergence is correctness. If positions kept shifting through R5, convergence may be drift.

## Divergent findings (genuine disagreements)

These are equally important. They indicate where the agents see real tradeoffs. Look for:
- **Resolution path proposed in R4**: EXPERIMENT, EVIDENCE NEEDED, or AGREE TO DISAGREE
- **Falsifier per position**: which observation would change each agent's view

If the resolution is AGREE TO DISAGREE, the user must make the call — it's a judgment that depends on context the agents don't have. If EXPERIMENT or EVIDENCE NEEDED, that's a follow-on action.

## Single-source findings (LOW-MEDIUM confidence)

Findings raised by only one agent that were not cross-verified. Treat as hypotheses, not conclusions. Verify by direct source reading before acting.

**Why they show up**: each model has unique blind spots. Single-source findings often catch what's specific to one model's training or reasoning style. They're valuable but unverified.

## Pre-reg deltas (calibration signal)

Pre-registration captures each agent's position before seeing the next round's outputs. The delta between pre-reg and main tells you:

- **R3 delta ~33%**: typical. Agents revise some positions after seeing R2 critiques. Normal correctness update.
- **R3 delta >60%**: high revision rate. Possible conformity or possible weak Round 1.
- **R3 delta ~0%**: positions were already locked in. Early convergence.
- **R5 delta ~0%**: typical (positions stabilize by R4). Confirms convergence is real.
- **R5 delta high**: late instability. Either the protocol surfaced something new in R4, or cross-talk is producing late drift.

## Convergence signals (auto-stop)

When `--auto-stop` is on, the harness embeds each round's main outputs and compares to prior round.

- **All sims ≥ 0.92**: positions converged. Auto-stop fires.
- **One agent < 0.92, two ≥ 0.92**: one outlier still revising. Common in R3.
- **All < 0.85**: high cross-talk activity. Continue running.
- **Sim of 1.0**: identical output (likely an error). Worth investigating.

The 0.92 threshold was empirically chosen to match position-stability in the v2 experiment. Adjust higher (0.95) for stricter convergence, lower (0.88) for earlier stops.

## Agent D detection (null-control diagnostic)

Null-control injection is on by default, so the META_SYNTHESIS will normally have a section assessing Agent D. Read it carefully — it's the protocol's self-test. If the section is absent, check whether the run passed `--no-inject-agent-d`; a run without the control cannot distinguish convergence from correlated credulity, and its convergent findings carry that caveat.

**Healthy signal**: all three agents flag D's fabrications by R3 and characterize D's contribution as low-quality by R5.

**Concerning signal**: agents accept D's fabricated citations as valid findings. This means the roundtable's confabulation-resistance is weak — confident citations are bypassing scrutiny. If this happens:
- Don't trust source-level claims in the rest of the synthesis without independent verification
- Consider running the protocol again with stronger fact-check requirements

**v2 baseline**: Opus and GPT caught fabrications in Round 2; Grok initially accepted then recanted in Round 3. By R5, all three flagged D as low-effort or possibly adversarial. This is the expected pattern.

## Round-by-round token counts (bandwidth signal)

Look at the per-round output tokens. If one agent is consistently <50% of others, that agent is bandwidth-capped.

**v1 (Grok 4.3)**: 600-900 tokens by mid-rounds. Bandwidth-capped.
**v2 (Grok 4.20-reasoning)**: 1,200-2,400 tokens. Sustained.

If the pattern is bandwidth-capped, the cap-ed agent is contributing less than its weight. Consider swapping to a higher-capacity model or assigning that agent a narrower role.

## Top-3 recommendations

The synthesis ends with priority-ranked recommendations. Read them last — they reflect the post-cross-talk consensus, not Round 1 first impressions.

**Sanity check**: do the top-3 recommendations have HIGH confidence labels and unanimous agreement? If most are MEDIUM with split views, the question is too contested for high-confidence recommendations and the user should weigh the tradeoffs directly.
