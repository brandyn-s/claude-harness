# Finding output template

The full schema for a /scout-frontier finding. Used in Step 5.

## Schema

```
### Finding N: <name>

**Source**: <URL or DOI>
**Paradigm distance**: N/4 — differs on <axes from the 4-axis rubric>
**Implementation maturity**: <production | prototype | paper-only | speculative>
**Integration cost**: <Tier A/B/C/D> — <one-line: what's preserved / what's replaced>

**Outcome (what we get)**:
  <1-2 sentences naming the concrete capability this unlocks. Reference
   the Phase 0 friction ID(s) directly: "addresses F1, F3".>

**Expected improvement**:
  - Friction addressed: <F1, F2, ... — name the specific Phase 0 IDs>
  - Metric: <which measurable axis improves>
  - Baseline: <copy verbatim from friction[Fn].measured — no manual re-typing>
  - Target: <expected post-adoption value>
  - Confidence: <high | medium | low>
  - Source of estimate: <paper benchmark | vendor case study | derived>

**Test**:
  - Scenario: <concrete setup that exercises the improvement>
  - Pass criterion: <numeric threshold for success>
  - Method: <how to actually measure>

**Failure modes (regression detection)**:
  - <anti-signal 1: what would tell us adoption hurt the metric, not helped>
  - <anti-signal 2: secondary regressions to watch for during the spike>

**Verification**:  (filled in by Step 6 — see references/verification.md)
```

## Field-by-field guidance

### Source
URL to the canonical reference: GitHub repo, paper landing page, vendor
docs page. If the finding spans multiple papers/repos, list the most
representative one and put others in Outcome.

### Paradigm distance
Computed in Step 3. Score from the 4-axis rubric in
`references/paradigm-distance-rubric.md`. Always name the axes that differ
(not just the count): `differs on data_structure, computation_model`.

### Implementation maturity
- **production**: vendor or in-house GA; used at scale by named users
- **prototype**: working code, demo'd, limited adoption (Example-Internal,
  research-prototype, github with last commit <12mo)
- **paper-only**: peer-reviewed or preprint, no public code (or code is
  research-grade and unmaintained)
- **speculative**: discussion, position paper, no implementation — discard
  per Step 4 filter

### Integration cost
See `references/integration-cost-rubric.md` for Tier A/B/C/D criteria. The
one-line justification names what's preserved vs replaced.

### Outcome (what we get)
**Most important field** for user decision. Two rules:
1. State the concrete capability unlocked, not a vague "improvement"
2. Reference the Phase 0 friction IDs by name ("addresses F1, F3"), not
   prose paraphrase ("addresses the rebuild slowness")

A good Outcome reads like a workflow that's currently impossible:
"answer 'where does this Rust→Go FFI handoff actually go in production?'
by recording mixed-runtime stack frames at 19-100 Hz from kernel."

A bad Outcome reads like marketing: "modern alternative to graph traversal."

### Expected improvement

Quantified. The flow is:
1. **Friction addressed**: name the Phase 0 friction IDs this finding hits
   (F1, F2, F3). One finding can address multiple friction points.
2. **Metric**: which axis the friction measures.
3. **Baseline**: copy `friction[Fn].measured` verbatim from the constraint
   trace. Do not re-derive or paraphrase — Phase 0 is the source of truth
   for baselines, and re-typing introduces drift between Phase 0 and Step 5.
4. **Target**: the value we expect after adoption. Cite the source.
5. **Confidence**: grade the Target estimate (criteria below).
6. **Source of estimate**: where the Target number came from (paper Table N,
   vendor case study URL, derived).

If you can't quantify the improvement, the finding may not be ready —
revisit whether it actually addresses a measurable friction point.

### Confidence (on the Target estimate)

The same numeric target can be high or low confidence depending on how
it's grounded:

- **high**: vendor production case study with similar workload, OR a
  peer-reviewed benchmark on the same task domain we're applying it to,
  OR an in-house spike result. Reproducible via published methodology.
- **medium**: paper benchmark on different but comparable data; a vendor
  claim without a case study; a peer-reviewed result on a related task.
  Methodology is published but applicability requires assumptions.
- **low**: derived from the incumbent profile + a claim ("if their X is N,
  ours should be ~N"); cross-domain analogy without measurement;
  speculation tied to a plausible mechanism but not measured.

Tag confidence per finding. A finding with a 95% F1 target Confidence: low
is honest about its uncertainty; the same target Confidence: high is a
load-bearing claim. The user can prioritize spikes accordingly.

### Test
The forward falsification path — proves the improvement materialized.
Three rules:
1. Scenario must be runnable on Example infrastructure (or an equivalent
   reduction). "Reproduce X paper benchmark" is acceptable; "wait for
   industry adoption" is not.
2. Pass criterion is numeric, not qualitative. "<30s rebuild" not "fast";
   "≥80% F1" not "good recall".
3. Method describes the measurement, including the comparison set
   (before/after, A/B, vs ground truth).

If you can't write a test in 2-3 lines, the finding is not actionable yet
— it's research, not engineering. Mark it as such in the report rather
than papering over with a vague test.

### Failure modes (regression detection)

The reverse falsification path — proves we'd notice if adoption made
things worse. This is **mandatory for Tier B/C/D** findings (substrate-
touching changes have real regression risk) and **strongly recommended
for Tier A** (additive layers can still cause performance, accuracy, or
operational regressions in surprising ways).

Each Failure mode is a named anti-signal. Two rules:
1. Specific, observable — not "performance regresses" but "p95 query
   latency on existing Cypher queries climbs above current baseline".
2. Tied to the metrics the existing system already measures — if a
   regression isn't visible in current dashboards/tests, the failure mode
   is invisible until customers complain.

Per-tier guidance on what to surface:

- **Tier A (additive)**: name the existing-system regression risks
  ("learned edges introduce false positives that pollute caller-callee
  analysis"; "trace ingestion increases write QPS to FalkorDB above
  capacity"). The risk is that the new layer hurts the unchanged base.
- **Tier B (substrate reuse, component replaced)**: name the lost-
  capability risks ("the new indexer doesn't capture private-symbol
  edges the old indexer did"; "schema migration drops fields the
  query layer expects"). The risk is the replaced component is
  silently weaker on some axis.
- **Tier C (substrate replacement)**: name the parity risks ("Datalog
  query latency on the existing 90th-percentile question set regresses
  vs the prior graph traversal"; "edge-case queries that used to return
  results return empty"). Substrate changes touch every downstream
  consumer.
- **Tier D (separate system)**: usually N/A — the incumbent isn't
  modified — but if there's any shared substrate (auth, logging,
  storage), name the contention.

A finding without Failure modes is incomplete: you have a forward
falsifier but no regression detection. The first time the spike makes
things worse on a metric you didn't think to watch, you find out from a
user.

### Verification (Step 6)
Filled in after Step 6 runs. See `references/verification.md` for the
5-check schema (URL health, attribution, popularity-bias, etc.).

## Worked examples

### Example 1: Tier A integration (additive, low blast radius)

```
### Finding 6: CupidCall / CFG+xRef GNN

**Source**: https://arxiv.org/abs/<arXiv ID>
**Paradigm distance**: 2/4 — differs on computation_model (learning vs traversal),
                        data_structure unchanged
**Implementation maturity**: prototype (research code on GitHub, no GA)
**Integration cost**: Tier A — graph stays a graph. Learned edges added with
                      `type=learned` label alongside static edges. FalkorDB
                      schema, MCP tool surface, and downstream consumers all
                      unchanged.

**Outcome (what we get)**:
  Predicted indirect-call edges fill cross-language and dynamic-dispatch gaps
  that static analysis returns zero on. Addresses F1 (Go↔Rust FFI: 0/12
  measured) and F2 (TS dynamic dispatch: 30% miss).

**Expected improvement**:
  - Friction addressed: F1, F2
  - Metric: F1 on indirect-call edge resolution
  - Baseline: 0/12 expected edges in fleet-mgr crate (F1); 30% miss rate on
    hand-annotated 100-call sample, claude-hud (F2)
  - Target: ≥80% F1 (precision and recall both ≥80%)
  - Confidence: medium
  - Source of estimate: CupidCall paper reports 95.2% F1 on similar-but-not-
    identical setup; conservative 80% target accounts for domain shift,
    which is why Confidence is medium not high.

**Test**:
  - Scenario: train GNN on Example monorepo's existing static graph + observed
    FFI edges from runtime samples. Predict indirect-call edges. Compare to
    hand-annotated 100-call sample.
  - Pass criterion: ≥80% F1 (precision and recall both ≥80%)
  - Method: extend existing hand-annotated test set (claude-hud + fleet-mgr);
    compute precision/recall against ground truth; A/B vs current static-only
    graph on the same questions.

**Failure modes (regression detection)**:
  - Learned edges introduce false-positive call edges that pollute existing
    caller-callee analysis: watch precision drop on the same hand-annotated
    sample on the SUBSET of edges that were already correct from static
    analysis. If learned + static < static-only on a hand-annotated subset,
    the model is replacing real edges with noise.
  - Training pipeline write-load to FalkorDB exceeds current capacity:
    monitor write QPS during edge backfill; cap at <50% of current peak.
```

### Example 2: Tier B structural change

```
### Finding 3: Stack Graphs (GitHub)

**Source**: https://github.com/github/stack-graphs
**Paradigm distance**: 3/4 — differs on computation_model (stitching vs
                       traversal), abstraction_level (scope vs symbol),
                       time_dynamics (incremental-per-file vs static-with-incremental)
**Implementation maturity**: production (GitHub Precise Code Nav)
**Integration cost**: Tier B — replaces SCIP indexer + name-resolution
                      semantics + symbol schema. Reuses FalkorDB storage,
                      MCP tool surface, and downstream consumers.

**Outcome (what we get)**:
  Per-file isolated subgraphs let multi-repo polyglot edits avoid full
  rebuild. Name resolution stitches at query time, so only changed files
  re-index. Addresses F3 (>10 min rebuild on 600K LOC).

**Expected improvement**:
  - Friction addressed: F3
  - Metric: incremental rebuild time on single-file edit in 600K LOC monorepo
  - Baseline: >10 min on 600K LOC monorepo for multi-repo polyglot edits
    (Phase 0 measurement — friction[F3].measured)
  - Target: <30 seconds
  - Confidence: high
  - Source of estimate: GitHub Precise Code Nav published rebuild
    characteristics — production system on similar polyglot scale, so
    Confidence is high.

**Test**:
  - Scenario: re-index one Example crate (fleet-mgr or a TS package) as a
    Stack Graphs subgraph. Edit one file. Trigger rebuild via existing CI path.
  - Pass criterion: rebuild <30s on edits that currently take >10 min in the
    monolithic indexer.
  - Method: time the existing CI rebuild path before vs after migration on
    the same set of edits. Measure 10 representative edits; report median +
    P95.

**Failure modes (regression detection)**:
  - Loss of cross-file symbol resolution that the SCIP indexer captured:
    run the existing 100-question architectural test set against the new
    Stack Graphs index; pass criterion is ≥95% answer parity. <95% means
    capability was silently lost in the indexer swap.
  - Per-file subgraphs grow unbounded for files with many cross-references:
    monitor per-file subgraph size during initial reindex; flag any file
    whose subgraph exceeds 10x the median.
  - Query-time stitching latency exceeds the prior traversal latency on
    common questions: P95 query latency on the existing test set must stay
    within 1.5x of the pre-migration baseline.
```

## Anti-patterns

- **Outcome as marketing**: "modern alternative to X" — replace with concrete
  workflow.
- **Improvement without baseline**: "should be faster" — pull baseline from
  Phase 0 friction by ID; copy `friction[Fn].measured` verbatim.
- **Test that requires waiting**: "monitor adoption over 6 months" — the test
  must run in the lab.
- **Pass criterion as "better"**: pin a numeric threshold or admit the
  finding isn't ready.
- **Skipped Integration cost field**: every finding gets Tier A/B/C/D.
  Without it the user can't compare adoption costs across paradigm-distinct
  candidates.
- **Skipped Failure modes**: every Tier B/C/D finding requires at least one
  regression-detection signal. Tier A strongly recommended.
- **Confidence overgrading**: "Confidence: high" when the Target is from a
  paper on different data is dishonest. Use medium with the caveat in
  Source of estimate.
