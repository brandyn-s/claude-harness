# Oracle design — agent benchmarks

> Phase 1 reference for measurement projects in the **agent-benchmark** class: predictions on labeled corpora where the labels come from a published benchmark. Examples: Loc-Bench (file-level localization), SWE-bench (issue-to-patch), MultiSWE-bench (multi-language SWE-bench), CSN (code search), HumanEval (code completion).

## What you're measuring

Pass/fail on a fixed labeled corpus. Common metrics:
- **Pass@K**: fraction of problems solved within K attempts
- **Top-K accuracy**: did the prediction appear in the labeled set's top-K?
- **Resolved rate**: fraction where the produced patch passes hidden tests (SWE-bench)
- **Edit distance / BLEU**: for completion tasks where any reasonable answer is acceptable

The oracle IS the benchmark's labeled set. The question is not "is the label correct?" — it's "did your system match the label?"

## Three modes of agent-benchmark measurement

### Mode A — Published benchmark, off-the-shelf

Use the benchmark exactly as published. Pros: directly comparable to literature. Cons: leaderboard compression near state-of-the-art; benchmark may not match your real query distribution.

When this mode is correct: validating that a system change preserves baseline competence on a well-known benchmark before shipping. Code-graph's LocAgent implementation measured 82.5% file Acc@10 on Loc-Bench at n=200 (Haiku 4.5, $0.05/query). The legible comparison points: LocAgent paper's Loc-Bench results are 86.07% (Claude-3.5, ~$0.66/query, 13× cost) and 79.64% (Qwen-7B fine-tuned, $0.05/query — the open-model peer at our cost tier). Their oft-cited 92.7% is on SWE-Bench-Lite with a fine-tuned Qwen-32B — a DIFFERENT benchmark and model class. Always identify (benchmark, model, cost tier) before claiming exceedence.

### Mode B — Subset / extension of published benchmark

Sample a subset (e.g., 16 instances of Loc-Bench's 200) for cheap iteration, OR extend with custom instances that match your distribution. Pros: cheaper iteration; better distribution match. Cons: not directly comparable to published numbers; subset selection introduces sampling bias.

**Subset gate**: if you sample <50 instances, statistics are noisy. Pass@10 with 95% CI on n=16 has ±15pp confidence interval — not enough to distinguish many real-world changes. Use subsets for early iteration; full set for shipping decisions.

### Mode C — Custom labeled corpus

Build your own labeled set when no published benchmark fits. This is hand-labeling at scale (see `oracle-retrieval.md` Option A) plus a graded difficulty distribution. Reserve for long-term measurement projects; expensive.

## Oracle reliability characteristics

Published benchmarks have known biases. Document them at Phase 1:

- **SWE-bench**: instances drawn from 12 popular Python repos. Skews toward Django/Flask/sympy patterns. Top systems may overfit to those patterns.
- **Loc-Bench**: instances from a fixed set of GitHub issues. Issue text quality is variable — some have clear repro steps, some don't. Difficulty stratification by issue-text quality is required to avoid measuring "ability to read clear issue texts" instead of "ability to localize bugs."
- **HumanEval**: 164 hand-written problems. Saturated at >95% on top systems; can't distinguish between strong systems anymore. Use HumanEval+ (extended test cases) or MBPP+ for current iteration.
- **CSN (CodeSearchNet)**: function-docstring pairs. Docstrings vary in quality; some are placeholder. Performance on noisy docstrings != performance on real queries.

## Two-source pattern for agent benchmarks

The benchmark labels are the oracle. Your system is the second source. Disagreement reveals system error (or, rarely, label error — published benchmarks DO have label errors; estimate ~3-5% bad labels in any large hand-labeled corpus).

**For Phase 9 cell verification**: when a cell of failures concentrates around a benchmark instance, sample 3-5 instances from the cell and read them. If ≥3 of 5 are bad labels (the "correct" answer is debatable or wrong), the cell is an oracle artifact, not a system bug. Document the bad-label rate; report metrics with and without the disputed instances.

**FORBIDDEN**: silently dropping disputed instances from your reported number without disclosure. That's gaming the benchmark.

## Stratification dimensions for agent benchmarks

Pick from this menu:

- **difficulty**: easy / medium / hard (per benchmark or hand-classified)
- **repo / project** (for multi-repo benchmarks like SWE-bench)
- **language** (for multi-language benchmarks)
- **task_type**: bug-fix / feature-add / refactor / test-add (for SWE-bench-style tasks)
- **issue_quality**: clear-repro / partial-repro / vague (for issue-text-driven benchmarks like Loc-Bench)
- **prediction_position**: top-1 / top-3 / top-10 (for ranked prediction tasks)
- **agent_turns_used**: 1 / 2-5 / 6-15 / 16+ (for multi-turn agent benchmarks; cost dimension)
- **failure_mode**: timeout / wrong-answer / parse-error / context-overflow

Code-graph's LocAgent measurement stratifies by `repo_size` (small <10K LOC, medium, large >100K LOC) and `prediction_position` (top-1, top-3, top-10). The 82.5% file Acc@10 (n=200, Haiku 4.5) is the top-10 file-level metric; top-1 is significantly lower and is the better number for production usefulness.

## Tiny known-truth fixture for agent benchmarks

The "tiny" fixture is your N=16 (or whatever) sampled subset of the full benchmark. Verify:

- Your harness correctly parses the benchmark's expected output format
- Your harness correctly computes Pass@K on N=16 (manually compute Pass@1 on N=16 by hand and compare)
- Your harness correctly identifies "no answer" / "timeout" / "format error" as distinct from "wrong answer"

If the harness misidentifies any of these, you're measuring different things. Catch this before scaling to full benchmark.

## Synthetic negative fixtures for agent benchmarks

Build 3-5 instances designed to fail in specific ways:

1. **Trivially impossible**: instance where the correct answer is not in the available context. System should report low confidence / no answer, not hallucinate.
2. **Distractor-rich**: instance with multiple plausible-but-wrong candidates. Tests discrimination.
3. **Multi-step**: instance requiring the system to chain reasoning across N steps. Exposes single-shot vs multi-turn capability gap.
4. **Edge-of-distribution**: instance just outside the benchmark's typical pattern (different repo style, different issue-text format).
5. **Adversarial**: instance designed to trigger known agent failure modes (prompt injection in issue text, hidden constraint in code comment).

These complement the benchmark by testing failure-handling robustness, not just nominal accuracy.

## Truncation audit for agent benchmarks

Specific to agent harness chains:

- **Agent turn cap**: harness may impose `--max-turns` that silently cuts off agents. Document the cap; report timeout vs wrong-answer separately.
- **Context window**: long benchmark instances may exceed the agent's context. Verify the harness either errors loudly or has an explicit chunking strategy.
- **Tool result cap**: tool calls within agent execution may return truncated results (search tools, file reads). Same `Truncated bool` requirement as elsewhere.
- **Score aggregation**: "Pass@K" requires K attempts; verify your harness actually runs K attempts and not 1 attempt counted K times.

## Freshness gate for agent benchmarks

Specific staleness sources:

- **Agent prompt template** version (system prompt, examples, format instructions)
- **Agent model version** (Opus 4.5 vs 4.6 vs 4.7 produces different numbers — record per measurement)
- **Tool implementations** the agent uses (e.g., code-search version, code-graph version)
- **Benchmark version** (Loc-Bench v1 vs v2 has different instance set)

Record all four in baseline files. Same-benchmark same-prompt different-model comparisons are valid; cross-version comparisons require explicit re-baseline.

## Two operating points for agent benchmarks

- **Best-of-K** (precision-sensitive): require K attempts, count instance as solved only if all K succeed. Useful for "is this reliable enough to ship?" decisions.
- **Pass@K** (recall-sensitive): instance solved if ANY of K attempts succeed. Useful for "can the agent ever find the answer?" decisions.

Most published benchmarks report Pass@K. Best-of-K is harder and arguably more honest for production use.

## CI regression gate for agent benchmarks

Per-subset thresholds:
- Per-difficulty (easy / medium / hard) — easy regression > 1pp is suspicious; hard regression > 5pp is concerning
- Per-repo (for multi-repo benchmarks) — single-repo regression often signals overfitting to other repos
- Per-task-type — fix vs feature-add are different skill sets

Aggregate gate: typically 3-5pp on Pass@10. Tighter for high-variance subsets.

## Code-search-relevant note

Agent-benchmark mode applies to code-search if you're measuring "did the agent find the right file?" rather than "did retrieval rank the right item?". The two have different oracles:

- Retrieval mode: oracle = labeled relevance pairs; metric = nDCG / Recall@K
- Agent mode: oracle = benchmark labels; metric = Pass@K / file-level accuracy

LocAgent (the code-graph paper) is in agent mode. Evaluate code-search in retrieval mode unless the consumer is an agent that uses code-search results as one input among many.
