# Live-Arm Measurement Plan — efficacy of the prose-only skills

**Handoff brief for local Claude Code** (the machine with API keys, MCP servers,
live repos, and the knowledge base). This is self-contained — you do not need the
prior conversation. Paste it, or run: *"execute docs/live-arm-measurement-plan.md."*

---

## 0. Why you're running this

Three review waves established this skill corpus is well-*built*, *honest* about
what it does, and *sensible* in approach — but **effectiveness was unmeasured**
for almost everything. Recommendation #1 ("measure, don't assume") was then
executed for the skills whose value-prop is **deterministically** checkable. Read
those first as your template (they're on `main`, or on branch
`claude/wonderful-cori-N5sWd` / PR #1084 if not yet merged):

- `skills/roundtable/harness/` + `skills/roundtable/tests/test_consensus_integrity.py` — **the exemplar.** Mirror its shape.
- `skills/variant-analysis/harness/`, `skills/persona/harness/`, `skills/supergoal/harness/`.

What those found (so you trust the method): two of four expensive value-props were
**not delivered** as advertised — `roundtable`'s "3-vendor consensus" silently
collapsed to one vendor (100%→0% after fix); `variant-analysis`'s only quality
bound was inert. Measurement caught what structural review didn't.

**What's left = the live arm.** These skills have **no deterministic value-prop
surface** — their value is open-ended LLM + web/MCP judgment, so you can only
measure them by *running them on a labeled task and scoring the outcome*:
`gather-research`, `gather-intel`, `gather-claude`, `gather-internal-intel`,
`deep-dive`, `triage`, `investigate`, `evaluate-repos`. The cloud session couldn't
(no keys/MCP/corpus). You can.

Use the repo's own meta-skill — invoke **`/build-measurement-harness`** — to
scaffold each instance; this plan supplies the per-skill oracle/fixture/metric it
will ask for.

---

## 1. The discipline (non-negotiable)

1. **CARDINAL RULE — anti-circularity.** The oracle (ground truth) must be
   **independent** of the skill. NEVER let a skill grade its own output, and never
   let the same model that produced the output also judge it. Legitimate oracles:
   (a) **human-curated** labels, (b) **historical** items whose true outcome is now
   known, (c) a **deterministic check** (e.g., does the cited URL actually contain
   the quoted claim — like `threat-model`'s grep grounding, but over fetched pages),
   (d) a **held-out different model** as grader (e.g., grade Opus output with Grok,
   or vice-versa). If you can't construct an independent oracle for a skill, say so
   and stop — do not fake a measurement.
2. **Fair baseline.** The A/B baseline must be a *strong* single pass (best model,
   no framework), not a strawman. The skill costs 3–6× a single pass; it must beat
   the baseline by **more than its cost ratio** to be worth keeping, not marginally.
3. **Report variance.** LLM-judged metrics are noisy. Run **N ≥ 3** and report
   mean + spread, not a single cherry-picked run.
4. **Honest verdict, reported at the layer that fired.** Distinguish "the skill
   underperformed" from "the measurement instrument broke." A measured *negative*
   ("does not beat baseline → trim it") is a **successful** measurement.
5. **Keep fixtures small** (10–20 labeled items): live calls cost money + time.

---

## 2. Deliverable shape (per skill — mirror the deterministic harnesses)

```
skills/<skill>/harness/
  PROBLEM.md      # classify → independent oracle → fixture → metric → baseline →
                  # REAL-vs-INSTRUMENT note → results table. (Copy roundtable's structure.)
  fixture.json    # the labeled corpus (oracle ground truth, hand/historical-derived)
  run_live.py     # the A/B runner: invokes the skill + the baseline + the grader,
                  # writes results.json. REQUIRES keys/MCP — run manually, not in CI.
  results.json    # the MEASURED numbers (committed; the frozen baseline)
skills/<skill>/tests/test_<skill>_efficacy.py
                  # CI gate that asserts on the COMMITTED results.json (key-free,
                  # deterministic) — e.g. "recorded value-prop delta >= threshold".
                  # CI must never make live calls. Refreshing results.json is a
                  # manual keyed `run_live.py` run.
```

After each: update the skill's SKILL.md **Success Criteria** (or add a "Measured
efficacy" line) with the honest result — `measured <metric> vs baseline <metric>
over N=<n>, <date>` — and rebuild the marketplace mirror (`python3
scripts/build-marketplace.py`, commit the result).

---

## 3. Per-skill measurement designs

### 3.1 `gather-research` — **DO THIS FIRST** (cleanest gradeable output, mostly-deterministic oracle)
- **Value-prop:** claims grounded in **PRIMARY** sources, correctly tier-labeled, outdated info caught (its `references/citation-domain-freshness.md` is the framework under test).
- **Fixture (≈15 claims):** hand-curate research claims about Claude Code / agent engineering, each with a **known verdict** + the real primary-source URL: mix of `true+primary`, `plausible-but-refuted`, `outdated` (was true, now false), and `unsupported/fabricated-sounding`.
- **Independent grader (mostly deterministic):** for every claim the skill labels GROUNDED/PRIMARY, **fetch the cited URL (Tavily/Firecrawl/Exa) and check it actually contains supporting text** — a deterministic grounding check, not a model opinion. For verdict correctness use the hand-labeled truth.
- **Metrics:** grounding precision (cited-PRIMARY claims that truly trace to a supporting primary source), refutation recall (outdated/false claims correctly downgraded), hallucination rate (claims with no real source). **A/B** vs `deep-dive` with grounding-framework off, or plain Opus.
- **Verdict question:** does the freshness/PRIMARY framework raise grounding precision + refutation recall enough over baseline to justify its cost?

### 3.2 `gather-intel` / `gather-claude` / `gather-internal-intel`
- Same shape, scoped to each one's source domain. `gather-intel` = community; `gather-claude` = Anthropic first-party (its CHANGELOG/`gh` claims are deterministically checkable — strongest oracle of the three); `gather-internal-intel` = Slack/Linear/Confluence.
- **`gather-internal-intel` oracle:** use **resolved** internal items (a Slack thread / Linear issue with a known outcome) as ground truth; measure whether it correctly classifies *incident-verified* vs *discussion-opinion* and **excludes opinion from memory** (its stated discipline). Uses your live Slack/Linear/Confluence MCP.

### 3.3 `deep-dive`
- **Oracle:** ~15 factual questions with known answers, several with a deliberate "is X still true / current pricing" currency twist. **Metric:** answer correctness **+ confidence calibration** — does its mandatory HIGH/MEDIUM/LOW confidence actually correlate with correctness? (HIGH should be right far more than LOW; if not, the confidence labels are noise.) Also check the mandatory per-finding counterfactual isn't boilerplate. **A/B** vs plain Opus single pass.

### 3.4 `triage`
- **Value-prop:** correct prioritization + cross-tool correlation of findings.
- **Oracle:** a set of **real findings** (pull from your security MCP tools) with a **human-assigned correct priority ranking** + known correct correlations — or a **historical incident** whose true priority/root-cause is now known.
- **Metrics:** rank correlation (Spearman) between the skill's composite-priority order and the expert ranking; correlation accuracy (precision/recall of "these N findings share a root cause"). **A/B** vs an unstructured "just rank these findings" prompt. The 14-article constitution earns its weight only if the ranking is materially better.

### 3.5 `investigate`
- **Value-prop:** correct cross-tool timeline + verdict for an entity (user/IP/device).
- **Oracle:** a **resolved historical investigation** with a known true timeline + true verdict (benign / compromised). Measure timeline reconstruction accuracy + whether it reaches the correct verdict, **A/B** vs a single-tool lookup. (Honors the skill's own main-thread-auth invariant — run it where the MCPs authenticate.)

### 3.6 `evaluate-repos`
- **Value-prop:** de-biased adopt/defer/reject — it exists to remove the documented self-eval *dismissal* bias (Quality-3 → SKIP).
- **Oracle:** external patterns with a **known-correct disposition by hindsight** — patterns you adopted that proved good; rejected that proved right; and (the key cases) ones you **wrongly dismissed** earlier and later adopted.
- **Metric:** decision accuracy, esp. **false-dismissal rate**. **A/B that directly tests the bias claim:** run the same patterns through (a) the full advocate/skeptic harness and (b) a single self-evaluation pass — does the harness actually *lower* false-dismissal vs the single pass? If not, the multi-agent cost isn't buying de-biasing.

---

## 4. A/B protocol (general, applies to all)

For each skill: (1) pick the representative task; (2) run **WITH** the skill's full
procedure and a **fair baseline** (strong single pass, no framework); (3) score
**both** against the independent oracle on the value-prop metric; (4) repeat N≥3,
report mean+spread; (5) verdict: **keep** (delta > cost ratio), **trim** (delta
small / not worth the ceremony), or **fix** (a specific mechanism underperforms).
Record raw transcripts under `harness/runs/` for auditability (Phase-9: anyone
should be able to re-grade your sample and reach the same verdict).

---

## 5. Guardrails for your environment

- **Keys/MCP you'll use:** `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`XAI_API_KEY`/`VOYAGE_API_KEY`; Tavily/Exa/Firecrawl (research); the security MCPs (triage/investigate); Slack/Linear/Confluence (internal-intel); code-search/code-graph (evaluate-repos grounding). Use a **held-out** provider as grader so the producer isn't the judge.
- **Cost:** budget per skill before running; small fixtures; cache fetched pages.
- **CI stays key-free:** the gate asserts on committed `results.json`; live runs are manual.
- **Keep all existing gates green** after each commit: `pytest skills/`, rubric (`python3 scripts/validate-skills.py`, must stay 13/13), `python3 manifests/compile.py --root . --check --no-reindex`, and the marketplace sync (`python3 scripts/build-marketplace.py` then `git diff --quiet marketplace/ .claude-plugin/`). `python3 bin/audit-skill.py --all` must report 0 `FAIL`.
- **Order:** `gather-research` first (it's the template — mostly-deterministic oracle), then the other gather skills + `deep-dive`, then `triage`/`investigate`/`evaluate-repos` (these need real findings/incident ground truth, so curate those oracles carefully).
- **One PR per skill** (or per cluster) so each measured verdict is reviewable on its own.

---

## 6. Definition of done (per skill)

A committed `harness/` with an **independent** oracle, a `results.json` carrying the
**measured** A/B numbers (N≥3, with spread), a key-free CI gate on those results, a
one-line honest verdict in the SKILL.md (keep/trim/fix, with the numbers + date),
and the marketplace mirror rebuilt. A negative result ("does not beat baseline →
recommend trim") is a complete, valuable deliverable — that's the entire point of
measuring instead of assuming.
