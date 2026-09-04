# docs/

Two kinds of document live here. The split matters, because one kind is worth your
time as an evaluator and the other is a historical record.

## Start here — the "why"

| Document | What it gives you |
|---|---|
| [DESIGN_RATIONALE.md](DESIGN_RATIONALE.md) | Why the layers are split the way they are, and what each one is for. |
| [EVOLUTION.md](EVOLUTION.md) | The decision log — what changed, when, and on what evidence. Detailed entries end 2026-03-03; later decisions are recorded in the rules themselves and in `rules/incidents/`. |
| [rule-reference/](rule-reference/) | Long-form rationale for individual ambient rules, loaded on demand rather than always. |
| [PLATFORM_NOTES.md](PLATFORM_NOTES.md) | Host-specific behaviour and gotchas (large; skim by heading). |

## Reference

| Document | What it gives you |
|---|---|
| [ci-matrix.md](ci-matrix.md) | What each CI check covers. |
| [macos-migration.md](macos-migration.md) | Notes from moving the harness between hosts. |
| [sandbox-evaluation.md](sandbox-evaluation.md) | Evaluation of sandboxing options. |
| [live-arm-measurement-plan.md](live-arm-measurement-plan.md) | Measurement design for a live A/B arm. |
| [code-architecture-review-2026-06-07.md](code-architecture-review-2026-06-07.md) | A dated architecture review. |
| [research-skills-root-cause.md](research-skills-root-cause.md) | Why the five research skills showed no A/B lift on Opus 4.8 or Fable 5.1: grader artifacts, fixture ceilings, noise, and a proxy the skill forbids; per-skill recommendations. |

## What is deliberately not here

Dated audit and review reports from earlier passes were removed from this export.
Their findings are not lost — they are the reason the corresponding entries in
`rules/` and `rules/incidents/` exist, which is where a reader should look for a
lesson rather than at the report that produced it.
