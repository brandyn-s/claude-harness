# Phase 3 Profile Format — Pattern Entries, Groupings, Length, Tracking

Consult when writing the Phase 3 profile and the Phase 5 tracking section.

## Format for each pattern

```
### Pattern: <name>
**Evidence:** <commit SHA / PR #number / file:line / quote>
**What they do:** <1-2 sentences>
**Why it works for them:** <context — their role, team size, repo type>
```

## Target length

50-100 lines per profile (persisted to knowledge base). 2-4 sentences per
pattern. Prolific developers with many repos may warrant up to 120 lines, but resist the
urge to document every pattern — only patterns that have a chance of surviving Phase 4 gates
are worth synthesizing in detail.

## Groupings (code-first ordering)

- **Coding style & practices** (naming, function decomposition, error handling, type usage,
  comment density, guard clauses, import organization — PRIMARY grouping, highest signal)
- **Architecture & design** (module structure, dependency philosophy, configuration approach,
  performance instrumentation, security posture)
- **Automation & tooling** (skill design, hook architecture, agent configuration, CLAUDE.md
  philosophy, settings patterns, prompt engineering in automation — NEW, from Tier 2 evidence)
- **Engineering discipline** (test behavior, refactoring isolation, revert patterns)
- **Workflow practices** (commit messages, PR patterns, branch naming, merge speed)
- **Collaboration style** (review voice, review response, triage, participation breadth)
- **Documentation & communication** (PR descriptions, docs contributions, commit rationale)

## Language-tagging worked examples

`[principle-transferable]` — the mechanism is language-specific but the underlying principle
applies everywhere. Extract the principle explicitly. Example: Rust's `#[non_exhaustive]`
is a Rust attribute, but the principle "don't break callers when adding variants" applies
to Python enums and TypeScript union types. Python's `dataclasses vs dicts` is Python
syntax, but the principle "structured data vs ad-hoc maps" applies universally.

## No-vibes rule — prompt engineering example (2m)

For prompt engineering patterns (2m): the artifact is the skill/agent file and the evidence
is a direct quote of the specific text. "Their /review skill uses a severity decision tree
at SKILL.md lines 45-60: `if security → critical, if performance → warning, else → info`"
is a pattern. "They write good prompts" is not.

## Effectiveness tracking — `## What Shipped` template (Phase 5)

Add a `## What Shipped` section to the persisted profile. After Phase 5, record:

```
## What Shipped
- [date] Recommendations made: N
- [date] Recommendations implemented: (fill after integration)
- [date] Recommendations reverted: (fill if revert trigger fires)
- [date] Latent gaps promoted: (fill when incidents surface)
```

This section is updated by future sessions — not by this run. It closes the feedback loop
so you can measure whether the skill's recommendations are actually improving the
architecture over time. A skill that produces 7 recommendations where 0 ship is a
different problem than one that produces 7 where 5 ship and 2 revert.
