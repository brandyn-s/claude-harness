# Code-Graph Property Extraction Fix + A/B Benchmark

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the Q10 benchmark failure (properties=null for Python/JS/TS/Go/Rust) so function signatures, parameter types, return types, and complexity metrics are populated in the graph.

**Architecture:** The C extraction infrastructure (`extract_defs.c`) already has `extract_param_names()`, `extract_param_types()`, `cbm_count_branching()`, and return type extraction. The Go pipeline (`pipeline_cbm.go`) already stores these in node `properties`. The problem is that specific languages' tree-sitter AST node types don't match the extraction patterns. Fix is per-language debugging, not new infrastructure.

**Tech Stack:** C (tree-sitter extraction), Go (pipeline + tests), SQLite (graph storage)

---

## Phase A: Baseline Measurement

### Task 1: Run A/B baseline benchmark (before changes)

**Files:**
- Read: `BENCHMARK.md`
- Read: `scripts/benchmark-index.sh`

**Step 1: Identify the benchmark repos and Q10 queries**

Read `BENCHMARK.md` to find which repos are used for benchmarking and what Cypher queries are used for Q10 (Properties).

**Step 2: Run Q10-equivalent query on an indexed repo**

Index a known repo (e.g., code-graph itself or a small Python project) and query properties:

```bash
# Via MCP (after session restart to load new binary):
# search_graph with label=Function, limit=10 — check if properties contain param_names, complexity
# query_graph with: MATCH (f:Function) WHERE f.name CONTAINS 'handle' RETURN f LIMIT 5
```

Record: how many functions have non-null `param_names`, `param_types`, `return_types`, `complexity`.

**Step 3: Document baseline**

Record Q10 pass rate per language before any changes. This is the number to beat.

**Step 4: Commit baseline**

No code changes — just record the baseline numbers in a `benchmarks/q10-baseline.md` file.

---

## Phase B: Debug Property Extraction per Language

### Task 2: Trace Python property extraction

**Files:**
- Read: `internal/cbm/extract_defs.c:533-637` (extract_param_names)
- Read: `internal/cbm/extract_defs.c:635-790` (extract_param_types)
- Read: `internal/cbm/lang_specs.c` (language-specific node type tables)
- Test: `internal/pipeline/cbm_debug_test.go`

**Step 1: Write a debug test that extracts a Python function**

Create a test file with a Python function that has typed parameters:

```python
def authenticate(username: str, password: str, mfa_token: Optional[str] = None) -> bool:
    """Authenticate a user."""
    if not username:
        return False
    return check_credentials(username, password)
```

Run the CBM extraction on this file and dump the `CBMDefinition` fields.

**Step 2: Check if tree-sitter Python grammar exposes parameter nodes**

The extraction functions iterate over child nodes looking for specific `ts_node_type` values. For Python, the parameter list is `parameters` containing `typed_parameter` children. Check if the C code's switch cases cover `CBM_LANG_PYTHON`.

**Step 3: Identify the specific mismatch**

The most likely issue: `extract_param_names` and `extract_param_types` have per-language switch statements that may not cover all languages, or the tree-sitter node type names may have changed between grammar versions.

Run:
```bash
go test ./internal/pipeline/ -run TestASTDump -v -count=1
```

This dumps the actual AST structure for each language, showing what node types exist.

**Step 4: Fix Python extraction if needed**

Update `extract_defs.c` to handle the specific Python parameter node types that are present in the tree-sitter AST but not matched by the extraction code.

**Step 5: Verify fix**

```bash
go test ./internal/cbm/ -run TestLSP -v -count=1
go test ./internal/pipeline/ -run TestLangParity -v -count=1 -run Python
```

### Task 3: Trace Go property extraction

Same process as Task 2 but for Go. Go has the LSP bridge so it should already work — verify.

**Step 1: Check if Go functions have param_names populated**

Run the existing LSP test:
```bash
go test ./internal/cbm/ -run TestStep0Wires -v -count=1
```

This test specifically checks `return_types` and `param_names` for Go functions.

### Task 4: Trace JavaScript/TypeScript property extraction

Same process as Task 2 but for JS/TS. Check if `formal_parameters` → `required_parameter` / `optional_parameter` node types are handled.

### Task 5: Trace Rust property extraction

Same process. Rust uses `parameters` → `parameter` with `type_identifier` children.

---

## Phase C: Fix and Verify

### Task 6: Apply fixes and run language parity tests

After fixing each language's extraction:

```bash
# Full language parity test (125+ cases across all languages)
go test ./internal/pipeline/ -run TestLangParity -v -count=1

# Full test suite
go test ./... -count=1
```

### Task 7: Run Q10 post-fix benchmark

**Step 1: Reindex the benchmark repo**

Using the fixed binary, reindex the same repo used in Task 1.

**Step 2: Run the same Q10 query**

Record: how many functions now have non-null `param_names`, `param_types`, `return_types`, `complexity`.

**Step 3: Compare before/after**

```
Q10 PROPERTY EXTRACTION A/B COMPARISON

| Language | Before (properties non-null) | After | Delta |
|----------|----------------------------|-------|-------|
| Python   | 0%                          | ?%    | ?     |
| Go       | ?%                          | ?%    | ?     |
| JS/TS    | 0%                          | ?%    | ?     |
| Rust     | 0%                          | ?%    | ?     |
```

### Task 8: Build and deploy new binary

```bash
cd $HOME/Documents/GitHub/code-graph
CGO_ENABLED=1 go build -o C:/Users/you/bin/codebase-memory-mcp-new.exe ./cmd/codebase-memory-mcp/

# Kill old processes
taskkill /F /PID $(tasklist | grep codebase-memory | awk '{print $2}')

# Swap
mv ~/bin/codebase-memory-mcp.exe ~/bin/codebase-memory-mcp-old.exe
mv ~/bin/codebase-memory-mcp-new.exe ~/bin/codebase-memory-mcp.exe
rm ~/bin/codebase-memory-mcp-old.exe
```

---

## Phase D: Ship

### Task 9: Commit and PR

```bash
cd $HOME/Documents/GitHub/code-graph
git checkout -b fix/property-extraction
git add internal/cbm/extract_defs.c internal/pipeline/ internal/cbm/
git commit -m "fix: populate param_names, param_types, return_types, complexity for Python/JS/TS/Go/Rust"
git push -u origin fix/property-extraction
gh pr create --title "fix: Q10 property extraction for 5 languages" --body "..."
gh pr merge --auto --squash --delete-branch --repo example-apps-org/code-graph
```

---

## Key Implementation Notes

- The C extraction infrastructure (`extract_param_names`, `extract_param_types`, `cbm_count_branching`) ALREADY EXISTS in `extract_defs.c`
- The Go pipeline (`pipeline_cbm.go:117-148`) ALREADY stores these in node properties
- The problem is likely per-language tree-sitter node type mismatches in the C switch statements
- `extract_param_names` (line 535) and `extract_param_types` (line 637) have language-specific logic
- `cbm_count_branching` counts `if`, `for`, `while`, `match`, `case` etc. node types per language
- The BENCHMARK.md Q10 query is the acceptance test — PARTIAL→PASS is the goal
- DO NOT add new infrastructure — debug and fix what exists
