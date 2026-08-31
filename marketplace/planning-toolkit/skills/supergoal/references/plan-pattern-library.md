# Plan-pattern library — Voyager-inspired lifelong learning

## What it is

A `~/Documents/knowledge-base/plan-patterns/` directory of reusable plan templates extracted from successful supergoal runs. Each pattern captures the *load-bearing shape* of a plan that moved its metric — Demo line shape, metric_commands shape (with project-specific paths abstracted), guard_commands shape, falsifiers shape, baseline pattern. Embedded via memory-search for similarity retrieval.

Inspired by Voyager (Wang et al., 2023) which indexed executable Minecraft programs by embedding their natural-language descriptions. Our equivalent: index reusable plan templates by embedding their purpose.

## Why it exists

Today, each new plan starts from scratch. Even after 5 successful arcs on "extractor accuracy," the 6th plan does not begin with the proven scaffolding from the 5 prior wins — the next plan author re-derives the same structure. Terminal docs capture *what didn't work* (retired hypotheses); patterns capture *what did work, structurally*.

This is the missing half of the prior-arc system. The ledger says "don't try X again" (negative signal); the pattern library says "structures like Y have worked before for tasks like Z" (positive signal).

## Write side — triggered by successful supergoal exit

When `write_terminal.py` runs with `exit_reason == "success"`:

1. Extract a pattern template from `state.json`:
   - `purpose` — derived from `plan.Goal` + `demo` (used as the embedding key)
   - `demo_template` — `Demo:` line with project-specific paths replaced by placeholders (`<TEST_PATH>`, `<METRIC_CMD>`)
   - `metric_commands_template` — same abstraction
   - `guard_commands_template` — same abstraction
   - `falsifiers_template` — keep the shape; abstract specific numbers
   - `baseline_template` — `currently <N>` / `expected <M>` with N/M as placeholders
   - `effort` — the tier this pattern was sized at
   - `provenance` — `{terminal_doc_path, date, turns_to_demo, wallclock_to_demo}`

2. Write to `~/Documents/knowledge-base/plan-patterns/<pattern-slug>.md`. Slug derived from purpose + date.

3. If memory-search MCP is available, the embedding is computed automatically when the file lands in the KB (existing indexing pipeline).

## Read side — triggered by superplan Phase 2e

When superplan reaches Phase 2 with `memory-search` substrate available:

1. Query `mcp__memory-search__memory_search(query=<task description>, source_filter="plan-patterns/", limit=3)`.

2. For each hit (cosine > 0.65), present the pattern as scaffolding:
   - "A similar task succeeded with this structure: [Demo template, metric_commands shape, falsifiers shape]"
   - Mark as *suggestion*, not mandate. The current task may differ in ways the embedding can't detect.

3. The planning agent then either adopts, adapts, or rejects each pattern. Adopted patterns get cited in the new plan's Session Context.

## Substrate-aware skips

- `memory-search` MCP unavailable → no retrieval at plan-creation time; patterns still written on successful exit (write side is independent)
- `~/Documents/knowledge-base/plan-patterns/` directory missing → first successful exit creates it
- KB has no .git → patterns are written locally but not committed; the next session won't see them across machines

## What NOT to capture in a pattern

- Project-specific paths, function names, file locations (abstract them to placeholders)
- Specific metric values (the next task will have different baselines)
- Session context / accumulated decisions (those belong in the plan's Session Context, not the reusable template)
- Failed mechanisms (those belong in terminal docs)

The discipline: a pattern should be *loadable into a new plan* without project-specific edits. If it can't be reused as-is across projects, it's not a pattern — it's a copy of one plan.

## Relationship to terminal docs

| Artifact | Captures | Read by | When written |
|----------|----------|---------|--------------|
| Plan file | This attempt's full structure (project-specific) | This session's executor | At plan creation (superplan Step 5a) |
| Terminal doc | This attempt's outcome + retired hypothesis | Next session's prior-arc check | At exit (supergoal Step 7) |
| Bug ledger row | One-line cross-session retired-mechanism index | grep tooling | At exit (when not success) |
| Plan pattern | Reusable structural template, no project specifics | Future plan creation (Phase 2e) | At exit (only when success) |

Together: terminal docs prevent re-litigation of known-bad mechanisms; bug ledger makes the cross-session view greppable; plan patterns make the cross-session view *constructive* (positive signal for next plan). The three are complementary, not redundant.

## v1 scope (this PR)

- Documentation of the convention (this file)
- Reference in supergoal SKILL.md Step 2 (retrieval) and Step 7 (write on success)
- `~/Documents/knowledge-base/plan-patterns/` directory created on first successful exit
- No automated pattern-extraction script in v1 — the agent writes patterns by hand on first successful exits, following the template shape documented here

v2 will add automated extraction once we have ~5 hand-written patterns to verify the template shape works.
