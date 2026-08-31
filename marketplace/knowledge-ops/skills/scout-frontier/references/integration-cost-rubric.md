# Integration cost rubric

A second axis orthogonal to paradigm distance. A finding can be paradigm-distant
(distance 4) and still a Tier A integration; it can be paradigm-near (distance 2)
and still a Tier C rewrite. Both axes matter for the adoption decision.

## Tier definitions

### Tier A — Integration on top
- The existing system stays intact. New components add data, edges, results,
  or queries to the existing substrate.
- Storage, schema, and external API surface are preserved.
- Rollback = remove the new component; nothing else changes.
- Risk: low (additions don't break existing consumers).
- Typical effort: days to weeks.
- Examples: GNN learned edges atop a static graph; runtime traces ingested
  into an existing graph as new edge types; separate analysis layer writing
  results back to the primary store; a sidecar service that consumes and
  enriches the existing data.

### Tier B — Structural change with substrate reuse
- One or more components replaced (indexer, query layer, schema definition).
- Storage substrate, external API surface, and downstream consumers preserved.
- Rollback = revert the replaced component; existing data still readable.
- Risk: medium (replaced component must be functionally equivalent or better
  on the metrics that matter).
- Typical effort: weeks to months.
- Examples: replacing a SCIP indexer with Stack Graphs while keeping the same
  graph storage and query API; swapping a tokenizer while keeping the same
  embedding pipeline; replacing a query optimizer while keeping the same SQL
  surface.

### Tier C — Fundamental architectural change
- Storage substrate, query language, or core schema replaced.
- External API surface may need new shape; downstream consumers may need
  to migrate.
- Rollback = restore from backup of prior substrate; partial migration is
  expensive.
- Risk: high (substrate replacement touches every layer).
- Typical effort: months.
- Examples: graph database → Datalog fact database; relational → graph;
  custom indexer → vendor-managed indexer; on-prem → cloud-native rewrite.

### Tier D — Separate system, not an integration
- Different question shape from the incumbent. The finding is not a
  replacement or addition to the incumbent — it answers a different
  question that happens to share keywords or domain.
- Belongs as a sibling tool/skill, not as a modification.
- Rollback = N/A; the system was never modified.
- Risk: deployment of a new tool, not modification of an existing one.
- Examples: byte-level taint analyzer alongside a structural code-graph;
  metrics dashboard alongside a logs index; threat-model tool alongside
  a vulnerability scanner.

## Tier criteria checklist

Use these questions to score a finding. The first NO determines the tier.

| # | Question | If NO, tier is |
|---|---|---|
| 1 | Does the finding answer the same question as the incumbent? | D |
| 2 | Can it run alongside the existing substrate without replacing it? | B or C (continue) |
| 3 | Does it preserve the existing storage substrate / API surface? | C |
| 4 | Does it require replacing one or more existing components (indexer, query layer, schema)? | A (all-yes path) |

If question 1 is YES, question 2 is YES, question 3 is YES, and question 4
is NO → **Tier A** (pure addition).

If question 1 is YES, question 2 is YES, question 3 is YES, and question 4
is YES → **Tier B** (component replaced, substrate kept).

If question 1 is YES, question 2 is NO or question 3 is NO → **Tier C**
(substrate replacement).

If question 1 is NO → **Tier D** (separate system).

## Examples (from 2026-04-27 code-graph scout)

| Finding | Paradigm distance | Integration tier | Why |
|---|---|---|---|
| CupidCall GNN learned edges | 2 | A | Train offline; predicted edges added to existing graph as new edge type. FalkorDB schema unchanged. |
| OTel eBPF runtime traces | 4 | A | New edge type from traces. Code-graph already has `ingest_traces` MCP tool — infrastructure exists. |
| Stack Graphs | 3 | B | Replaces SCIP indexer + name-resolution semantics. FalkorDB storage and MCP tool surface preserved. |
| Glean (Meta) | 3 | C | FalkorDB → Datalog fact database. Cypher → Angle. Indexer, storage, query all change. |
| CodeFuse-Query | 3 | C | Same shape as Glean — substrate replacement. |
| egglog | 2 | A | Deployed as separate analysis layer that writes results back to code-graph. |
| PolyTracker | 4 | D | Byte-level taint is a different question shape; belongs in a security skill, not code-graph. |

## When this rubric matters

The user's decision typically isn't "which paradigm is most distant" — it's
"which paradigm-distinct finding has the lowest cost to try." Tier A findings
are spike candidates (run in parallel, low rollback cost). Tier B/C findings
need their own dedicated experiments. Tier D findings get routed to a
different skill or backlog.

The Step 7 report sorts within each paradigm-distance tier by integration
cost (Tier A first), so the user sees the cheapest experiments first.
