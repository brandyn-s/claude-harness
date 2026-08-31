# L3 — Opus 4.7 Skill-Activation Study

**Pre-registered factorial design replicating Seleznov's 650-trial study on the new model.**

> **Historical pre-registration (2026-05-27):** This design is preserved so
> its hypotheses are not rewritten after the fact. It was not executed and is
> not current model policy. A new Fable 5, Opus 5, or Sonnet 5 study must use a
> separate dated design and runtime receipts rather than editing this baseline.

## Background

The most recent published activation study (Seleznov 2026 via dev.to; Bara
2026 via Medium) ran on Sonnet 4.5. It found a 20.6× odds ratio (95% CI
[8.4, 50.6], CMH p < 0.0001) for directive-language descriptions over
passive ones. The Spence sandboxed-eval work is directionally consistent
but uses different methodology and doesn't cite Seleznov.

**Opus 4.7's docs describe "more literal instruction following"** ([source](
https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7))
which *should* amplify the directive effect. But no published study has
measured activation on 4.7.

This study fills that gap. See `_shared/eval-harness-roadmap.md` for the
context.

## Pre-registered hypotheses

**H1**: Directive + Do-NOT description style produces ≥80% activation rate
on Opus 4.7. Passive style produces ≤60%. CMH odds ratio between styles
is > 5×.

**H2**: The effect size on Opus 4.7 is **larger** than the Sonnet 4.5
baseline (Seleznov 20.6×). One-tailed test against the Seleznov estimate.

**H3**: Hook-injected skill-recommendation conditions converge to ≥95%
activation across all description styles (replicates Seleznov's hook
finding).

## Factorial design

- **Description style** (3 levels):
  - `passive` — "Use when X happens"
  - `directive` — "ALWAYS invoke this skill when X"
  - `directive_do_not` — "ALWAYS invoke when X. Do NOT do Y directly."

- **Trigger type** (4 levels):
  - `exact` — user prompt is a verbatim trigger phrase
  - `near` — paraphrased trigger (1-2 words substituted)
  - `semantic` — semantic equivalent, no lexical overlap
  - `unrelated` — negative control: prompt has nothing to do with the skill

- **Pilot skills** (5 levels, varied content for generalizability):
  - `capture` (knowledge-base I/O)
  - `recall` (retrieval)
  - `refine` (prompt enrichment)
  - `ship` (git/PR ops)
  - `audit-skill` (linting)

- **Prompt-prefix condition** (3 levels):
  - `none` — bare user prompt
  - `use_skills_hint` — system-prompt prefix: "Use available skills when relevant."
  - `hook_inject` — UserPromptSubmit hook injects skill recommendation

**Cells**: 3 × 4 × 5 × 3 = 180. **Trials per cell**: 4. **Total invocations**: 720.

## Expected outcome shape

| Style \ Trigger | exact | near | semantic | unrelated |
|---|---|---|---|---|
| passive | ~85% | ~65% | ~40% | ~5% (correct negative) |
| directive | ~95% | ~85% | ~60% | ~5% |
| directive_do_not | ~100% | ~95% | ~70% | ~3% |

(per-prefix means; hook_inject should push exact/near columns to ~100%.)

## Files in this directory

```
tests/l3-activation-study/
├── README.md                            # this file
├── design.yaml                          # full cell matrix
├── skill-variants/                      # 15 SKILL.md files (5 skills × 3 styles)
│   ├── capture-passive/SKILL.md
│   ├── capture-directive/SKILL.md
│   ├── capture-directive_do_not/SKILL.md
│   ├── ... (15 total)
├── trigger-prompts/                     # 20 trigger-prompt files (5 skills × 4 trigger types)
│   ├── capture-exact.txt
│   ├── capture-near.txt
│   ├── capture-semantic.txt
│   ├── capture-unrelated.txt
│   ├── ... (20 total)
├── prefix-conditions/                   # 3 prompt-prefix wrappers
│   ├── none.txt
│   ├── use_skills_hint.txt
│   └── hook_inject.txt
├── runner.py                            # invokes claude -p per cell, captures JSONL
├── mock_runner.py                       # offline validator — exercises the harness without API calls
├── analysis.py                          # CMH odds ratios + 95% CIs from results.jsonl
├── results/                             # one JSONL per run; trial-level records
│   └── 2026-MM-DD-results.jsonl
└── analysis/                            # per-run analysis output
    └── 2026-MM-DD-cmh.md
```

## How to run

### Prerequisites

```bash
# 1. ANTHROPIC_API_KEY set in environment
export ANTHROPIC_API_KEY="sk-ant-..."

# 2. `claude` CLI installed and authenticated
claude --version          # 2.x or later

# 3. tiktoken for token-cost estimation
pip install tiktoken anthropic
```

### Dry-run (no API calls; validates harness)

```bash
python3 tests/l3-activation-study/mock_runner.py
```

Expected: 720 mock trials, each "fires" or "skips" pseudo-randomly per a
plausible distribution. Output goes to `results/dry-run.jsonl`. Then:

```bash
python3 tests/l3-activation-study/analysis.py --input results/dry-run.jsonl
```

### Live run (real LLM invocations; ~$16, ~4 hours)

```bash
python3 tests/l3-activation-study/runner.py --output results/2026-MM-DD-results.jsonl
```

The runner:
1. For each of the 180 cells:
   - Constructs the cell config (style × trigger × skill × prefix)
   - For each of 4 trials:
     - Sets up a sandboxed env with the variant SKILL.md and prefix
     - Invokes `claude -p --bare --model claude-opus-4-7 --output-format stream-json` with the trigger prompt
     - Parses the JSONL for `Skill` tool use referencing this skill
     - Records `{cell_id, trial_idx, activated: bool, latency_ms, tokens}`
2. Writes to `results/<date>-results.jsonl`
3. Reports running totals and estimated cost.

### Analysis

```bash
python3 tests/l3-activation-study/analysis.py --input results/<date>-results.jsonl --output analysis/<date>-cmh.md
```

Computes:
- Per-cell activation rates with 95% CIs (Wilson interval)
- Cochran-Mantel-Haenszel odds ratios stratified by skill + prefix
- Effect-size comparison against Seleznov's 20.6× baseline (one-tailed)
- Hook-condition convergence test
- Markdown report with all three pre-registered hypotheses evaluated

## Cost estimate

- 720 invocations × ~$0.022 (Spence's published number) = **~$16 USD**
- Pessimistic upper bound (high-effort + 4.7's larger tokenizer): **~$40**
- Time at 5-30s per call, serial: **~4 hours**
- Time at 4-way parallel (cap recommended for safety): **~1 hour**

## Publishability

Per the literature scan in `_shared/research-notes.md`, this is unpublished
work. Sources:
- [Seleznov 650-trial study (Sonnet 4.5)](https://medium.com/@ivan.seleznov1/why-claude-code-skills-dont-activate-and-how-to-fix-it-86f679409af1)
- [Bara: Two reliability problems](https://medium.com/@marc.bara.iniesta/claude-skills-have-two-reliability-problems-not-one-299401842ca8)
- [Spence sandboxed evals (Sonnet 4.5)](https://scottspence.com/posts/measuring-claude-code-skill-activation-with-sandboxed-evals)

A 720-trial CMH-analyzed study on Opus 4.7 closes the gap between the
official "more literal instruction following" claim and any quantitative
measurement.

## Risks / caveats

1. **Single-author, single-environment** — same caveat as Seleznov's
   original. Replication would strengthen.
2. **Non-determinism in skill activation** — pre-registered: ≥80% over 4
   trials counts as "fires." Lower threshold under-rejects directive-style
   effect.
3. **Model-version drift** — Anthropic ships model updates without
   notice. Pin model ID to the dated alias on every trial; record in JSONL.
4. **Refusal contamination** — 4.7's cybersecurity safeguards may refuse
   security-context skills. Pilot skills chosen to minimize this; `capture`
   and `refine` are lowest risk.
5. **Prompt-prefix bias** — the `hook_inject` condition mimics what
   activation hooks do; results may be confounded with hook quality. Honest
   limitation; documented in the analysis output.
