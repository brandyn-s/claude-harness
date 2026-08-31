# /roundtable improvements runbook

Items surfaced by the 2026-05-02 frontier survey (~38 implementations
+ 13 academic papers; report at `~/tmp/roundtable-frontier-survey.md`).
Shipped items removed from this list when merged. Update this file
when an item lands; remove it from the runbook entirely.

## Already shipped

- **P0 #1 — Anti-sycophancy R3 prompt** (PR #816, 2026-05-02). Concession requires citing specific peer evidence; falsifier must reference what would re-flip. Source: focuslead/ai-council-framework + Free-MAD + ConsensAgent + duh.
- **#2 — `--anonymize-peers` opt-in flag** (PR #823, 2026-05-02). Per-prompt random shuffle of peer labels to "Agent A/B/C (anonymized)" in cross-exposure rounds. Self-identity preserved. Default off. Decision experiment (A/B run, ~$30) still pending: ship the flag-on-by-default if anonymized run produces sharper critiques. Source: karpathy/llm-council + 5 derivatives.
- **#4 — Post-hoc concession audit script** (PR #820, 2026-05-02). `scripts/audit_concessions.py` scans R3/R4 transcript records for CONCEDE/PARTIAL responses missing peer-evidence citation OR falsifier. `--strict` exits non-zero on any failure. Complements P0 #1 (preventive) by catching cases where the prompt didn't hold.
- **#5 (simplified) — Post-hoc claim factuality validator** (PR #824, 2026-05-02). `scripts/validate_claims.py` extracts verifiable claims (citations, version numbers, named studies, quantitative claims) from R3-R5 main outputs and tags each `[OK]`/`[WARN]`/`[FAIL]` via Tavily web search. ~$0.25/run. Chose post-hoc over runtime validator (the original spec): no harness changes, no inter-round latency cost, runs on demand for audit-class runs only. The runtime validator with logprob mode remains a future option if post-hoc shows enough claim-fabrication signal to justify the +$10-20/run runtime cost.
- **#6 Phase 1 — Selective-triggering instrumentation** (PR #821, 2026-05-02). `scripts/tag_run.py` + `runs.csv`. Auto-fills target_word_count and num_findings; prompts user to tag `multi_agent_useful=yes|no|unclear` per run. Phase 2 (classifier) gated on ≥10 tagged rows AND ≥30% `useful=no` rate. Currently at 1 row.
- **#7 — `--topology=star` opt-in flag** (PR #822, 2026-05-02). Drops Grok↔GPT direct cross-exposure; both see only Opus's outputs. ~25% cost reduction. Default unchanged (mesh). Source: Solvely-Colin/Quorum.

## Closed (measured, no action needed)

- **#3 — Drift measurement** (closed 2026-05-02). Measured drift on `2026-05-02-codegraph-roundtable` run using Becker et al's DRIFTJudge methodology (arXiv:2502.19559). Result: R1=5.00, R2=4.00, R3=3.67, R4=3.67, R5=4.33. **R1→R5 drop = 0.67**, below the 1.0 action threshold. /roundtable is drift-resistant on this protocol+target. Notable: drift was non-monotonic (R5 recovered above R4), suggesting the synthesis-style final round re-anchors agents to the original target. Full report: `~/Documents/knowledge-base/research/2026-05-02-roundtable-drift-measurement.md`. Re-trigger conditions documented; re-measure if round structures change or target class shifts to open-ended generation.

## Deferred — test-first, then decide

### #5 (full version) — `--validator` runtime fact-checker

**What**: Optional validator role that runs alongside (not within) the round dispatch. Validator reads each round's outputs, identifies factual claims (numbers, dates, citations, code references), uses web search to verify, and emits `[OK]` / `[WARN]` / `[FAIL]` markers. Markers injected into next round's prompt with explicit instruction: "Do NOT use claims marked `[FAIL]`."

**Why**: Complements Agent D — Agent D *tests* whether peers catch fabrications; Validator *prevents* fabrications from propagating. Different value.

**Real problem**: Real fabrications (not synthetic null-control) could pass through. v1 caught a false code claim only because peers happened to spot it.

**Adoption cost**: HIGH — substantial new role with web search. ~150-200 LoC. Per-run cost: +$10-20.

**Pattern source**: capitansuat/swarm-debate. Alternative: GranSabio_LLM's logprob-based detector (no web search needed, but requires logprob API access — Anthropic supports, xAI partial, OpenAI yes).

**How to ship**:
1. New `--validator [websearch|logprob|off]` flag, default `off`.
2. websearch mode: new `scripts/adapters/validator_adapter.py` calling Tavily for each extracted claim.
3. logprob mode: re-prompt agent with claim removed, measure logprob delta on the dependent assertion. If P(claim|evidence) ≈ P(claim|no_evidence), flag as ungrounded.
4. Markers injected into round N+1's per-agent prompt under `## Round N validator findings`.

**Decision rule before shipping**: estimate cost on a typical methodology review (~5 KB context, ~20 verifiable claims per round → ~$3-5 in Tavily, or ~10% extra tokens for logprob). If both fit budget, ship logprob mode as default (no external dep) and websearch as opt-in.

### #6 Phase 2 — Selective triggering classifier

**What**: After Phase 1 accumulates ≥10 tagged rows in `runs.csv`, analyze for discriminating features that predict whether /roundtable adds value over single-agent review. If a pattern emerges, add Step 0 triage that suggests skipping.

**Why**: $32/run is high. If 30-50% of targets don't benefit from full 5 rounds, we waste $10-16/run.

**Status**: DEFERRED until Phase 1 (PR #821) accumulates the data. Currently 1/10 rows.

**Codify if pattern emerges**:
1. If `target_word_count < N` correlates with `multi_agent_useful=no`, codify as a triggering threshold.
2. If structural features matter (specific keywords, target type), train a 41-feature classifier (iMAD pattern, arXiv:2511.11306).
3. Add Step 0 triage: emit "/roundtable is unlikely to add value for this target type; consider /fp-check or /interview" with confidence score.

**Decision rule**: only ship Phase 2 if Phase 1 shows ≥30% of runs are `multi_agent_useful=no` AND a discriminating feature is identifiable.

### #8 — Nonce-fenced XML against prompt injection

**What**: Wrap peer responses in `<nonce-XYZ>...</nonce-XYZ>` tags during cross-exposure. Critics instructed to ignore manipulation inside the fences.

**Why**: Security hardening if /roundtable is ever exposed to untrusted target inputs (user-supplied context from unsigned source).

**Real problem we have?** Not currently. /roundtable is invoked by the user with their own context. No untrusted inputs.

**Adoption cost**: ~30 LoC. Non-additive — changes every round's prompt structure.

**Decision rule**: ship only when the user has a use case for untrusted input (e.g., assessing a third-party RFC or external auditor's report that might contain prompt-injection attempts). Otherwise YAGNI.

**Pattern source**: 0ri/llm-council.

## Defended differentiators (do NOT lose to feature creep)

The frontier survey (n=~38) confirmed three genuinely uncommon features:
- **Pre-registration substep**: 0/38 — no community or academic implementation predicts what others will say before seeing them. The strongest unique value.
- **Null-control synthetic Agent D**: 0/38 — no implementation injects synthetic fabrications to test whether peers catch them. Distinct from runtime validators (swarm-debate, GranSabio, reviewer2) which are real fact-checkers, not test instruments.
- **Falsifier-required claims**: 1/38 — focuslead's reactive "evidence-required position changes" is close but not identical.

Drop any feature in this runbook before dropping these.

## Lost differentiator (stop claiming uniqueness)

**Embedding-based convergence detection** is no longer a differentiator. ~6/38 surveyed implementations have automated convergence (KS-statistic, Jaccard, response distribution shift). Voyage cosine isn't meaningfully different from KS-statistic on response distributions. Don't market this as unique going forward; keep it as a feature.

## Survey artifacts

Full survey report: `~/tmp/roundtable-frontier-survey.md` (frontier survey, n=~38, 2026-05-02).
Original 10-repo comparison: `~/tmp/roundtable-vs-github-comparison.md`.
