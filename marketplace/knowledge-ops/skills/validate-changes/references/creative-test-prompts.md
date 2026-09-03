# Creative-Regression Test Fixture

Canonical 7-prompt fixture for validating creative-output skills (`/scout-frontier`, `/design-evidence-first`, `/deep-dive`, `/refine`) when:

- A change affects diversity primitives (PR #2 of the implementation plan)
- A change affects output grounding (PR #3)
- A model migration is being evaluated (Experiment 11: Opus 4.7 vs 4.6)
- A new creative-discovery skill is added

The fixture is structured after the KINTAL Creative Benchmark with rubrics adapted for this architecture's verification-centric framing. Each prompt is independently scoreable; mechanical rubrics replace vibes.

---

## Critical Gotchas

Lead with these.

1. **Do not interpret the rubric scores as quality measurements.** They measure WHETHER the three-layer defense (confidence + provenance + counterfactual) is present and whether candidates are distinct, NOT whether candidates are good. A high-scoring output can still be useless; a low-scoring output can still be useful. The rubric measures *output structure*, not *output value*.
2. **The fixture is a relative comparison tool, not an absolute benchmark.** Use it to compare baseline vs treatment, NOT to claim "this output is good."
3. **Do not modify prompts when a skill changes.** The fixture's value is its consistency across runs. If the skill genuinely needs a different test, add a NEW prompt rather than editing existing ones.
4. **Pass threshold ≥80% within-1-rubric-point of baseline.** This is a recommendation gate that informs your decision. Below threshold suggests holding for further investigation; above suggests proceeding. The final call is yours.
5. **Treat "5 different approaches" prompts as the failure-mode canary.** KINTAL T4 (variation generation) is where Opus 4.7 mode-collapses. If Prompt 3 fails this gate while others pass, mode-collapse is the culprit.
6. **Counterfactual-test scoring is binary, not gradient.** A surviving counterfactual = score 1; collapsing counterfactual = score 5. There is no "kinda survives." If you can't decide, the answer is 1 (the analogy is too vague to test).
7. **Run full fixture, not a subset.** Each prompt tests a distinct capability; partial runs miss regression patterns.

---

## Rubric (per prompt)

Each prompt produces an output that is scored on TWO dimensions, each 1-5:

**Dimension A — Distinctness** (variation-generation health):
- 5: each candidate has a clearly different underlying psychology, structure, or viewpoint
- 4: 4 of 5 candidates are distinct; 1 is a paraphrase
- 3: 3 of 5 candidates are distinct; 2 are paraphrases
- 2: 2 of 5 are distinct; mostly paraphrases
- 1: mode-collapse — all candidates are surface-paraphrases of the same idea

**Dimension B — Grounding** (three-layer defense health):
- 5: every load-bearing claim has confidence + provenance + at least one counterfactual offered
- 4: confidence + provenance present; counterfactual offered for at least one but not all candidates
- 3: confidence labels present; provenance partial (>=50% claims sourced or `[INFERRED]`); counterfactual sometimes offered
- 2: confidence present; provenance absent or rare; no counterfactual
- 1: no confidence labels, no provenance, no counterfactual

**Pass criterion**: each dimension scored within 1 rubric-point of baseline.
**Aggregate**: ≥80% of prompts score within 1 rubric-point of baseline on both dimensions → fixture passes.

---

## Fixture: 7 prompts

### Prompt 1 — Cross-domain analogy

```
Map this code-graph optimization problem onto a non-software domain. The problem:
the graph misses edges where a Go function calls a Rust function via FFI (cross-language
boundary). Surface 5 cross-domain mappings (NOT 5 paraphrases of "neural network").
For each, name a technique used in the distant domain that could apply.
```

Expected behavior signature:
- 5 distinct cross-domain mappings (e.g., chemistry reaction pathways, biology protein folding, urban traffic, music theory, geological strata)
- Per-candidate: confidence label, source URL or `[INFERRED]`, structural mapping (decompose → abstract → map)
- At least one counterfactual: "If FFI calls were unidirectional, would chemistry-pathway analogy still hold?"

What good output looks like (from PR #2 diversity primitives + PR #3 grounding rule):
- VS-style probability assignments per candidate
- Ordinary-persona attribution per candidate (no Steve Jobs / Eno)
- Abstraction-then-mapping decomposition shown explicitly
- Counterfactual-test result for at least one candidate

---

### Prompt 2 — Brief-to-pitch (KINTAL inverse)

```
Given this requirement: "We need a way to detect when a regulatory document
references a stale STIG benchmark version." Identify the buried strongest idea
and pitch it over the 3 obvious alternatives. State explicitly what makes the
strong idea stronger (not "it's better").
```

Expected behavior signature:
- Strong idea named with 1-paragraph rationale tied to a specific regulatory or operational property
- 3 obvious alternatives named, each with a specific weakness (not "less rigorous")
- Confidence label per option (HIGH for strong, LOWER for alternatives)
- At least one counterfactual: "if the strongest idea required X but X is unavailable, would the next-strongest hold?"

What good output looks like:
- The "strong idea" is genuinely buried (not the first thing the model would say)
- Provenance: the strong idea's framing cites a real regulatory / pattern source
- The counterfactual genuinely changes the recommendation

---

### Prompt 3 — Variation generation (KINTAL T4 canary)

```
Generate 5 distinctly different approaches to "automated detection of confidence
miscalibration in LLM outputs." Distinct means different underlying psychology,
structure, or viewpoint — NOT different word choice. Each must have a probability
in [0.02, 0.09] and an ordinary-persona attribution. Show the abstraction-then-mapping
for any cross-domain candidates.
```

Expected behavior signature:
- 5 candidates with VS probabilities summing to a value in [0.20, 0.40]
- 5 distinct ordinary personas (analyst / maintenance engineer / careful reviewer / non-domain-expert / adjacent-field researcher)
- At least 2 candidates show abstraction-then-mapping (decompose → abstract → map → translate)
- Counterfactual-test for at least one candidate

What good output looks like:
- Candidates differ on PARADIGM, not WORDS (e.g., one is "interpretability-mechanistic", another is "sampling-statistical", another is "behavioral-observational", another is "ground-truth comparison", another is "self-referential calibration")
- Mode-collapse failure mode: 5 paraphrases of "use a calibration dataset" → distinctness score = 1

---

### Prompt 4 — Constraint extraction

```
From this code sample [provide an arbitrary 30-line Python function from a
mature codebase], infer 3 invariants the function relies on without stating.
The invariants must be auditable by a non-domain-expert (someone who hasn't
read this codebase before).
```

Expected behavior signature:
- 3 inferred invariants stated as testable propositions
- Each invariant carries a confidence label (HIGH/MEDIUM/LOW) and provenance (line numbers in the function, or `[INFERRED]`)
- Counterfactual: "if invariant X were violated, what observable behavior changes?" — answer per invariant
- Audit instruction: how the non-expert could check each invariant

What good output looks like:
- Invariants are not surface-level (e.g., "input is non-null" is too obvious; better: "list-of-tuples must have monotonically increasing first element")
- The audit instruction is concrete (specific assertion to add, specific test to run, specific input that would expose violation)

---

### Prompt 5 — Oblique reframing

```
Restate this problem so a biologist would recognize it without losing the
structural problem: "Our distributed key-value store experiences write skew when
two clients update overlapping keys without serializability."
```

Expected behavior signature:
- Restatement uses biology terminology accurately
- Structural problem (concurrent updates without coordination) preserved
- Confidence label on the restatement
- Counterfactual: "if the analogy were 'overlapping rather than identical', would the bio framing still apply?"

What good output looks like:
- Biology terminology is specific (e.g., "competing transcription of overlapping gene regulatory regions"), not generic ("biological process")
- Structural mapping is checkable: a biologist reading the restatement can identify the corresponding software pattern

---

### Prompt 6 — Counterfactual probe

```
Given this recommendation: "Use Verbalized Sampling to mitigate Opus 4.7
mode-collapse on /scout-frontier outputs." Generate the inverted counterfactual
and assess whether the recommendation still holds.
```

Expected behavior signature:
- Inverted counterfactual stated structurally
- Three possible outcomes: SURVIVES (recombination — downgrade confidence), COLLAPSES (potential extrapolation — maintain confidence), AMBIGUOUS (DISPUTED — flag for review)
- Confidence label on the counterfactual analysis itself
- Provenance: cite Lewis-Mitchell (arXiv:2402.08955) or Salvi et al. (arXiv:2604.13242)

What good output looks like:
- The counterfactual is genuinely inverted (not just negated)
- The assessment offers a structural reason for SURVIVES/COLLAPSES, not "I think so"
- The counterfactual would be useful for an auditor checking the original recommendation

---

### Prompt 7 — Persona diversity

```
Generate 3 perspectives on the question "What makes a Hybrid Intelligence system
trustworthy in a knowledge-asymmetric collaboration?" — each from a different
ordinary professional (NOT creative celebrities). Each must offer a distinct
lens.
```

Expected behavior signature:
- 3 different ordinary personas (e.g., a junior systems engineer, a healthcare auditor, a regulatory compliance officer, a security operations analyst — pick three)
- Each perspective has a distinct lens (different priority, different blind spot, different verification method)
- Confidence label per perspective
- Provenance: each perspective should reference at least one source for its lens (Hybrid Intelligence quality model paper, or domain-specific source)

What good output looks like:
- Perspectives don't converge (each emphasizes something different)
- No creative-celebrity personas (Steve Jobs / Brian Eno / Bezos / etc.)
- The "distinct lens" is operationally meaningful (a different audit you'd run, a different question you'd ask, a different metric you'd track)

---

## How to run the fixture

The `/validate-changes` skill, when invoked with a creative-regression mode (see SKILL.md Step 3b), will:

1. **Detect** that one or more changes affect creative-discovery skills.
2. **Run baseline**: invoke the skill on each of the 7 prompts pre-change. Capture outputs.
3. **Run treatment**: invoke the skill on the same 7 prompts post-change. Capture outputs.
4. **Score**: apply the rubric to each output (Dimensions A and B per prompt).
5. **Compare**: for each prompt, compute baseline-vs-treatment delta on each dimension.
6. **Aggregate**: pass criterion = ≥80% of prompts score within 1 rubric-point of baseline on both dimensions.
7. **Report**: structured per-prompt table + aggregate verdict (PASS / FIX FIRST / REVERT).

Pass threshold rationale: KINTAL Creative Benchmark uses similar within-1-point thresholds; this gives us calibration consistency with existing literature.

## How to score outputs (mechanical, not vibes)

For Dimension A (distinctness):
1. List every distinct concept in the candidate set.
2. Cluster paraphrases (concept = same underlying psychology / structure / viewpoint).
3. Distinctness score = number of distinct concept clusters (integer 1-5).
4. Tiebreaker: if a paraphrase is borderline (could be either same or different), default to "same" (be strict on distinctness).

For Dimension B (grounding):
1. Count load-bearing claims in the output (claims that, if false, change the recommendation).
2. For each, check: confidence label present? provenance present (URL / `[INFERRED]` / DOI)? counterfactual offered?
3. Grounding score:
   - 5: 100% claims have confidence + provenance + at least one counterfactual offered
   - 4: 100% claims have confidence + provenance; counterfactual on at least one
   - 3: confidence on all; provenance on ≥50%; counterfactual sometimes
   - 2: confidence on all; provenance rare or absent; no counterfactual
   - 1: missing confidence labels OR missing provenance entirely

## Fixture maintenance

When adding a new creative-discovery skill or significantly changing the diversity / grounding pattern:

1. Add a new prompt to this fixture rather than editing existing ones (preserves comparison stability).
2. Note the addition in the "Fixture: N prompts" header at the top.
3. Re-baseline by running the new prompt on the current production version of each affected skill.

When KINTAL releases a new variation-generation prompt: consider adding it as Prompt 8.

## Sources

- KINTAL Creative Benchmark (April 16 2026): [kintal.co](https://www.kintal.co/insights/we-put-opus-47-through-our-creative-benchmark-is-it-worth-experimenting-with). Source for the variation-generation (T4) prompt structure and the within-1-point pass threshold heuristic.
- Salvi et al. "On the Creativity of AI Agents." [arXiv:2604.13242](https://arxiv.org/abs/2604.13242). Theoretical underpinning for distinctness scoring (interpolation/extrapolation/hyperpolation distinction).
- Lewis-Mitchell et al. "Counterfactual Analogy in Language Models." [arXiv:2402.08955](https://arxiv.org/abs/2402.08955). Source for counterfactual-test methodology.
- Zhang et al. "Verbalized Sampling." [arXiv:2510.01171](https://arxiv.org/abs/2510.01171). Source for Prompt 3 probability format.
- van der Stappen et al. "A Quality Model for Hybrid Intelligence Systems." [Springer, AAMAS 40(10) Feb 2026](https://link.springer.com/article/10.1007/s10458-025-09730-8). Source for Prompt 7's HI framing.
- Cross-reference: `skills/_shared/output-grounding.md` (the contract this fixture validates; relocated out of rules/ 2026-08-26).
- Cross-reference: `${CLAUDE_PLUGIN_ROOT}/skills/scout-frontier/references/verbalized-sampling-template.md` (the diversity primitives this fixture exercises).
- Cross-reference: `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md`, `~/Documents/knowledge-base/topics/knowledge-asymmetric-collaboration.md`, `~/Documents/knowledge-base/topics/opus-4-7-creative-tradeoffs.md`.
