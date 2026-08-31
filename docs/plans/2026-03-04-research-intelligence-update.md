# Research Intelligence Update - March 2026 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply all 18 approved items from the 2026-03-04 gather-research run with A/B testing to validate each change's effectiveness before permanent adoption. Every actionable change gets a measured baseline, isolated treatment, and pass/fail criteria.

**Architecture:** Four phases:
- **Phase A**: Update the research intelligence report (documentation only, no A/B needed)
- **Phase B**: Build the eval harness (the measurement infrastructure for all A/B tests)
- **Phase C**: Apply changes with A/B testing (tool descriptions, response caps, context management)
- **Phase D**: Design longer-term experiments (experience replay, trajectory capture)

**Tech Stack:** Python (FastMCP, sentence-transformers), pytest, Markdown, Bash (git, gh CLI)

**A/B Testing Approach:**
- Level 1 (Deterministic): Extend `security-remix/evals/test_scenarios.py` - measure call counts, response sizes, workflow pass rate
- Level 2 (Semantic search): Feed tool schemas into ToolIndex, measure Recall@5 for discovery queries
- Level 3 (LLM-in-the-loop): Give Claude tool schemas + prompt, measure tool selection accuracy (optional, API cost)

---

## Phase A: Update Research Intelligence Report

### Task 1: Snapshot and update report

**Files:**
- Read: `~/Documents/knowledge-base/research/claude-code-research-intelligence.md`
- Create: `~/Documents/knowledge-base/research/2026-03-04-research-intelligence-snapshot.md`
- Modify: `~/Documents/knowledge-base/research/claude-code-research-intelligence.md`

**Step 1: Create snapshot**

```bash
cp ~/Documents/knowledge-base/research/claude-code-research-intelligence.md \
   ~/Documents/knowledge-base/research/2026-03-04-research-intelligence-snapshot.md
```

**Step 2: Update report metadata**

Replace the metadata block with:
```
Last updated: 2026-03-04
Claude Code version: v2.1.68
Tavily credits consumed this run: ~30
Phase A items audited: 6 (all from 2026-03-01 run)
Phase B findings: 9 new, 1 update, 1 confirmation
```

**Step 3: Update the 6 existing Active Findings with currency status**

Add a "Currency audit (2026-03-04)" note to each:

1. **MCP-Zero**: "EVOLVED - Anthropic's Code Execution with MCP + Programmatic Tool Calling + Tool Search Tool now implement this as first-party features."
2. **Microsoft Tool-Space Interference**: "CURRENT - Anthropic engineering blogs confirm tool definitions consuming 50K+ tokens is a real production problem."
3. **Tool RAG / RAG-MCP**: "EVOLVED - Tool Search Tool is now GA in Claude API (`betas=['advanced-tool-use-2025-11-20']`)."
4. **VGCO**: "EVOLVED - 'MCP Tool Descriptions Are Smelly' (arXiv:2602.14878) shows augmentation helps but REGRESSES 16.67% of cases. Best: P+G+L+PEx (skip examples)."
5. **Tool-to-Agent Retrieval**: "CURRENT - No superseding work."
6. **Tool Description Rewriting**: "CONFIRMED - Anthropic tool testing agent improved completion by 40%."

**Step 4: Add 10 new findings to Active Findings**

Add these using standard finding format (full text from the gather-research Phase C report):

HIGH findings:
1. Anthropic: Code Execution with MCP (anthropic.com/engineering/code-execution-with-mcp)
2. Anthropic: Writing Effective Tools for AI Agents (anthropic.com/engineering/writing-tools-for-agents)
3. Anthropic: Multi-Agent Research System (anthropic.com/engineering/multi-agent-research-system)
4. CER: Contextual Experience Replay (arXiv:2506.06698, ACL 2025)
5. SiriuS: Self-Improving Multi-Agent Systems (arXiv:2502.04780, NeurIPS 2025)

MEDIUM findings:
6. MCP 2025-06-18 Specification Update
7. MCP Tool Descriptions Are Smelly (arXiv:2602.14878)
8. CoSAI MCP Security Framework
9. JetBrains Context Management Research
10. Memory in the Age of AI Agents Survey (arXiv:2512.13564)

**Step 5: Update Research Threads**

- Rename "Active Discovery > Passive Injection" to "Context-Efficient Tool Interaction" (maturity: Established)
- Keep "Tool Count is the #1 Accuracy Killer" (add Anthropic engineering confirmations)
- Add "Self-Improvement via Experience Replay" (CER, SiriuS, Reflexion, Voyager, SICA - maturity: Establishing)
- Add "MCP Maturation: Protocol + Security + Quality" (MCP 2025-06-18, CoSAI, mcp-tef - maturity: Established)

**Step 6: Update Radar and Experiment Backlog**

- Promote "Programmatic Tool Calling" from Radar to Active
- Add to Radar: "ICLR 2026 Workshop MemAgents", "Policy as Prompt (arXiv:2509.23994)"
- Add Experiments 3-5 (see Phase D for designs)

**Step 7: Add 13 new citations (items 13-25)**

**Step 8: Commit**

```bash
cd ~/Documents/knowledge-base
git add research/claude-code-research-intelligence.md research/2026-03-04-research-intelligence-snapshot.md
git commit -m "research: update intelligence report with 2026-03-04 findings

Add 10 new findings (5 HIGH, 5 MEDIUM), update 6 baseline entries,
add 2 new research threads, queue 3 experiments, 13 new citations."
git push origin main
```

---

## Phase B: Build the Eval Harness

### Task 2: Extend test_scenarios.py with measurement metrics

**Files:**
- Modify: `~/Documents/GitHub/mcp-servers/security-remix/evals/test_scenarios.py`
- Create: `~/Documents/GitHub/mcp-servers/security-remix/evals/ab_metrics.py`

**Step 1: Write the metrics collection module**

```python
"""A/B testing metrics for tool description and response optimization.

Collects:
- Tool discovery accuracy: does discover_tools return the expected tool in top-K?
- Discovery rank: what position is the expected tool in results?
- Response size: character count of execute_tool results
- Call efficiency: meta-tool calls per completed workflow
- Workflow pass rate: % of scenarios that complete successfully
"""
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DiscoveryMetric:
    """Measures discover_tools accuracy for a single query."""
    query: str
    expected_tool: str
    returned_tools: list[str]
    rank: int | None = None  # Position of expected tool (0-indexed), None if not found

    @property
    def found(self) -> bool:
        return self.rank is not None

    @property
    def found_in_top3(self) -> bool:
        return self.rank is not None and self.rank < 3


@dataclass
class ResponseMetric:
    """Measures execute_tool response characteristics."""
    tool_name: str
    response_chars: int
    response_fields: int  # Number of top-level JSON keys


@dataclass
class ABTestRun:
    """Full metrics from a single eval run (baseline or treatment)."""
    label: str  # "baseline" or "treatment-{name}"
    discovery_metrics: list[DiscoveryMetric] = field(default_factory=list)
    response_metrics: list[ResponseMetric] = field(default_factory=list)
    workflow_pass: int = 0
    workflow_fail: int = 0
    total_calls: int = 0

    @property
    def discovery_accuracy(self) -> float:
        if not self.discovery_metrics:
            return 0.0
        return sum(1 for m in self.discovery_metrics if m.found) / len(self.discovery_metrics)

    @property
    def discovery_top3_accuracy(self) -> float:
        if not self.discovery_metrics:
            return 0.0
        return sum(1 for m in self.discovery_metrics if m.found_in_top3) / len(self.discovery_metrics)

    @property
    def mean_rank(self) -> float:
        ranks = [m.rank for m in self.discovery_metrics if m.rank is not None]
        return statistics.mean(ranks) if ranks else float('inf')

    @property
    def mean_response_chars(self) -> float:
        if not self.response_metrics:
            return 0.0
        return statistics.mean(m.response_chars for m in self.response_metrics)

    @property
    def workflow_pass_rate(self) -> float:
        total = self.workflow_pass + self.workflow_fail
        return self.workflow_pass / total if total > 0 else 0.0

    def summary(self) -> str:
        lines = [
            f"=== {self.label} ===",
            f"Discovery accuracy:     {self.discovery_accuracy:.1%} ({sum(1 for m in self.discovery_metrics if m.found)}/{len(self.discovery_metrics)})",
            f"Discovery top-3:        {self.discovery_top3_accuracy:.1%}",
            f"Mean discovery rank:    {self.mean_rank:.1f}",
            f"Mean response size:     {self.mean_response_chars:,.0f} chars",
            f"Workflow pass rate:     {self.workflow_pass_rate:.1%} ({self.workflow_pass}/{self.workflow_pass + self.workflow_fail})",
            f"Total meta-tool calls:  {self.total_calls}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "discovery_accuracy": self.discovery_accuracy,
            "discovery_top3_accuracy": self.discovery_top3_accuracy,
            "mean_rank": self.mean_rank,
            "mean_response_chars": self.mean_response_chars,
            "workflow_pass_rate": self.workflow_pass_rate,
            "total_calls": self.total_calls,
        }

    def save(self, path: Path):
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding='utf-8')


def compare(baseline: ABTestRun, treatment: ABTestRun) -> str:
    """Compare two runs and produce a verdict."""
    lines = [
        "",
        "=" * 60,
        "  A/B COMPARISON",
        "=" * 60,
        "",
        baseline.summary(),
        "",
        treatment.summary(),
        "",
        "--- DELTAS ---",
    ]

    disc_delta = treatment.discovery_accuracy - baseline.discovery_accuracy
    top3_delta = treatment.discovery_top3_accuracy - baseline.discovery_top3_accuracy
    rank_delta = treatment.mean_rank - baseline.mean_rank  # Lower is better
    resp_delta = treatment.mean_response_chars - baseline.mean_response_chars
    pass_delta = treatment.workflow_pass_rate - baseline.workflow_pass_rate

    lines.append(f"Discovery accuracy:  {disc_delta:+.1%}")
    lines.append(f"Discovery top-3:     {top3_delta:+.1%}")
    lines.append(f"Mean rank:           {rank_delta:+.1f} ({'worse' if rank_delta > 0 else 'better'})")
    lines.append(f"Response size:       {resp_delta:+,.0f} chars")
    lines.append(f"Workflow pass rate:  {pass_delta:+.1%}")

    # Verdict
    lines.append("")
    regressions = []
    improvements = []

    if disc_delta < -0.05:
        regressions.append(f"Discovery accuracy dropped {abs(disc_delta):.1%}")
    elif disc_delta > 0.05:
        improvements.append(f"Discovery accuracy improved {disc_delta:.1%}")

    if pass_delta < 0:
        regressions.append(f"Workflow pass rate dropped {abs(pass_delta):.1%}")
    elif pass_delta > 0:
        improvements.append(f"Workflow pass rate improved {pass_delta:.1%}")

    if rank_delta > 0.5:
        regressions.append(f"Mean rank worsened by {rank_delta:.1f}")
    elif rank_delta < -0.5:
        improvements.append(f"Mean rank improved by {abs(rank_delta):.1f}")

    if regressions:
        lines.append("VERDICT: REGRESSION DETECTED")
        for r in regressions:
            lines.append(f"  - {r}")
        lines.append("ACTION: Do NOT merge. Investigate regressions before proceeding.")
    elif improvements:
        lines.append("VERDICT: IMPROVEMENT CONFIRMED")
        for i in improvements:
            lines.append(f"  + {i}")
        lines.append("ACTION: Safe to merge.")
    else:
        lines.append("VERDICT: NO SIGNIFICANT CHANGE")
        lines.append("ACTION: Change is neutral. Merge only if it improves readability/maintainability.")

    return "\n".join(lines)
```

**Step 2: Run to verify it imports cleanly**

```bash
cd ~/Documents/GitHub/mcp-servers
python -c "from security_remix.evals.ab_metrics import ABTestRun, compare; print('OK')"
```

Expected: OK (or adjust import path if needed)

---

### Task 3: Build the discovery accuracy test suite

**Files:**
- Create: `~/Documents/GitHub/mcp-servers/security-remix/evals/test_ab_discovery.py`

**Step 1: Write discovery accuracy tests**

These test whether `discover_tools` returns the expected tool for a set of canonical queries. This is the core A/B measurement.

```python
"""A/B test: tool discovery accuracy.

Runs canonical queries against discover_tools and measures whether
the expected tool appears in results and at what rank.

Usage:
    cd security-remix
    python -m evals.test_ab_discovery --label baseline
    # (apply changes)
    python -m evals.test_ab_discovery --label treatment-pgplpex
    # (compare)
    python -m evals.test_ab_discovery --compare baseline treatment-pgplpex
"""
import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from fastmcp import Client

from evals.ab_metrics import ABTestRun, DiscoveryMetric, ResponseMetric, compare
from evals.test_scenarios import (
    build_eval_server,
    call_meta,
    WorkflowTrace,
    scenario_triage,
    scenario_investigation,
    scenario_hash_block,
    scenario_execution_history,
)


# -----------------------------------------------------------------------
# Canonical discovery queries (prompt -> expected tool name)
# -----------------------------------------------------------------------
DISCOVERY_QUERIES = [
    # CrowdStrike
    ("search for security detections", "falcon_search_detections"),
    ("get details about a detection", "falcon_get_detection_details"),
    ("find hosts managed by falcon sensor", "falcon_search_hosts"),
    ("search for vulnerabilities on hosts", "falcon_search_vulnerabilities"),
    ("search falcon alerts", "falcon_search_alerts"),
    # Tenable
    ("search for vulnerabilities by severity", "search_vulnerabilities"),
    ("find assets by hostname", "search_assets"),
    ("get asset details by UUID", "get_asset_details"),
    ("export vulnerability data", "export_vulnerabilities"),
    # Airlock
    ("search endpoints managed by airlock", "airlock_search_endpoints"),
    ("check file hash reputation", "airlock_query_hash"),
    ("get execution history for a hash", "airlock_get_execution_history"),
    # MS Graph
    ("list risky users in identity protection", "list_risky_users"),
    ("get user sign-in logs", "list_sign_ins"),
    ("list security incidents from defender", "list_security_incidents"),
    # Cross-domain (ambiguous - tests ranking quality)
    ("check if a host has vulnerabilities", "search_vulnerabilities"),
    ("who signed in from a suspicious IP", "list_sign_ins"),
    ("block a malicious file hash", "block_hash"),
]


async def run_eval(label: str, results_dir: Path) -> ABTestRun:
    """Run full eval suite and collect metrics."""
    print(f"Building eval server for [{label}]...")
    server, pool, index = await build_eval_server()
    run = ABTestRun(label=label)

    async with Client(server) as client:
        # --- Discovery accuracy ---
        print(f"\nRunning {len(DISCOVERY_QUERIES)} discovery queries...")
        for query, expected in DISCOVERY_QUERIES:
            result = await client.call_tool("discover_tools", {"query": query, "limit": 5})
            # Parse result
            data = []
            if result.content:
                for block in result.content:
                    if hasattr(block, "text"):
                        try:
                            data = json.loads(block.text)
                        except (json.JSONDecodeError, TypeError):
                            pass

            names = [t["name"] for t in data] if isinstance(data, list) else []
            rank = names.index(expected) if expected in names else None

            metric = DiscoveryMetric(
                query=query,
                expected_tool=expected,
                returned_tools=names,
                rank=rank,
            )
            run.discovery_metrics.append(metric)

            status = f"rank={rank}" if rank is not None else "MISS"
            print(f"  {status:>8}  {query[:50]:<50} -> {expected}")

        # --- Response sizes (from workflow execution) ---
        print(f"\nRunning 4 workflow scenarios...")
        scenarios = [
            scenario_triage,
            scenario_investigation,
            scenario_hash_block,
            scenario_execution_history,
        ]
        for scenario_fn in scenarios:
            try:
                trace = await scenario_fn(client)
                if trace.success:
                    run.workflow_pass += 1
                else:
                    run.workflow_fail += 1
                run.total_calls += trace.call_count

                # Collect response sizes from execute_tool calls
                for call in trace.calls:
                    if call.tool == "execute_tool" and call.result is not None:
                        result_str = json.dumps(call.result) if not isinstance(call.result, str) else call.result
                        fields = len(call.result) if isinstance(call.result, dict) else 0
                        run.response_metrics.append(ResponseMetric(
                            tool_name=call.args.get("tool_name", "unknown"),
                            response_chars=len(result_str),
                            response_fields=fields,
                        ))
            except Exception as e:
                run.workflow_fail += 1
                print(f"  FAIL: {scenario_fn.__name__}: {e}")

    await pool.close()

    # Save results
    results_dir.mkdir(parents=True, exist_ok=True)
    run.save(results_dir / f"{label}.json")
    print(f"\n{run.summary()}")
    print(f"\nResults saved to {results_dir / f'{label}.json'}")
    return run


def load_and_compare(label_a: str, label_b: str, results_dir: Path):
    """Load two saved runs and compare."""
    a_data = json.loads((results_dir / f"{label_a}.json").read_text(encoding='utf-8'))
    b_data = json.loads((results_dir / f"{label_b}.json").read_text(encoding='utf-8'))

    a = ABTestRun(label=label_a)
    b = ABTestRun(label=label_b)

    # Reconstruct enough for summary (not full metrics, just aggregates)
    for key in ['workflow_pass', 'workflow_fail', 'total_calls']:
        setattr(a, key, a_data.get(key, 0))
        setattr(b, key, b_data.get(key, 0))

    print(f"\nLoaded {label_a}: {a_data}")
    print(f"Loaded {label_b}: {b_data}")

    # Compare key metrics
    print("\n" + "=" * 60)
    print("  A/B COMPARISON (from saved results)")
    print("=" * 60)
    for metric in ['discovery_accuracy', 'discovery_top3_accuracy', 'mean_rank',
                    'mean_response_chars', 'workflow_pass_rate']:
        val_a = a_data.get(metric, 0)
        val_b = b_data.get(metric, 0)
        delta = val_b - val_a
        direction = "better" if (delta > 0 and metric != 'mean_rank') or (delta < 0 and metric == 'mean_rank') else "worse" if delta != 0 else "same"
        print(f"  {metric:<25} {val_a:>8.3f} -> {val_b:>8.3f}  ({delta:+.3f} {direction})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A/B test tool discovery accuracy")
    parser.add_argument("--label", help="Label for this run (e.g., 'baseline', 'treatment-pgplpex')")
    parser.add_argument("--compare", nargs=2, metavar=("LABEL_A", "LABEL_B"), help="Compare two saved runs")
    parser.add_argument("--results-dir", default="evals/results", help="Directory for saving results")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)

    if args.compare:
        load_and_compare(args.compare[0], args.compare[1], results_dir)
    elif args.label:
        asyncio.run(run_eval(args.label, results_dir))
    else:
        parser.print_help()
```

**Step 2: Run baseline measurement**

```bash
cd ~/Documents/GitHub/mcp-servers/security-remix
python -m evals.test_ab_discovery --label baseline
```

Expected: Prints discovery accuracy, top-3 accuracy, mean rank, response sizes, workflow pass rate. Saves to `evals/results/baseline.json`.

**Step 3: Commit the eval harness (no server changes yet)**

```bash
cd ~/Documents/GitHub/mcp-servers
git add security-remix/evals/ab_metrics.py security-remix/evals/test_ab_discovery.py
git commit -m "feat: add A/B testing eval harness for tool description optimization

Measures discovery accuracy, rank, response size, and workflow pass rate.
Supports labeled runs (baseline vs treatment) with saved JSON results
and automated comparison with regression detection.

Research basis: arXiv:2602.14878, Anthropic 'Writing Effective Tools'."
```

---

## Phase C: Apply Changes with A/B Testing

### Task 4: A/B Test - Tool Description Augmentation (P+G+L+PEx)

**Files:**
- Modify: Mock backend tool descriptions in `security-remix/evals/test_scenarios.py`
- Run: `security-remix/evals/test_ab_discovery.py`

**IMPORTANT**: We test on mock backends first (not production servers). The mock backends in `test_scenarios.py` have simple one-line descriptions. We augment those to match the P+G+L+PEx pattern, then measure if discovery accuracy improves.

**Step 1: Verify baseline was captured in Task 3**

```bash
cat ~/Documents/GitHub/mcp-servers/security-remix/evals/results/baseline.json
```

Expected: JSON with discovery_accuracy, mean_rank, etc.

**Step 2: Create a copy of test_scenarios.py with augmented descriptions**

Create `evals/test_scenarios_augmented.py` that imports and overrides `make_backends()` with P+G+L+PEx augmented tool descriptions. Example transformation:

Before (current mock):
```python
@cs.tool(description="Search for detections using FQL filters.")
def falcon_search_detections(filter: str = "", limit: int = 10) -> str:
```

After (P+G+L+PEx augmented):
```python
@cs.tool(description="Search CrowdStrike Falcon detections using FQL filter syntax. Use to find security detections by severity, hostname, technique, or time range. Prefer over listing all detections when you know what you're looking for. Limitations: Read-only, cannot modify status. FQL dates require ISO 8601 with quotes. Max 5000 results.")
def falcon_search_detections(
    filter: Annotated[str, "FQL filter string. Common fields: severity, hostname, technique, created_timestamp."] = "",
    limit: Annotated[int, "Maximum results to return. Default 10, max 5000."] = 10,
) -> str:
```

Apply this pattern to ALL mock backend tools (CrowdStrike, Tenable, Airlock, MS Graph).

**Step 3: Run treatment measurement**

Modify `test_ab_discovery.py` to accept a `--augmented` flag that uses the augmented backends:

```bash
cd ~/Documents/GitHub/mcp-servers/security-remix
python -m evals.test_ab_discovery --label treatment-pgplpex --augmented
```

**Step 4: Compare baseline vs treatment**

```bash
python -m evals.test_ab_discovery --compare baseline treatment-pgplpex
```

Expected output (example):
```
  A/B COMPARISON
  discovery_accuracy       0.722 ->  0.833  (+0.111 better)
  discovery_top3_accuracy  0.889 ->  0.944  (+0.056 better)
  mean_rank                1.200 ->  0.800  (-0.400 better)
  workflow_pass_rate        1.000 ->  1.000  (+0.000 same)
```

**Step 5: Decision gate**

- If discovery_accuracy improved AND no workflow regressions: proceed to apply to real servers (Task 5)
- If discovery_accuracy dropped on any domain: investigate which descriptions caused regression, refine
- If no significant change: the descriptions are cosmetic-only, skip production rollout

**Step 6: Commit treatment results**

```bash
git add security-remix/evals/
git commit -m "test: A/B test results for P+G+L+PEx tool description augmentation

Baseline: {discovery_accuracy}% | Treatment: {discovery_accuracy}%
Delta: {+X}% discovery accuracy, {+Y}% top-3 accuracy
Verdict: {IMPROVEMENT/REGRESSION/NEUTRAL}"
```

---

### Task 5: Apply augmentation to real servers (only if Task 4 shows improvement)

**GATE: Only proceed if Task 4 verdict is IMPROVEMENT.**

**Files:**
- Modify: `~/Documents/GitHub/mcp-servers/airlock/airlock_mcp_server.py`
- Modify: `~/Documents/GitHub/mcp-servers/tenable/tenable_mcp.py`

**NOTE**: CrowdStrike uses falcon-mcp (external package) - its tool descriptions are NOT ours to modify. Skip it for now.

**Step 1: Apply P+G+L+PEx to airlock tool docstrings**

For each `@mcp.tool()` function, enhance the `description=` string (not the docstring - FastMCP uses `description` kwarg for MCP schema):
- **P**: What the tool does, when to use it (first sentence)
- **G**: Usage patterns, when to prefer this over alternatives
- **L**: Known constraints, rate limits, what it cannot do
- **PEx**: Already covered via `Annotated[type, "desc"]` on params

**Step 2: Apply P+G+L+PEx to tenable tool descriptions**

Same pattern as airlock.

**Step 3: Verify compilation**

```bash
python -m py_compile airlock/airlock_mcp_server.py && echo "OK"
python -m py_compile tenable/tenable_mcp.py && echo "OK"
```

**Step 4: Run ruff lint**

```bash
ruff check airlock/ tenable/
```

**Step 5: Do NOT commit yet** - batch with Task 6 changes.

---

### Task 6: A/B Test - Response Size Caps

**Files:**
- Modify: `~/Documents/GitHub/mcp-servers/shared/mcp_http.py` (if adding centralized cap)
- Modify: `security-remix/evals/test_scenarios.py` (add large-response test scenario)

**Step 1: Add a large-response scenario to test_scenarios.py**

Create `scenario_large_response` that calls tools known to return large data (e.g., `airlock_search_endpoints` with no filter, `airlock_get_execution_history` with broad query). Mock backends should return realistically-sized data (10KB+).

**Step 2: Run baseline measurement of response sizes**

```bash
cd ~/Documents/GitHub/mcp-servers/security-remix
python -m evals.test_ab_discovery --label baseline-response-size
```

Record: mean_response_chars, max_response_chars

**Step 3: Implement response cap in shared middleware**

Add to `shared/mcp_http.py` a configurable response cap:

```python
import os

MAX_RESPONSE_CHARS = int(os.environ.get("MCP_MAX_RESPONSE_CHARS", "100000"))  # ~25K tokens

def _truncate_response(text: str) -> str:
    """Truncate tool response if it exceeds the cap."""
    if len(text) > MAX_RESPONSE_CHARS:
        return text[:MAX_RESPONSE_CHARS] + "\n\n[Truncated at ~25K tokens. Use filters or pagination.]"
    return text
```

Integrate into the response path (the `_j()` serialization helper or equivalent).

**Step 4: Run treatment measurement**

```bash
python -m evals.test_ab_discovery --label treatment-response-cap
```

**Step 5: Compare**

```bash
python -m evals.test_ab_discovery --compare baseline-response-size treatment-response-cap
```

Check: response sizes decreased AND workflow pass rate unchanged (truncation didn't break any workflows).

**Step 6: Decision gate**

- If workflows still pass with capped responses: safe to merge
- If any workflow fails due to truncation: increase cap or add per-tool exceptions

---

### Task 7: Commit and PR for server changes (if A/B tests pass)

**GATE: Only proceed if Task 4 AND Task 6 both show IMPROVEMENT or NEUTRAL (no regressions).**

**Step 1: Commit all changes**

```bash
cd ~/Documents/GitHub/mcp-servers
git add security-remix/evals/ airlock/ tenable/ shared/mcp_http.py
git commit -m "feat: tool description augmentation + response caps with A/B validation

Tool descriptions: Applied P+G+L+PEx pattern to airlock and tenable.
A/B test: +X% discovery accuracy, +Y% top-3, no workflow regressions.

Response caps: Added configurable truncation (MCP_MAX_RESPONSE_CHARS,
default 100K chars / ~25K tokens) to shared middleware.
A/B test: response size reduced by Z%, no workflow regressions.

Research basis: arXiv:2602.14878, Anthropic 'Writing Effective Tools'."
```

**Step 2: Follow protected repo PR flow**

```bash
git checkout -b feat/research-validated-optimizations
git push -u origin feat/research-validated-optimizations

gh pr create --title "feat: A/B-validated tool description + response caps" --body "$(cat <<'EOF'
## Summary
- Augment tool descriptions on airlock, tenable with P+G+L+PEx pattern
- Add configurable response size cap to shared middleware
- Add A/B testing eval harness (ab_metrics.py, test_ab_discovery.py)

## A/B Test Results
- Discovery accuracy: baseline X% -> treatment Y% (+Z%)
- Response size: baseline Xk chars -> treatment Yk chars (-Z%)
- Workflow pass rate: 100% in both conditions

## Test plan
- [x] A/B eval harness passes (test_ab_discovery.py)
- [x] All 4 workflow scenarios pass (test_scenarios.py)
- [ ] py_compile on all modified servers
- [ ] ruff check passes

Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Wait for CI, then merge per git-hygiene rules.

---

## Phase D: Design Longer-Term Experiments

### Task 8: Document CoSAI + MCP 2025-06-18 audit designs

**Files:**
- Create: `~/Documents/knowledge-base/research/2026-03-04-cosai-audit.md`
- Create: `~/Documents/knowledge-base/research/2026-03-04-mcp-spec-compliance.md`

These are audit documents, not code changes, so no A/B testing needed. They identify gaps for future work.

**Step 1: Extract CoSAI threat taxonomy**

Use tavily_extract on the CoSAI blog to get threat categories. Map each against our hooks.

**Step 2: Create compliance checklist for MCP 2025-06-18**

Check FastMCP 3.1 support for each spec change. Identify gaps.

**Step 3: Commit audit documents**

```bash
cd ~/Documents/knowledge-base
git add research/2026-03-04-cosai-audit.md research/2026-03-04-mcp-spec-compliance.md
git commit -m "research: CoSAI security audit + MCP 2025-06-18 compliance checklist"
git push origin main
```

---

### Task 9: Design experience replay experiment (Experiment 3)

**Files:**
- Add to: `~/Documents/knowledge-base/research/claude-code-research-intelligence.md` (Experiment Backlog)

**Experiment Design:**

```markdown
### Experiment 3: Experience Replay Trajectory Capture

- **Hypothesis**: Injecting brief successful execution summaries from past sessions
  into new sessions via SubagentStart hook will improve first-attempt task completion.
- **Control**: Current system (topic files + learnings, no trajectory summaries)
- **Treatment**: Extend recent-sessions.md entries with 2-3 sentence trajectory summaries.
  SubagentStart hook injects the 3 most relevant past trajectories (matched by keyword
  overlap with current task prompt).
- **A/B measurement**: Track over 20 sessions:
  - First-attempt success rate (no "try again" or reformulation needed)
  - Tool selection accuracy (correct tool on first call)
  - Number of turns to task completion
- **Success criteria**: >5% improvement in first-attempt completion
- **Confounders**: Task type variance, model version changes. Control by running
  diverse task types in both conditions within the same week.
- **Duration**: 2 weeks (aim for 10 sessions per condition)
- **Rollback plan**: Remove trajectory injection from SubagentStart hook,
  revert recent-sessions.md format change
- **Status**: Not started. Requires modifying session-stop.py and subagent-start-context.py.
```

---

### Task 10: Design tool description optimization experiment (Experiment 4)

**Experiment Design:**

```markdown
### Experiment 4: Tool Description Optimization with mcp-tef

- **Hypothesis**: Running mcp-tef (open-source tool evaluation framework) against
  self-hosted servers will identify description conflicts and improvement opportunities
  beyond what P+G+L+PEx augmentation alone achieves.
- **Control**: P+G+L+PEx augmented descriptions (from Task 5)
- **Treatment**: mcp-tef-guided refinements (disambiguation of conflicting tools,
  differentiated descriptions for similar tools)
- **A/B measurement**: Run test_ab_discovery.py before and after mcp-tef changes
- **Success criteria**: >5% improvement over P+G+L+PEx baseline
- **Duration**: 1 session
- **Rollback plan**: git revert
- **Status**: Not started. Requires installing mcp-tef (npx or pip).
```

---

### Task 11: Final verification across all repos

**Step 1: Check all repos are clean**

```bash
# Knowledge base
cd ~/Documents/knowledge-base && git status --short

# MCP servers
cd ~/Documents/GitHub/mcp-servers && git status --short

# Claude config (if any hooks were modified)
cd ~/.claude && git status --short
```

**Step 2: Sync local main after any merges**

```bash
cd ~/Documents/GitHub/mcp-servers && git checkout main && git fetch origin main && git rebase origin/main
```

---

## Summary

| Phase | Tasks | What | A/B Test? |
|---|---|---|---|
| A | 1 | Update research report with all 18 findings | No (documentation) |
| B | 2-3 | Build eval harness + capture baseline | Baseline capture |
| C | 4 | Test P+G+L+PEx on mock backends | Yes - discovery accuracy |
| C | 5 | Apply to real servers (gated on Task 4) | Gated |
| C | 6 | Test response size caps | Yes - response size + workflow |
| C | 7 | Commit + PR (gated on Tasks 4+6) | Gated |
| D | 8 | CoSAI + MCP spec audits | No (audit documents) |
| D | 9-10 | Design experience replay + mcp-tef experiments | Experiment designs |
| D | 11 | Final verification | Cleanup |

**Decision gates:**
- Task 4 MUST show improvement before Task 5 proceeds
- Task 6 MUST show no regressions before Task 7 proceeds
- Tasks 5+7 are skipped entirely if A/B tests show regressions

**Estimated effort:** ~2 hours (Phase A: 30min, Phase B: 30min, Phase C: 45min, Phase D: 15min)

**PRs needed:** 0-1 (mcp-servers, only if A/B tests pass), 1 direct push (knowledge-base)
