---
name: roundtable
description: "Run a multi-agent adversarial roundtable (Claude, Grok, GPT) for independent critique."
when_to_use: 'Run a multi-agent adversarial roundtable on any target context. Three LLMs (Claude Fable 5, Grok 4.6, GPT-5.6 Sol by default) produce independent assessments, then engage in up to 5 rounds of forced critique, defend/concede, and resolution (default 5 rounds; R1 independent, R2 forced critique, R3-R4 pre-reg + defend/concede, R5 final consolidated; auto-stop typically halts at R3-R4). Built-in null-control injection, falsifier-required claims, embedding-based auto-stop, single-retry on transient failures. Use when a methodology review, design proposal, security audit, or multi-stakeholder critique needs independent multi-model adversarial scrutiny. Trigger phrases - "roundtable", "multi-agent review", "adversarial review", "second opinion from multiple models". Do NOT use for bug-shaped problems with obvious answers, single-tool lookups, or trivial questions.'
argument-hint: "[context-file-path] [--max-rounds N] [--no-inject-agent-d] [--no-prereg] [--auto-stop] [--budget USD]"
allowed-tools: AskUserQuestion Bash Edit Glob Grep Read Write Agent
compatibility:
  requires:
    - cli: python3
    - env_var: ANTHROPIC_API_KEY
    - env_var: XAI_API_KEY
    - env_var: OPENAI_API_KEY
  optional:
    - python_pkg: requests
      fallback: "Claim validation (validate_claims.py) disabled; skip --strict mode"
    - env_var: VOYAGE_API_KEY
      fallback: "Embedding-based convergence detection disabled; auto-stop falls back to fixed max-rounds"
    - env_var: ROUNDTABLE_ANTHROPIC_MODEL
      fallback: "Uses the qualified production default claude-fable-5"
    - env_var: ROUNDTABLE_ANTHROPIC_EFFORT
      fallback: "Uses high effort"
verified_on: 2026-08-08
metadata:
  author: example-security-engineering
  version: "2.0"
  body-cap: exempt
  body-cap-reason: "PERIODIC: occasional multi-model adversarial review run with a USD budget, 15-40 turns; no requires_skills edge into it"
effort: high
---

# /roundtable — Multi-agent adversarial roundtable

Run a structured adversarial review of any target context using three frontier LLMs in parallel. Empirically-validated protocol from two prior experiments (see `examples/`):

> **Runtime policy:** This harness dispatches provider API calls explicitly.
> Resolve and record each effective model per
> `../_shared/model-runtime-policy.md`.

The qualified production default for the Anthropic arm and synthesis is
`claude-fable-5` at `high` effort. It is explicit in the adapter and configurable
per run with `ROUNDTABLE_ANTHROPIC_MODEL` and
`ROUNDTABLE_ANTHROPIC_EFFORT`. The transcript records the requested and effective
model returned by the provider in a nested `runtime_receipt`, together with
provider, effort, context class, fallback/switch, refusal, and observation-source
fields. Unobserved values remain `<unavailable>`; do not infer the serving model
from the agent label. A provider response-model mismatch is a typed failed arm,
not quorum or JRH evidence. `context_class` likewise remains `<unavailable>`
unless provider or runtime metadata explicitly observes it; a requested model
name or capability table is not evidence of the active context class.

Fable 5 has thinking always on. The adapter sends effort explicitly and omits
sampling parameters and manual thinking budgets. An Anthropic HTTP-200
`stop_reason: refusal` is a typed failed arm, not a successful assessment —
and Fable's safety classifiers fire more readily than Opus-tier on
security/bio-adjacent contexts, so security-audit roundtables should expect
occasional refusal-failed arms. The adapter deliberately does not enable
automatic refusal fallback: silently substituting a second model would change
the panel composition and invalidate the decorrelated-consensus claim. If the
Fable arm refuses on a given context, requalify that run explicitly on
`claude-opus-5` via `ROUNDTABLE_ANTHROPIC_MODEL`.

Fable 5 and Mythos 5 require 30-day data retention (unavailable under ZDR;
Mythos also requires Project Glasswing access). The org's 30-day retention was
confirmed 2026-08-19 and Fable is now the default arm; the former per-run
`ROUNDTABLE_COVERED_MODEL_RETENTION_APPROVED` gate is retired. If the org's
retention posture ever changes, the API rejects Fable requests with a 400,
which surfaces as a typed failed arm.

Because adaptive thinking and visible text share `max_tokens`, the harness
selects Anthropic headroom from the effective model and effort. Main and JRH
calls use at least 16K tokens; pre-registration uses at least 8K. `xhigh`/`max`
on any supported arm, and `high` on Fable/Mythos, raise the ceiling to at least
64K per Anthropic's current effort guidance. A truncation still fails the arm
instead of becoming partial evidence.

- **Round 1**: independent assessment by each agent (preserves blind-spot diversity)
- **Round 2**: forced critique — each agent attacks the weakest finding from each other agent (the fabricated null-control "Agent D" is in the peer set by default)
- **Round 3**: pre-registration substep + defend/concede with falsifier requirement
- **Round 4**: pre-registration substep + resolve genuine remaining disagreements with experimental resolution paths
- **Round 5**: final consolidated position with confidence deltas (no pre-reg — proven zero-info-gain in v2 experiments)

The harness handles model dispatch, retries on transient failures, embedding-based auto-stop when positions converge, and JSONL persistence for downstream tooling. A final synthesis pass produces a meta-report.

## Step 0 — Inputs and triage

**Required**: a context file (markdown) describing the target under review. Should be 1,000-5,000 words. Include:
- What is being reviewed (target description)
- Source material (key code excerpts, doc snippets, transcript excerpts) — **prefer including primary documents inline when load-bearing**, since the harness cannot fetch external files mid-run. Single-source claims that require document inspection cannot be adjudicated by added rounds; see Step 3's primary-evidence early-exit verdict.
- The assessment task (what should the agents produce?)
- Any pre-existing analysis the user wants the agents to verify or extend
- **Section-header audit reminder**: when the context.md frames events with a count or category in a header ("Three executions", "Five rounds", "Two patterns"), audit the count against the cited evidence before submitting. R1's framing audit will catch some miscounts, but author-side discipline is cheaper than relying on agents to discover it.

**Triage gate** — if the user's question is:
- Bug-shaped with obvious cause → use superpowers:systematic-debugging instead
- Single-tool lookup → just use the tool
- Brainstorming with no friction signal → use /superpowers:brainstorming
- Audit-class verdict gathering → use /fp-check or /triage

Roundtable is for **methodologically subtle** targets where individual blind spots are likely and structured cross-talk earns its cost.

## Step 1 — Configuration

Default protocol uses Claude Fable 5 (`claude-fable-5`, `high` effort) + Grok
4.6 + GPT-5.6 Sol across 5 rounds with pre-reg in R3-R4 only and the
Agent D null-control **ON**. Injection is the default, not an opt-in: it is the
only instrument that detects placebo agreement (arms endorsing a fabricated
peer's invented citations), and the `round_sycophancy` metric is blind to that
mode, so a run without it cannot separate convergence from correlated credulity.
You must author `<output>/round_1/agent_d.md` before launching — see Step 1b.
Override only the Anthropic arm with per-run environment values after
qualification:

```bash
ROUNDTABLE_ANTHROPIC_MODEL=claude-fable-5 \
ROUNDTABLE_ANTHROPIC_EFFORT=high \
python3 ~/.claude/skills/roundtable/scripts/harness.py \
  --context path/to/context.md \
  --output ./roundtable-results/$(date +%Y-%m-%d-slug)/ \
  [--max-rounds 5] \
  [--auto-stop]                 # stop early on convergence (default OFF; requires --auto-stop flag + VOYAGE_API_KEY)
  [--no-inject-agent-d]          # DISABLE the null control (default is ON; the harness exits 2 unless round_1/agent_d.md is pre-seeded)
  [--no-prereg]                  # skip prereg substeps (faster, less calibration data)
  [--budget 30]                  # abort if projected cost exceeds $USD
```

Use a new or empty `--output` directory for every run. The harness rejects a
non-empty directory before preflight or provider dispatch so outputs and model
receipts cannot be mixed across executions. The only allowed seed is exactly
`round_1/agent_d.md`, which the default configuration requires.

## Step 1b — Seed the null control (required)

There is no `--agent-d-file` flag. Author the fabricated Round 1 directly at
`<output>/round_1/agent_d.md` using `templates/agent_d_template.md`, before
launching. The harness checks for it and returns 2 with guidance if it is
absent — before creating a transcript or dispatching any provider call — so a
missing seed costs nothing but a relaunch.

Tailor the fabrications to the actual target: one or two genuinely correct
findings so the panel cannot dismiss D wholesale, two or three
confidently-stated false claims carrying specific-sounding citations, and
optionally a contrarian framing on a point where convergence is expected. Every
plant must be falsifiable by inspecting the context document — a plant nobody
can check tests nothing. Record what you planted, so the detection result in
Round 5 can be read against the actual list rather than an impression.

To run the Anthropic arm on a non-default model (e.g. falling back to Opus 5
after a Fable refusal on a security-adjacent context), bind the override to the
same invocation rather than exporting an ambient shell default:

```bash
ROUNDTABLE_ANTHROPIC_MODEL=claude-opus-5 \
ROUNDTABLE_ANTHROPIC_EFFORT=high \
python3 ~/.claude/skills/roundtable/scripts/harness.py \
  --context target.md --output results/
```

## Step 2 — Execution

The harness runs each round in this order:
1. Build per-agent prompts (target context + accumulated round history + current task)
2. Call all 3 agents in parallel (max 3 concurrent)
3. On transient failure (network, 5xx, timeout): retry once with 5s backoff
4. On hard failure (4xx, auth): record that arm as failed; abort the run if fewer than two distinct vendors survive the main round
5. Save outputs as JSONL records (one per agent per phase)
6. If `--auto-stop` and Voyage key set: embed each surviving main output, compute cosine similarity to prior round; stop only when the quorum guard holds, every surviving arm has sim ≥ 0.92, and ≥3 rounds completed

## Step 3 — Synthesis

After the harness completes its final round (or auto-stops), it prints:
`Next step: run synthesize.py to produce META_SYNTHESIS.md`. The harness
does **not** auto-invoke synthesis — you must run it as a separate command
once the rounds finish. (Confirmed 2026-05-10 — the SKILL.md previously
implied auto-run; the harness leaves it as a manual next step. Per /distill.)

```bash
python3 ~/.claude/skills/roundtable/scripts/synthesize.py --output <results-dir>
```

`synthesize.py` uses the same configured Anthropic model and effort to produce
`META_SYNTHESIS.md`. It requires a terminal `run_complete` receipt, reads
successful-arm receipts for every main round, refuses synthesis for running,
crashed, budget-aborted, or quorum-aborted transcripts, and permits a 3-of-3
label only when all three arms succeeded in every main round. A valid panel
receipt still does not prove finding-level agreement:
- Convergent findings with exact arm/round support and coverage-qualified confidence
- Divergent findings with positions per agent
- Single-source findings flagged for verification
- Top-3 priority recommendations with confidence labels
- Round-by-round delta analysis (if pre-reg ran)

### Optional: post-run concession audit

For high-stakes runs, scan the transcript for concessions that lack citation or falsifier:

```bash
python3 ~/.claude/skills/roundtable/scripts/audit_concessions.py <results-dir>
# or with strict-mode exit code:
python3 ~/.claude/skills/roundtable/scripts/audit_concessions.py <results-dir> --strict
```

Flags any R3 CONCEDE or PARTIAL response missing (a) explicit peer-evidence citation that flipped the agent, or (b) a falsifier referencing what would re-flip. Complements the preventive R3 prompt language by catching cases where the prompt didn't hold. Note: Round 4 uses a different response format (`**Resolution**: EXPERIMENT | EVIDENCE NEEDED | AGREE TO DISAGREE`) without a `**Response**` verdict line, so template-conformant R4 outputs are NOT detected by this script -- not even when an agent's prose explicitly withdraws a position (e.g., "I now accept GROK's position"). Detection is a literal regex match on `**Response**: CONCEDE|PARTIAL|DEFEND`; there is no free-text fallback, so R4 concessions/withdrawals require manual review.

The report also includes a **round-level sycophancy metric** (`round_sycophancy` in the JSON). For each round it computes the fraction of CONCEDE/PARTIAL position-changes that lack new evidence (reusing the same per-concession citation detection). When that fraction exceeds `SYCOPHANCY_THRESHOLD` (0.5), the round is flagged `CORRELATED-SYCOPHANCY` — agents caving to each other without citing anything new. This pairs with the Agent-D null-control to cover both groupthink failure modes: the null-control catches *placebo agreement* (agents endorsing a fabricated peer), while this catches *caving-without-evidence*. It is a **reported metric, not a hard gate** — `runs.csv` has only ~5 historical runs and rounds typically carry <2 concessions, so the per-round fraction is low-signal in practice and `--strict` still keys its exit code off per-concession citation/falsifier failures, not the round flag.

### Optional: post-run claim factuality check

For audit-class runs, factuality-check the verifiable claims (citations, version numbers, named studies, quantitative claims) in agent outputs against Tavily web search:

```bash
python3 ~/.claude/skills/roundtable/scripts/validate_claims.py <results-dir>
# default checks rounds 3-5; tag --strict to exit non-zero on FAIL:
python3 ~/.claude/skills/roundtable/scripts/validate_claims.py <results-dir> --strict
```

Tags each extracted claim `[OK]` (≥2 corroborating results), `[WARN]` (1 corroborating result, search error, or no distinctive tokens to verify), or `[FAIL]` (search returned results but none corroborate the claim). Requires `TAVILY_API_KEY`. Cost: ~$0.005/claim, default ~45 claims/run = ~$0.25. Complements `audit_concessions.py` (procedural rigor) by adding content rigor — catches fabricated citations or numeric overclaims that the round-by-round critique didn't flag.

**Qualify the instrument before trusting a `[FAIL]`, and do NOT use `--strict` on a
self-referential target.** The extractor cannot tell an external factual claim from an
intra-run statement about what a peer argued, and web search structurally cannot
corroborate the latter. Measured on the 2026-08-30 methodology run: **12 claims
extracted (not ~45), and 4 of 4 `[FAIL]`s were false positives** — all were
intra-panel meta-statements such as "Neither attacked delivery, the 100% table,
creativity-drop, or the deletion list" and "I predicted GROK's illegality rule would
quietly disappear." Zero real factuality problems existed. `--strict` would have
exited non-zero on those four and read as a content-rigor failure.

Target class decides the value:
- **Vendor / security / research** targets, where claims cite CVEs, versions, named
  studies, vendor behavior → the check earns its cost; `--strict` is reasonable.
- **Methodology / self-review** targets, where the corpus is the panel's own argument
  → expect a low claim count and mostly-unverifiable extractions. Read `[FAIL]` as
  "not externally checkable," never as "false," and skip `--strict`.

### Required: tag the run for selective-triggering data

After reading META_SYNTHESIS.md, tag whether multi-agent surfaced anything beyond Round 1's single-agent independent assessment. The tags accumulate in `runs.csv` at the skill root and feed the future selective-triggering classifier (improvements-runbook #6).

```bash
python3 ~/.claude/skills/roundtable/scripts/tag_run.py \
  --run-dir <results-dir> \
  --useful yes \
  --notes "what made it useful (or not)"
# --useful values: yes | no | unclear
```

The script auto-fills `target_word_count` from `context.md` and `num_findings` from `META_SYNTHESIS.md`. After ~10-20 tagged runs, analyze `runs.csv` for selectivity heuristics that predict when multi-agent is worth its $32 cost. Until then: every run gets tagged.

## Step 4 — Outputs

Run directory contains:
```
results-dir/
├── round_1/{opus,grok,gpt[,agent_d]}.md      # opening assessments
├── round_2/main/{opus,grok,gpt}.md            # forced critique
├── round_3/{prereg,main}/{opus,grok,gpt}.md   # defend/concede
├── round_4/{prereg,main}/{opus,grok,gpt}.md   # resolve disagreements
├── round_5/main/{opus,grok,gpt}.md            # final positions
├── transcript.jsonl                            # one record per (round, phase, agent) — prompt size + response + cost; also run_start/auto_stop/run_complete events
├── convergence.json                            # per-round embedding similarity matrix
└── META_SYNTHESIS.md                           # final synthesis
```

## Examples

```bash
# Methodology review: assess a skill design
/roundtable ~/Documents/proposals/new-skill-spec.md

# Security review with strict budget cap
/roundtable ~/security-reviews/auth-redesign.md --budget 25

# Quick 3-round review without null control
/roundtable ~/draft-rfc.md --max-rounds 3 --auto-stop  # null-control off by default
```

## Success Criteria

- At least 2 distinct vendor arms complete every main round; otherwise the run
  aborts and cannot be synthesized
- All 3 arms complete every main round before any finding is eligible for a
  3-of-3 label
- META_SYNTHESIS.md surfaces both convergent and divergent findings explicitly
- Cost stays within budget (or aborts if not)
- For pre-reg runs: pre-reg → main delta is reported per agent (calibration signal)

## When NOT to use

- Bug-shaped problems with obvious causes (use superpowers:systematic-debugging)
- Single-tool lookups (just call the tool)
- Brainstorming with no friction signal (use /superpowers:brainstorming)
- Audit-class verdict gathering (use /fp-check, /triage)
- When budget is <$10 (the protocol's value comes from sustained cross-talk)

## Cost / time guidance

The ranges below are historical protocol measurements, not a current quote.
The runtime estimates now apply the configured Anthropic arm's current base
token price, but have not been live-requalified on the current three-model
panel. Prompt caching, fast mode, provider price changes, fallback attempts,
and the changed reasoning/token behavior of a replacement model can move total
cost materially.

- 5 rounds with prereg in R3-R4: ~$25-35, ~25 min wall
- 4 rounds with prereg, auto-stop on: ~$15-25, ~15 min wall
- 3 rounds no prereg: ~$8-12, ~8 min wall

**First live requalification on the Fable 5 / grok-4.6 / gpt-5.6-sol panel
(2026-08-30) came in ~5x BELOW those historical ranges**, so budget from this
row, not the ones above, and treat the ranges above as an upper bound until
more runs land:

| measured | value |
|---|---|
| total | **$5.45** across 21 provider calls |
| per arm | Anthropic (Fable 5, `high`) $3.69 · GPT $1.23 · Grok $0.54 |
| configuration | 5 rounds, prereg in R3-R4, `--inject-agent-d`, no auto-stop |
| context | 15,981 chars (~2,500 words) |
| completeness | 3/3 arms succeeded in every main round; terminal `run_complete`; 0 malformed transcript lines |

Provenance: summed from `transcript.jsonl` `cost_usd` per call, measured
exhaustively (21 of 21 = 15 main + 6 prereg). **n=1 run, one context size** —
cost scales with context and with accumulated round history, so a 5,000-word
context will cost materially more than this.

That same run exposed a budget-accounting bug, fixed in the same change: the
round loop discarded `run_phase`'s return value for the prereg substep, so
prereg spend never reached `total_cost` — the variable `--budget` is enforced
against. The run therefore self-reported **$4.22** against $5.45 actual, and a
`--budget 30` run could have spent roughly $39 without tripping the guard.
Any cost figure produced by this harness before 2026-08-30 under-reports by its
prereg share; treat historical numbers as floors. The Anthropic arm is ~68% of spend, so
`ROUNDTABLE_ANTHROPIC_MODEL`/`_EFFORT` is the dominant cost lever. Do not quote
`$5.45` as the price of a roundtable; quote it as the price of THIS shape.

The protocol's marginal value drops fast past Round 4 (v2 experiment: R5 prereg→main delta was zero for all agents). Default `--max-rounds 5` is conservative; `--auto-stop` typically halts at R3-R4.

**5 is a CEILING, not just a default.** Round tasks come from
`templates/round_tasks/`, which defines rounds 2-5 only (Round 1 is built in
code). `harness.py` validates `--max-rounds` against the templates actually on
disk and exits immediately if you exceed it. Before that guard existed, a larger
value ran rounds 1-5, spent the whole budget, and only then raised
`FileNotFoundError` when building the round-6 prompt — leaving no terminal
`run_complete` receipt, which `synthesize.py` requires, so the entire paid run
became unsynthesizable. To genuinely add a round you must author
`templates/round_tasks/round_6_main.md` (and a prereg template if wanted); the
ceiling then rises on its own, since it is read from disk rather than hardcoded.
Do not raise the number expecting a better review — R5 already showed zero
information gain, so a sixth round extends the flattest part of the curve.
Spend a larger budget on full 5-round cross-talk instead. The null control is
already on by default and costs about nothing, since Round 1 is the small round.

## Known operational constraints

- **Anthropic model contract**: `ROUNDTABLE_ANTHROPIC_MODEL` defaults to
  `claude-opus-5`; `ROUNDTABLE_ANTHROPIC_EFFORT` defaults to `high` and accepts
  `low`, `medium`, `high`, `xhigh`, or `max`. Opus 5 thinking cannot be disabled
  at `xhigh`/`max`; the adapter does not send a disabling override. A refusal is
  logged as a failed arm so it cannot silently become consensus. Any model or
  effort override requires a fresh reliability and cost run before its output
  inherits the production-default evidence.

- **JRH qualification integrity**: `jrh_harness.py` uses the same model/effort
  headroom policy and writes one nested `runtime_receipt` per provider call. A
  provider failure, truncation, or unparseable verdict raises an invalid-run
  outcome before `judge_card.json` can be emitted; it is never scored as judge
  disagreement or instability. Set `JRH_OUT_DIR` to a new or empty durable
  directory for each run; a non-empty directory is rejected so a failed rerun
  cannot leave a stale Judge Card looking current.

- **GPT reasoning + max_output_tokens accounting**: Per the OpenAI
  Responses API, `max_output_tokens` caps reasoning tokens AND visible
  output tokens combined. With `reasoning_effort: "high"` (openai_adapter
  default), ~80% of the budget allocates to internal reasoning. R1 main
  on dense context (framing audit + recommendation discipline + fresh
  independent assessment) typically needs 10-12K output tokens; empirically
  observed 11,506 on the 2026-05-10 cellular-threats run.
  `DEFAULT_MAX_TOKENS["main"]["gpt"]` is set to 32000 (prereg 8000) to
  ensure visible-output headroom after worst-case reasoning consumption.
  If you ever see a single GPT response return `status: "incomplete"`,
  `incomplete_details.reason: "max_output_tokens"`, with `output: [{type:
  "reasoning", summary: []}]` and zero visible text, that's the truncation
  failure mode — the model consumed its entire budget on reasoning before
  emitting prose. Mitigations if 16K is insufficient: (a) bump further to
  24-32K, (b) drop `reasoning_effort` to "medium" in openai_adapter.py
  (intelligence delta on AA Index is 1 point; token cost halves), or
  (c) shorten the context.md. Per /distill 2026-05-10 investigation with
  primary sources at OpenAI Responses API guide + OpenRouter formula.
  `reasoning_effort` on gpt-5.6-sol accepts `low` (smoke-verified 2026-08-19),
  unlike the prior GPT pin whose floor was `medium` — but keep `medium`+ for
  panel work; `low` is a cost lever for smoke tests only (the openai_adapter
  passes `reasoning_effort` straight through).

- **API key resolution**: `harness.py`, `synthesize.py`, `jrh_harness.py`, and
  `validate_claims.py` all resolve credentials in-process via
  `scripts/keychain.py` before any provider dispatch, so you do NOT inline
  secrets at the invocation site. An env var that is already set
  always wins; otherwise each key is looked up against an ordered list of
  Keychain **item** names. Status lines naming the resolved item (never the
  value) print to stderr, and a missing REQUIRED key aborts the run rather than
  failing one arm — a dropped arm silently reduces the panel and invalidates the
  decorrelated-consensus claim.

  **The Keychain item name is not the env-var name.** Do not "simplify" the
  candidate lists back to the env-var name:

  | env var (adapters read) | Keychain item candidates, in order |
  |---|---|
  | `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` |
  | `XAI_API_KEY` | `XAI_API_KEY` |
  | `OPENAI_API_KEY` | **`OPENAI_PLATFORM_API`**, then legacy `OPENAI_API_KEY` |
  | `VOYAGE_API_KEY` (optional, `--auto-stop` only) | `VOYAGE_API_KEY` |
  | `TAVILY_API_KEY` (optional, `validate_claims.py` only) | `TAVILY_API_KEY` |

  OpenAI's items were renamed 2026-08-04 and `OPENAI_API_KEY` no longer exists
  on this host, so a name-keyed lookup fails the GPT arm. `jrh_harness.py` had
  that bug from the rename until 2026-08-30. The OpenAI **ADMIN** items
  (`OPENAI_PLATFORM_ADMIN_API`, `OPENAI_CHATGPT_ADMIN_API`) are deliberately
  excluded — they authenticate the Admin/Compliance surfaces, not inference, and
  a panel arm must never fall back to one.

  On Windows, User-scope env vars may not reach the bash subprocess and there is
  no Keychain; export the three keys in the launching shell instead.

## References

| File | Purpose |
|---|---|
| `references/when-to-use.md` | Decision guidance: roundtable vs other review skills |
| `references/interpreting-results.md` | How to read pre-reg deltas, convergence signals, single-source findings |
| `references/cost-tradeoffs.md` | Historical cost evidence from earlier model slates; requalification baseline only |
| `references/judge-reliability-protocol.md` | JRH-style protocol to validate the jury's verdict reliability (position/paraphrase/verbosity/stochastic) |
| `references/jrh-fixture/JUDGE_CARD.md` | Historical measured Judge Card from the 2026-06-14 model slate (+ frozen fixture and raw records) |
| `examples/persona-skill-review.md` | Historical worked example from v1+v2 experiments |
