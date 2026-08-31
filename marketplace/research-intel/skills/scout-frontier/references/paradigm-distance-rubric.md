# Paradigm-Distance Rubric

A finding is **paradigm-distinct** if it differs from the incumbent on at least one of four axes.

## Four axes

### 1. data_structure
Primary backing structure for queries.
Values: graph, vector, tree, log, table, execution-tree, structured-index, fact-database, stream

### 2. computation_model
How queries are answered.
Values: lookup, traversal, learning, lm-inference, datalog-inference, simulation, stitching, abstract-interpretation

### 3. abstraction_level
Granularity of indexed entities.
Values: token, symbol, ast, scope, type, behavior, intent

### 4. time_dynamics
When and how the index is built/updated.
Values: static, static-with-incremental, incremental-per-file, streaming, runtime-traced, path-sensitive

## Distance calculation

`distance = count of axes where finding != incumbent`

- **0** = paradigm-similar (same approach)
- **1** = single-axis variation
- **2-3** = clear paradigm shift
- **4** = orthogonal approach

## Worked examples (incumbent: code-graph = graph + traversal + symbol + static-with-incremental)

- **Stack Graphs** (graph, stitching, scope, incremental-per-file): distance 3
- **SCIP/LSIF** (structured-index, lookup, symbol, static-with-incremental): distance 2
- **Glean** (fact-database, datalog-inference, symbol, static): distance 3
- **GNN call resolution** (graph, learning, symbol, static): distance 2
- **LLM-as-oracle** (graph, lm-inference, symbol, static-with-incremental): distance 1
- **KLEE/symbolic execution** (execution-tree, simulation, behavior, path-sensitive): distance 4
- **tokensave/srclight peers** (graph, traversal, symbol, static-with-incremental): distance 0

## Edge cases

**Hybrid systems**: pick the dominant primitive (the one driving user-facing query semantics). RAG-over-code with embeddings as primary lookup → vector. Graph as primary, embeddings as side-channel → graph.

**Industrial vs research**: score on demonstrably implemented capabilities, not paper claims. A GNN paper that only evaluates on Java doesn't count as a multi-language system.

## Anti-patterns

- Score by features (RRF, multi-repo, dashboard) — those are /scout territory
- Score by language/runtime/license — implementation details, not paradigm
- Conflate distance with quality — orthogonal axes
- Score on what could exist — only on what is implemented
