# Code-Search & Code-Graph: Rename + Optimization Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename local directories to match their GitHub repo names, then optimize code-search with the same techniques that improved memory-search (0.82 HR → 0.97 HR).

**Architecture:** Two independent repos. code-search is a Python MCP server (hybrid vector+BM25 search via FAISS/FTS5, Voyage AI embeddings). code-graph is a Go MCP server (tree-sitter AST → SQLite knowledge graph with Cypher queries). Both are forks maintained in example-apps-org.

**Tech Stack:** Python 3.12 (code-search), Go 1.26 (code-graph), pytest, `go test`, FAISS, FTS5, Voyage AI API

---

## Part A: Renames (Both Repos)

### Task 1: Rename claude-context-local directory to code-search

The GitHub repo is already named `example-apps-org/code-search`. The local clone at `$HOME/Documents/GitHub/claude-context-local` should match.

**Files:**
- Modify: `$HOME/Documents/GitHub/claude-context-local/pyproject.toml` (project name)

**Step 1: Close any running code-search MCP server**

The MCP server has a file lock on the venv. Verify no Python processes hold locks.

Run: `tasklist | grep -i pythonw`

If the code-search server PID is running, it will be killed when Claude Code restarts. Proceed — the rename happens outside the session.

**Step 2: Rename the directory**

Run:
```bash
mv "$HOME/Documents/GitHub/claude-context-local" \
   "$HOME/Documents/GitHub/code-search"
```

**Step 3: Update pyproject.toml project name**

In `$HOME/Documents/GitHub/code-search/pyproject.toml`, change:
```toml
name = "claude-context-local"
```
to:
```toml
name = "code-search"
```

**Step 4: Update MCP server config in ~/.claude.json**

The `code-search` entry's `command` and `args` reference the old path. Update:
```json
"code-search": {
  "command": "$HOME/Documents/GitHub/code-search/.venv/Scripts/pythonw.exe",
  ...
}
```

Use Python atomic read-modify-write (don't use Edit tool on .claude.json — process races):
```python
import json, pathlib
p = pathlib.Path.home() / ".claude.json"
cfg = json.loads(p.read_text(encoding="utf-8"))
srv = cfg["mcpServers"]["code-search"]
# Update command path
srv["command"] = srv["command"].replace("claude-context-local", "code-search")
# Update any args that reference the old path
if "args" in srv:
    srv["args"] = [a.replace("claude-context-local", "code-search") for a in srv["args"]]
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
```

**Step 5: Update session-start.py path reference**

In `~/.claude/hooks/session-start.py` line ~902, change:
```python
Path.home() / "Documents" / "GitHub" / "claude-context-local",
```
to:
```python
Path.home() / "Documents" / "GitHub" / "code-search",
```

**Step 6: Update protected-repos.json**

In `~/.claude/hooks/protected-repos.json`, the `names` array has `"claude-context-local"` and the `remotes` mapping has `"claude-context-local": "example-apps-org/code-search"`. Update:
```json
{
  "names": ["code-search"],
  "remotes": {
    "code-search": "example-apps-org/code-search"
  }
}
```
Remove the duplicate `"claude-context-local"` entries.

**Step 7: Update repo-map.md**

In `~/.claude/skills/_shared/repo-map.md`, update the code-search row's local path:
```
| code-search | example-apps-org/code-search | `$HOME/Documents/GitHub/code-search` | Fork of FarhanAliRaza/claude-context-local; use `--repo example-apps-org/code-search` with all `gh pr` commands |
```

**Step 8: Update git-hygiene.md clone locations**

In `~/.claude/rules/git-hygiene.md`, update the clone location comment:
```
claude-context-local → $HOME/Documents/GitHub/code-search
```
Change to:
```
code-search         → $HOME/Documents/GitHub/code-search
```

**Step 9: Verify git remote still works**

Run:
```bash
cd $HOME/Documents/GitHub/code-search && git remote -v && git fetch origin
```
Expected: remote points to `example-apps-org/code-search.git`, fetch succeeds.

**Step 10: Commit pyproject.toml change**

Run:
```bash
cd $HOME/Documents/GitHub/code-search
git checkout -b chore/rename-project-name
git add pyproject.toml
git commit -m "chore: rename project from claude-context-local to code-search"
git push -u origin chore/rename-project-name
gh pr create --title "chore: rename project to code-search" --body "Aligns pyproject.toml name with GitHub repo name." --repo example-apps-org/code-search
gh pr merge --auto --squash --delete-branch --repo example-apps-org/code-search
```

---

### Task 2: Rename codebase-memory-mcp directory to code-graph

The GitHub repo is already named `example-apps-org/code-graph`. The local clone at `$HOME/Documents/GitHub/codebase-memory-mcp` should match.

**Step 1: Rename the directory**

Run:
```bash
mv "$HOME/Documents/GitHub/codebase-memory-mcp" \
   "$HOME/Documents/GitHub/code-graph"
```

**Step 2: Update repo-map.md**

In `~/.claude/skills/_shared/repo-map.md`, update the code-graph row:
```
| code-graph | example-apps-org/code-graph | `$HOME/Documents/GitHub/code-graph` | |
```

**Step 3: Update git-hygiene.md clone locations**

No existing entry for codebase-memory-mcp in git-hygiene.md, but if one exists, update it.

**Step 4: Verify git remote still works**

Run:
```bash
cd $HOME/Documents/GitHub/code-graph && git remote -v && git fetch origin
```

**Step 5: Note — Go module path stays as-is**

The Go module path in `go.mod` is `github.com/DeusData/codebase-memory-mcp`. Changing this would break all import paths across 80+ Go files. The binary name `codebase-memory-mcp.exe` is built from `cmd/codebase-memory-mcp/main.go`. **Do not rename the Go module or binary** — the directory rename is sufficient for human navigation. The MCP server name in `.claude.json` is already `code-graph`.

---

## Part B: Code-Search Optimizations

### Task 3: Add query embedding LRU cache

The biggest single performance win from memory-search. Each identical query re-embeds via Voyage API. An LRU cache on the embedder eliminates redundant API calls.

**Files:**
- Modify: `code-search/mcp_server/code_search_server.py:237-253` (searcher property)
- Modify: `code-search/search/searcher.py:178-184` (IntelligentSearcher.__init__)
- Test: `code-search/tests/unit/test_query_cache.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/test_query_cache.py`:
```python
"""Tests for query-level result caching."""
import pytest
from unittest.mock import MagicMock, patch
from search.searcher import IntelligentSearcher


def test_identical_queries_use_cache(tmp_path):
    """Second identical query should not call embedder again."""
    mock_index = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1] * 768

    # Mock the index manager to return empty results
    mock_index.search_similar.return_value = []
    mock_index.bm25_search.return_value = []

    searcher = IntelligentSearcher(mock_index, mock_embedder)

    # First call
    searcher.search(query="find authentication handler", k=5)
    first_call_count = mock_embedder.embed_query.call_count

    # Second identical call
    searcher.search(query="find authentication handler", k=5)
    second_call_count = mock_embedder.embed_query.call_count

    # Embedder should NOT be called again for the same query
    assert second_call_count == first_call_count, (
        f"Embedder called {second_call_count - first_call_count} extra times for cached query"
    )


def test_different_queries_bypass_cache(tmp_path):
    """Different queries should each call embedder."""
    mock_index = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1] * 768
    mock_index.search_similar.return_value = []
    mock_index.bm25_search.return_value = []

    searcher = IntelligentSearcher(mock_index, mock_embedder)

    searcher.search(query="find auth handler", k=5)
    searcher.search(query="database connection pool", k=5)

    assert mock_embedder.embed_query.call_count == 2


def test_cache_cleared_on_reindex(tmp_path):
    """Cache should be invalidated when index changes."""
    mock_index = MagicMock()
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1] * 768
    mock_index.search_similar.return_value = []
    mock_index.bm25_search.return_value = []

    searcher = IntelligentSearcher(mock_index, mock_embedder)

    searcher.search(query="find auth handler", k=5)
    searcher.clear_cache()
    searcher.search(query="find auth handler", k=5)

    # Should call embedder twice — cache was cleared
    assert mock_embedder.embed_query.call_count == 2
```

**Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_query_cache.py -v`
Expected: FAIL — `IntelligentSearcher.search` doesn't exist yet or cache not implemented.

**Step 3: Implement query embedding cache**

In `search/searcher.py`, modify `IntelligentSearcher.__init__` (~line 181):
```python
def __init__(self, index_manager: CodeIndexManager, embedder: CodeEmbedder):
    self.index_manager = index_manager
    self.embedder = embedder
    self._logger = logging.getLogger(__name__)
    self._query_embedding_cache: Dict[str, Any] = {}  # query -> embedding
    self._search_result_cache: Dict[str, Any] = {}    # (query, k, mode) -> results
```

Add cache lookup in the search method (the method that calls `self.embedder.embed_query()`). Before embedding:
```python
cache_key = query.strip().lower()
if cache_key in self._query_embedding_cache:
    query_embedding = self._query_embedding_cache[cache_key]
else:
    query_embedding = self.embedder.embed_query(query)
    self._query_embedding_cache[cache_key] = query_embedding
```

Add cache clear method:
```python
def clear_cache(self):
    """Clear query and result caches (call after reindex)."""
    self._query_embedding_cache.clear()
    self._search_result_cache.clear()
```

**Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_query_cache.py -v`
Expected: PASS

**Step 5: Wire cache invalidation to reindex**

In `mcp_server/code_search_server.py`, after any successful reindex completes (in `index_directory` method, after the indexing job finishes), add:
```python
if self._searcher:
    self._searcher.clear_cache()
```

**Step 6: Update cache_hit TODO**

In `code_search_server.py:387`, replace:
```python
cache_hit=False,  # TODO: detect from embedder cache
```
with:
```python
cache_hit=cache_key in searcher._query_embedding_cache if hasattr(searcher, '_query_embedding_cache') else False,
```
(Set `cache_key = query.strip().lower()` earlier in the method.)

**Step 7: Commit**

```bash
git checkout -b feat/query-embedding-cache
git add search/searcher.py mcp_server/code_search_server.py tests/unit/test_query_cache.py
git commit -m "feat: add query embedding LRU cache to eliminate redundant Voyage API calls"
```

---

### Task 4: Add embedding content-hash cache for reindexing

Full reindex re-embeds every chunk even if content is unchanged. Cache embeddings by content hash.

**Files:**
- Modify: `code-search/search/indexer.py:152-214` (add_embeddings)
- Modify: `code-search/search/incremental_indexer.py:216-239` (_full_index batch loop)
- Test: `code-search/tests/unit/test_embedding_cache.py` (new)

**Step 1: Write the failing test**

Create `tests/unit/test_embedding_cache.py`:
```python
"""Tests for embedding content-hash cache."""
import hashlib
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from search.incremental_indexer import IncrementalIndexer


def test_unchanged_chunks_skip_embedding():
    """Chunks with cached content hashes should not be re-embedded."""
    mock_embedder = MagicMock()
    mock_embedding = np.random.rand(768).astype(np.float32)
    mock_embedder.embed_chunks.return_value = [mock_embedding]

    indexer = IncrementalIndexer.__new__(IncrementalIndexer)
    indexer._embedding_cache = {}

    content = "def hello(): pass"
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    # Pre-populate cache
    indexer._embedding_cache[content_hash] = mock_embedding

    # Should return cached embedding without calling embedder
    result = indexer._get_or_embed(content, content_hash, mock_embedder)
    assert np.array_equal(result, mock_embedding)
    mock_embedder.embed_chunks.assert_not_called()


def test_new_chunks_embed_and_cache():
    """New chunks should embed via API and store in cache."""
    mock_embedder = MagicMock()
    mock_embedding = np.random.rand(768).astype(np.float32)
    mock_embedder.embed_chunks.return_value = [mock_embedding]

    indexer = IncrementalIndexer.__new__(IncrementalIndexer)
    indexer._embedding_cache = {}

    content = "def new_function(): return 42"
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    result = indexer._get_or_embed(content, content_hash, mock_embedder)
    assert np.array_equal(result, mock_embedding)
    assert content_hash in indexer._embedding_cache
    mock_embedder.embed_chunks.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_embedding_cache.py -v`
Expected: FAIL — `_get_or_embed` and `_embedding_cache` don't exist.

**Step 3: Implement content-hash embedding cache**

In `search/incremental_indexer.py`, add to `__init__`:
```python
self._embedding_cache: Dict[str, np.ndarray] = {}  # content_hash -> embedding vector
```

Add helper method:
```python
def _get_or_embed(self, content: str, content_hash: str, embedder) -> np.ndarray:
    """Return cached embedding or embed and cache."""
    if content_hash in self._embedding_cache:
        return self._embedding_cache[content_hash]
    result = embedder.embed_chunks([content])[0]
    self._embedding_cache[content_hash] = result
    return result
```

Modify the batch embedding loop in `_full_index` (lines ~216-239) to check the cache before calling `embed_chunks_grouped()`. For each chunk in the batch, compute `hashlib.sha256(chunk.content.encode()).hexdigest()` and check the cache. Only embed uncached chunks.

**Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_embedding_cache.py -v`
Expected: PASS

**Step 5: Persist cache to disk**

Add save/load using `sqlite3` or `pickle` at `{index_dir}/embedding_cache.pkl`. Load on init, save after each batch.

```python
import pickle

def _load_embedding_cache(self):
    cache_path = Path(self._index_dir) / "embedding_cache.pkl"
    if cache_path.exists():
        with open(cache_path, "rb") as f:
            self._embedding_cache = pickle.load(f)
    else:
        self._embedding_cache = {}

def _save_embedding_cache(self):
    cache_path = Path(self._index_dir) / "embedding_cache.pkl"
    with open(cache_path, "wb") as f:
        pickle.dump(self._embedding_cache, f)
```

**Step 6: Commit**

```bash
git add search/incremental_indexer.py tests/unit/test_embedding_cache.py
git commit -m "feat: content-hash embedding cache to skip re-embedding unchanged chunks"
```

---

### Task 5: Add golden test set evaluation framework

Port the memory-search evaluation pattern. Create a golden set of code search queries with known-good file targets.

**Files:**
- Create: `code-search/benchmarks/golden_test_set.json`
- Create: `code-search/benchmarks/evaluate.py`
- Test: Built into evaluate.py (self-contained)

**Step 1: Create golden test set**

Create `benchmarks/golden_test_set.json` with 30 queries targeting the most common code-search use cases. Each query has `expected_files` (at least one file that MUST appear in results):

```json
[
  {
    "query": "reciprocal rank fusion search",
    "expected_files": ["search/searcher.py"],
    "category": "algorithm"
  },
  {
    "query": "incremental indexing merkle tree",
    "expected_files": ["search/incremental_indexer.py"],
    "category": "architecture"
  },
  {
    "query": "tree-sitter python chunker",
    "expected_files": ["chunking/languages/python_chunker.py"],
    "category": "component"
  },
  {
    "query": "FAISS vector index creation",
    "expected_files": ["search/indexer.py"],
    "category": "component"
  },
  {
    "query": "BM25 keyword search FTS5",
    "expected_files": ["search/indexer.py"],
    "category": "algorithm"
  },
  {
    "query": "MCP tool definitions search_code",
    "expected_files": ["mcp_server/code_search_mcp.py"],
    "category": "tool-find"
  },
  {
    "query": "voyage embedding provider",
    "expected_files": ["embeddings/embedding_model.py"],
    "category": "component"
  },
  {
    "query": "code domain synonym expansion",
    "expected_files": ["search/searcher.py"],
    "category": "algorithm"
  },
  {
    "query": "cross-encoder reranker model",
    "expected_files": ["search/reranker.py"],
    "category": "component"
  },
  {
    "query": "snapshot change detection merkle",
    "expected_files": ["merkle/change_detector.py"],
    "category": "architecture"
  }
]
```

Expand to 30 queries covering: algorithm, component, tool-find, architecture, debugging.

**Step 2: Create evaluation script**

Create `benchmarks/evaluate.py`:
```python
"""Golden test set evaluation for code-search retrieval quality."""
import json
import sys
import time
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.code_search_server import CodeSearchServer


def evaluate_golden(golden_path: str, project_path: str, k: int = 5):
    """Run golden test set and compute HR@k, P@k, MRR."""
    with open(golden_path, encoding="utf-8") as f:
        golden = json.load(f)

    server = CodeSearchServer()
    server.ensure_project_indexed(project_path)

    hits = 0
    precision_sum = 0.0
    mrr_sum = 0.0
    total = len(golden)
    category_stats = {}

    for entry in golden:
        query = entry["query"]
        expected = set(entry["expected_files"])
        category = entry.get("category", "unknown")

        t0 = time.time()
        raw = server.search_code(query=query, k=k)
        latency = (time.time() - t0) * 1000

        results = json.loads(raw).get("results", [])
        result_files = [r.get("relative_path", r.get("file", "")) for r in results]

        # Hit Rate@k: did ANY expected file appear in top k?
        hit = any(f in expected for f in result_files[:k])
        hits += int(hit)

        # Precision@k: what fraction of top k results are relevant?
        relevant_count = sum(1 for f in result_files[:k] if f in expected)
        precision = relevant_count / k
        precision_sum += precision

        # MRR: reciprocal rank of first relevant result
        rr = 0.0
        for rank, f in enumerate(result_files[:k], 1):
            if f in expected:
                rr = 1.0 / rank
                break
        mrr_sum += rr

        # Per-category tracking
        if category not in category_stats:
            category_stats[category] = {"hits": 0, "total": 0, "mrr_sum": 0.0}
        category_stats[category]["total"] += 1
        category_stats[category]["hits"] += int(hit)
        category_stats[category]["mrr_sum"] += rr

        status = "HIT" if hit else "MISS"
        print(f"  [{status}] {query} -> {result_files[:3]} ({latency:.0f}ms)")

    hr = hits / total
    precision = precision_sum / total
    mrr = mrr_sum / total

    print(f"\n{'='*60}")
    print(f"Hit Rate@{k}: {hr:.3f} ({hits}/{total})")
    print(f"Precision@{k}: {precision:.3f}")
    print(f"MRR: {mrr:.3f}")
    print(f"\nPer-category:")
    for cat, stats in sorted(category_stats.items()):
        cat_hr = stats["hits"] / stats["total"]
        cat_mrr = stats["mrr_sum"] / stats["total"]
        print(f"  {cat}: HR={cat_hr:.3f} MRR={cat_mrr:.3f} ({stats['hits']}/{stats['total']})")

    return {"hr": hr, "precision": precision, "mrr": mrr}


if __name__ == "__main__":
    project = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent.parent)
    golden = str(Path(__file__).parent / "golden_test_set.json")
    evaluate_golden(golden, project)
```

**Step 3: Run initial baseline**

Run: `.venv/Scripts/python.exe benchmarks/evaluate.py .`

Record baseline HR@5, P@5, MRR. These are the numbers to beat.

**Step 4: Commit**

```bash
git add benchmarks/
git commit -m "feat: add golden test set evaluation framework (30 queries, HR/P/MRR)"
```

---

### Task 6: RRF parameter sweep

Use the evaluation framework to find optimal RRF parameters.

**Files:**
- Create: `code-search/benchmarks/rrf_sweep.py`

**Step 1: Create sweep script**

Create `benchmarks/rrf_sweep.py`:
```python
"""RRF parameter sweep using golden test set."""
import os
import json
import sys
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).parent.parent))
from benchmarks.evaluate import evaluate_golden

VECTOR_WEIGHTS = [0.3, 0.4, 0.5, 0.6, 0.7]
K_VALUES = [20, 40, 60, 80]

results = []
golden = str(Path(__file__).parent / "golden_test_set.json")
project = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent.parent)

for vw, k in product(VECTOR_WEIGHTS, K_VALUES):
    os.environ["VECTOR_WEIGHT"] = str(vw)
    os.environ["BM25_WEIGHT"] = str(1.0 - vw)
    os.environ["FUSION_K"] = str(k)

    print(f"\n--- vw={vw}, bm25w={1-vw:.1f}, k={k} ---")
    metrics = evaluate_golden(golden, project, k=5)
    results.append({"vw": vw, "bm25w": round(1-vw, 1), "k": k, **metrics})

# Sort by composite score (0.4*HR + 0.3*P + 0.3*MRR)
results.sort(key=lambda r: 0.4*r["hr"] + 0.3*r["precision"] + 0.3*r["mrr"], reverse=True)

print(f"\n{'='*70}")
print(f"{'vw':>4} {'bm25w':>5} {'k':>3} | {'HR@5':>6} {'P@5':>6} {'MRR':>6} | {'composite':>9}")
print(f"{'-'*70}")
for r in results:
    comp = 0.4*r["hr"] + 0.3*r["precision"] + 0.3*r["mrr"]
    print(f"{r['vw']:>4.1f} {r['bm25w']:>5.1f} {r['k']:>3} | {r['hr']:>6.3f} {r['precision']:>6.3f} {r['mrr']:>6.3f} | {comp:>9.3f}")
```

**Step 2: Run the sweep**

Run: `.venv/Scripts/python.exe benchmarks/rrf_sweep.py .`

This tests 20 combinations (5 weights x 4 k values). Pick the winner.

**Step 3: Apply winning parameters**

Update `search/searcher.py` default FUSION_K and CONTENT_MODE_WEIGHTS with the winning values.

**Step 4: Commit**

```bash
git add benchmarks/rrf_sweep.py search/searcher.py
git commit -m "feat: RRF parameter sweep — apply optimal vw/k from golden eval"
```

---

### Task 7: Evaluate reranker on/off

memory-search found reranking HURTS when domain-specific boosts already produce good ranking. Test this for code-search.

**Files:**
- No new files — use existing evaluation framework

**Step 1: Run eval with reranker ON (current default)**

Run:
```bash
RERANKER=on .venv/Scripts/python.exe benchmarks/evaluate.py .
```

Record: HR, P, MRR, avg latency.

**Step 2: Run eval with reranker OFF**

Run:
```bash
RERANKER=off .venv/Scripts/python.exe benchmarks/evaluate.py .
```

Record: HR, P, MRR, avg latency.

**Step 3: Compare and decide**

If reranker OFF improves precision AND reduces latency (like memory-search), disable it as default. If reranker ON is better, keep it.

**Step 4: Apply the decision**

Update `CLAUDE.md` env var table with the chosen default and rationale. If disabling, keep the code (set `RERANKER=off` as default).

**Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "perf: evaluate reranker impact — [enable/disable] based on golden eval"
```

---

### Task 8: Title enrichment for BM25

Port the memory-search title enrichment pattern. Prepend file-level context to chunk names so BM25 and title-match can find them.

**Files:**
- Modify: `code-search/chunking/base_chunker.py` or wherever chunk metadata is assigned
- Test: `code-search/tests/unit/test_title_enrichment.py` (new)

**Step 1: Identify where chunk names are set**

Read the chunking pipeline to find where `name` metadata is assigned to chunks. It's likely in the tree-sitter chunkers or the base chunker class.

**Step 2: Write the failing test**

```python
def test_chunk_name_includes_file_context():
    """Chunk name should include the parent file/module for BM25 discoverability."""
    # Given a chunk from search/searcher.py, function "reciprocal_rank_fusion"
    # The chunk name should be "searcher - reciprocal_rank_fusion"
    # not just "reciprocal_rank_fusion"
    chunk = create_chunk(file_path="search/searcher.py", name="reciprocal_rank_fusion")
    enriched = enrich_chunk_title(chunk)
    assert "searcher" in enriched.name.lower()
    assert "reciprocal_rank_fusion" in enriched.name
```

**Step 3: Implement title enrichment**

In the FTS5 insertion path (`indexer.py:206-210`), enrich the `name` field:
```python
# Before inserting into FTS5, enrich name with file context
file_stem = Path(file_path).stem if file_path else ""
enriched_name = f"{file_stem} - {name}" if name and file_stem else (name or "")
```

**Step 4: Run evaluation to measure impact**

Run: `.venv/Scripts/python.exe benchmarks/evaluate.py .`
Compare against baseline. Expected: +2-8% precision improvement (free).

**Step 5: Commit**

```bash
git add search/indexer.py tests/unit/test_title_enrichment.py
git commit -m "feat: title enrichment for BM25 — prepend file context to chunk names"
```

---

## Part C: Code-Graph Improvements

### Task 9: Add query result caching to code-graph

code-graph makes SQLite queries for every tool call. Common patterns (search_graph, query_graph with repeated Cypher) should cache.

**Files:**
- Modify: `code-graph/internal/store/store.go` (add cache layer)
- Test: `code-graph/internal/store/cache_test.go` (new)

**Step 1: Identify hot query paths**

Read `internal/tools/search.go` and `internal/tools/query.go` to see what SQLite queries are executed most. The `search_graph` tool likely does full-text search + filter joins on every call.

**Step 2: Write the failing test**

```go
func TestQueryCacheHit(t *testing.T) {
    cache := NewQueryCache(100)

    // First call: cache miss
    key := "search:Function:auth"
    _, hit := cache.Get(key)
    assert.False(t, hit)

    // Store result
    cache.Set(key, []Node{{Name: "authenticate"}})

    // Second call: cache hit
    result, hit := cache.Get(key)
    assert.True(t, hit)
    assert.Len(t, result, 1)
}

func TestQueryCacheInvalidatedOnReindex(t *testing.T) {
    cache := NewQueryCache(100)
    cache.Set("search:Function:auth", []Node{{Name: "authenticate"}})

    cache.Invalidate()

    _, hit := cache.Get("search:Function:auth")
    assert.False(t, hit)
}
```

**Step 3: Implement LRU cache**

Add a simple LRU cache to `internal/store/`:
```go
type QueryCache struct {
    mu       sync.RWMutex
    entries  map[string]cacheEntry
    maxSize  int
}

type cacheEntry struct {
    result    interface{}
    timestamp time.Time
}
```

Wire it into `search_graph` and `query_graph` tool handlers. Invalidate on `index_repository` completion.

**Step 4: Run tests**

Run: `go test ./internal/store/ -run TestQueryCache -v`
Expected: PASS

**Step 5: Commit**

```bash
git checkout -b feat/query-cache
git add internal/store/cache.go internal/store/cache_test.go internal/tools/search.go internal/tools/query.go
git commit -m "feat: add LRU query cache for search_graph and query_graph"
```

---

### Task 10: Add benchmarking to code-graph

The BENCHMARK.md exists but needs live benchmarks against current indexed repos.

**Files:**
- Create: `code-graph/benchmarks/bench_queries.go` or use existing Go bench framework

**Step 1: Check existing benchmarks**

Read `internal/pipeline/pipeline_bench_test.go` to see what's already benchmarked.

**Step 2: Add search/query benchmarks**

Add to existing bench test file or create new:
```go
func BenchmarkSearchGraph(b *testing.B) {
    // Setup: index a known repo
    // Benchmark: search_graph with common patterns
    for i := 0; i < b.N; i++ {
        SearchGraph(project, "Function", "auth", 10)
    }
}

func BenchmarkQueryGraph(b *testing.B) {
    for i := 0; i < b.N; i++ {
        QueryGraph(project, "MATCH (f:Function) WHERE f.name CONTAINS 'auth' RETURN f LIMIT 10")
    }
}
```

**Step 3: Run and record baseline**

Run: `go test ./internal/tools/ -bench=. -benchmem -count=3`

**Step 4: Commit**

```bash
git add internal/tools/bench_test.go
git commit -m "feat: add search/query benchmarks for performance baseline"
```

---

## Part D: Ship All Changes

### Task 11: Ship code-search PRs

Combine Tasks 3-8 into 2-3 PRs (cache + eval framework, then tuning + enrichment).

**Step 1: PR 1 — Caching + Eval Framework (Tasks 3, 4, 5)**

```bash
cd $HOME/Documents/GitHub/code-search
git checkout -b feat/caching-and-eval
# Stage all caching + eval files
git add search/searcher.py search/incremental_indexer.py mcp_server/code_search_server.py \
        tests/unit/test_query_cache.py tests/unit/test_embedding_cache.py \
        benchmarks/
git commit -m "feat: query cache, embedding cache, and golden eval framework"
git push -u origin feat/caching-and-eval
gh pr create --title "feat: caching + evaluation framework" \
  --body "$(cat <<'EOF'
## Summary
- Query embedding LRU cache eliminates redundant Voyage API calls
- Content-hash embedding cache skips re-embedding unchanged chunks on reindex
- Golden test set (30 queries) with HR@5, P@5, MRR evaluation
- RRF parameter sweep script

## Test plan
- [ ] `pytest tests/unit/test_query_cache.py -v` passes
- [ ] `pytest tests/unit/test_embedding_cache.py -v` passes
- [ ] `python benchmarks/evaluate.py .` runs and produces metrics
EOF
)" --repo example-apps-org/code-search
gh pr merge --auto --squash --delete-branch --repo example-apps-org/code-search
```

**Step 2: PR 2 — Tuning + Enrichment (Tasks 6, 7, 8)**

```bash
git checkout main && git pull --rebase
git checkout -b feat/rrf-tuning-and-enrichment
# Stage tuning + enrichment files
git add search/searcher.py search/indexer.py benchmarks/rrf_sweep.py \
        tests/unit/test_title_enrichment.py CLAUDE.md
git commit -m "feat: RRF parameter sweep, reranker eval, title enrichment"
git push -u origin feat/rrf-tuning-and-enrichment
gh pr create --title "perf: RRF tuning + title enrichment" \
  --body "$(cat <<'EOF'
## Summary
- RRF parameter sweep finds optimal vector_weight/k values
- Reranker on/off evaluation with decision
- Title enrichment for BM25 chunk discoverability

## Test plan
- [ ] `pytest tests/unit/test_title_enrichment.py -v` passes
- [ ] `python benchmarks/evaluate.py .` shows improvement over baseline
EOF
)" --repo example-apps-org/code-search
gh pr merge --auto --squash --delete-branch --repo example-apps-org/code-search
```

### Task 12: Ship code-graph PR

```bash
cd $HOME/Documents/GitHub/code-graph
git push -u origin feat/query-cache
gh pr create --title "feat: LRU query cache + benchmarks" \
  --body "$(cat <<'EOF'
## Summary
- LRU cache for search_graph and query_graph results
- Cache invalidated on reindex
- Search/query benchmarks for performance baseline

## Test plan
- [ ] `go test ./internal/store/ -run TestQueryCache -v` passes
- [ ] `go test ./internal/tools/ -bench=. -benchmem` produces baseline
EOF
)" --repo example-apps-org/code-graph
gh pr merge --auto --squash --delete-branch --repo example-apps-org/code-graph
```

### Task 13: Update claude-config references

Commit all the config file changes from Tasks 1-2 (session-start.py, protected-repos.json, repo-map.md, git-hygiene.md).

```bash
cd ~/.claude
git checkout -b chore/rename-local-dirs
git add hooks/session-start.py hooks/protected-repos.json \
        skills/_shared/repo-map.md rules/git-hygiene.md
git commit -m "chore: rename claude-context-local → code-search, codebase-memory-mcp → code-graph"
git push -u origin chore/rename-local-dirs
gh pr create --title "chore: update local directory names" \
  --body "Aligns local clone directory names with GitHub repo names."
gh pr merge --auto --squash --delete-branch
```
