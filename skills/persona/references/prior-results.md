# Prior results — index of past dispatches and experiments

Cross-reference for context-loading. When a new run is similar to a
prior one, reading the prior result avoids re-litigating settled
questions.

## Original dispatches

### 2026-04-29 — Code-graph Go precision = 0.515 (the canonical success)

**Mode**: Discovery (loose problem, manual synthesis)
**N**: 11 (sub-agents in batches via Claude Code)
**Result**: Surfaced edge-type partitioning as a frame across 5
buckets (Bisociation, Cynefin, ToC, CoT, Grotowski). Engineering
shipped PR #121 (+0.17 precision lift). Subsequent investigation
on the same plateau surfaced PR #123 (receiver-qualification, +0.32
recall) and PR #124 (test-caller scope filter, +0.10 precision).
Aggregate F1: 0.629 → 0.890 across 5 PRs.

**Documentation**:
- `~/Documents/knowledge-base/research/2026-04-29-frameworks-applied-to-code-graph.md`
- `~/Documents/knowledge-base/research/2026-04-30-A1-chesterton-fence-module-callers.md`

## Methodology experiments (M-series)

### M1 — Measurement-design inversion

**Date**: 2026-04-30
**Output**: `~/Documents/knowledge-base/research/2026-04-30-framework-driven-metric-design.md`
**Finding**: When current metrics plateau, dispatch can be inverted to
ask "what would your framework measure that current metrics don't
capture?" Discovery mode supports `--inversion`.

### M2 — Triage gate (Article VI)

**Date**: 2026-04-30
**Output**: Article VI of `2026-04-30-framework-dispatch-template-v2.md`
**Finding**: 5-trigger AND-gate prevents speculative dispatch. ≥2 of
5 must hold.

### M3 — Inventory audit

**Date**: 2026-04-30
**Output**: `~/Documents/knowledge-base/research/2026-04-30-inventory-audit.md`
**Finding**: 165/170 entries quality-passing. Mean word count 135.
No rewrite needed.

### M4 — Scaling experiment

**Date**: 2026-04-30
**Output**: `~/Documents/knowledge-base/research/2026-04-30-scaling-experiment-results.md`
**Finding**: All-3-RC saturates at N=11 on synthetic fixture. Higher
N slightly increases FL rate. Saturation generalizes across Haiku/
Sonnet/Opus (all hit 100% all-3-RC at N=11). Capability tier reduces
noise (~30% fewer FL on Sonnet/Opus) but not signal.

**Caveat (F6 finding)**: synthetic fixture telegraphed answers in
its symptoms. Saturation may be fixture-specific, not general.

### M5 — Prompt-detail × code-context ablation

**Date**: 2026-04-30
**Output**: Same doc as M4
**Finding**: Detailed framework prompt + lean code context = lowest
FL rate (small effect; n=15 per cell underpowered for strong claims).

### F6 — Fixture-validity test

**Date**: 2026-04-30
**Output**: `~/Documents/knowledge-base/research/2026-04-30-f6-fixture-validity-results.md`
**Finding**: B1 casual scoring and B2 rubric scoring measure
orthogonal constructs (kappa=0). Loose problem + rubric =
uninterpretable (0% RC endorsement). Structured problem + LLM-judge
= meaningful rubric scoring. Off-rubric "novelty" is mostly generic
diligence advice, not insight. **Most important methodology finding
in the session.**

### Red-team self-critique

**Date**: 2026-04-30
**Output**: documented in conversation; informed v3 design
**Finding**: synthetic fixture leaks answers; keyword scoring p-hacked;
bucket-coverage sampling tautologically saturates at N=11; no null/
no-framework controls; single seed.

## Post-skill runs (will populate as they happen)

The skill auto-appends to `~/Documents/knowledge-base/research/dispatch-runs/INDEX.md`
on every run. That file serves as the live cross-reference.

Format per entry:
```
| Date | Slug | Mode | Problem | N | Model | Key metric | Link |
```

## How to use this index

When dispatching against a new problem:
1. Check this file for similar prior problems
2. If found, read the prior run's `analysis.md` for what was tried
3. Avoid re-running what's already been settled
4. If extending, cite the prior result in the new run's pre-registration

When designing a new methodology experiment:
1. Check the M-series for prior tests of similar variables
2. If pre-registered hypothesis was already tested, replicate not
   redo
3. If finding superseded by F6 or red-team, design the new
   experiment to address the residual
