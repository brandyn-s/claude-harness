# Oracle design — graph extraction

> Phase 1 reference for measurement projects in the **graph-extraction** class: call edges, import graphs, type relationships, dataflow edges, dependency graphs. Reference implementation: code-graph (163 PRs, Mar 14 – May 2 2026).

## What you're measuring

Edge-level correctness of an extracted graph:
- **Precision**: of the edges your system emits, how many exist in ground truth?
- **Recall**: of the edges in ground truth, how many did your system emit?
- **F1**: harmonic mean

Edge types vary by project — call edges (function A calls function B), import edges (module M imports module N), inheritance edges, dataflow edges, etc. The recipe is the same regardless of edge type; the oracle changes.

## The two-source pattern

The system under measurement uses one parser/resolver. The oracle uses an independent parser/resolver. When they disagree, you have either a system error or an oracle error. Sample the disagreements (Phase 9 / Step 6) to classify.

**Why independence matters**: code-graph uses tree-sitter, which has no type information. The oracles use compiler frontends *with* type information. The two sources have orthogonal strengths and weaknesses; their disagreement is information.

If the system and oracle share a parser stack (e.g., both use tree-sitter, both use the same AST library), you've built a tautology. The oracle has to be more correct, which means it has to know things the system doesn't know.

## Oracle source by language

For call edges specifically:

| Language | Oracle | Notes |
|---|---|---|
| Python | PyCG | call-graph generation with type inference |
| Rust | syn + custom resolver | Rust has no compiler-as-library equivalent of PyCG; build resolver on syn AST + trait/impl tracking |
| Go | go-callgraph (golang.org/x/tools/cmd/callgraph) | uses go/types for type-resolved call edges |
| JavaScript / TypeScript | ts-morph + tsc | TypeScript compiler API; for JS, fall back to type inference quality of TS |
| Java | javac AST + Spoon | bytecode call analysis via ASM as alternative |
| C / C++ | clang AST + libclang | requires compilation database (`compile_commands.json`) |

For import / dependency edges: usually language-native tooling (e.g., `cargo metadata` for Rust, `go list` for Go, `pip show` / `importlib` for Python).

For type relationships (inheritance, trait/interface implementation): same source as call edges, different traversal of the resolved AST.

## Oracle reliability characteristics

Each oracle has known failure modes you should document at Phase 1:

- **PyCG**: misses dynamic dispatch through `getattr` / `globals()`; under-resolves decorators with metaprogramming.
- **syn-based Rust resolver**: bare-name conflation when multiple definitions in the project share a last-segment name (e.g., `call`, `run`, `get_result`). Code-graph's PR #163 fixed this by dropping bare-name resolutions only when the bare name has multiple definitions; single-def names still resolve cleanly. **The oracle had the same bare-name conflation pattern code-graph's discrimination ladder was built to prevent — five recurrences across instrument-vs-system bug classification.**
- **go-callgraph**: misses interface dispatch when interface satisfaction is computed lazily; over-conservative on closures.
- **ts-morph**: requires `tsconfig.json` to resolve module specifiers; fails on JS-only projects without TypeScript declarations.

**The oracle is not ground truth — it's a more-likely-correct second opinion.** This is why Phase 9 cell verification matters: every "system bug" cell could be an oracle bug. Five recurrences in code-graph alone.

## Stratification dimensions for graph extraction

Code-graph emits these on every edge measurement:

- **caller_node_kind**: function-body / method-body / test-body / package-init-block / closure / async-block
- **resolver_rule**: which path through the resolver fired (exact-qn-match, same-package-shadow, cross-package-heuristic, type-discrimination, import-binding-discrimination, etc.)
- **candidate_set_size**: 1 / 2 / 3 / ≥4 — how many internal candidates matched the call's bare name before discrimination
- **confidence_band**: high / medium / low — emitted with the edge to support two-operating-point reporting

Plus per-edge:
- **edge_type**: CALLS / CALLS_EXTERNAL / CALLS_PSEUDO / IMPORTS / IMPLEMENTS / DEFINES_METHOD (split per code-graph PR #121)
- **fixture / project / language** — the natural subdivision dimensions

These dimensions combine into the contingency table that `/plateau-diagnose` Step 5 reads. The 62-percentage-point gap between unambiguous (82% correct) and ambiguous (20% correct) call sites was visible only because `candidate_set_size` was a stratification dimension.

## Tiny known-truth fixture for graph extraction

Build a single-file fixture with hand-enumerable edges:

- 5-10 functions with explicit call relationships
- Hand-enumerate every (caller, callee) edge
- Run system + oracle against the fixture
- Verify FP=FN=0 for both system and oracle on this fixture

If the oracle has FN > 0 on the tiny fixture, the oracle is broken. Fix the oracle first before measuring system against it.

## Synthetic negative fixtures for graph extraction

Code-graph's Era 6 set: 4 hand-built Rust fixtures, each isolating ONE phantom co-hallucination pattern:

1. **rust-actix-data**: receiver-type discrimination — `let metrics: MetricsCollector = ...; metrics.record(...)` should NOT bind to other `record()` methods in the project.
2. **rust-diesel**: function-scoped `use` declarations — `fn entry(conn: &mut PgConnection) { use schema::users::dsl::users; users.execute(conn) }` should resolve `users` correctly inside the function scope only.
3. **rust-futures-ready**: import-binding discrimination for free-function calls — `use futures_util::future::ready; ready(42)` should NOT bind to internal `*::ready` functions.
4. **rust-restate-chain**: external-type-receiver passthrough — `ctx: Context` parameter where `Context` is external; subsequent `ctx.run().invocation().target().send()` should NOT bind to internal methods.

Each fixture targets one resolver path. Each is <50 lines. Each fails in a measurable, distinct way under a system without the corresponding fix. The set is a regression suite for resolver mechanism correctness.

For a new graph-extraction project, design synthetic fixtures by:
1. Listing the resolver paths your system has (each rule, each fallback heuristic)
2. For each path, design the smallest input that exercises ONLY that path
3. For each path, design the smallest input that should NOT trigger it but might

## Truncation audit for graph extraction

Per code-graph PRs #64-65, the canonical incident:

- **MCP `query_graph` tool**: defaulted to 200 rows. Harness's `compare.py` retrieved 400 of ~2000 CALLS edges, reported recall=0.20. Real recall after fix was 0.98. **78pp error was 100% instrument.**
- **Fix**: tool now returns `Truncated bool` and `EffectiveCap int` in result; SQL fetches `limit + 1` so truncation is detectable.

Audit checklist for graph-extraction harness:
- SQL queries fetching edges (default LIMIT? Compare to `COUNT(*)` of underlying query.)
- MCP tools returning edges (max_rows? page_size? pagination signal?)
- Subprocess CLIs (oracle binaries — do they have `--limit` defaults?)
- Result formatters (truncation in output stage)

## Freshness gate for graph extraction

Code-graph's `check_index_freshness` (PR #145) compares project DB mtime to binary mtime. Generalizes to:

- **Project index** (DB mtime) vs **harness binary** (binary mtime) — if binary is newer than index, the index was built with an older resolver and may produce different edges than the current binary would.
- **Source SHA** vs **baseline SHA** — measurement on different SHAs is invalid for comparison.
- **Oracle version** — pinned in baseline file.

PR #144's revert (PR #145) was caused by missing this gate: shipped a fix measured against stale per-subset DBs, fix inverted on fresh DBs because Janusian penalty (#135) had shipped between measurements. Stale-index check makes that class of failure visible.

## Cross-language fixture organization

Code-graph's fixture set is organized as `harness/fixtures/<language>/<repo>` with a frozen SHA per fixture. Per-language F1 computation enables stratification by language without crossing project boundaries. Aggregate F1 across languages can hide single-language regression — always report per-fixture and per-language alongside aggregate.

## Code-graph stratification incident (illustrative)

The Era 5 PR #135 ("Janusian penalty") used these stratification dimensions:
- candidate_set_size {1, 2, 3+}
- resolver_rule {exact-qn-match, cross-package-heuristic, ...}

The plateau-diagnose Step 5 cell was: `candidate_set_size ≥ 2` AND `resolver_rule = cross-package-heuristic`. That cell held 20% of the failure mass and resolved correctly only 20% of the time (vs 82% baseline). Without the stratification, the failure mass was hidden in aggregate F1 = 0.890.

The lesson for any graph-extraction project: stratify by the dimensions of your resolver's decision tree. If your resolver branches on N inputs (call shape, available type info, import context), each branch is a stratification dimension. The cell where one branch underperforms is the next fix target.

## Related code-graph artifacts

- `harness/` directory — fixture management, baseline files, comparison scripts
- `internal/store/` — edge storage and retrieval (the truncation audit started here)
- `internal/resolver/` — discrimination ladder (4 tiers, shared CallContext)
- PR #121 — CALLS modal split (precision win)
- PR #123 — Go method QN qualification (precision win)
- PR #135 — Janusian penalty (stratification-driven fix)
- PR #140 — oracle Y.5 fix (instrument bug, +8.7pp F1)
- PRs #145-148 — stale-index gate
- PRs #158-163 — discrimination ladder consolidation, oracle bare-name fix
