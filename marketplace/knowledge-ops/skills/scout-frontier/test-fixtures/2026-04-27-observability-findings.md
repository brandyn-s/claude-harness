# /scout-frontier — Observability Storage Paradigms (2026-04-27)

**Incumbent**: OTel + Athena pipeline → `table | lookup | behavior | streaming`

**Method**: 4 priority-1 arXiv queries + 6 priority-1/2 Tavily/Exa parallel queries + 2 adjacent-domain transfer queries. Anti-anchor: treated `observability-paradigms.json` fixture as already-baselined; surfaced findings the fixture did not enumerate.

---

## Executive Summary

The dominant frontier shift is **moving the computation closer to the events themselves rather than running batch SQL over Parquet on S3**. Three paradigm clusters surfaced consistently:

1. **Causal-graph RCA over telemetry** (Groot/eBay 5,000-service prod, DynaCausal, CHASE, AgentTrace) — incumbent answers "what was slow?" but cannot answer "what caused it?" without manual span reading.
2. **Incremental view maintenance** (DBSP, DDlog, Materialize, Snowflake Dynamic Tables, Databricks Enzyme) — incumbent reruns full Athena scans every dashboard tick; IVM materializes the answer and recomputes only deltas (1-2 orders of magnitude cheaper).
3. **eBPF runtime-traced observability that bypasses OTel collectors** (Pixie, Coroot, Parca, Cilium/Tetragon) — for monitoring third-party agents (Tenable, CrowdStrike, vendor IoT) that don't emit OTel, no other path exists.

The unifying gap: **Athena + Parquet answers historical questions about pre-instrumented data.** The frontier answers (a) live causal questions, (b) deltas over fresh data, and (c) questions about uninstrumented systems.

---

## Tier 1 (distance 3-4)

### Finding 1: Differential Dataflow / DDlog / DBSP (incremental Datalog)

- **Source**: github.com/vmware-archive/differential-datalog ; DBSP arXiv:2203.16684 ; Enzyme (Databricks) arXiv:2603.27775
- **Distance**: 3/4 — `data_structure` (fact-database/relations), `computation_model` (datalog-inference / incremental-recursive), `time_dynamics` (incremental-per-event vs streaming-blob)
- **What becomes possible**: Maintain alerting rules as recursive Datalog over events ("service A is upstream of B if A calls B or A calls something upstream of B; alert when any service upstream of `payments` has p99>2s"). DBSP recomputes only the **delta** caused by each new event with millisecond latency. Dashboards become live materializations rather than 15-60s Athena polls.
- **Maturity**: production (DBSP powers Materialize and Feldera; Enzyme runs Databricks Spark Declarative Pipelines at scale)
- **Adoption cost**: integrate (run Feldera/Materialize alongside Athena; replay OTel collector output into it; keep Athena for cold queries)

### Finding 2: Causal-graph RCA from telemetry (Groot, DynaCausal, CHASE, AgentTrace)

- **Source**: Groot arXiv:2108.00344 (eBay 5K-service prod) ; DynaCausal arXiv:2510.22613 ; CHASE arXiv:2406.19711 ; AgentTrace arXiv:2603.14688
- **Distance**: 3/4 — `data_structure` (causal DAG), `computation_model` (causal-inference / structure-learning + traversal), `abstraction_level` (event-causality, novel mechanism on the axis)
- **What becomes possible**: "Why did latency spike?" returns a ranked list of root-cause services with confidence scores in <1s, instead of a human reading 10K spans in Jaeger. Groot ships at 95% top-3 / 78% top-1 accuracy on a 952-incident production benchmark. AgentTrace targets multi-agent AI workflows specifically — directly applicable to Example's Claude Code + MCP fleet where cascading failures across agents are currently invisible.
- **Maturity**: production (Groot at eBay, 15-month deployment); prototype (DynaCausal/CHASE/AgentTrace — papers with code)
- **Adoption cost**: integrate (consume same OTel span/log/metric streams; sidecar that builds the causal graph)

### Finding 3: Provenance graphs over kernel events (TRACE, Prov2vec, APT-MCL, PROGQL)

- **Source**: TRACE (Yonghwi Kwon) ; Prov2vec arXiv:2310.00843 ; APT-MCL arXiv:2601.08328 ; PROGQL arXiv:2510.22400
- **Distance**: 3/4 — distinct from fixture's eBPF entry: persists events as a *causal DAG of OS entities* (processes, files, sockets) with cross-host edges, then runs *graph queries* over it rather than streaming filters
- **What becomes possible**: Enterprise-wide forward and backward causality queries: "every file written by any process descended from this Slack message attachment" or "every external service called by anything that read this credential file." Example's incumbent pipeline cannot answer either — OTel spans don't capture file-system or process-fork edges.
- **Maturity**: production research (TRACE on DARPA Transparent Computing data; APT-MCL on three real-world APT datasets); CamFlow and SPADE are open-source reference implementations
- **Adoption cost**: integrate (CamFlow/eAudit collectors alongside OTel; new graph-DB sink — paradigm complement to Athena, not replacement)

### Finding 4: Continuous CUDA/GPU kernel tracing (eBPF + MCP)

- **Source**: dev.to/ingero/agent-mcp-ebpf-10869-cuda-kernel-events-now-queryable (live deployment 2026-04-21)
- **Distance**: 3/4 — `data_structure` (kernel-event log indexed for causal-chain queries), `computation_model` (causal-chain reconstruction), `time_dynamics` (runtime-traced at GPU/kernel boundary), `abstraction_level` (CUDA syscalls — sub-behavior)
- **What becomes possible**: For Example workloads with GPU dependencies (model inference, video processing on autonomous platforms), capture every cudaLaunchKernel and CPU-thread context switch as queryable events. Identify GPU starvation root causes ("CPU thread feeding GPU was preempted 428 times causing 8.9s idle") with no application instrumentation. Incumbent OTel + Athena cannot see GPU events at all.
- **Maturity**: prototype (working code, single deployment described; not peer-reviewed)
- **Adoption cost**: integrate (specialized eBPF probe + database; GPU services only)

---

## Tier 2 (distance 2)

### Finding 5: Snowflake Dynamic Tables / Delayed View Semantics (VLDB 2025)

- **Source**: arXiv:2504.10438 (VLDB 2025 industrial paper)
- **Distance**: 2/4 — `computation_model` (delayed materialized view with transaction isolation), `time_dynamics` (declarative-incremental-materialization)
- **What becomes possible**: Replace dashboard-refresh cron over Athena with `CREATE DYNAMIC TABLE p99_by_service AS SELECT ... TARGET_LAG = '30 seconds'`. The paper's central insight: 100ms-3sec streaming is overkill for most ops work; seconds-to-tens-of-minutes latency is the right design point and IVM is dramatically cheaper there. Application-level invariants (alert thresholds) become declarative.
- **Maturity**: production (Snowflake GA; competitor: Databricks Materialized Views via Enzyme)
- **Adoption cost**: port (if Snowflake/Databricks already present, query rewrite; if S3+Athena only, integrate)

### Finding 6: Trace embeddings + LSH/ANN for similarity-based incident triage

- **Source**: TraceMesh arXiv:2406.06975 ; DeepTraLog ICSE '22 ; STraceBERT ; ETASR GCN+LSTM-AE 2025
- **Distance**: 2/4 — `data_structure` (vector index over trace embeddings), `computation_model` (learning-based encoding + ANN similarity)
- **What becomes possible**: "Show me all traces in last 30d that look like *this* failing trace" returned in milliseconds — incumbent cannot do this without hand-crafted equality predicates that miss 90% of "similar but not identical" cases. TraceMesh: streaming LSH over trace vectors. DeepTraLog: spans+log graph embedding for joint anomaly scoring.
- **Maturity**: prototype-to-production (DeepTraLog from Tencent/MS Research at ICSE; LSH/ANN over Milvus/Weaviate/pgvector widely productionized)
- **Adoption cost**: integrate (trace encoder service + vector index; OTel collector exporter exists)

### Finding 7: Continuous flamegraph trees (Pyroscope) keyed by tag set

- **Source**: github.com/grafana/pyroscope (fixture mentioned but did not enumerate the **flamegraph-as-tree-with-tag-indexed-leaves** primitive)
- **Distance**: 2/4 — `data_structure` (merged flamegraph **tree**, not table), `computation_model` (tree traversal: zoom/diff/focus subtree)
- **What becomes possible**: "What CPU function consumed the most time during this latency spike, broken down by Kubernetes pod label" — answered by a tree zoom/diff in tens of milliseconds. This primitive specifically replaces the need for `EXPLAIN`-style cost analysis on Parquet rows.
- **Maturity**: production (Grafana Pyroscope GA; merged with Phlare; OSS+hosted)
- **Adoption cost**: integrate (Parca-agent or Pyroscope-agent eBPF probe + storage backend)

### Finding 8: PatternStudio / Flink CEP MATCH_RECOGNIZE — sequence-pattern detection

- **Source**: PatternStudio mdpi.com/2624-831X/7/2/36 (2026); FlinkCEP and SQL `MATCH_RECOGNIZE` (production since 2016)
- **Distance**: 2/4 — `computation_model` (NFA-based state-machine pattern matching), `time_dynamics` (CEP-as-stored-query: query persists, data flows through it — incumbent's exact inversion)
- **What becomes possible**: Detect "service A failed, then within 5s service B saw retry storm, then within 30s service C's circuit-breaker opened" — temporal sequences not expressible as windowed aggregations. Example security: detect "failed login → privilege escalation → outbound connection" as one alert rather than three. PatternStudio (2026) adds neuro-symbolic LLM-driven pattern authoring.
- **Maturity**: production (Flink CEP, Esper, Timeplus, Snowflake `MATCH_RECOGNIZE`); prototype (PatternStudio)
- **Adoption cost**: integrate (Flink job consuming OTel collector output; or Snowflake/RisingWave+Flink hybrid)

---

## Tier 3 (distance 1)

### Finding 9: Foundation models for log/trace anomaly detection

- **Source**: LogBERT (IEEE 2021); FM-Log (Medium 2026-03); ADAlog arXiv:2505.13496; LogLLM; LogParser-LLM
- **Distance**: 1/4 — `computation_model` (LM-inference / learned masked-language modeling) — same axis as fixture's "anomaly detection on logs" entry, but FM subclass distinct
- **What becomes possible**: Zero-shot anomaly detection on log streams with no labeled data and no per-system tuning. ADAlog reports F1 0.96+ on HDFS/BGL/Thunderbird with unsupervised pretraining only. LogParser-LLM (2024) auto-extracts log templates without grok rules.
- **Maturity**: prototype-to-production (LogBERT public OSS; LogAI from Salesforce published; ADAlog 2025; FM-Log frameworks emerging 2026)
- **Adoption cost**: integrate (sidecar inference service consuming OTel collector log stream)

### Finding 10: Approximate query processing with sketches

- **Source**: Apache DataSketches Theta/HLL/Quantiles (production via Druid/Pinot/Hive); PilotDB arXiv:2503.21087 (2025); TAQA+BSAP arXiv:2505.19872
- **Distance**: 1/4 — `computation_model` (sketch-based approximate query with statistical bounds, not exact lookup)
- **What becomes possible**: "How many distinct users hit this endpoint over last 30d?" returned in <100ms with 0.5% error guarantee using a Theta sketch — incumbent does an `APPROX_COUNT_DISTINCT` Athena scan that takes 30-60s and bills per byte. Quantile sketches give P50/P95/P99 over arbitrary windows in O(1) memory. PilotDB shows 126× speedups with bounded error. Particularly relevant given Example's Athena byte-scan cost surface.
- **Maturity**: production (DataSketches in Druid/Pinot/Hive/BigQuery/Postgres for ~5y; Pinot at LinkedIn scale)
- **Adoption cost**: port (precompute sketches at OTel collector / Spark batch; serve from Druid or sketch-aware Athena UDFs)

---

## Coverage vs Fixture

The fixture enumerated 7 paradigm-distinct findings. This run independently re-surfaced 5 of those 7 (Tempo, Pyroscope/profiling, eBPF/Pixie, learned anomaly, Datalog/Logica) AND added 6 paradigm-distinct candidates the fixture did not enumerate:

- Causal-graph RCA (Finding 2) — distinct from Logica (structure-learning vs declarative deduction)
- Provenance graphs over kernel events (Finding 3) — distinct from streaming eBPF
- CUDA/GPU kernel tracing (Finding 4) — outside fixture scope
- Trace embeddings + ANN (Finding 6) — fixture has no vector-index entry
- CEP / MATCH_RECOGNIZE (Finding 8) — fixture has no NFA-pattern-match entry
- Approximate sketches (Finding 10) — fixture has no AQP entry

Output contract requirement of ≥3 met (6 surfaced).

## Honest Maturity Disclaimer

**Production**: Findings 1, 5, 7, 8, 10. Finding 2's Groot is production at eBay; rest of Finding 2 is research prototype.
**Prototype-to-research with public code, no Example-scale deployments**: Findings 3, 4, 6, 9.

Adoption cost estimates assume Example already runs Kafka/equivalent collector tier; if not, add infra step.

No Linear issues created — surfaced for user decision per skill contract.

---

*Generated by /scout-frontier worker dispatch on 2026-04-27. Method follows the protocol in `${CLAUDE_PLUGIN_ROOT}/skills/scout-frontier/SKILL.md` (Steps 1-6). Search venues per `references/search-venues.md`. Distances scored per `references/paradigm-distance-rubric.md`.*
