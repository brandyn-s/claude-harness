# Verification methodology for /scout-frontier findings

Run after Step 5 (Frame as "What Becomes Possible"), before Step 7 (Report). Every surviving finding gets tagged with confidence + URL status + any popularity-bias warning before it reaches the user.

## Critical Gotchas

- Do not default to WebFetch for URL resolution or attribution. Use this priority chain: **Firecrawl > Exa > Tavily > WebFetch**. Firecrawl is first because it natively decodes PDFs (Adapton/Pluto/JFP/Achille/Tup PDFs all extracted clean markdown in 2026-04-27 measurement). Exa is second for semantically-rich extraction including code context. Tavily is third for HTML-heavy structured content. WebFetch is the last resort because it returns "binary content saved" on PDF URLs without extracting text — the 2026-04-27 controlled re-run on Bazel showed URL resolution jumping 67% → 100% and attribution 60% → 100% on Firecrawl swap alone. Each step in the chain is a fallback when the prior tool refuses, rate-limits, or returns empty content.
- Do not present a finding as "verified" if URL resolves but content is paywalled — distinguish `[paywalled]` from `[hallucinated]`.
- Do not trust a single retrieval provider for citation attribution — cross-check with at least 2 of (Tavily, Exa, Firecrawl, arXiv direct). They use different ranking models (Tavily keyword/recency-biased, Exa embedding-based, Firecrawl crawl-based, arXiv structured-metadata). SAGE 2026 found provider variance is large: BM25-style retrieval still wins ~30% of comparable queries against LLM-based retrieval, and within-provider variance reaches 4.3× per arXiv:2604.03173.
- Do not skip popularity-bias filter when the topic is "frontier" — Algaba 2024-2025 measured 90% of LLM-generated valid references concentrate in top-10% most-cited papers. That bias is structurally anti-frontier.
- Do not treat counterfactual analogy tests as optional for cross-domain claims — Lewis-Mitchell 2024 demonstrated GPT models' analogy generalization collapses on counterfactual variants while humans remain robust.

## Check 1: Per-claim confidence calibration

Pattern source: Yuan et al., "Towards Trustworthy Report Generation: A Deep Research Agent with Progressive Confidence Estimation and Calibration" (arXiv:2604.05952, April 2026).

For each claim within the finding, tag confidence ∈ `{high, medium, low}`:

| Confidence | Criteria |
|---|---|
| **high** | Multi-source corroboration (≥2 independent sources), citations resolve, claim consistent with retrieved text |
| **medium** | Single high-quality source OR multiple lower-quality sources; citations resolve but content is single-perspective |
| **low** | Single source OR sources whose claims diverge OR citations partially unresolvable |

Calibration is per-claim, not per-finding. A finding can mix high/medium/low.

**Output format**: `[h]`, `[m]`, `[l]` tags inline next to the claim, OR a confidence column in the finding table.

## Check 2: URL health check

Pattern source: arXiv:2604.03173 "Detecting and Correcting Reference Hallucinations in Deep Research Agents" (April 2026): 3-13% of citation URLs hallucinated, 5-18% non-resolving across 10 deep-research models.

**Tool priority chain**: `mcp__firecrawl__firecrawl_scrape` → `mcp__exa__crawling_exa` (or `mcp__claude_ai_Exa__web_fetch_exa`) → `mcp__tavily__tavily_extract` → WebFetch. Each step is a fallback when the prior tool refuses, rate-limits, or returns empty content.

- **Firecrawl** (first): use `firecrawl_scrape` with `formats: ["markdown"]`. Natively decodes PDFs from PLDI/POPL/ICSE/FSE/NeurIPS proceedings.
- **Exa** (second): use `crawling_exa` for direct URL fetch or `web_fetch_exa` for the Claude.ai-hosted variant. Strong on semantically-rich extraction (highlights, code context).
- **Tavily** (third): use `tavily_extract` for HTML-heavy structured content. Good when Firecrawl is rate-limited and the source is not a PDF.
- **WebFetch** (last resort): only for known-HTML sources (GitHub READMEs, vendor blog posts) when all three MCP tools are unavailable. Returns "binary content saved" on PDFs without extractable text — see Critical Gotchas.

**Match tools by name suffix, not literal prefix** (`*__firecrawl_scrape`, `*__crawling_exa`, `*__web_fetch_exa`, `*__tavily_extract`) — MCP server prefixes are environment-dependent (see SKILL.md Preflight).

**If Firecrawl is not connected at all** (SKILL.md Preflight flagged a degraded stack): Checks 2-3 run on the Exa → Tavily → WebFetch fallback. Per the calibration log below, the WebFetch PDF path produced the *only* URL/attribution failures on record (Bazel-WebFetch: 67% URL / 60% attribution vs 100%/100% with Firecrawl). So when Firecrawl is absent, **downgrade confidence on any PDF-sourced finding** and record the degraded verification stack in the Step 7 telemetry footer — don't report literature-target gate compliance you couldn't actually measure.

For every URL in the finding:
1. Call `firecrawl_scrape(url=<url>, formats=["markdown"])`; inspect the returned markdown
2. Classify:
   - markdown non-empty + matches finding's claim → `[ok]`
   - markdown contains paywall/login phrasing ("subscribe to read", "sign in to access") → `[paywalled]`
   - HTTP 4xx returned by Firecrawl → `[non-resolving]`
   - HTTP 5xx returned by Firecrawl → `[server-error]`
   - timeout → `[timeout]`
   - markdown empty but file delivered (rare with Firecrawl) → `[ok-unparseable]`
3. If a URL is `[non-resolving]`, also check if the title/author exists via Tavily / Exa search — if yes, mark `[stale-link]`; if no, mark `[likely-hallucinated]`

**Threshold for action**: if >18% of URLs in a finding are non-resolving, flag the entire finding as suspect and surface the issue to the user before reporting.

## Check 3: Citation attribution check

Pattern source: CiteAudit (Yuan et al. 2026): 97% verification accuracy on generated benchmarks, 90% on real-world. CiteGuard (Choi et al. 2026): approaches human-level (68% vs 70%) at attribution.

For each citation:
1. Fetch the cited document (if URL resolves)
2. Verify the claim attributed to that citation actually appears in the document (paraphrase OK; substantive contradiction is not)
3. Tag attribution as `verified`, `partial`, or `not-found`

**Threshold**: target ≥90% of finding's citations should be `verified`. If <70% verified, flag the finding as low-confidence regardless of other checks.

## Check 4: Popularity-bias filter

Pattern source: Algaba et al. 2024-2025: LLM-generated references show strong popularity bias — 40-50% existence rate at baseline, with **90% of valid references falling among the top 10% most-cited papers**.

For each finding:
1. Pull citation count for each cited paper (Crossref / Semantic Scholar / OpenAlex)
2. Compute the % of cited papers in the top-10% most-cited for the field/year
3. If >70% of cited papers are in the top-10% most-cited → **flag as canonical, not frontier**

**This is the most distinctive frontier-detection check.** A finding that mostly cites canonical work is, by construction, not at the frontier — it is a reframing of established work. Surface this to the user as: "⚠ popularity-bias: this finding cites mostly canonical work; treat as canon-summary, not frontier."

## Check 5: Counterfactual analogy test (for cross-domain findings only)

Pattern source: Lewis & Mitchell, "Using Counterfactual Tasks to Evaluate the Generality of Analogical Reasoning in LLMs" (arXiv:2402.08955, 2024). GPT models' analogy performance declines sharply on counterfactual variants while humans remain robust.

Apply only when the finding makes a cross-domain claim ("X from domain A applies to B" or "this paradigm transfers across domains").

For each cross-domain claim:
1. Identify the structural relation being mapped (Gentner Structure-Mapping: relations, not attributes)
2. Construct a counterfactual variant — same relational structure, different surface (e.g., permute labels, invert direction, replace domain entities)
3. Ask: does the analogy still hold under the counterfactual?
4. If yes → `[robust-analogy]`. If no → `[surface-similarity-only]` and downgrade confidence to low.

**For abstract relations** (causality, temporal "before/after", spatial), expect lower reliability — Opiełka et al. 2025 showed LLMs lack invariant Concept Vectors for these. Apply more skepticism.

## Verification output format

Each surviving finding gets a verification block appended:

```
**Verification**:
- Per-claim confidence: [h] N claims | [m] N claims | [l] N claims
- URL health: N/N resolved | N paywalled | N non-resolving
- Citation attribution: N/N verified
- Popularity-bias: <ok | flagged: X% canonical>
- Counterfactual analogy: <robust | surface-only | n/a>
```

If any check fails its threshold, prepend `⚠` to the finding heading.

## Skip conditions

- **Check 5 (counterfactual)**: skip if the finding makes no cross-domain claim
- **Check 4 (popularity-bias)**: skip if fewer than 5 citations (statistical noise)
- **Check 3 (attribution)**: skip individual citations whose source is paywalled (note as `[unverifiable]`)
- All other checks: do not skip without explicit justification

## When verification is too expensive

If verifying every finding exceeds time budget, prioritize:

1. Top-tier findings (paradigm distance ≥3 OR explicit "frontier" framing) — verify all 5 checks
2. Tier-2 findings (distance 2) — checks 1, 2, 4 minimum
3. Tier-3 findings (distance 1) — check 2 minimum (URL health is cheap and catches the most common failure)

Document any skipped checks in the report.

## Literature target rates (soft targets, not auto-fail gates)

Section 10 of `research/2026-04-27-frontier-research-generic-framework-2024plus.md` recommends these rates as benchmark targets for production deep-research systems:

| Metric | Target rate | Source |
|---|---|---|
| Citation-attribution accuracy | ≥90% verified | CiteAudit (Yuan et al. 2026), CiteGuard (Choi et al. 2026) |
| URL resolution | ≥85% | arXiv:2604.03173 (Apr 2026), 5-18% baseline non-resolution |
| Reference existence (paper exists, not hallucinated) | ≥95% | arXiv:2604.03173 |
| Top-10% citation concentration | ≤70% | Algaba et al. 2024-2025, 90% baseline in unmitigated LLM outputs |

**These are reference targets, not auto-fail gates.** The existing thresholds in Checks 2-4 above (e.g., "if >18% of URLs in a finding are non-resolving, flag the entire finding") remain the active gates. Encoding the literature targets as hard gates requires measuring the actual distribution our `/scout-frontier` produces over multiple diverse runs — see "Measured rates" below for the calibration log.

If a single finding falls below the literature targets, that's data, not a failure. Use it to refine source selection, not to drop the finding.

## Measured rates (calibration log)

Tracking actual rates from `/scout-frontier` runs to determine whether the literature targets above are achievable floors or aspirational ceilings for our usage. Each row is one run; aggregate to assess distribution.

| Date | Incumbent | Tool | Findings | URL res. | Attribution | Top-10% conc. | Notes |
|---|---|---|---|---|---|---|---|
| 2026-04-27 | code-graph (Test 4) | WebFetch | 3 | 8/8 = 100% | 3/3 = 100% | flagged on Vaswani+Mamba | Smoke test, narrow query, mostly arXiv |
| 2026-04-27 | Prometheus-style TSDB | WebFetch | 5 | 5/5 = 100% | 5/5 = 100% | ~20% | Mostly industrial blogs/docs + 1 VLDB paper |
| 2026-04-27 | LangGraph (LLM orchestration) | WebFetch | 6 | 6/6 = 100% | 5/5 = 100% | ~33% | Mix of academic (arXiv/OpenReview/AAMAS) + GitHub + dev.to |
| 2026-04-27 | Bazel (monorepo build) | WebFetch | 6 | 4/6 = 67% | 3/5 = 60% | ~67% | **Heavy academic PDF set; WebFetch couldn't extract binary PDFs — tooling artifact** |
| 2026-04-27 | Bazel (re-run, controlled) | **Firecrawl** | 7 | 9/9 = 100% | 5/5 = 100% | ~31% | Same incumbent + similar candidate list, swapped tool. Firecrawl with `parsers:["pdf"]` extracted clean markdown from all 4 academic PDFs |
| 2026-04-28 | code-graph (full skill, post-upgrade) | Firecrawl | 7 | 7/8 = 87.5% | 7/7 = 100% | ~30% | Full skill run: Phase 0 validator passed, 12-query width-scaling, multilingual sweep 0-yield (domain limit), Eval-Optimizer not triggered. 1 DNS failure on browse.arxiv.org (alt arxiv.org resolves clean) |

### Summary across n=5 runs (2026-04-27)

| Metric | Median | P25 | Min (WebFetch) | Min (Firecrawl-only) | Literature target |
|---|---|---|---|---|---|
| URL resolution | 100% | 100% | 67% (Bazel-WebFetch) | 100% across all Firecrawl runs | ≥85% |
| Attribution | 100% | 100% | 60% (Bazel-WebFetch) | 100% across all Firecrawl runs | ≥90% |
| Top-10% concentration | ~31% | ~24% | n/a | n/a | ≤70% |

### Calibration verdict — Firecrawl is mandatory; gates are achievable with the right tool

The Bazel WebFetch run produced the only failures (67% URL, 60% attribution), but the controlled re-run with Firecrawl on the same incumbent jumped to 100% / 100%. This is **decisive evidence** that the prior failure was a tooling artifact, not a finding-quality issue. WebFetch returns binary content for PDF URLs that resolve correctly (HTTP 200, file delivered) but cannot extract text. Firecrawl with `parsers:["pdf"]` extracts clean markdown from those same PDFs.

**Required tooling for verification (Checks 2 and 3):**

1. **URL health (Check 2): use `mcp__firecrawl__firecrawl_scrape` with `formats: ["markdown"]`**, not WebFetch. Firecrawl natively handles PDFs (academic paper proceedings, technical PDFs from PLDI/POPL/ICSE/FSE/NeurIPS/etc).
2. **Citation attribution (Check 3): use `mcp__firecrawl__firecrawl_scrape` with `formats: ["markdown"]`**. The extracted markdown is required to verify the cited claim appears in the document — WebFetch on a binary PDF returns "binary content saved" without the text needed for attribution.
3. **Fallback only when Firecrawl is unavailable**: WebFetch is acceptable for HTML-only sources (GitHub, blog posts, vendor docs). For mixed sets, default to Firecrawl.

**Gate calibration with Firecrawl as the verification tool:**

With Firecrawl, most runs hit 100% URL resolution and 100% attribution (see calibration log: 2 of 2 Firecrawl runs shown achieved or exceeded targets). The literature targets (≥85% / ≥90%) become **comfortable floors**, not aspirational ceilings. Recommended gate values:

- URL resolution gate: **≥85%** (literature target, with ~15pp margin)
- Attribution gate: **≥90%** (literature target, with ~10pp margin)
- Top-10% concentration gate: **≤70%** (literature target — all 5 runs below threshold)

These are achievable as auto-fail gates *as long as Firecrawl is the verification tool*. Encoding gates while still allowing WebFetch on PDF-heavy domains will produce false-negatives — see the Bazel-WebFetch row.

**Status**: gates remain *soft* in this skill version because n=5 is still small and we have only one controlled tool-swap. After n≥10 with consistent Firecrawl tooling, promote to hard gates.
