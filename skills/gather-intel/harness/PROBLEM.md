# Measurement harness — gather-intel community-intel efficacy (LIVE ARM)

A `build-measurement-harness` instance (recommendation #1, live arm) for
`gather-intel`. It answers: **does gather-intel's source-authority (T1-T5) +
adversarial framework correctly classify community claims (real / stale /
false / nonexistent) — by enough over a fair baseline (a strong single Opus
pass with web search, no framework) to justify its ~3-6× cost?**

## 0. Oracle-scope caveat (CARDINAL RULE honesty — read first)
gather-intel's HEADLINE value-prop is judging community-pattern **effectiveness /
hype / source-authority** (its Popularity-vs-Effectiveness + T1-T5 frameworks).
That has **no clean deterministic oracle** — "is this pattern effective / hype"
is not hand-verifiable the way a primary-source citation or a CHANGELOG entry is.
Per the cardinal rule ("if you can't construct an independent oracle, say so"),
this harness measures the surface that IS cleanly gradeable: **existence +
currency of community tools/patterns, and false-specific claims**. Two structural
limits, both disclosed in the verdict:
1. **Ecosystem density weakens `fabricated`:** the Claude Code community is so
   dense that "plausible fabricated tool" claims are usually REAL (verified
   2026-05-31: `claude-code-orchestrator`, `claude-supervisor`, orchestrator-kit
   all exist). So the fixture leans on `refuted` (false claims about real things)
   over `fabricated`, and the 3 fabricated claims use absurd specifics.
2. **Effectiveness/authority is not graded** — only existence/currency/falsity.

## 1. Classify the measurement (Phase 0)
- **Unit:** one community claim → `(verdict, cited_urls, confidence)`.
- **Decision under test:** gather-intel's source-authority scoring + adversarial
  search + currency discipline (Phase A/B).
- **Cost asymmetry:** ASYMMETRIC — asserting a stale community workaround as
  current, or confirming a hyped/nonexistent tool, is worse than a cautious UNCHARTED.
- **Class:** agent-benchmark, Mode C, n=15. Directional.

## 2. Oracle — independent ground truth (Phase 1)
1. **Hand-curated labels** verified against GitHub/web (tool existence) + the
   anthropics/claude-code CHANGELOG @ v2.1.158 (currency of community workarounds).
   See `fixture.json` `ground_truth` per claim.
2. **Deterministic term-overlap grounding** on the arm's cited URL.
Producer never judges itself; both arms share model + web_search.

## 3. Fixture (`fixture.json`) — 15 claims
| Category | n | Expected | Tests |
|---|---|---|---|
| `true_primary` (real community tools/patterns) | 5 | supported | true_recall + grounding (awesome-claude-code, orchestrators, CLAUDE.md, MCP servers, 3-worker heuristic) |
| `outdated` (platform-obsoleted community workarounds) | 3 | not_supported | refutation_recall (TaskOutput, Agent `resume`, "search is broken") |
| `refuted` (false claims about real things) | 4 | not_supported | refutation_recall (never-use-CLAUDE.md, "official certification", "always-linear throughput", over-generalized 64.5% stat) |
| `fabricated` (absurd-specific nonexistent) | 3 | not_supported | fabrication_resistance (ContextZip 90%-lossless, claude-code-telepathy, AgentForge cert) |

## 4. Metrics, A/B, operating points (Phase 7)
- **`grounding_precision`** (primary) — fetch-dependent (community GitHub READMEs
  are fetchable, so it works for existence claims).
- **`refutation_recall`** (recall-sensitive) — of `outdated`+`refuted` (n=7),
  fraction correctly NOT marked SUPPORTED. The framework's adversarial + currency
  discipline should help here.
- **`fabrication_resistance`** — of `fabricated` (n=3); weak category (see §0).
- **`true_recall`** — of `true_primary` (n=5); guards over-correction.
- **`verdict_accuracy`** — overall.
A/B: `with_skill` (source-authority + adversarial) vs `baseline` (strong plain
pass). N=3, mean+spread. Verdict via `grade.decide_verdict` (keep/trim/fix;
this copy's regression set includes true_recall, per the gather-claude finding).

## 5. Frozen baseline — the measured answer
<!-- RESULTS_TABLE_START : transcribed from results.json (N=3, claude-opus-4-8, 2026-05-31). -->
Measured 2026-05-31, N=3, `claude-opus-4-8`, n=15, both arms with hosted web_search:

| Metric | baseline (mean) | with_skill (mean) | Δ | with_skill stdev |
|---|---|---|---|---|
| **grounding_precision** (primary) | 0.833 | 0.878 | +0.045 | 0.088 |
| refutation_recall | 0.857 | **0.952** | +0.095 | 0.067 |
| fabrication_resistance | 1.000 | 1.000 | 0.000 | 0.0 |
| true_recall | 1.000 | 0.933 | −0.067 | 0.094 |
| verdict_accuracy | 0.933 | **0.956** | +0.023 | 0.031 |

**Verdict: `trim`.** The source-authority + adversarial framework is **directionally
net-positive** — better on refutation_recall (+0.095), grounding_precision (+0.045),
and overall verdict_accuracy (+0.023) — but **every delta is within the N=3 noise
floor** (per-metric stdev 0.03–0.09). The primary metric's +0.045 is under the 0.05
keep bar AND inside its own 0.088 spread. So the framework does not *clearly* beat a
strong searching baseline by more than its ~5× cost → trim (directional signal worth
noting; not a clean win).

Note the verdict was a `fix` false-trigger under a flat-0.05 regression bar (the
true_recall −0.067 dip just cleared 0.05); the **noise-aware** regression check
(`> max(0.05, stdev)`; this copy's `decide_verdict` refinement) correctly treats
−0.067 < 0.094-stdev as noise → `trim`. Contrast gather-claude's −0.20 true_recall
drop (> its stdev), which stays a real `fix`.
<!-- RESULTS_TABLE_END -->

## 6. REAL vs INSTRUMENT (Phase-9 check) — PERFORMED
Scorer proven non-trivial (`test_grader_instrument_fp_fn_zero`: 0.5/0.0 on mixed
synthetic); committed `runs/sample-records-2026-05-31.json` re-grades to
`results.json`. Transcript inspection confirms the metrics are REAL, not artifacts —
and pinpoints the **noise source**: both the grounding_precision <1.0 AND the
true_recall dip trace to the SAME claim, `three-workers-sweetspot` — the one fuzzy
"community *heuristic*" claim. Both arms marked it supported but cited general
worktree blogs lacking the specific "3-worker" terms (→ ungrounded), and the
framework CONTESTED it once (→ true_recall dip) — arguably correct for a contestable
heuristic. This is a concrete demonstration of the §0 oracle-scope caveat:
gather-intel's consensus/effectiveness claims aren't cleanly gradeable, while the
existence/currency/false-specific claims behaved cleanly. No mis-scoring found.

## 7. Truncation / freshness
hosted web_search `max_uses=5` (symmetric); grounding fetch 25s, non-200/JS →
grounded=False; `max_tokens=2000`; `claude-opus-4-8` (no temperature). `results.json`
pins model, fixture_sha, run_date, n_runs.

## 8. Provenance
Keys: `ANTHROPIC_API_KEY` only (hosted web_search + keyless grounding fetch).
