# Eight-component harness map

(Extracted from SKILL.md 2026-07-24 to meet the 5000-word Q1 budget; content unchanged.)

`audit-skill` is the reference implementation of the eight-component
harness pattern in this repo. Other skills should look here when extending
their own verification surface. The entry test (verification asymmetry —
generation is more expensive than verification) holds for skill auditing:
generating a useful skill is hard; checking H1-Q3 lint codes against a
SKILL.md is cheap.

## Component table

| # | Component | Where in audit-skill |
|---|---|---|
| 1 | **Proposer** (generates candidates) | `bin/audit-skill.py` — the scanner; generates findings as Finding YAML records |
| 2 | **Oracle / verifier** (stratified) | `bin/audit-skill-oracle.py` — Layer A reproducer runner classifies findings as STILL-FIRES / STALE / MANUAL / ERROR; **Tier 1** mechanical (grep/AST/parse) — no LLM in the verifier loop |
| 3 | **Context engineering** | `audit-context.md` (ground truth for what counts as drift); `known-tools.yaml` (registry of valid MCP tool names); `known-external-paths.yaml` (path-claim allowlist) |
| 4 | **Tool surface** (minimal) | `Read`, `Bash`, `Grep`, `Write` declared in manifest. No specialized linters; bash + Python AST + regex are the universal primitives |
| 5 | **Orchestration / parallelism** | `--parallel=N` flag wires `ProcessPoolExecutor` over per-skill audits. Per-skill work is CPU-bound (regex + AST parse), so processes — not threads — are needed for real speedup; the GIL would otherwise serialize the workers. Findings cross the process boundary via pickle (Finding is a plain picklable class — string fields plus optional `path`/`line`) and are re-ordered to the deterministic `skill_names` sequence before reporting. |
| 6 | **Memory / skill library** | `audit-history.jsonl` (one row per `--all` run with per-code finding counts, git SHA, model version). `scripts/audit_history.py {append,diff,summary}` accumulates patterns across runs; "repeat-offender" codes are surfaced by `summary`. Suppression file (`audit-suppress.yaml`) is the per-finding memory layer |
| 7 | **Failure-detection middleware** | `scripts/backfill_reproducers.py` enforces the label contract (`type: manual` must pair with `label: unverified`); the suppression file gates downstream tooling away from known-noise findings. Loop-detection on the oracle reverify is documented in `bin/audit-skill-oracle.py` |
| 8 | **Observability / audit trail** | `--ndjson=PATH` flag emits one record per finding (replayable, grep-able). `--json` emits per-skill summaries; `--sarif` emits GitHub-code-scanning format. Finding YAML schema is the audit-trail record format. Phase 4 bundling is mechanical via `oracle.py report --phase1 NDJSON --phase2 WORKLIST` so the final artifact has the same guarantees as the gating steps. |

## Why audit-skill is the reference

**Why audit-skill is the reference**: it's the only skill in this corpus
with all eight components present in real form. Other skills should
study it before adding their own harness — most don't need all eight
(the entry test fails for operational/generative skills like `ship` or
`capture`), but for the ones that do (`mcp-forge-build`, `insecure-defaults`,
`variant-analysis`, `threat-model`), the structural pattern lifts almost
verbatim.

