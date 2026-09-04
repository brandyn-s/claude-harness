---
name: persona
description: "Dispatch framework personas at a plateaued metric to break diminishing returns."
when_to_use: Dispatch framework personas at a problem. Use when (a) a metric is plateau-ed and conventional engineering returned diminishing results, or (b) verifying that dispatch reproducibly finds known answers is required. Three modes — discovery (loose problem, manual synthesis, novelty-seeking), rubric (structured problem, pre-registered scoring, dual-scorer with kappa report), meta (manual-only iteration of rubric across a variable matrix). Triage gate (Article VI) at Step 0 — if conventional engineering hasn't been tried, exit. Do NOT use for fresh problems with obvious bug-shaped explanations, or for trivial debugging.
argument-hint: "[problem] [--mode discovery|rubric|meta] [--n 15] [--model MODEL] [--effort LEVEL] [--judge-model MODEL] [--judge-effort LEVEL] [--inventory PATH]"
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, AskUserQuestion
compatibility:
  requires:
    - cli: python3
    - python_pkg: anthropic
  optional:
    - python_pkg: yaml
      fallback: rubric.yaml parsed manually
metadata:
  author: example-security-engineering
  version: "1.0"
effort: high
---

# /persona — Framework dispatch

Dispatch N framework personas (≥15 by default) against a problem. Each
persona reads the same problem through a different framework's lens and
produces 3-5 specific recommendations.

Three modes capture three distinct goals:
- **Discovery** — loose problem, manual synthesis. Optimized for finding
  framings the team hasn't considered. Matches the original 2026-04-29
  dispatch that produced the edge-type-partitioning insight.
- **Rubric** — structured problem, pre-registered scoring. Optimized for
  verifying dispatch reproducibly finds known answers. Use for regression
  tests, model comparison, methodology validation.
- **Meta** — manual-only mode for iterating rubric across a variable matrix
  (multiple N, sampling rules, models, seeds). Currently a stub that prints
  guidance; users invoke rubric mode N times with different slugs and
  aggregate via `scripts/analyze.py`.

Rubric-quality gate: `scripts/analyze.py <run-dir> --strict` exits non-zero
when any RC's keyword-vs-LLM-judge agreement falls below an in-band Cohen's
kappa floor (default 0.6), so rubric ambiguity blocks a run instead of only
being annotated. The kappa-paradox guard still applies — out-of-band low
kappa (extreme base rates) never gates.

Output (discovery mode): each recommendation tagged `[novel]` or `[default]`
per the calibration criteria in `references/discovery-mode.md` (added
2026-05-02). Each tag is accompanied by a measurable axis specification
(the categorical property to GROUP BY for validation). Recommendations
without a measurable axis are tagged `[SPECULATIVE]` and bucketed
separately.

The three modes are NOT interchangeable. F6 found Cohen's kappa = 0
between casual scoring (discovery's review approach) and rubric scoring
(rubric mode's automated dual-scorer). They measure orthogonal
constructs. Never average their results.

## Operational model runtime

Follow `../_shared/model-runtime-policy.md`. The economical persona producer
default remains the current Haiku 4.5 API identifier; the independent rubric
judge defaults to Opus 5 at `high` effort. Both lanes are explicit and
configurable:

- CLI: `--model`, `--effort`, `--judge-model`, `--judge-effort`
- Environment: `PERSONA_MODEL`, `PERSONA_MODEL_EFFORT`,
  `PERSONA_JUDGE_MODEL`, `PERSONA_JUDGE_EFFORT`
- Pre-registered rubric fixture: `models.persona`,
  `models.persona_effort`, `models.judge`, `models.judge_effort`

A model value is either an exact current API id or a tier alias (`fable`,
`mythos`, `opus`, `sonnet`, `haiku`). Aliases resolve against
`contracts/model-capabilities.json` before any request; an unknown or
superseded id, or Claude Code's `default`, is a configuration error (exit 2)
before the fixture is dispatched, never a 404 from the API. The resolved id is
what the request and every `runtime_receipt` record.

Covered Models (the Fable and Mythos families) require 30-day retention and are
unavailable under ZDR. Set `PERSONA_COVERED_MODEL_RETENTION_APPROVED=1` only
after that retention lane is approved. Every producer and judge result records a `runtime_receipt` with
the requested model/effort and provider-observed effective model. Refusals,
truncation, context exhaustion, and empty responses are failed typed outcomes,
not qualification evidence. A provider model switch is a typed
`model_mismatch` failure: fallback output never qualifies the requested lane.
Missing response-model metadata is a typed `model_unobserved` failure; an
unverified effective model cannot qualify even the initial run.
A cached result is reusable only when its receipt matches the requested model
and effort, the effective model exactly matches the requested model, the
observation came from response metadata, and `fallback` is false.

Discovery and rubric execution fail closed when any producer result is invalid;
rubric execution also fails closed when any independent judgment is invalid.
The run is marked **failed closed**: the command returns nonzero, preserves
partial typed evidence for diagnosis,
does not update `INDEX.md`, and does not print `Run complete`. Re-run the failed
lane successfully before treating the cohort as qualification evidence.

Because `max_tokens` covers adaptive thinking plus visible output, explicit
effort lanes reserve 16,000 tokens; `xhigh`/`max` and covered-model `high`
lanes reserve 64,000. These are ceilings for headroom, not expected output or
billing estimates. The default Haiku lane without effort retains its 1,000-token
persona-output ceiling.

Dated Opus 4.7/4.8 references in methodology, inventory provenance, and prior
results are frozen evidence for those runs. They do not define current runtime
defaults.

## Step 0 — Triage gate (Article VI)

See `references/triage-protocol.md`. Five trigger criteria:

1. Aggregate metric plateau ≥2 sessions of standard engineering work
2. Per-subset variance ≥2× the aggregate
3. Both precision AND recall stuck simultaneously
4. Engineer cannot articulate "what to measure next" (consider
   measurement-design inversion via `--inversion`)
5. >30 minutes of conventional investigation already done with
   diminishing results

**At least 2 must hold.** If <2, exit and recommend conventional
engineering. The skill refuses to dispatch on cargo-cult problems.

## Step 1 — Mode selection

If `--mode` is set, proceed. Otherwise:
- Goal is to find unknowns / surface novel framings → **discovery**
- Goal is to verify dispatch finds pre-specified answers → **rubric**
- Goal is to test methodology itself (e.g., scaling experiments) → **meta** (manual)

## Step 2 — Mode workflow

| Mode | Read |
|---|---|
| discovery | `references/discovery-mode.md` |
| rubric | `references/rubric-mode.md` |
| meta | `references/meta-mode.md` (manual-only) |

Mode workflows are non-interactive — they execute end-to-end without
prompts (matches the original dispatch character).

## Step 3 — Result archival

Every run lands in `~/Documents/knowledge-base/research/dispatch-runs/YYYY-MM-DD-<slug>/`:

```
pre-registration.md     # rubric mode only — git-committed before dispatch
fixture.yaml            # rubric mode only — machine-readable problem + rubric
problem.md              # both modes — the problem statement used
results-by-persona/     # one JSON per persona dispatch
analysis.md             # synthesis (discovery) OR per-cell metrics (rubric)
INDEX.md updated        # cross-link added to dispatch-runs/INDEX.md
```

Each persona JSON preserves producer and (for rubric mode) judge
`runtime_receipt` objects so model switches and historical baselines remain
auditable.

`STARTED.lock` marks the run as started (it gates pre-registration edits by convention). Note: dispatch.py does NOT currently enforce immutability — re-running with the same slug silently rewrites `problem.md` / `fixture.yaml` in place with no warning, so use a fresh slug per run (or treat slug reuse as caller responsibility).

## Step 4 — Cross-run index

Append to `~/Documents/knowledge-base/research/dispatch-runs/INDEX.md`:
date, slug, mode, problem summary, key metrics, link.

## Examples

**Discovery — code-graph plateau**:
```
/persona "Code-graph's Go fixture F1 plateau-ed at 0.890 after PR #125.
Per-subset variance was the diagnostic that surfaced receiver-qualification
last time. What dimension are we now blind to?"
```
→ Skill runs discovery mode, dispatches 15 personas with bucket coverage,
synthesizes convergent themes, writes analysis to a new run dir.

**Rubric — verify scaling-experiment claim across new model**:
```
/persona --mode rubric --model haiku \
    --slug 2026-05-25-haiku-rerun \
    --fixture path/to/fixture.yaml
```
→ Skill loads the fixture at `--fixture`, applies the pre-registered
rubric, dispatches the cohort against the structured problem in the
fixture, scores via keyword + LLM-judge, reports kappa. `--slug` and
`--fixture` are both required in rubric mode -- the dispatcher refuses
to proceed without an explicitly named fixture, so a run is always
pinned to a named, pre-registered fixture rather than silently rebound
to whatever fixture is newest.

**Meta — test new sampling rule**:
```
python3 dispatch.py rubric --slug runA-haiku-N11 --model haiku --n 11 ...
python3 dispatch.py rubric --slug runA-haiku-N25 --model haiku --n 25 ...
...
python3 scripts/analyze.py --aggregate <run-dir-1> <run-dir-2> ...
```
→ Skill guides manual methodology research: run rubric mode N times with
different --slug suffixes and parameters, then pass all run dirs to
analyze.py with --aggregate to compare cells side-by-side.

## Success Criteria

- Triage gate fires on cargo-cult dispatches (refuses to run)
- Discovery and rubric modes never accidentally cross-contaminate scoring
- Pre-registration timestamp is git-committed BEFORE first dispatch in
  rubric mode
- Inter-rater kappa is reported per RC in rubric mode
- New methodology lessons append cleanly to `references/methodology-evolution.md`
- Cross-run INDEX gives a 30-second view of "what dispatches have we run"

## When NOT to use

- Fresh problems where conventional engineering hasn't been tried (gate
  exits)
- Trivial bug fixes (use diagnostic engineering, not dispatch)
- Curiosity-driven application without a friction signal (use
  `/scout-frontier` or `/superpowers:brainstorming`)
- Audit-class assessments where verdict-gathering is the goal (use
  `/fp-check` or `/triage`)

## References

| File | Purpose |
|---|---|
| `references/triage-protocol.md` | Article VI gate criteria + denied override petitions |
| `references/discovery-mode.md` | Loose-problem workflow + manual synthesis |
| `references/rubric-mode.md` | Structured problem + pre-reg rubric + dual scoring |
| `references/meta-mode.md` | Manual rubric-iteration pattern across a variable matrix |
| `references/scoring-disciplines.md` | Why kappa=0 between B1/B2; never average |
| `references/methodology-evolution.md` | Living history of M1-M5, F6, and beyond |
| `references/inventory-management.md` | Multi-inventory support; how to add sources |
| `references/prior-results.md` | Index of past runs with key findings |
