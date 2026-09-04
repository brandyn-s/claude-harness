---
name: build-measurement-harness
description: "Build an instrumented measurement harness with two-source ground truth and freshness gates from day one."
when_to_use: Use at the start of any new measurement project — when the question "is this getting better?" must be answered defensibly for a system. Walks 10 phases that produce instrumented harnesses with two-source ground truth, stratified failure analysis, truncation auditing, and freshness gates from day one — instead of accruing the discipline through five-plus instrument-bug recurrences. Trigger phrases - "build harness", "build measurement harness", "instrument measurement", "set up accuracy harness", "measure quality of X", "how do I measure X", "harness for X". Do NOT use for diagnosing existing plateaus on an instrumented system (use /plateau-diagnose), per-PR validation of a single change (use /validate-changes), or quick one-off correctness checks where no longitudinal measurement is needed.
metadata:
  author: example-security-engineering
  version: "1.0"
  body-cap: exempt
  body-cap-reason: "PERIODIC: once-per-project harness bootstrap ('at the start of any new measurement project'), 20-50 turns; no requires_skills edge into it"
allowed-tools: Bash Read Write Edit AskUserQuestion
effort: high
---

# Build Measurement Harness

> Ten-phase recipe for instrumenting a new measurement project so that aggregate metrics, per-cell failure analysis, and instrument-vs-system disambiguation all work from the first baseline. The recipe is the inverse of `/plateau-diagnose`: that skill operates on an instrumented system; this one produces the instrumentation.

## Provenance

Every phase below corresponds to a recurring failure mode in code-graph's six-week buildout (Mar 14 – May 2, 2026, 163 PRs). The architectural commitments this skill captures came from five separate instrument-bug recurrences across four fixtures and two languages. Codifying them upfront means project #2 doesn't have to relive that arc.

## When to invoke

- You're starting a new measurement project (retrieval quality, agent benchmark, rule precision, edge extraction, calibration accuracy).
- You're auditing an existing measurement system for the gaps this recipe addresses.
- You're about to publish a baseline number and want to verify the instrument before treating the number as load-bearing.

## When NOT to invoke

- Diagnosing an existing plateau on a system already instrumented per this recipe → `/plateau-diagnose`.
- Per-PR validation of a single behavior change → `/validate-changes`.
- One-off correctness check with no longitudinal "is this getting better?" question → write the test directly.
- The system is not yet measurable in principle (no oracle exists, no labeled set is feasible). Stop and design the oracle before this recipe is useful.

---

## Phase 0 — Classify the measurement

Answer four questions in writing before continuing. The classification drives Phase 1's oracle design and Phase 4's stratification dimensions.

1. **What is the unit being measured?** (edge, finding, ranked-list item, prediction, label, span)
2. **What does success look like?** (binary correct/incorrect, ranked relevance, calibrated probability, span overlap, top-K presence)
3. **What is the cost asymmetry of FP vs FN?** Symmetric or asymmetric? If asymmetric, which is worse and by how much?
4. **What measurement class does this fit?**
   - **graph-extraction** (call edges, type relationships, import graphs, dataflow edges) → load `references/oracle-graph-extraction.md`
   - **retrieval** (semantic search, ranking, top-K relevance, RAG context selection) → load `references/oracle-retrieval.md`
   - **agent-benchmark** (Loc-Bench, SWE-bench, MultiSWE-bench, prediction-on-labeled-corpus tasks) → load `references/oracle-agent-benchmark.md`
   - **static-analysis** (rule precision, vulnerability findings, lint detections, custom matchers) → load `references/oracle-static-analysis.md`
   - **other** → no class-specific reference; design the oracle from scratch using Phase 1's universal requirements

If you cannot articulate (1) and a candidate oracle for (2), **the system is not yet measurable**. The deliverable is "make this measurable" before any tuning work.

**Output of Phase 0**: a one-paragraph problem statement naming the unit, success criterion, cost asymmetry, and measurement class. Save as `harness/PROBLEM.md` (or equivalent) in the project. This document is referenced by every subsequent phase.

---

## Phase 1 — Two-source oracle

Load the class-specific reference identified in Phase 0. The reference covers source selection, calibration protocols, and class-specific gotchas. Universal requirements that apply regardless of class:

- **Independent**: oracle does not share code, parser, or assumptions with the system under measurement. Code-graph's tree-sitter resolver and PyCG/syn/go-callgraph oracles use entirely different parser stacks; that independence is what makes disagreement informative.
- **Reproducible**: same input → same output across runs. If the oracle is an LLM-judge, this means seed pinning + temperature 0 + cached responses for replay.
- **Sanity-checkable**: oracle on a tiny known input matches hand-verified expectation. This becomes Phase 2's tiny fixture.
- **More-correct-than-system**: the oracle should be authoritative on the inputs where it disagrees. If you can't argue why the oracle is more likely correct, you don't have an oracle — you have a second system.

**FORBIDDEN**: using your own system's output as the ground truth (circular). **FORBIDDEN**: treating "the oracle agrees with my system" as evidence the oracle is correct (could be shared bias).

**Output of Phase 1**: oracle source documented, reproducibility verified, calibration metrics if applicable (Cohen's Kappa for hand labels or LLM-judge, inter-rater reliability for multi-labeler corpora).

---

## Phase 2 — Tiny known-truth fixture

Build a ≤20-unit hand-verifiable fixture where ground truth is trivially enumerable by hand. Run the full measurement harness end-to-end against it.

**Required gate**: verify **FP=0, FN=0**. Not "the harness ran" — every expected positive matched, every expected negative absent.

If FP or FN is nonzero on the tiny fixture, the harness is broken. Stop. Do not run on real data. Fix the harness, re-run the tiny fixture, repeat until clean.

This phase enforces the rule from `~/.claude/rules/verify-effectiveness.md` ("prove the instrument before publishing the measurement"). Code-graph's PR #64 incident (recall=0.20 published, real recall=0.98, cause was undocumented `query_graph` 200-row default) is exactly the failure this phase prevents.

**Output of Phase 2**: tiny fixture committed under `harness/fixtures/tiny/`, harness output showing FP=FN=0, hand-verified manifest of expected positives/negatives.

### Identity-bound production acceptance fixtures

For a production canary that reads or mutates user-scoped data, the fixture is
not valid until it proves which identity it is exercising. Before seeding or
mutation, assert the token subject and tenant against the managed canary
identity; fail closed on mismatch, expired refresh state, interaction-required,
or fallback to a human account.

Use one versioned fixture manifest for seed, probe, expected result, cleanup,
and replay. Test the production response envelope, not a hand-shaped mock of the
upstream API. Include continuation/pagination assertions where the capability
promises complete traversal, and design cleanup to be idempotent after partial
failure. For Outlook-style acceptance, a compact fixture should cover nested
folder resolution, attachment metadata plus content retrieval, calendar event
creation/readback, and online-meeting behavior when the canary identity is
licensed and provisioned for it.

**Output**: the acceptance receipt binds source SHA, deployed digest, canary
identity, fixture version, exercised operations, continuation state, cleanup
status, and value-free pass/fail evidence. Never store message bodies,
attachment bytes, tokens, or passwords in the receipt.

---

## Phase 3 — Synthetic negative fixtures

Build 3-5 small cases, each isolating ONE failure pattern you expect or have observed. Each fixture should reproduce a specific phantom or miss in <50 lines of input.

Code-graph's pattern (Era 6): four hand-built Rust fixtures (rust-actix-data, rust-diesel, rust-futures-ready, rust-restate-chain), each targeting a distinct phantom co-hallucination pattern. Each fixture exercised exactly one resolver path and was the unit-test analog for the discrimination ladder.

**Selection criterion**: each fixture should fail in a measurable, distinct way under the current system. Fixtures that all pass don't add information. Fixtures that all fail in the same way are redundant.

**Synthetic fixtures complement the tiny fixture**: tiny fixture proves the harness can measure; synthetic fixtures prove the system handles known failure shapes correctly. Both are required.

**Output of Phase 3**: 3-5 synthetic fixtures committed under `harness/fixtures/synthetic/`, each with a one-paragraph README naming the failure pattern it exercises and the expected behavior.

---

## Phase 4 — Stratification dimensions

Define 3-5 categorical fields emitted on every measurement record. Without these, you have aggregate metrics and no way to find the failure cell. Aggregate F1 is identification-grade information only; per-cell F1 is fix-grade.

Code-graph emits: `caller_node_kind`, `resolver_rule`, `candidate_set_size`, `confidence_band`. Each has 3-8 distinct values; combinations form the contingency table that `/plateau-diagnose` Step 5 reads.

**Selection criteria**:
- 2-8 distinct values per dimension (too few → no discrimination; too many → cells too sparse to be statistically meaningful)
- Cheap to compute at measurement time (not post-hoc reconstruction)
- Plausibly correlated with failure mode (each dimension should be one you'd guess might explain failure mass concentration)

Class-specific dimension menus appear in the Phase 1 reference for each measurement class.

**Output of Phase 4**: stratification schema documented (field name, allowed values, computation source) and emitted on every measurement record. Validate that every record has every field populated (no nulls, no defaults).

---

## Phase 5 — Truncation audit

For every tool in the measurement chain, verify and document its truncation behavior. Silent caps turn a "census" into a "sample" without notice and produce baselines that look correct but aren't.

**Audit checklist**:
- **MCP tools**: read source for `max_rows`, `default_limit`, `pagination`, `page_size`. If the tool can return partial results without signaling, file an issue OR add `Truncated bool` and `EffectiveCap int` to result shape.
- **SQL/query engines**: run `COUNT(*)` on the underlying query and compare to returned row count. Mismatch = silent cap.
- **REST APIs**: make one over-sized request, inspect response for partial-result signals (`nextPageToken`, `X-Total-Count`, `has_more`). Absent signal + capped result = silent truncation.
- **Subprocess CLIs**: run `--help`, look for `--limit`, `--max`, `--top-k` flags whose defaults might cap output.
- **Embedding/scoring models**: input length caps that silently truncate long inputs.

If any tool caps without signaling, **fix the tool's contract first** (explicit truncation field) OR **bypass via sharding/pagination/raw queries**. Do not run the real baseline until the chain is audited.

This phase is `~/.claude/rules/verify-effectiveness.md`'s instrument-validation procedure as a mandatory gate. Code-graph's PRs #64-65 codified the truncation-signaling contract after the 200-row default produced a 78pp recall error.

**Output of Phase 5**: audit document listing every tool in the chain, its known caps, and the signaling mechanism (or workaround) for each. Any unsignaled cap is blocking until resolved.

### Phase 5b — Resilience for long runs against a remote service

Four integrity checks that bite specifically when a measurement run is **long** (hours, API-spend, throttle-prone), judges against a **remote service** (Bedrock, an API), and may need to be interrupted and restarted:

- **Glob provenance — the reader must not sweep sibling junk.** A metrics reader that loads `oracle_panel_*.jsonl` (or any wildcard) will silently include `*_smoke`, `*partial`, `*oldcode`, and the `.drops.jsonl` sidecar living in the same dir — mixing wrong-provenance rows into the real corpus. **Default the reader's glob to the narrowest pattern that matches ONLY current-run output, and log the matched filenames + row count before computing anything.** Eyeball the file list every run. (2026-06-20: a `compute_metrics` default glob would have mixed 854 smoke/partial/drops rows into 476 real ones; caught by listing the matched files first.)
- **Resumability — restart must not truncate collected work.** If the run writes incrementally (per-unit flush so a kill preserves partial progress — itself a requirement for any multi-hour run), then a restart must **append + skip-already-done**, never reopen the output in truncate (`"w"`) mode. Add a `RESUME` path: read the existing output, collect done-unit IDs, skip them, open in append (`"a"`). Prove it on the real partial file before relying on it (count lines == unique IDs; sample rows are complete). Mind the summary math: a resumed run's "kept this run" ≠ emit-file total — report both. (2026-06-20: the oracle harness opened emit with `"w"` and had no skip-existing; a naive throttle-retune restart would have destroyed ~4h / 457 rows of Bedrock-spent output. A `RESUME` env-guard + append-mode fixed it; the skip-filter was dry-tested on the 457-row file before relaunch.)
- **Transient-vs-deterministic error handling + circuit-breaker.** "Hard-fail on error → drop the unit" is correct ONLY for **deterministic** errors (parse / validation / context-limit — re-running changes nothing). For **transient** ones (network / connection / 5xx / timeout / throttle — the endpoint comes back), hard-fail turns a recoverable blip into permanent coverage loss. Classify the two; **retry only the transient class**; on a burst of consecutive transient drops, **circuit-break** (pause + probe-until-recovered) rather than burning units through a sustained outage; **capture every drop** (SID + error-class to a sidecar) and run an **auto-retry pass**; compute the coverage checkpoint **POST-retry**. (2026-06-20: a ~10-min Bedrock network blip caused 139 EndpointConnectionError drops = 34% of a day's coverage, because the retry matched only throttle strings; shipped as mcp-servers #600.)
- **Per-unit wall-clock timeout (the giant-unit-hang backstop).** A single pathological unit (a 2-3MB transcript that throttles on every attempt) can wedge a worker for the full `read_timeout × max_attempts` budget — CPU-flat but alive, OR SIGKILLed — poisoning the whole run and blocking every later unit. Bound it twice: a **tight per-call client timeout** (read_timeout sized to a real response, not a generous max), AND a **per-unit wall-clock deadline** that raises the retryable `timeout` class so the drop/auto-retry path frees the worker. (2026-06-21: read_timeout=300 × max_attempts=10 = a ~50-min worst-case per unit; two giant sessions hung the run twice across resumes before being capped + fixed in mcp-servers #610. The live-monitor must use a CPU-delta check — a wedged worker is *alive*, so a process-liveness check alone reads it as healthy; only CPU-flat-while-rows-frozen distinguishes hang from slow-giant.)

**Output of Phase 5b**: the reader's glob is provenance-scoped and logs its files; a tested resume path exists (append + skip-done, both counts reported); errors are classified transient-vs-deterministic with retry+circuit-breaker+auto-retry on the transient class and a POST-retry checkpoint; and no single unit can wedge the run (per-call + per-unit timeouts, with a CPU-delta-aware live monitor).

**Import, don't re-hand-roll — `bin/durable_run.py` implements all of Phase 5b.** A dependency-free library (`import sys; sys.path.insert(0, str(Path.home()/'.claude'/'bin')); import durable_run`) ships these behaviors so each new harness does not re-derive them under crash pressure (the 2026-06-23 Phase-F batch re-discovered all four the hard way before they were extracted):

- `classify(exc)` / `is_transient(exc)` — the transient-vs-deterministic-vs-auth-expiry split. `heal(fn, …)` wraps a call: retries the transient class with backoff, fails LOUD on the deterministic class (never retries a `ConflictException`/`ValidationException` — that burned 8 wasted retries pre-fix).
- `Checkpoint(path)` — atomic write-then-replace resume cursor (the Phase-5b resumability requirement).
- `unique_name(base, attempt, chunk)` — collision-proof resource/job names (a fixed job name colliding with a prior FAILED job is what made `_heal` retry a deterministic error).
- `run_json(cmd)` / `run_text(cmd)` — subprocess wrappers that NEVER bare-`json.loads` stdout: empty/non-JSON → transient-retry, truly unparseable → loud `DurableError` (replaces the `json.loads(empty_athena_stdout)` opaque crash).
- `success_marker(path, verified=<bool>)` — writes a `.done` ONLY when `verified` is true; a terminal-but-FAILED job must never leave a success marker (the false-`.DONE`-on-Failed-job bug).
- `assert_instrument_sound(measure, known_cases)` — the Phase-2 known-truth gate as an importable call (warns on a one-sided fixture; requires both a known-positive and a known-negative). Shipped as the #2 meta-improvement after the E2 bare-excerpt instrument flaw (4.8% → 86.9% once the instrument was fixed).
- `fail_loud(stage, item, exc, …)` / `ErrorLog` — structured, detailed, explicit errors (stage + item + exception + action) so a silent drop becomes a loud diagnostic, not guesswork.

Monitor a detached run by **terminal state + output growth**, not pid-liveness or fuzzy name match: a `.done`/`.fail` marker is the status; an exact resource ARN (not a substring of the job name) is what the monitor keys on — a substring match false-alarmed on an orphaned old-prefix job 5× on a succeeding run.

### Phase 5c — Throughput architecture for a CENSUS-scale run (choose before building, not after)

The resilience checks above keep a synchronous per-call run from *failing*; they do not make it *fast*. For a CENSUS-scale run against a throttled remote service (every unit judged, not a sample), measure the bottleneck first, then pick the request architecture — do NOT default to "loop calls + more workers."

- **Diagnose bottleneck by the CPU-to-wall-clock ratio.** If the worker burns minutes of wall-clock for seconds of CPU (e.g. 73 min / 12 s = 0.3%), the run is **I/O-and-throttle-bound on the remote API**, not compute-bound — adding workers makes it WORSE (more concurrent token-bursts → more throttling → more backoff). (2026-06-20: WORKERS 6→3 *raised* net throughput AND cut drops; past the TPS knee, concurrency is negative.) The fix is request-architecture, not parallelism.
- **For a TPS-bound census, prefer Bedrock BATCH inference over synchronous InvokeModel/Converse** (`CreateModelInvocationJob`): submit all records as JSONL in S3, poll/EventBridge for completion, read results from S3. It bypasses per-call TPS entirely and is **50% cheaper** than on-demand. VERIFIED CAVEATS that gate the choice (AWS docs, 2026-06-21 — do not skip these):
  - **No tool-calling and NO structured-output (`response_format`)** — each record is processed independently, no multi-turn. If your judge depends on a structured-JSON contract via Converse, you must port it to a parse-the-text-response form first (the oracle judge's `_extract_json` tolerance already does this — so it's portable, but verify per harness).
  - **Min 1,000 records per job** (max 50,000). A SMOKE (tens of records) CANNOT use batch — keep synchronous InvokeModel for smokes; batch is census-only. (A 557-session × ~10-inference run = ~5,570 records, clears the floor.)
  - **No SLA; jobs run async over HOURS** (AWS's own Claude-Haiku example: ~9 h/job). Batch trades LATENCY for throughput + cost — right for a census that doesn't need interactivity, wrong when you need a result this turn.
  - **10 concurrent jobs per model per region** (quota-adjustable); cross-region inference profiles in the job spread load across regions.
- **Decision rule:** smoke / interactive / <1,000 records → synchronous InvokeModel with the Phase-5b resilience. Census / ≥1,000 records / latency-insensitive → batch inference. The mistake is running a multi-thousand-record census synchronously and then tuning WORKERS to fight throttle that batch sidesteps by construction.

**Output of Phase 5c**: the request architecture is a documented CHOICE (synchronous-with-resilience vs batch) justified by the CPU/wall-clock bottleneck diagnosis and the record count, not a default.

---

## Phase 6 — Freshness gate

Identify what state changes invalidate a baseline measurement, and implement a gate that warns or hard-blocks when measurement is taken against stale state.

**Sources of staleness**:
- **Index/database**: code-graph uses `check_index_freshness` (project DB mtime vs binary mtime). PR #145 added this after PR #144 shipped a measured "win" that inverted to a regression on fresh indexes.
- **Source under measurement**: any commit on the system invalidates measurements taken on prior commits. Pin SHA in baseline files; warn on mismatch.
- **Oracle**: oracle updates require re-baselining. Version the oracle; warn when measurement and baseline use different oracle versions.
- **Tool-chain**: harness binary version, MCP server version, dependent library versions. Capture `harness_version` field on every measurement record.

**Output of Phase 6**: freshness gate implemented with at least source-SHA + oracle-version + harness-version pinning. Measurements taken against stale state produce a visible warning (or hard fail in CI).

---

## Phase 7 — Two operating points

Report measurements at two confidence thresholds:

- **All-bands** (recall-sensitive): everything the system emitted, regardless of confidence. Useful when missing an item is more costly than including a noisy one.
- **High-confidence** (precision-sensitive): only emitted records with confidence ≥ threshold. Useful when noise is more costly than misses.

Different consumers want different tradeoffs. A single F1 number hides this; two numbers force the consumer to pick the right view. Code-graph's harness reports both per-fixture; the divergence between them is itself a diagnostic signal.

**Threshold selection**: start with the natural split (e.g., medium-confidence boundary). Tune based on consumer use cases, not based on which threshold makes the metric look best.

**Output of Phase 7**: harness emits two metric vectors (all-bands, high-confidence) per fixture, per stratification cell. Both reported in baseline files.

---

## Phase 8 — Frozen baseline + per-subset CI regression gate

- Freeze a baseline file with current per-subset metrics. "Per-subset" = per-fixture × per-stratification-cell × per-operating-point. The natural subdivision of the project (per-language, per-rule, per-query-class — whatever is meaningful for the measurement class).
- Set a CI gate that fails on regression beyond a threshold. Code-graph uses 5pp F1 drop on aggregate scope-aligned, plus per-subset thresholds.

**Per-subset thresholds matter more than aggregate**: an aggregate F1 win can hide a single-subset regression. Code-graph's PR #144 looked like +3.3pp aggregate but inverted on fresh indexes; per-subset checks would have caught it earlier (and per-subset checks DID catch it once Phase 6's freshness gate fired).

**Output of Phase 8**: baseline file committed (`harness/baselines/<date>-<sha>.json` or equivalent), CI gate active, regression thresholds documented per subset.

---

## Phase 9 — Step 6 verification protocol

Wire the instrument-first gate of `~/.claude/rules/verify-effectiveness.md` ("Verify the instrument before fixing the subject") into the team's workflow. Whenever the harness identifies a failure cell holding ≥30% of failure mass:

1. Sample 3-5 edges from the cell at random.
2. For each, open the source code at the cited location and verify by direct inspection.
3. Classify each as REAL (system bug), INSTRUMENT (harness/oracle bug), or UNCLEAR.
4. **If ≥3 of 5 sampled are INSTRUMENT** → fix lives in the harness. File the harness bug. Do not fix the system. (This has happened five times in code-graph; the rule was promoted to T1 on 2026-05-02 after the third recurrence in three sessions.)
5. **If ≥3 of 5 are REAL** → cell is a real failure mode. Proceed to fix design. Then `/plateau-diagnose` and `/persona` operate as designed.
6. **If mixed** → expand the sample. Cell may contain two distinct sub-modes that need separate fixes.

**This phase is mandatory before any fix targeting harness output.** Skipping it is the #1 cause of fixes targeting instrument artifacts (THEME D revert, PR #144 → #145, May 2 2026).

**Output of Phase 9**: Step 6 protocol documented in the team's runbook. First failure cell that surfaces becomes the rehearsal — sample, classify, decide. The discipline is the deliverable.

---

## Final output

After all 10 phases, you should have:

- An instrumented harness producing per-subset stratified metrics
- Two-source oracle with documented independence and calibration
- ≤20-unit known-truth fixture passing FP=FN=0
- 3-5 synthetic negative fixtures, each isolating one failure pattern
- Truncation-audited tool chain with explicit signaling contracts
- Freshness gate covering source SHA, oracle version, harness version
- Two operating points (precision-sensitive + recall-sensitive)
- Frozen baseline with per-subset CI regression gate
- Step 6 verification protocol embedded in the team's workflow
- Phase 0 problem statement that ties the whole thing together

Then `/plateau-diagnose` and `/persona` work as designed when you hit your first plateau, and the failure mode "we shipped a fix and the metric moved but it was actually instrument noise" is structurally prevented.

## Class-specific references

- `references/oracle-graph-extraction.md` — call/import/type-relationship edges (code-graph pattern)
- `references/oracle-retrieval.md` — semantic search, ranking, RAG (code-search pattern)
- `references/oracle-agent-benchmark.md` — Loc-Bench, SWE-bench, prediction-on-labeled-corpus tasks
- `references/oracle-static-analysis.md` — rule precision, vulnerability findings, lint detections

## Related rules and skills

- `~/.claude/rules/verify-effectiveness.md` — instrument validation, tiny known-truth fixture procedure, and the Phase 9 dominant-cell gate (its own rule from 2026-05-02 to 2026-09-03)
- `/plateau-diagnose` — six-step diagnosis recipe; operates on a system instrumented per this skill
- `/persona` — hypothesis generation; used as `/plateau-diagnose` Step 1 when hypothesis space is unmapped
- `/validate-changes` — per-PR validation; complementary to longitudinal harness measurement

## Examples

**Example 1: New retrieval-quality eval for a code-search redesign**
User: "Set up an accuracy harness for the new chunk-augmentation pipeline."
Actions:
1. Phase 0 classifies as `retrieval` class → loads `references/oracle-retrieval.md`
2. Phase 1 selects Voyage embeddings + human-labeled gold queries (two independent sources)
3. Phase 2 builds a 15-query tiny fixture with hand-verified top-3 expectations; harness output matches FP=FN=0
4. Phase 4 stratifies by `query_class` (concept / API / debug), `rank_bin` (1, 2-5, 6-10), `retrieval_stage` (BM25 / vector / rerank)
5. Phase 5 audit catches `search_code` defaulting to top-5 silently; fixes via `k=20` explicit param
6. Phases 6-8 freeze baseline at `harness/baselines/2026-05-12-<sha>.json` with CI gate at 3pp HR@5 drop per query_class
Result: First plateau hits in Phase 9 protocol — 3-of-5 sampled "low-rank-bin" failures turn out to be oracle labels using outdated terms, not system bugs. Oracle gets updated; system was already correct.

**Example 3: Agent benchmark harness for /triage**
> User: /build-measurement-harness "measure /triage routing accuracy"
> Skill: Walks 10 phases. Phase 1 two-source ground truth: 50 historical
> triage decisions reviewed by two SMEs, FP=FN=0 on the known-truth fixture.
> Phase 3 synthetic negatives: 15 false-positive seeds (low-severity items
> mis-routed to incident channel). Phase 7 dual operating points: strict
> (precision-first, fewer routes) vs permissive (recall-first, more routes).
> Phase 8 frozen baseline at 88% precision / 92% recall.
> Result: Instrumented harness committed; future /triage changes get an
> automated regression gate.

**Example 2: Static-analysis rule precision for a new Semgrep ruleset**
User: "Measure rule precision/recall on the new custom rules before rolling out."
Actions:
1. Phase 0 classifies as `static-analysis` → loads `references/oracle-static-analysis.md`
2. Phase 1 picks CodeQL queries as the independent oracle (different parser stack from Semgrep)
3. Phase 2 builds an 18-finding tiny fixture from prior incident vulnerabilities; harness FP=FN=0 on second iteration
4. Phase 3 adds 4 synthetic negatives, each targeting one known false-positive shape
5. Phase 4 stratifies by `rule_id`, `severity`, `language`, `file_class` (prod/test/vendored)
6. Phase 6 freshness gate pins ruleset SHA + CodeQL pack version per measurement
Result: Two operating points reported per rule; the high-confidence band runs in CI, the all-bands band powers triage backlog.

## Success Criteria

- Phase 0 classification and `harness/PROBLEM.md` exist before any harness code is written
- Phase 1 two-source oracle: each measurement has an independent verifier (different code path / data source from the harness); reproducibility verified by re-running the oracle and getting the same verdict
- Tiny known-truth fixture passes FP=FN=0 before any real-data measurement runs
- Phase 3 synthetic negative fixtures: at least 3-5 hand-crafted negative cases, each isolating one observed/expected failure pattern, each failing distinctly under the current system
- Every measurement record carries the Phase 4 stratification fields (no nulls, no defaults)
- Truncation audit document lists every tool in the chain with explicit cap/signaling status; any unsignaled cap is resolved before baseline
- Freshness gate covers at minimum source SHA, oracle version, and harness version
- Phase 7 two operating points: harness reports at two thresholds (e.g., precision-favoring + recall-favoring) with documented tradeoffs
- Baseline file committed and CI regression gate active before the harness output is treated as load-bearing
- Phase 9 protocol is invoked the first time the harness surfaces a failure cell ≥30% of mass — REAL vs INSTRUMENT classification is documented for that first cell as the discipline rehearsal
