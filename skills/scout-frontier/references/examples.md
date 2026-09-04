# scout-frontier — worked examples

Example 1 (code intelligence engines vs our code-graph) stays in SKILL.md.

### Example 2: Observability / telemetry storage

```
/scout-frontier observability storage vs an OTel + Athena pipeline
```

Profiles incumbent (table + lookup + behavior + streaming). Searches for paradigm-distinct: column-stores (ClickHouse), trace graphs (Tempo's exemplar+span graph model), eBPF-driven runtime indexes, learned anomaly detection on logs. Reports findings grouped by tier.

### Example 3: Code-graph engine improvement (canonical positive — knowledge-asymmetric)

```
/scout-frontier code intelligence engines vs our code-graph engine; user is no longer the
day-to-day maintainer and can't validate output by reading
```

Profiles incumbent. Diversity primitives fire: VS-generated cross-domain queries (5 candidates with probabilities, ordinary-persona attribution), abstraction-then-mapping for adjacent-domain analogies (decompose → abstract → map → translate, NOT end-to-end "make a bio analogy"), factuality filter rejects unsourced tail samples, counterfactual-test downgrades surface-similarity findings. Output: ≥3 paradigm-distinct findings each with confidence + provenance + counterfactual signal so the user can spot-check WHICH parts to verify rather than auditing the whole report.

### Negative example (do NOT use)

"Find me a transcendent novel approach to debugging that no one has thought of before." — That asks for transformational creativity / hyperpolation, which is constrained for LLMs per multi-source 2024+ evidence (see `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md` — tradeoff curve, contested at the boundary). /scout-frontier produces combinational variation at scale, framed against the tradeoff curve, not transcendent novelty. Reframe as: "Find paradigm-distinct debugging approaches across other domains" (combinational + cross-domain), which IS in scope.
