# Verbalized Sampling — Diversity Primitives for /scout-frontier

This reference adds five diversity primitives to /scout-frontier's candidate generation and verification phases. Sourced from 2026-04-28 research findings (see `~/Documents/knowledge-base/research/claude-code-research-intelligence.md` Findings #4, #7, #10) and `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md`.

The primitives address two distinct failure modes:

1. **Mode collapse on candidate generation** — model returns five paraphrases of the same idea instead of five distinct candidates (KINTAL T4 mode-collapse on Opus 4.7 confirmed). Mitigations: Verbalized Sampling, ordinary personas, abstraction-then-mapping.
2. **Plausible-but-wrong outputs** — combinational recombinations that look like extrapolation. Mitigations: factuality filter (Tavily/Exa grounding), counterfactual-test (Lewis-Mitchell).

---

## Critical Gotchas

Lead with these so they're not missed under cognitive load.

1. **Tail-sample factuality risk.** Verbalized Sampling raises diversity 1.6-2.1× by surfacing low-probability candidates — but those tail samples are also more likely hallucinated. **Always run the factuality filter (below) on VS outputs before framing.** Skipping the filter trades mode-collapse for confident-but-wrong findings (the AI Scientist v2 failure mode — see `~/Documents/knowledge-base/topics/knowledge-asymmetric-collaboration.md`).

2. **3× compute cost.** VS makes the model generate AND rate N candidates instead of greedy-sample. Acceptable for /scout-frontier (deliberate, slow); not acceptable for high-frequency hooks.

3. **Prompt sensitivity.** Small phrasing changes flip VS behavior. Use the templates below verbatim. If you must adapt, smoke-test against the canonical fixture (PR #4) before relying on the variant.

4. **Probability gaming.** Without explicit constraints, models assign 0.01 to everything to satisfy the VS instruction without producing diverse candidates. Always include the "each must have meaningfully different style, structure, OR viewpoint" constraint in the prompt.

5. **Creative-celebrity persona collapse.** Asking "what would Steve Jobs / Brian Eno / Bezos say" surfaces stereotype mode rather than diversity (KINTAL T4 finding). **Always use ordinary personas: "an analyst," "a maintenance engineer," "a careful reviewer."**

6. **End-to-end analogy collapse.** "Make a bio analogy for code-graph" mode-collapses to surface similarities (graph = neural network = brain). The abstraction-then-mapping pattern (below) requires structural decomposition before mapping — do not skip the decomposition.

7. **Counterfactual-test threshold matters.** A surviving counterfactual is informative (analogy is structural recombination). A collapsing counterfactual *may* indicate genuine extrapolation but is also noisy. Use the test to **downgrade confidence**, not to **upgrade** it.

8. **Counterfactual already in Step 6.** /scout-frontier Step 6 Check 5 (Lewis-Mitchell) is the existing counterfactual-test. The patterns below extend it to candidate-generation phases, not to replace it.

---

## 1. Verbalized Sampling — Query Generation

**Use when:** generating cross-domain queries (Step 2's cross-domain query template) or candidate framings for findings (Step 5).

**Source:** Zhang et al., "Verbalized Sampling," [arXiv:2510.01171](https://arxiv.org/abs/2510.01171), ICLR 2026.

**Prompt template (verbatim):**

```
Generate 5 distinct candidate <queries|framings|axes> for <target>.

For each candidate:
  - Assign a probability between 0.02 and 0.09 reflecting how likely
    this candidate is to surface paradigm-distinct findings.
  - Each candidate must differ in style, structure, OR viewpoint —
    not just word choice.
  - The probabilities must sum to a value in [0.20, 0.40] — otherwise
    you are gaming the constraint and the output will be rejected.

Output format:
  <candidate 1> | <prob> | <axis: style | structure | viewpoint>
  <candidate 2> | <prob> | <axis>
  ...
```

**Why the probability range.** The 0.02-0.09 floor prevents probability-gaming (assigning 0.01 to everything). The 0.20-0.40 sum range forces the model to commit — if all 5 are 0.02, sum is 0.10 (below floor), so the model has to assign higher probabilities to genuine candidates. The non-tight ceiling (0.40 not 0.45) leaves room for asymmetric weighting (one strong + four supporting).

**When to use the output.** Run all 5 candidates as parallel queries (per Step 2's width-scaling). Don't filter to top-probability — the diversity is in the long tail.

---

## 2. Ordinary-Persona Instruction

**Use when:** generating queries OR framings OR cross-domain analogies.

**Source:** KINTAL Creative Benchmark observation, April 2026 — creative-celebrity personas mode-collapse to stereotype.

**Accepted personas (use one per candidate):**

- "an analyst" — quantitative, evidence-anchored
- "a maintenance engineer" — operational, regression-aware
- "a careful reviewer" — adversarial, edge-case-focused
- "a non-domain-expert reading the docs" — first-principles, naive-but-fresh
- "a researcher in an adjacent field" — structural-pattern, transfer-aware

**Prohibited personas (do NOT use):**

- "Steve Jobs" / "Elon Musk" / "Bezos" / any creative-celebrity name
- "the smartest person in the room"
- "a 10× engineer"
- Any persona with a specific name (real or fictional)

**Why.** Creative-celebrity personas surface the model's training-distribution stereotype of that person, which collapses to a single mode regardless of the actual prompt. Ordinary personas force the model to sample from a broader personality distribution.

**Prompt template:**

```
For each candidate <query|framing|axis>, frame it from the viewpoint of
one of the following ordinary personas (use a different persona for each):
  - an analyst
  - a maintenance engineer
  - a careful reviewer
  - a non-domain-expert reading the docs
  - a researcher in an adjacent field

Format: <candidate> | <persona> | <one-sentence rationale>
```

---

## 3. Factuality Filter — Post-VS Grounding

**Use when:** VS or any candidate-generation step has run AND before framing the output (between Step 2-3 and Step 5 in /scout-frontier flow).

**Source:** AI Scientist v2 57% False-Data Rate (byteiota, 2026); see `~/Documents/knowledge-base/topics/knowledge-asymmetric-collaboration.md` for the Hybrid Intelligence framing.

**Filter spec:**

For each VS-generated candidate that will be framed as a finding:

1. **Literature retrieval.** Run `mcp__tavily__tavily_search` with the candidate's claim phrased as a query. If 0 hits → reject. If hits exist but all redirect to unrelated content → reject.
2. **Citation existence.** If the candidate includes a citation (URL, DOI, paper title), resolve it. If non-resolving → reject. If resolving but doesn't say what's claimed → reject.
3. **Cross-source corroboration.** Run a second query via `mcp__exa__web_search_exa`. If the second source contradicts the first → flag as "DISPUTED" and downgrade confidence to LOW.
4. **`[INFERRED]` tagging.** If the candidate cannot be sourced but is structurally reasonable, tag it `[INFERRED]` rather than dropping it. Forward to framing with explicit `[INFERRED]` marker.

**Critical:** the filter rejects MORE than it accepts under VS. Tail samples (probability 0.02-0.04) reject at >50%. This is intended — VS surfaces variety; the filter ensures grounding. Without the filter, VS becomes a hallucination amplifier.

---

## 4. Abstraction-then-Mapping (YARN Pattern)

**Use when:** generating cross-domain analogies (Step 2's cross-domain query template can use this in place of axis-name templates for adjacent-domain queries).

**Source:** YARN-style structural decomposition pattern (referenced in /scout-frontier Step 6 Evaluator-Optimizer trigger 3).

**Procedure:**

1. **Decompose target into structural units.** For the incumbent system, list 3-5 structural units (not features — units that participate in the system's behavior). For code-graph: nodes (symbols), edges (call-relations), traversal-engine, query-language.
2. **Abstract each unit.** Replace concrete terms with structural roles. Example: nodes → "addressable entities with identity," edges → "directed binary relations with provenance."
3. **Map onto distant domain.** For each abstracted unit, identify a counterpart in a distant domain. Example: "addressable entities" → biology cells, library books, chemical compounds; "directed binary relations" → reaction pathways, citation graphs, parent-child kinship.
4. **Translate back.** For each mapped distant-domain pattern, identify what techniques apply there but not in the incumbent paradigm. Example: chemistry-style reaction-pathway analysis → could code-graph use "reaction-style" stepwise transformation traces?

**Forbidden:** end-to-end "make a bio analogy for X" prompts. They mode-collapse. The decomposition + per-unit mapping is mandatory.

**Prompt template:**

```
DECOMPOSE: List 3-5 structural units of <incumbent>. Each unit should be
  addressable, have a clear input/output role, and participate in the
  system's primary behavior.

ABSTRACT: For each unit, replace the concrete name with a structural
  role description (no incumbent-domain terms).

MAP: For each abstracted role, list 2-3 counterparts in unrelated domains
  (biology, economics, urban planning, music theory, geology — pick a
  different domain per role).

TRANSLATE: For each mapping, name a technique used in the distant domain
  for that role that is NOT applied in the incumbent's paradigm. This is
  the candidate finding.
```

---

## 5. Counterfactual-Test (Lewis-Mitchell Extension)

**Use when:** verifying surviving findings (extends Step 6 Check 5 from `references/verification.md`).

**Source:** Lewis & Mitchell, "Using Counterfactual Tasks to Evaluate the Generality of Analogical Reasoning in LLMs" (arXiv:2402.08955, 2024); see `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md`.

**Procedure:**

For each surviving finding labeled "cross-domain analogy" or "novel mechanism":

1. **State the analogy structurally.** "X in domain A maps to Y in domain B because both have property P."
2. **Generate the inverted counterfactual.** "If X did NOT have property P, would the analogy still hold?"
3. **Score:**
   - Analogy survives counterfactual → recombination (interpolation). **Downgrade confidence to LOW** unless the user explicitly wants combinational variation.
   - Analogy collapses under counterfactual → potential extrapolation. **Maintain confidence** but tag as "untested in production."
   - Test result ambiguous → tag as DISPUTED.

**Scoring example:**

> Finding: "Apply chemistry reaction-pathway analysis to code-graph traces (cross-domain analogy)."
>
> Structural statement: "Code-graph traces map to chemistry reactions because both are directed sequences of state transformations with intermediate products."
>
> Counterfactual: "If code-graph traces were NOT sequences of state transformations (e.g., if they were unordered sets), would the chemistry analogy still hold?"
>
> If the model says "yes, the analogy still holds because chemistry is also a graph of compounds connected by reactions" → analogy is shallow recombination. Downgrade confidence.
>
> If the model says "no, the analogy depends on the sequencing" → potential extrapolation. Maintain confidence.

**Note:** the existing Step 6 Check 5 in `references/verification.md` already implements counterfactual-test for cross-domain claims at the verification stage. This section extends it to candidate-generation phases (when the YARN mapping in Section 4 produces a cross-domain candidate, run counterfactual-test before adding to candidate set). The extension is a no-cost duplicate of work that would otherwise happen at Step 6.

---

## Integration with /scout-frontier flow

The five primitives map to existing skill steps:

| Primitive | /scout-frontier integration point |
|---|---|
| Verbalized Sampling | Step 2 query generation (cross-domain queries) and Step 5 framing |
| Ordinary personas | Step 2 query generation (paired with VS) |
| Factuality filter | Between Step 2/3 (search/score) and Step 5 (framing) — new sub-step |
| Abstraction-then-mapping | Step 2 cross-domain query template (replaces simple axis-name template for adjacent-domain queries) |
| Counterfactual-test | Step 6 Check 5 (already present) — extended via this reference's Section 5 to candidate-generation phases |

For workflow integration, see SKILL.md Step 2 "Diversity primitives" sub-section pointing to this file.

## Smoke-test compatibility

When /scout-frontier is run on the canonical creative-test fixture (PR #4 of the implementation plan), the output should show:

- ≥5 candidates per finding cluster, each with VS probability and ordinary-persona attribution
- ≥80% of candidates carry a source URL (factuality filter accepted) OR `[INFERRED]` tag
- ≥1 cross-domain candidate per finding cluster shows abstraction-then-mapping decomposition
- ≥1 counterfactual-test result per cross-domain finding

If any of these are missing, the integration is incomplete. Re-check that the SKILL.md sub-section actually loads the prompts from this reference (Tier 2 reference pattern — the skill should not duplicate the prompts inline).

## Sources

- Zhang et al., "Verbalized Sampling: How to Mitigate Mode Collapse and Unlock LLM Diversity." [arXiv:2510.01171](https://arxiv.org/abs/2510.01171), ICLR 2026.
- Lewis & Mitchell, "Using Counterfactual Tasks to Evaluate the Generality of Analogical Reasoning in LLMs." [arXiv:2402.08955](https://arxiv.org/abs/2402.08955), 2024.
- KINTAL Creative Benchmark, April 16 2026. [kintal.co](https://www.kintal.co/insights/we-put-opus-47-through-our-creative-benchmark-is-it-worth-experimenting-with).
- byteiota, "AI Scientist v2 Passes Peer Review — But 57% Is False Data," March 2026. [byteiota.com](https://byteiota.com/ai-scientist-v2-passes-peer-review-but-57-is-false-data/).
- Franceschelli & Musolesi, "On the Creativity of AI Agents." [arXiv:2604.13242](https://arxiv.org/abs/2604.13242), April 2026.
- Cross-reference: `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md` (theoretical ceiling).
- Cross-reference: `~/Documents/knowledge-base/topics/knowledge-asymmetric-collaboration.md` (three-layer defense).
- Cross-reference: `~/Documents/knowledge-base/topics/opus-4-7-creative-tradeoffs.md` (mode-collapse failure mode).
- Cross-reference: `~/Documents/knowledge-base/research/claude-code-research-intelligence.md` Findings #4, #7, #10 + Threads A, C (2026-04-28 section).
