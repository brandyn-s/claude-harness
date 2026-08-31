# Scoring disciplines — why kappa=0, never average

The single most important methodological finding from F6 (fixture-
validity test, 2026-04-30): **B1 (casual scoring) and B2 (rubric
scoring) measure orthogonal constructs**. Cohen's kappa = 0.0 between
them on the same persona outputs.

Implications below are absolute. Violating them produces invalid
analysis.

## What B1 and B2 measure

| Scorer | Input | Output | What it actually measures |
|---|---|---|---|
| **B1 casual** | Persona output + neutral prompt to fresh LLM session | Y/N per axis (actionable, novel, framework-coherent, addresses-RC) | **Plausibility** — does this look like a smart recommendation? |
| **B2 keyword** | Persona output + keyword sets per RC | endorse/reject/absent per RC | **Token presence with stance check** — does the recommendation contain known answer language without negation context? |
| **B2 LLM-judge** | Persona output + pre-registered rubric | endorse/reject/orthogonal/absent per RC | **Rubric application** — does the recommendation satisfy strict criteria specified pre-dispatch? |

B1 with Haiku or Opus or Sonnet as rater all measure plausibility —
the model has no ground truth, so it grades on "does this read as
intelligent." F6 found B1 marks ~93% of recommendations as
"addresses-root-cause" even when 0% match the actual ground truth.

## Disciplines (load-bearing rules)

### NEVER use B1 alone as evidence of dispatch effectiveness

F6: B1 approved 4.64/5 recs as "addresses-root-cause" while B2 strict
rubric scored 0% endorsement on the same outputs. B1 is plausibility-
detection, not correctness-detection. Use only when:
- Discovery mode (where there's no ground truth and plausibility is
  the closest proxy you have)
- Combined with manual review (user reads and re-rates each rec)

### NEVER average B1 and B2 scores

They measure different things. Averaging produces a meaningless
composite. Always report each separately.

### NEVER use keyword scoring alone

F6: keyword scorer false-positived RC1 endorsement on a Bisociation
recommendation that mentioned "edge-type" but in a different context
(schema completeness, not stub-target separation). The LLM-judge
correctly identified the recommendation as orthogonal.

Use keyword scoring AS A CHECK against the LLM-judge:
- Both endorse → high-confidence endorsement
- Both reject/absent → high-confidence absence
- Disagreement → flag for manual inspection (often the LLM-judge is
  right but worth human eyes)

### Inter-rater agreement is mandatory in rubric mode

Compute Cohen's kappa between keyword and LLM-judge per RC. Report it
in `analysis.md`. Per F6:

| Kappa | Interpretation | Action |
|---|---|---|
| ≥ 0.8 | High agreement; rubric is unambiguous | Trust the result |
| 0.6 - 0.8 | Substantial agreement; some ambiguity | Spot-check disagreements |
| 0.4 - 0.6 | Moderate; rubric needs sharpening | Flag for manual review |
| < 0.4 | Low agreement; rubric is broken | Reject this run; rewrite rubric |
| 0.0 | Systematic disagreement | The two scorers measure different constructs; check rubric definition |
| NaN | One scorer was unanimous | Degenerate case; need broader cohort |

### When kappa = 0 systematically

If kappa stays 0 across multiple seeds and conditions, the two
scorers are measuring orthogonal constructs (F6 finding). This is
NOT a rubric bug — it's information. Document it and use both
scorers for orthogonal claims:
- "Rubric scorer: dispatch found N of 3 known root causes"
- "Casual scorer: rater judged dispatch's recommendations as
  N/5 plausible"

These can both be reported, separately, with no combination.

## Stance check on keyword scoring

The keyword scorer applies a **stance check** before counting endorse:
look at the 30 chars before each matched keyword for negation
patterns:

```
"should not", "avoid", "not the issue", "ignore",
"rule out", "is not the cause", "isn't the cause", "don't bother"
```

If any of these appear within the window, the keyword counts as
REJECT not ENDORSE. F6 confirmed this catches ~80% of negation
contexts.

Edge cases the stance check may miss:
- Long-distance negation ("This embedding work, even though tempting,
  ... [200 chars later] ... is not the issue")
- Sarcasm or rhetorical reframing
- Recommendation to NOT do X stated as positive recommendation to do
  Y instead

For these, the LLM-judge catches what the keyword scorer misses.

## Source

F6 results: `~/Documents/knowledge-base/research/2026-04-30-f6-fixture-validity-results.md`

Primary findings F6.1, F6.2, F6.6 in that document map to the three
"NEVER" rules above.
