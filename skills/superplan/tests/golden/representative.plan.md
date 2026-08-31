# Plan: Lift PSM HTTP_CALLS extractor coverage

Demo: Indexed PSM graph reports METRIC HTTP_CALLS=30 (baseline 17) via bench/count_http_calls.py — observable by re-running the Metric Commands fenced block below.

Effort: L

## Session Context

- Files explored: `internal/pipeline/http_links.go` (HTTP-link pass entry point; drops templated-URL call shapes), `internal/tools/service_map.go` (downstream consumer of HTTP_CALLS edges)
- Decision: extend the existing HTTP-link pass rather than adding a new pipeline pass — pass ordering is load-bearing (structure → definitions → calls → HTTP links), so a new pass risks ordering regressions
- Constraint discovered: only literal-URL reqwest call sites resolve today; templated URLs are dropped silently
- Open question: whether path normalization should strip trailing slashes before edge matching

## Goal

Raise HTTP_CALLS edge extraction on the PSM repo from its measured baseline by handling the templated-URL call shape the extractor drops today.

## Target-State Baseline

- PSM HTTP_CALLS = 17 (cmd: `MATCH (a)-[r:HTTP_CALLS]->(b) RETURN count(r)` on indexed PSM)
- PSM source: 5 reqwest::get sites read at file:lines — all use literal-URL form
- Full findings in the sibling baseline file per Step 5a conventions

### Phase 3.5 Baseline

currently 17, expected 30

## Domains Involved

- MCP Development (primary) — code-graph fork; main thread; no MCP server (code task)
- Infrastructure/Cloud (supplementary) — CI workflow touch only

## Known Constraints

- Read-only through Phase 4; Step 5a is the single write-tool escalation
- Gotcha (topic file): extractor pass ordering is load-bearing — instrument inside the existing pass

## Execution Path

Python script + main-thread inline (code task; no agent-memory benefit beyond the loaded gotchas).

## Steps

### Phase A: Instrument and investigate

#### Step 1: Add drop-counter instrumentation to the HTTP-link pass
- **Tool**: Edit on internal/pipeline/http_links.go
- **Agent**: main thread
- **Depends on**: none
- **Gotcha**: pass ordering is load-bearing — instrument inside the existing pass, do not add a new pass
- **Expected output**: indexed PSM run logs a drop-counter line with per-shape counts
- Scope: Critical
Demo: re-index PSM and read the drop-counter line from the index log.

#### Step 2: Classify dropped call shapes
- **Tool**: Python script (bench/classify_drops.py)
- **Agent**: main thread
- **Depends on**: Step 1
- **Expected output**: shape histogram; templated-URL shape dominant
- Scope: Critical
Demo: histogram file lists the dominant dropped shape with counts.

### Phase B: Implement and verify

#### Step 3: Handle the dominant dropped shape in the extractor
- **Tool**: Edit + go test
- **Agent**: main thread
- **Depends on**: Step 2
- **Gotcha**: keep the change inside the HTTP-link pass (no new pass)
- **Expected output**: METRIC HTTP_CALLS rises above the baseline on re-index
- Scope: Critical
Demo: re-run the Metric Commands block and observe the lifted count.

## Dependency Summary

1 → 2 → 3

## Verification

Re-index PSM and confirm the metric moved; guards keep the existing suite green; the artifact probe inspects the emitted edges themselves (not the count), per the Goodhart-probe convention.

### Metric Commands

```bash
go test ./internal/pipeline/ -run TestHTTPLinks -count=1
echo "METRIC HTTP_CALLS=$(python3 bench/count_http_calls.py --repo psm)"
```

### Guard Commands

```bash
go test ./... -count=1
```

### Artifact Probe

```bash
python3 bench/dump_edges.py --type HTTP_CALLS --repo psm --limit 5
```

### Forbidden Actions

- Bash(rm *)
- Edit(file_path=/etc/*)
- Bash(git push --force *)

## Falsifiers

- **Phase A**: if the drop-counter shows zero drops on PSM, the "extractor drops a shape" diagnosis is wrong — the gap is downstream (matchAndLink, path normalization). Action: stop before Phase B, instrument matchAndLink instead. Derived from: measured
- **Phase B**: if METRIC HTTP_CALLS stays at the baseline value after the shape handler ships, the dominant-shape classification was wrong. Action: re-run the Step 2 histogram and re-diagnose. Derived from: extrapolated

## Execution

- For scripts: write to bench/classify_drops.py, execute with `python3 bench/classify_drops.py`
- For agent work: main thread inline; hand off to subagent-driven-development only if Phase B fans out
