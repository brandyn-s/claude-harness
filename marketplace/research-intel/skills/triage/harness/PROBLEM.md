# Measurement harness — triage prioritization+correlation efficacy (LIVE ARM)

A `build-measurement-harness` instance (recommendation #1, live arm) for `triage`.
Its value-prop is correct **prioritization** + cross-tool **correlation** of findings,
backed by a 14-article constitution. This harness asks: **does the triage framework
rank closer to an expert priority order and detect root-cause correlations better than
an unstructured "rank these" prompt — enough to justify its ceremony?**

## 0. Heavy-cluster data note
triage/investigate need real operational findings, but `run_live.py` is a standalone
keyed script and CANNOT call session MCP tools. So the fixture **bakes in** the data:
12 findings ABSTRACTED from documented incidents (rules/incidents/) — no live MCP, no
sensitive external data committed. The live A/B is just the Anthropic ranking calls.

## 1. Classify the measurement (Phase 0)
- **Unit:** one full triage of the 12-finding set → (ranking, correlation groups).
- **Decision under test:** the severity-scoring + cross-tool-correlation discipline.
- **Primary metric:** Spearman rank correlation (arm ranking vs expert ranking).
- **Secondary:** correlation-group pair-level F1 (did the arm group findings sharing a
  root cause?).
- **Class:** agent-benchmark, Mode C, n=12 findings. Directional.

## 2. Oracle — independent ground truth (Phase 1)
- **Expert priority ranking** (`expert_rank` 1..12): human-curated by uncontroversial
  severity logic (active credential exposure needing rotation > latency w/ workaround >
  cosmetic nudge).
- **`true_groups`**: factual root-cause groups ({f1,f2} process-env-leak, {f4,f5} ipv6,
  {f7,f11} windows-CRLF-write).
Arms see only the `finding` text (ranks/groups hidden); producer never sets the labels.

## 3. Fixture (`fixture.json`) — 12 abstracted findings
P0 credential leaks (f1,f2,f3) → P2 availability (f4,f5,f6) → P3 ops/test (f9,f12,f7) →
P4 cosmetic (f11,f10,f8). 3 true correlation groups + 6 singletons.

## 4. Metrics, A/B (Phase 7)
- **`spearman`** (primary): arm ranking vs expert. Hand-rolled (no scipy).
- **`group_f1`** (+ precision/recall): correlation detection.
A/B: `with_skill` (severity + explicit correlation framework) vs `baseline`
(unstructured "rank + note shared root causes"), both claude-opus-4-8, NO web_search.
N=3. Verdict (`grade.decide_verdict`, noise-aware): keep if framework beats baseline on
spearman/group_f1 beyond noise; fix if worse; trim if within noise.

## 5. Frozen baseline — the measured answer
<!-- RESULTS_TABLE_START : N=3, claude-opus-4-8, 2026-05-31. -->
| Metric | baseline (unstructured) | with_skill (framework) | Δ |
|---|---|---|---|
| **spearman** (primary) | 0.939 | 0.958 | +0.019 (within noise; stdev 0.015) |
| group_precision | 0.600 | 0.600 | 0.000 |
| group_recall | 1.000 | 1.000 | 0.000 |
| group_f1 | 0.750 | 0.750 | 0.000 |

**Verdict: `trim`.** Both arms rank **near-perfectly** (Spearman ~0.94-0.96 vs expert) and
detect correlations **identically** (F1 0.75). The framework's +0.019 Spearman is inside
its own 0.015 noise. A strong model does severity-ranking + root-cause correlation well
WITHOUT the 14-article ceremony → no measurable lift on this fixture. (group_precision
0.60 is a defensible oracle-boundary disagreement, IDENTICAL across arms: both grouped all
3 credential-exposure findings {f1,f2,f3} together, while the oracle split f3's curl
mechanism out as a distinct root cause — a symptom-vs-mechanism call, not an arm difference.)

Caveat: n=12 directional; this is a single triage scenario built from incidents — a
harder/larger or genuinely cross-tool-noisy finding set might separate the arms.
<!-- RESULTS_TABLE_END -->

## 6. REAL vs INSTRUMENT (Phase-9 check) — PERFORMED
Spearman + group grader proven on synthetic inputs (`test_spearman_grader`,
`test_group_prf`, `test_score_run_fp_fn_zero`: perfect ranking→1.0, reversed→-1.0, exact
groups→F1 1.0). Transcript inspected: both arms produced sane, near-identical outputs
(top-5 rankings match the expert top-5; both proposed the same 3 groups). The tie is REAL
(both strong), not a parse artifact. Committed `runs/sample-records-2026-05-31.json`
re-grades to `results.json`.

## 7. Truncation / freshness
No web_search; `max_tokens` 1500; `claude-opus-4-8` (no temperature). `results.json` pins
model, fixture_sha, run_date, n_runs.

## 8. Provenance
Keys: `ANTHROPIC_API_KEY` only. Cost: 2 arms × n_runs calls (~6 at N=3).
