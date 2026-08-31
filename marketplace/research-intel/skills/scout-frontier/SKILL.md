---
name: scout-frontier
description: "Scout paradigm-distinct approaches and cross-domain analogies with mode-collapse mitigation."
when_to_use: 'Use when scouting paradigm-distinct technical approaches, oblique reframing, cross-domain analogy generation, or frontier-technique discovery. Combinational variation at scale with verification. Trigger phrases: "scout frontier", "paradigm scout", "oblique", "cross-domain analogy", "frontier technique", "what else solves X", "industrial state of the art". Searches academic frontier (arXiv, ICSE/FSE/POPL/PLDI), industrial state-of-the-art, adjacent-domain transfer with mode-collapse mitigation. Outputs are drafts subject to user verification, NOT a discovery oracle. Do NOT use for transcendent novelty (see llm-creativity-ceiling.md), incremental peer comparison (use /scout), AI agent architecture research (use /gather-research), Claude Code community patterns (use /gather-intel), or single-topic deep dive (use /deep-dive).'
disable-model-invocation: false
argument-hint: "[required: domain or incumbent system, e.g., 'code intelligence engines vs our code-graph']"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  # Requires arxiv-mcp-server (academic search), tavily and exa (web search), and firecrawl (deep crawl of research lab sites and conference proceedings) MCP servers.
  requires:
    - mcp: arxiv-mcp-server
    - mcp: firecrawl
    - mcp: tavily
    - mcp: exa
allowed-tools: AskUserQuestion Bash Read Write mcp__arxiv-mcp-server__* mcp__arxiv-mcp-server__search_papers mcp__exa__* mcp__exa__web_search_exa mcp__firecrawl__* mcp__firecrawl__firecrawl_search mcp__tavily__* mcp__tavily__tavily_search
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


## scout-frontier

# Frontier Paradigm Scout

Find techniques that solve the same outcome **a different way** — not the same approach with better tuning. Optimized for surfacing industrial state-of-the-art and academic-frontier work that /scout's GitHub-keyword search misses.

**The bar for inclusion is paradigm distance ≥1 on the 4-axis rubric, not stars or incident-documented friction.** This skill explicitly tolerates higher false-positive rates than /scout to catch paradigm-replacement candidates that look like noise to incremental scouts.

> **When to use vs /scout**: /scout finds *better-implemented peers* (same approach, different details). /scout-frontier finds *different approaches* (different paradigm, possibly less-mature implementation). Run both for full coverage.

> **When to use vs /gather-research**: /gather-research is scoped to AI-agent architecture and audits/updates an existing research baseline. /scout-frontier is domain-agnostic and frames findings as "what becomes possible" relative to an incumbent system.

> **Output grounding (REQUIRED READ)**: before drafting recommendations, read `skills/_shared/output-grounding.md` and apply its three-layer contract (confidence + provenance + counterfactual) to every load-bearing claim. That file is NOT ambient — it was relocated out of `rules/` on 2026-08-26 after measuring EXPOSED=0 over 438 transcripts — so it is in context only if you read it. The `creative-output-grounding-check` PostToolUse hook is an advisory payload diagnostic only; it does not grade the later final answer. Skill instructions and final-output evaluation are the primary controls.

---

## Scope guard

Before extracting the constraint trace, verify the request is in-scope. If the user wants:
- **Same-paradigm peer comparison** (better-implemented versions of the same approach) → redirect to `/scout`
- **AI agent architecture research** (arXiv papers, lab blogs, framework updates) → redirect to `/gather-research`
- **Claude Code community patterns** (Reddit, HN, config repo tips) → redirect to `/gather-intel`
- **Single-topic deep research** on one well-defined question → redirect to `/deep-dive`
- **Skills registry mining** → redirect to `/scout-skills`

If out-of-scope, tell the user which skill to use instead, then stop.

---

## Preflight: confirm the search + verify stack

This skill is a 15-30 turn run that fans out across MCP search providers. **Before Step 0, confirm the providers are actually connected** — don't discover a missing server at Step 6 after spending the budget.

Required for full operation: **arxiv-mcp-server** (academic), **tavily** + **exa** (web/semantic), **firecrawl** (deep-crawl + PDF-decoding for verification).

1. **Match tools by suffix, not by literal prefix.** MCP server names are environment-dependent — a server can surface as `mcp__exa__web_search_exa` in one environment and `mcp__<uuid>__web_search_exa` in another. Detect each provider by the tool-name *suffix* (`*__web_search_exa`, `*__tavily_search`, `*__firecrawl_scrape`, `*__search_papers`), and use whatever the connected names are. Do not assume the literal `mcp__exa__` / `mcp__tavily__` prefixes resolve.
2. **Degrade explicitly, and record it in the Step 7 telemetry footer:**
   - **No arxiv** → run priority-1 academic queries through Tavily/Exa with `site:arxiv.org`/`site:openreview.net` instead; flag that structured metadata (categories, citation counts) is unavailable.
   - **No tavily** → proceed on Exa + Firecrawl; note reduced recency/news coverage.
   - **No exa** → semantic and cross-domain queries degrade to keyword search; **skip the multilingual sweep** (it depends on Exa's multilingual embedding) and say so.
   - **No firecrawl** → verification (Step 6 Checks 2/3) loses native PDF decoding. Fall back Exa `crawling_exa`/`web_fetch_exa` → Tavily `tavily_extract` → WebFetch, and **downgrade confidence on any PDF-sourced finding** — per the calibration log in `references/verification.md`, the WebFetch PDF path produced the only URL/attribution failures on record. Note the degraded stack in the report.
3. **Hard stop** if zero web-search providers (no tavily AND no exa AND no firecrawl) are connected: tell the user which servers are missing and that frontier scouting can't run without at least one, then stop.

The `compatibility.requires` block in this skill's frontmatter lists the canonical server names; this preflight is the runtime check that they (or suffix-equivalent renames) are present.

---

## Step 0: Extract Constraint Trace

Before profiling the incumbent, decompose the **system + end-state** into a structured constraint trace. The structural idea — represent reasoning as a chain of source-grounded, individually verifiable steps rather than free prose — is borrowed loosely from Bouras, "CrossTrace: A Cross-Domain Dataset of Grounded Scientific Reasoning Traces for Hypothesis Generation" (arXiv:2603.28924, March 2026). Caveat: CrossTrace's reported 99.7% step-grounding / 0% fabrication describe the fidelity of *its own dataset extraction from scientific papers* — they are NOT a property this step inherits, and the paper studies hypothesis-generation training data, not system decomposition. We adopt the *form* (grounded, checkable units), not the metric.

Required input from the user OR derived from the incumbent:
- **End state**: What success looks like concretely (not abstractly). E.g., "code-graph answers any architectural question on the monolith with ≥90% accuracy."
- **Current friction**: What the incumbent specifically fails at TODAY (not what it might fail at).

Produce a constraint trace:

```
constraint_trace:
  end_state: <concrete success definition>
  friction:
    - id: F1
      what: <observed limitation, e.g., "graph misses Go-to-Rust FFI edges">
      measured: <numeric baseline Step 5 will cite, e.g., "0/12 expected edges in fleet-mgr crate">
    - id: F2
      what: <observed limitation>
      measured: <numeric baseline>
    - id: F3
      what: <observed limitation>
      measured: <numeric baseline>
  abstracted_constraints:  # mathematical / structural essence (Gentner SME pattern)
    - <constraint 1, e.g., "incremental graph reconstruction under partial information">
    - <constraint 2, e.g., "cross-language symbol resolution in polyglot context">
  assumptions_baked_in:
    - <constraint we're treating as fixed but might be relaxable>
```

**Friction IDs are required.** Each friction entry gets an explicit `id` (F1, F2, ...) and a `measured` field with the numeric baseline. Step 5's `Expected improvement.Baseline` field will reference these by ID and copy `measured` verbatim — making the scout output's baseline match the constraint trace exactly, with no manual re-typing or drift. The legacy single-string format ("observation with embedded measurement") still passes the validator but is deprecated; new traces should use the structured form.

**Why this step exists**: 2024+ research on scientific novelty detection (Liu et al. arXiv:2505.24615 "Harnessing LLMs for Scientific Novelty Detection") consistently finds that LLM-only similarity matching misses paradigm-distinct work. Anchoring on **structured constraints** (not incumbent keywords) is what lets Steps 2-3 catch novel mechanisms.

**FAIL conditions for this step**:
- Friction stated without evidence ("it's slow") → ask user for measured baseline
- End state abstract ("better at understanding code") → ask user for measurable target
- ≥3 friction points with no abstracted constraint → trace is incomplete; the constraints should reduce friction to 1-2 axes
- abstracted_constraints is empty or missing → constraint trace incomplete; add at least 1 structural constraint to guide search

**Validator (REQUIRED before proceeding to Step 1):**

Save the trace as YAML and run the bundled validator:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/scout-frontier/scripts/validate_constraint_trace.py" /path/to/trace.yaml
```

Exit 0 = trace passes; proceed to Step 1.
Exit 1 = trace fails one or more FAIL conditions; address the listed gaps before continuing.
Exit 2 = malformed YAML.

**Forbidden:** proceeding to Step 1 with a trace that has not passed the validator. The validator catches the cold-start failure mode (smoke test 2026-04-27 confirmed: cold-start traces fail "no evidence in friction"; strong traces with measured baselines pass cleanly). This converts the prose FAIL conditions into a machine-checkable gate.

The trace becomes the comparison anchor for "what becomes possible" framing in Step 5.

## Step 1: Define the Incumbent

The user must name the **incumbent system** being compared against (e.g., "our code-graph", "our claude-proxy guardrail engine"). If the argument doesn't include one, ask.

Profile the incumbent on the 4-axis rubric (`references/paradigm-distance-rubric.md`):

```
incumbent: <name>
  data_structure:    <one of: graph | vector | tree | log | table | execution-tree | structured-index | fact-database | stream>
  computation_model: <one of: lookup | traversal | learning | lm-inference | datalog-inference | simulation | stitching | abstract-interpretation>
  abstraction_level: <one of: token | symbol | ast | scope | type | behavior | intent>
  time_dynamics:     <one of: static | static-with-incremental | incremental-per-file | streaming | runtime-traced | path-sensitive>
```

Source the profile from the system's actual code/docs — don't guess. This profile is the comparison anchor for every finding.

## Step 2: Search the Frontier (priority order)

Search venues in the priority order from `references/search-venues.md`. Use **all three** of Tavily, Exa, and Firecrawl — they have complementary strengths and surface different findings on the same query:

- **Tavily** (`mcp__tavily__tavily_search`): broad web search, news/blog topic, time-range filtering. Best for: "what's the state of X today?" surveys, recent conference proceedings.
- **Exa** (`mcp__exa__web_search_exa`): semantically rich phrase queries, category filtering (people/company/research-paper), highlights. Best for: "describe the ideal page" queries, cross-domain transfer, finding specific researchers.
- **Firecrawl** (`mcp__firecrawl__firecrawl_search`, `firecrawl_crawl`, `firecrawl_map`): deep crawl of a specific site (research lab, conference proceedings page, vendor docs). Best for: once a research lab or proceedings URL is known, mapping all linked papers; extracting structured data from a known site.

### Width-scaling (W&D 2026 pattern)

Default to **issuing many parallel calls in one reasoning step**, not chaining sequentially. Lin et al. (arXiv:2602.07359) measured +7.3pp on BrowseComp from width alone (62.2% with GPT-5-Medium vs 54.9% original GPT-5-High).

**For every priority-1 search round, fire one query per paradigm axis × per provider in parallel** — that's 4 axes × 2-3 providers = **8-12 parallel tool calls per round**, not the 2 calls (Tavily + Exa on a single query) that earlier versions of this skill specified. Firecrawl is the third provider when a research-lab or proceedings page surfaces and warrants deep-crawl.

**Per-provider result-size caps (REQUIRED to prevent context blowup):**

| Provider | Width-scaling cap | Reason |
|---|---|---|
| Tavily | `max_results=5` (hook-enforced) | already capped, ~1.2KB per result |
| arXiv | `max_results=10` | structured metadata, low per-result cost |
| Exa | `numResults: 8` (basic), **never** use `web_search_advanced_exa` in width-scaling rounds | advanced returns 500KB+ per call, blows up context. Reserve advanced for narrow follow-up only. |
| Firecrawl | not used in width-scaling — reserved for deep-crawl phase after a high-signal site surfaces | crawls amplify result size dramatically |

If you find yourself wanting >8 Exa results per call, you don't need wider — you need a *different* axis-aligned query.

### Reasoning-aware query construction (AgentIR 2026 pattern)

Chen et al. (arXiv:2603.04384) measured **68% on BrowseComp-Plus by embedding the agent's reasoning trace alongside the query** — vs 50% with conventional embedding (2× model size) and 37% with BM25. Embedding-based search engines (Exa, Firecrawl semantic mode) react to the *full prompt context*, not just keywords.

**Construct queries as `<one-sentence reasoning context> | <keyword query>`**, not bare keywords. Example:

| Bare query (loses context) | Reasoning-aware query |
|---|---|
| `"learned call resolution"` | `Looking for paradigms that solve cross-language symbol resolution differently from static graph traversal | "learned call resolution" GNN cross-language` |
| `"datalog code analysis"` | `Looking for declarative-rule-based code analysis as alternative to imperative AST walks | "datalog code analysis" incremental rules` |

For Tavily/Firecrawl keyword search, the leading reasoning trace is ignored at the ranker but biases the LLM's interpretation of returned snippets. For Exa semantic search, the trace materially changes ranking. Cheap to add; large empirical gain.

**When to drop the reasoning prefix:** for Tavily and arXiv keyword search, the prefix is optional and adds tokens with no ranker benefit. Empirically (smoke test 2026-04-27): Tavily snippet ranking was unchanged whether the reasoning prefix was included; Exa results were materially different. Default to **prefix everywhere** for consistency, but if token budget is tight, drop the prefix on Tavily/arXiv calls and keep it on Exa/Firecrawl.

Search venue priority:

1. **Academic frontier** — arXiv (`mcp__arxiv-mcp-server__search_papers`) for papers; Tavily + Exa for conference proceedings; Firecrawl to deep-crawl venue sites once located
2. **Industrial state-of-the-art** — mature systems whose names don't match incumbent's keywords (search by **paradigm name**, not feature). Tavily + Exa parallel; Firecrawl on vendor docs sites for deep dive.
3. **Adjacent-domain transfer** — paradigms from unrelated domains. Exa is strongest here (semantic phrasing).
4. **Community/practitioner** — last; /scout and /gather-intel already cover this surface

**Mandatory: at least 3 priority-1 (academic) queries before any GitHub keyword search.** This prevents anchoring on incumbent's keywords.

**Cross-domain query template**: for each major paradigm axis, generate one query that searches the axis name explicitly:
- `"learned <abstraction>" <domain>` (computation_model = learning)
- `"datalog <abstraction>"` (computation_model = datalog-inference)
- `"symbolic <abstraction>"` (computation_model = simulation)
- `"streaming <abstraction>"` (time_dynamics = streaming)
- `"<abstraction> stitching"` (computation_model = stitching)

### Diversity primitives (mode-collapse mitigation)

When generating queries OR cross-domain analogies OR finding framings, use the diversity primitives in `references/verbalized-sampling-template.md`. The primitives address Opus 4.7's documented mode-collapse on variation generation (KINTAL T4) and the LLM creativity tradeoff curve (`~/Documents/knowledge-base/topics/llm-creativity-ceiling.md`).

**Five primitives, integration points:**

1. **Verbalized Sampling** — generate N=5 candidate queries with assigned probabilities (0.02-0.09 each, summing to 0.20-0.40); each must differ in style, structure, or viewpoint. Apply at every cross-domain query round.
2. **Ordinary personas** — frame each candidate as written by "an analyst," "a maintenance engineer," "a careful reviewer," "a non-domain-expert reading the docs," or "a researcher in an adjacent field." NEVER use creative-celebrity personas (Steve Jobs / Brian Eno / Bezos) — they mode-collapse to stereotype.
3. **Factuality filter** — between Step 2/3 (search/score) and Step 5 (framing), ground each VS-surfaced candidate against literature retrieval (Tavily + Exa). Reject candidates that fail citation existence or cross-source corroboration. Tag unsourced-but-structural candidates as `[INFERRED]`. Tail samples reject at >50% — that is intended.
4. **Abstraction-then-mapping (YARN)** — for adjacent-domain queries, REPLACE the simple axis-name template above with the four-step procedure: decompose → abstract → map → translate. End-to-end "make a bio analogy" prompts mode-collapse; the explicit decomposition is mandatory.
5. **Counterfactual-test** — for each cross-domain candidate, generate the inverted counterfactual (the same analogy with the source-target relation flipped). If the analogy survives → recombination, downgrade confidence to LOW. If it collapses → potential extrapolation, maintain confidence. (Step 6 Check 5 already runs this at verification; the primitive extends it to candidate-generation phase.)

See `references/verbalized-sampling-template.md` for full prompts (verbatim templates), Critical Gotchas (8 items, lead with these), and integration table mapping each primitive to a /scout-frontier step.

**Caveat:** these primitives produce drafts subject to user verification, not authoritative findings. /scout-frontier operates within the LLM creativity tradeoff curve — combinational variation is reliable; transformational creativity is constrained per multi-source 2024+ evidence (Franceschelli & Musolesi 2026, Padmakumar 2025, Springer 2024) but the boundary is contested (some recent agentic-systems work and HuggingFace community discussion argue the ceiling is extensible). See `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md` and `~/Documents/knowledge-base/topics/knowledge-asymmetric-collaboration.md`.

### Multilingual sweep (fires once per run, after priorities 1-3)

English-only retrieval misses Chinese-language frontier work (Gitee, CNKI, Aliyun research blogs), Russian-language CS preprints (Cyberleninka, Habr.com), and other non-English venues. arXiv:2602.19446 (Feb 2026) documented multi-decade growth in non-English open-source content; the 2024-2026 multilingual retrieval research (e.g., Huang et al. EMNLP 2025 cross-lingual semantic compression) shows direct multilingual embedding outperforms translate-then-search.

**Sweep checklist:**
1. For each paradigm axis, run **one** Exa query in the target language using a multilingual phrasing (Exa's underlying embedding is multilingual). Use Russian, Chinese (simplified), or another high-volume CS-research language relevant to the topic.
2. For high-signal Chinese results: deep-crawl Cyberleninka / Habr / Gitee / CNKI subpages via Firecrawl.
3. **Caveat:** top-tier CS venues (PLDI/POPL/ICSE/FSE/VLDB/SIGMOD) remain predominantly English even from non-English researchers. The drift surfaces in implementation/community discussion more than in peer-reviewed frontier publication. Use this sweep to find *engineering practice and community signal*, not to substitute for English peer-review search.
4. **Skip condition:** if the incumbent is so domain-specific to English-language regulatory contexts (DoD, FedRAMP, etc.) that non-English contributions are unlikely, document the skip in the report.

See `references/search-venues.md` "Priority 5 — Non-English venues" for the venue list.

## Step 3: Score Each Finding

For every candidate, compute paradigm distance using the rubric:

```
distance = |{axis : finding[axis] != incumbent[axis]}|
```

Apply the rules from `references/paradigm-distance-rubric.md`:
- Score on **demonstrably implemented** capabilities, not paper claims
- For hybrid systems, pick the **dominant** primitive (the one driving query semantics)
- Distance is **orthogonal to quality** — a distance-0 system can be objectively better

## Step 4: Filter (FP-tolerant)

Surface a finding if **either**:
- Distance ≥ 1, OR
- Distance = 0 BUT the system claims a novel mechanism on an axis we didn't profile

Discard a finding only if:
- Distance = 0 AND no novel mechanism, OR
- Implementation maturity = "speculative" (paper-only, no working code, no demo)

**Higher FP tolerance is the explicit design.** /scout uses compare-by-need to gate findings (high precision, low recall on novel work). /scout-frontier uses paradigm distance to gate findings (lower precision, higher recall on novel work). The user is expected to filter further at decision time.

## Step 5: Frame the Finding (Outcome / Improvement / Test / Integration cost)

For each surviving finding, produce the full output schema. The schema makes
each finding **decision-ready**: outcome ties to a Phase 0 friction point,
expected improvement is quantified against the constraint trace's baseline,
the test is runnable in the lab, and the integration cost tells the user
how invasive adoption would be.

Use the schema in `references/finding-output-template.md`:

```
### Finding N: <name>

**Source**: <URL or DOI>
**Paradigm distance**: N/4 — differs on <axes>
**Implementation maturity**: <production | prototype | paper-only | speculative>
**Integration cost**: <Tier A/B/C/D> — <what's preserved / what's replaced>

**Outcome (what we get)**:
  <1-2 sentences. Reference the Phase 0 friction ID(s): "addresses F3".>

**Expected improvement**:
  - Friction addressed: <F1, F2, F3 — name the specific Phase 0 IDs>
  - Metric: <which measurable axis improves>
  - Baseline: <copy verbatim from friction[Fn].measured — no re-typing>
  - Target: <expected post-adoption value>
  - Confidence: <high | medium | low>
  - Source of estimate: <paper benchmark | vendor case study | derived>

**Test**:
  - Scenario: <runnable setup>
  - Pass criterion: <numeric threshold>
  - Method: <how to measure>

**Failure modes (regression detection)**:
  - <anti-signal 1: what would tell us adoption hurt the metric, not helped>
  - <anti-signal 2: secondary regressions to watch for during the spike>
```

**Integration cost** is scored against the 4-tier rubric in
`references/integration-cost-rubric.md` (A: integration on top; B:
structural change with substrate reuse; C: fundamental architectural
change; D: separate system). Orthogonal to paradigm distance — a
distance-4 finding can still be Tier A if it adds rather than replaces.

**Confidence grade** on the Target estimate:
- **high**: vendor production case study with similar workload + reproducible benchmark
- **medium**: paper benchmark on different but comparable data; vendor claim without case study
- **low**: derived from incumbent profile; analogy without measurement

**Required field discipline:**
- Outcome must reference a Phase 0 friction ID. Vague "improves X" should be revised before reporting (this is author discipline — no automated validator enforces it).
- Baseline copies friction[Fn].measured verbatim (no manual re-typing — eliminates baseline drift between Phase 0 and Step 5).
- Target has Confidence and Source — over-optimistic claims (95% F1 from a paper on different data) get tagged Low.
- Test must be runnable on Example infra. "Wait for industry adoption" is not a test.
- Failure modes are mandatory for Tier B/C/D findings (substrate-touching changes have real regression risk). Tier A findings still benefit from naming "what would tell us the new layer hurt rather than helped."

See `references/finding-output-template.md` for worked examples and field-by-field guidance.

## Step 6: Verify Findings

Before reporting, run each surviving finding through 5 verification checks. Hallucinated citations are the #1 known failure of deep-research agents (arXiv:2604.03173: 3-13% URL hallucination, 5-18% non-resolving across 10 models). Without verification, frontier discovery looks confident but cites work that doesn't exist or is misattributed.

| Check | Purpose | Fail threshold |
|---|---|---|
| 1. Per-claim confidence | Tag each claim `[h]`/`[m]`/`[l]` (Yuan 2026) | n/a — informational |
| 2. URL health | Resolve every URL; classify ok/paywalled/non-resolving/timeout | >18% non-resolving in finding |
| 3. Citation attribution | Verify each cited claim exists in source (CiteAudit 2026) | <70% verified |
| 4. Popularity-bias filter | % of cites in top-10% most-cited (Algaba 2024-2025) | >70% canonical → flag as "canon, not frontier" |
| 5. Counterfactual analogy | Does cross-domain claim survive permutation? (Lewis-Mitchell 2024) | Surface-only similarity → downgrade confidence |

For methodology details, citations, output format, and skip conditions, see `references/verification.md`.

**Mandatory output:** every surviving finding gets a `**Verification:**` block with confidence breakdown, URL health, attribution rate, popularity-bias status, and (if applicable) analogy robustness.

**Auto-fail rule:** if a finding fails Check 4 (>70% canonical citations), prepend `⚠ canon` to its heading and demote it below all paradigm-distance tiers in the report. The user can choose to keep it but should not see it as a frontier candidate.

### Evaluator-Optimizer loop on systemic failures

Pattern source: Anthropic "Building Effective AI Agents" — generator + evaluator iteration. When >50% of findings in a tier fail the same check, the search itself is the problem, not individual findings. Iterate.

**Trigger conditions** (any one fires the loop):
1. **>50% of findings fail Check 4** (popularity-bias) → search is anchored on canonical work. Loop back to Step 2 with two query modifications: (a) add `-"<top 3 most-cited author surnames>"` exclusion clauses, (b) add date filters restricting to last 24 months. Re-search. Re-verify.
2. **>50% of findings fail Check 3** (citation attribution) → retrieval surfaced citation-poor sources. Loop back to Step 2 with one modification: prefer venues with structured citations (arXiv, ACM DL, IEEE Xplore) over blogs/news.
3. **>30% of cross-domain findings fail Check 5** (counterfactual) → the constraint trace from Step 0 is too keyword-shaped, not relation-shaped. Loop back to Step 0 and re-derive `abstracted_constraints` using YARN-style structural decomposition (relations, not attributes). Re-search.

**Hard stop**: maximum 2 iterations. If a third iteration is needed, surface as "search anchored on incumbent paradigm; recommend manual query review" — don't loop indefinitely.

Document in the report: which checks triggered which loop iteration, and what changed between rounds.

## Step 7: Report

The report has two parts: the tiered findings (below) and a telemetry footer. **Always include the telemetry footer** so the user can see which phases produced value:

```
## Run telemetry

- Width-scaling: <N> parallel calls in <M> rounds
- Multilingual sweep: <K> findings net-new beyond English queries (0 = sweep added no value this run)
- Verification triggers: <P> findings flagged ⚠ canon | <Q> findings flagged via URL/attribution
- Evaluator-Optimizer loop: <fired N times | not triggered>
```

If the multilingual sweep produces 0 net-new candidates on 3 consecutive runs in the same domain, document and consider dropping it for that domain (skip-condition).

Group findings by paradigm-distance tier. **Within each tier, secondary-sort by integration cost (Tier A first → D last)** so the user sees the cheapest experiments first within each paradigm distance band.

```
## Paradigm-Distinct Findings (distance ≥1)

### Tier 1 — distance 3-4 (strongly different paradigm)
[findings sorted by integration cost: Tier A → B → C → D]

### Tier 2 — distance 2 (clear paradigm shift)
[same sort order]

### Tier 3 — distance 1 (single-axis variation)
[same sort order]

## Paradigm-Similar Findings (distance 0)
Listed for completeness; route to /scout for evaluation.
```

**Each finding's report block must include the full Step 5 schema** (Source / Paradigm distance / Maturity / Integration cost / Outcome / Expected improvement / Test / Verification). The Expected improvement and Test fields are what make the report decision-ready — without them the user has paradigm distance but no path to deciding which to spike.

Pause for user decision. **No issue creation in this skill** — surface findings, let user decide which warrant /scout or implementation issues.

## Step 8: Test-Fixture Validation (when adding new domain coverage)

When extending /scout-frontier to a new domain (beyond code intelligence), build a hand-curated test fixture in `test-fixtures/<domain>-paradigms.json` following the schema of `test-fixtures/code-intel-paradigms.json`:
- 5+ expected paradigm-distinct findings, **each with all 4 axis values** so distance is recomputable
- 5+ negative controls (paradigm-similar peers), **also with all 4 axis values** — a control with no axes can't be verified and the scorer will refuse to pass
- Feature-parity "traps" (a better-implemented *same-paradigm* system that should score 0) go in `negative_controls`, NOT in the expected set. A distance-0 entry in the expected set violates the TPR contract below.

Verify the rubric against the fixture:
- Every expected finding recomputes to ≥1 distance (TPR = 1.0)
- Every negative control recomputes to 0 distance (FPR = 0)

If either fails, the rubric needs revision for that domain. Do NOT publish "scout-frontier works for <new-domain>" until the fixture passes.

**Validate the rubric automatically** with the bundled scorer:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/scout-frontier/scripts/score_rubric.py \
  ${CLAUDE_PLUGIN_ROOT}/skills/scout-frontier/test-fixtures/<domain>-paradigms.json
```

The scorer recomputes distance from the 4 axes for **both** the expected set and the controls, then checks: TPR = 1.0 (no expected finding scores 0), FPR = 0 (no control scores >0), no arithmetic drift between computed and declared distance, and nothing unverifiable (every entry carries axes). Exit 0 = instrument valid; exit 1 = mismatch (investigate before publishing measurements, per `~/.claude/rules/validate-to-improve.md`); exit 2 = malformed fixture. Note: the scorer checks the fixture's *internal* hand-scoring is self-consistent and discriminating — it does not by itself prove a live search run scores correctly; that's what running the skill against the fixture exercises.

The bundled unit tests (`tests/test_score_rubric.py`, `tests/test_validate_constraint_trace.py`) cover both instruments; run `python3 -m pytest tests/` from the skill directory.

---

## Examples

**Example 1: Code intelligence engines**
```
/scout-frontier code intelligence engines vs our code-graph
```
Profiles incumbent (graph + traversal + symbol + static-with-incremental). Searches arXiv for "learned call resolution", "datalog code analysis", "incremental name resolution". Searches conference proceedings (ICSE/FSE/POPL recent). Searches industrial: Stack Graphs, Glean, SCIP, Sourcegraph. Surfaces ≥3 paradigm-distinct findings with distance ≥1. User decides which warrant Linear issues against code-graph.

**Example 2: Observability / telemetry storage**
```
/scout-frontier observability storage vs our OTel + Athena pipeline
```
Profiles incumbent (table + lookup + behavior + streaming). Searches for paradigm-distinct: column-stores (ClickHouse), trace graphs (Tempo's exemplar+span graph model), eBPF-driven runtime indexes, learned anomaly detection on logs. Reports findings grouped by tier.

**Example 3: Code-graph engine improvement (canonical positive — knowledge-asymmetric)**
```
/scout-frontier code intelligence engines vs our code-graph engine; user is no longer the
day-to-day maintainer and can't validate output by reading
```
Profiles incumbent. Diversity primitives fire: VS-generated cross-domain queries (5 candidates with probabilities, ordinary-persona attribution), abstraction-then-mapping for adjacent-domain analogies (decompose → abstract → map → translate, NOT end-to-end "make a bio analogy"), factuality filter rejects unsourced tail samples, counterfactual-test downgrades surface-similarity findings. Output: ≥3 paradigm-distinct findings each with confidence + provenance + counterfactual signal so the user can spot-check WHICH parts to verify rather than auditing the whole report.

**Negative example (do NOT use):** "Find me a transcendent novel approach to debugging that no one has thought of before." — That asks for transformational creativity / hyperpolation, which is constrained for LLMs per multi-source 2024+ evidence (see `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md` — tradeoff curve, contested at the boundary). /scout-frontier produces combinational variation at scale, framed against the tradeoff curve, not transcendent novelty. Reframe as: "Find paradigm-distinct debugging approaches across other domains" (combinational + cross-domain), which IS in scope.

---

## Success Criteria

- ✅ Constraint trace extracted (Step 0) with concrete end-state and evidence-backed friction
- ✅ Incumbent profiled on all 4 axes from actual source/docs (not guessed)
- ✅ Priority-1 academic search executed before any GitHub keyword search (prevents incumbent-keyword anchoring)
- ✅ Cross-domain queries fired for each axis (prevents single-paradigm bias)
- ✅ Every finding scored on the 4-axis rubric with `differs_on` named
- ✅ Filter applied with FP-tolerant criterion (distance ≥1 OR novel mechanism)
- ✅ Each surviving finding framed as "what becomes possible" with concrete workflow
- ✅ Verification (Step 6) run on all surviving findings: confidence tags, URL health, attribution check, popularity-bias filter, counterfactual analogy (if cross-domain). `⚠ canon` prepended on canonical-citation findings.
- ✅ Findings grouped by tier (1: dist 3-4, 2: dist 2, 3: dist 1, similar: dist 0)
- ✅ For new-domain runs: test fixture built first; rubric FP=FN=0 on fixture before publishing findings

---

## When NOT to Use This Skill

- **Same-paradigm peer comparison**: use `/scout` — better-implemented peers of the same approach
- **AI agent architecture audits**: use `/gather-research` — scoped audit of agent-architecture research baseline
- **Claude Code community patterns**: use `/gather-intel` — Reddit/HN/blogs for Claude Code patterns
- **Single-topic deep research**: use `/deep-dive` — when you have one specific question to research thoroughly
- **GitHub config repo discovery**: use `/scout` — that's its scope
- **Skills registry mining**: use `/scout-skills` — Context7 skill patterns
