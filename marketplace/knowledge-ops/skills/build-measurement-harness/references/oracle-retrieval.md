# Oracle design — retrieval / semantic search

> Phase 1 reference for measurement projects in the **retrieval** class: semantic search, ranking, top-K relevance, RAG context selection, hybrid search. Most relevant active project: code-search.

## What you're measuring

Retrieval quality: given a query, did the system return the relevant items in a useful ranking?

Common metrics:
- **Recall@K**: of the relevant items for the query, how many appear in top-K?
- **Precision@K**: of the top-K results, how many are relevant?
- **nDCG@K**: rank-discounted cumulative gain — relevant items at higher ranks count more
- **MRR**: mean reciprocal rank — 1/rank of the first relevant item, averaged
- **Hit@K**: did *any* relevant item appear in top-K?

The oracle is a labeled set of `(query, item, relevance_label)` tuples OR a calibrated judge that can assess relevance for arbitrary `(query, item)` pairs.

## Three options for the oracle

### Option A — Hand-labeled relevance pairs

Build a corpus of `(query, item, relevance_label)` tuples by hand.

**Pros**: ground truth. Stable. Reproducible.
**Cons**: expensive to scale. Biased toward what the labelers think to query. Requires re-labeling when corpus changes.

**Minimum viable corpus**:
- 50-100 queries spanning realistic query distribution
- ≥3 relevant items labeled per query
- Binary or graded relevance (0-3 scale: not_relevant / partial / relevant / highly_relevant)

**Inter-rater reliability gate** (REQUIRED):
- ≥2 labelers do the same 30-query subsample independently
- Compute Cohen's Kappa
- **Kappa ≥0.6** = labels are usable; **<0.6** = labels are noise. Rewrite the labeling guide before scaling.
- Document the disagreement patterns: which query types had low agreement?

### Option B — LLM-judge with calibration

Use Claude/GPT to score `(query, item)` relevance.

**Pros**: scales. Can re-judge new query types cheaply. Works for corpora too large to hand-label.
**Cons**: judge has its own biases. Without calibration, you're measuring the judge's preferences, not retrieval quality. Judge model upgrades invalidate prior measurements.

**Calibration protocol** (REQUIRED before trusting LLM-judge for any production measurement):

1. Build a 50-query × 5-result hand-labeled subset (binary relevant/not). This is the calibration set.
2. Run LLM-judge on the same `(query, item)` pairs.
3. Compute Cohen's Kappa between LLM-judge labels and majority-vote human labels.
4. **Kappa ≥0.7 required** before LLM-judge replaces hand labels for production measurement. Below 0.7, the judge is a different system — don't conflate.
5. **Re-calibrate quarterly** OR when query distribution shifts OR when judge model upgrades. Document the calibration date in baseline files.

**FORBIDDEN**: using the same model for retrieval and judging (the judge will systematically favor its own embedding patterns). Use a different model family — e.g., Claude judge for OpenAI-embedded retrieval, or vice versa.

**FORBIDDEN**: treating Kappa = 0.5 as "good enough." Kappa < 0.7 means the judge and humans disagree about half the borderline cases; that's enough variance to invert any A/B test.

### Option C — Existing benchmark

Use a published retrieval benchmark.

For code-search specifically:
- **CodeSearchNet** — function-docstring pairs across 6 languages
- **CoIR** (Code Information Retrieval, 2024) — multi-task code retrieval benchmark
- **CSN-WMD** — extended CodeSearchNet with weighted multi-relevance
- **SWE-bench-retrieval** — file-level retrieval for SWE-bench bugs

For general retrieval:
- **MS MARCO** — passage retrieval
- **BEIR** — multi-domain heterogeneous IR benchmark

**Pros**: zero labeling cost. Comparable to literature. Reproducible across teams.
**Cons**: may not match your query distribution. Scores compress at top of leaderboard (state-of-the-art systems within 1-2pp of each other). Benchmark queries may be optimized-for in academic papers, leading to over-fitting.

**Use existing benchmarks as a sanity check**, not as the primary oracle. Your real-world query distribution differs from the benchmark distribution, and the only number that matters for shipped quality is the one measured against your distribution.

## What "two-source" means for retrieval

The oracle (labels OR judge) is one source. The retrieval system is the other. Disagreement is either system error or oracle error. Sample disagreements at Phase 9 (Step 6 verification) to classify.

**Bonus pattern — two-system comparison**: run TWO retrieval systems against the same query set, compare relative ranking. Catches relative quality (system A vs system B) without absolute relevance. Useful for A/B testing changes where you don't have absolute ground truth.

**FORBIDDEN**: using your own system's top-1 result as the relevance label for top-K evaluation. Circular. Will always score 1.0.

## Stratification dimensions for retrieval

These become Phase 4's categorical fields. Pick 3-5 from this menu (or design your own):

- **query_type**: lookup ("function name X") / how-does-it-work ("how does authentication work") / find-similar ("functions similar to Y") / debug ("why does X fail") / explore ("what's in this module")
- **query_length**: short (1-3 tokens) / medium (4-15) / long (>15)
- **target_kind**: function / class / file / docstring / config / test / readme
- **language** (multi-language code search): rust / go / python / typescript / etc.
- **rank_position**: where in top-K did the relevant item appear? 1 / 2-3 / 4-10 / 11-20 / not-found
- **score_band**: high (≥0.8) / medium (0.5-0.8) / low (<0.5) similarity score
- **corpus_size**: small (<1K docs) / medium / large (>100K) — for measuring scaling behavior

For code-search: **query_type stratification often surfaces that semantic search excels at how-does-it-work but degrades on lookup** (where exact-match grep wins). Without stratification, this is invisible in aggregate nDCG. Hybrid search (semantic + lexical) wins because it picks the right strategy per query_type — but you can't tune the hybrid weights without per-query-type stratification.

## Tiny known-truth fixture for retrieval

Build a 5-query × 10-document hand-verifiable fixture:

- 5 queries hand-written, each targeting 1-2 specific documents
- 10 documents you wrote yourself with known content
- Hand-verify which `(query, doc)` pairs are relevant

**Required gate**:
- Every relevant item ranks in top-K (Recall@K = 1.0 for K = total relevant items)
- No irrelevant item ranks above any relevant item at K = 2 × number_of_relevant
- Aggregate nDCG@10 = 1.0 (perfect ranking)

If this fails, the harness or retrieval system is broken. Do not run on real corpora.

**Code-search-specific tiny fixture** (suggested):
1. 5 functions in a fake "math" file (`add`, `multiply`, `divide_safe`, `power`, `factorial`)
2. 5 functions in a fake "auth" file (`login`, `logout`, `verify_password`, `hash_password`, `reset_token`)
3. Queries: "addition function" → expect `add`; "password hashing" → expect `hash_password`; "user logout" → expect `logout`; etc.

## Synthetic negative fixtures for retrieval

Each fixture isolates ONE failure pattern. Suggested set:

1. **Nonsense query**: query that has no semantic match in corpus. System should either return nothing in high-confidence band OR return results with low-confidence flag. Failure: returns first result with high confidence.

2. **Near-duplicate suppression**: corpus has 3 near-identical functions (e.g., copy-pasted with renamed variables). Query targets the concept. System should return all 3 (deduplication is the consumer's job) OR exactly 1 with explicit deduplication signal. Failure: returns 1 silently and the consumer thinks the corpus only has 1.

3. **Lexical-vs-semantic conflict**: corpus has function `cleanup_users()` (semantically about users, lexically about cleanup) and function `delete_user_records()` (semantically about user deletion). Query "delete users". Pure semantic search may rank `cleanup_users` above `delete_user_records` because of token overlap. Failure: lexical-strong query degrades when semantic-only is the strategy.

4. **Long-document boundary**: target answer is in middle of a 10K-token document. Many embedding models truncate to 512 tokens silently. Failure: target document doesn't appear in top-K because embedding was computed on truncated chunk.

5. **Cross-language query**: query in English, target in non-English language (or query in plain text, target in code). Failure: embedding model can't bridge the modality gap.

Each fixture should fail in a measurable, distinct way under the current system. If they all pass, the system is mature OR your fixtures aren't exercising the failure modes you care about. If they all fail in the same way, fixtures are redundant.

## Truncation audit for retrieval

Walk every tool in the chain:

| Component | Common silent caps | Verification |
|---|---|---|
| Embedding model | max input length (512 / 8192 tokens) — silently truncates long inputs | Send a known long input, check returned embedding shape; if model has no error, it truncated |
| Chunker | chunk size limits, overlap configuration | Count chunks per document, compare to expected from chunk-size math |
| Vector index (FAISS, Qdrant, etc.) | top-K cap on `search()`, default may be 10 | Read source for default `k`; verify result count matches request |
| Re-ranker | input cap (often top-100 candidates), input length cap per item | Send 200 candidates; check return count |
| Result formatter | max display count, score band filter | Compare formatter output to re-ranker output count |
| Hybrid scoring (BM25 + dense) | per-side caps before fusion | Verify fusion input counts match individual side outputs |

**Required outputs in result shape**:
- `truncated_at: int` — where in the pipeline truncation happened
- `total_candidates: int` — how many candidates existed before truncation
- `effective_top_k: int` — actual K returned (may be less than requested if corpus is small)

If the chain has any unsignaled cap, fix the contract first. Code-search's analog of code-graph's PR #64-65 is: discover the cap, surface it explicitly in tool result, propagate through harness.

## Freshness gate for retrieval

Sources of staleness specific to retrieval:

- **Index timestamp** — when was the FAISS / vector store last rebuilt?
- **Embedding model version** — re-embedding required when model changes
- **Re-ranker model version** — re-running required when model changes
- **Corpus snapshot** — commit SHA of source code being searched
- **Chunker config** — chunk size, overlap, boundary rules
- **Hybrid search weights** — BM25:dense fusion weights

Any change to embedding model, re-ranker, chunker, or corpus invalidates the baseline. Pin all of these in baseline files; warn on mismatch.

**Code-search-specific gotcha**: the index is rebuilt incrementally. Incremental rebuilds may use the OLD chunker config for unchanged files and the NEW config for changed files, producing a mixed-config index that no single version describes. Either force full rebuild on config changes, or version the index by `(embedding_model, chunker_config, snapshot_sha)` and gate on all three.

## Two operating points for retrieval

- **All-bands** (recall-sensitive): top-K including low-confidence results. Useful for "show me anything that might be relevant" UX (e.g., RAG context retrieval where the LLM consumer can filter).
- **High-confidence** (precision-sensitive): top-K filtered to score ≥ threshold. Useful for "answer this question" UX (e.g., code completion where the consumer trusts the result).

Threshold selection: don't tune to make the metric look best. Tune based on the consumer's tolerance for noise vs misses.

## CI regression gate for retrieval

Per-subset thresholds:
- Per-language nDCG@10
- Per-query-type nDCG@10
- Per-fixture (CodeSearchNet, hand-labeled, synthetic) nDCG@10

Aggregate-only gates miss single-subset regressions. A change that improves how-does-it-work queries by +5pp while regressing lookup queries by -10pp may show as +2pp aggregate; per-query-type gates catch the regression.

## Code-search-specific notes

The code-search project (per memory: fork of FarhanAliRaza/claude-context-local in example-org/code-search) uses Voyage AI embeddings and FAISS for vector storage. Active failure modes that this skill's recipe should expose:

- **Voyage embedding rate limits** at index time — slow indexing, possible retries that produce duplicate index entries (Phase 5 truncation audit)
- **Chunker configuration** — Python AST chunks vs naive line-based chunks — different recall profiles per language (Phase 4 stratification by language + chunker)
- **Query distribution** — what queries do real users ask? If unknown, build the labeled set from session transcripts + LLM-judge, and apply the calibration protocol above before treating it as ground truth (Option B)

When invoking this skill on code-search: Phase 0 problem statement should name the specific quality dimension (recall on lookup queries vs nDCG on RAG retrieval vs accuracy on cross-language search). Each dimension may want a different oracle and different stratification.
