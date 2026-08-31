# Superplan Phase 2 & 3 — Detailed Procedure

Full procedure for context loading (Phase 2 + sub-phases 2b/2c/2d/2e),
capability assessment (Phase 3 + 3.0), estimation/ambiguity resolution
(Phase 3b), and size-of-effect baseline + tiered opportunity gate
(Phases 3.5 + 3.6). Loaded by `/superplan` after the user's task
triggers planning. SKILL.md keeps the high-level Phase outline and
calls out this file for the procedural detail.

---

## Phase 2: Context Loading

Load context for the detected domain(s), with depth proportional to
primary vs supplementary designation.

**Substrate-guarded.** Each step below fires only if the corresponding Phase -1 probe returned Y. If all probes returned N (running outside the superplan substrate, e.g., on a fresh laptop or in a non-Example repo), skip Phase 2 entirely and proceed to Phase 3 with no domain-specific context. Note in output: `PHASE 2 — Skipped (no substrate)`.

### For the primary domain:

1. **Topic file** (operational gotchas and key patterns):
   - Read `~/.claude/agent-memory/topics/{domain}.md` (e.g., `crowdstrike.md`, `ramp.md`, `infrastructure.md`)
   - These contain: critical gotchas, auth constraints, response format quirks, key patterns
   - Note: [confirmed] entries are reliable facts. [observed] entries are leads.

2. **Deep reference** (full pattern details, if needed):
   - Read `~/.claude/projects/$CLAUDE_PROJECT_ID/memory/{tool}-patterns.md`
   - Only if the topic file's summary is insufficient for planning

3. **MCP tool inventory** (what's available for this domain):
   - Use `~/.claude/rules/mcp-tool-names.md` as the curated index, then load the current tool schema with ToolSearch using the reference's exact `select:` query. The older seven-day failure-rate warning predates native lazy loading and is not a current routing rule. If an exact selection returns no match, verify the current server registration and retry the exact server/tool identity before recording the capability as unavailable.
   - Note which MCP servers are relevant
   - Note which have OPA-gated writes requiring confirmation (CrowdStrike, Airlock)
   - Note which operations require Python scripts instead of MCP (bulk data, writes to read-only tools)
   - Do not assume a child inherits the parent's remote MCP authentication. Plan auth-required qualification probes in the main thread unless the child MCP configuration and effective authentication have been tested in the current release.

### For supplementary domains:

- Read the topic file only (step 1 above)
- Skip deep reference pattern files
- Note relevant MCP servers and read-only restrictions

### Phase 2b: Semantic Memory Search (if memory-search MCP available)

**Substrate-guarded.** Skip silently if the memory-search MCP is not available in this session (Phase -1 probe `memory-search:N`). Note in output: `PHASE 2b — Skipped (memory-search MCP unavailable)`.

After loading domain-specific files, call `mcp__memory-search__memory_search(query=<task description>, limit=5)` to surface cross-domain patterns that keyword-based domain detection would miss. This catches:
- Patterns in unexpected topic files (e.g., security.md learned something about Graph that helps a runbook task)
- Topic file entries that don't match domain detection keywords
- Stale entries that need attention before planning around them

### Phase 2c: Knowledge Base Context

**Substrate-guarded.** Skip silently if memory-search MCP is unavailable OR `~/Documents/knowledge-base` does not exist. Note in output: `PHASE 2c — Skipped (no KB)`.

After Phase 2b, query `mcp__memory-search__memory_search` for KB entries
relevant to the task, filtered to `knowledge-base/topics/` sources.

The full procedure (search query format, cosine relevance filter, two-pass
loading to prevent context bloat, 30-day date caveat, deduplication against
agent memory, skip conditions) is in `references/phase-2c-kb-context.md`.

Quick-reference summary: cosine > 0.65 minimum, max 3 full topic pages or 5
entries; skip entirely if Phase 2a-2b already provided sufficient context or
no KB results meet the threshold.

### Phase 2d: Prior-arc plan loading (mandatory if memory-search hits a prior plan against the same metric)

**Substrate-guarded.** Skip silently if `~/Documents/knowledge-base/plans` does not exist AND memory-search MCP is unavailable. Note in output: `PHASE 2d — Skipped (no plans dir)`.

If memory-search OR a `Glob ~/Documents/knowledge-base/plans/*.md` + grep against the task's named metric (e.g. `HTTP_CALLS`, `Acc@10`, `MRR`, named entity from request) returns ≥1 prior plan file, load those plan files.

### Phase 2e: Plan-pattern retrieval (Voyager-inspired scaffolding)

**Substrate-guarded.** Skip silently if `memory-search` MCP is unavailable OR `~/Documents/knowledge-base/plan-patterns/` does not exist. Note in output: `PHASE 2e — Skipped (no patterns dir or memory-search MCP)`.

Query `mcp__memory-search__memory_search(query=<task description>, source_filter="plan-patterns/", limit=3)`. For each hit (cosine > 0.65), present as scaffolding suggestion:

> A similar task succeeded with this structure:
>   Demo template: `<from pattern>`
>   Metric commands shape: `<from pattern>`
>   Falsifiers shape: `<from pattern>`

Patterns are *suggestions*, not mandates. The planning agent adopts, adapts, or rejects each. Adopted patterns get cited in the plan's `## Session Context`.

This is the **positive** half of cross-session learning — Phase 2d's prior-arc check is the negative half (don't try retired mechanisms again); Phase 2e provides "structures like this have worked before." See `${CLAUDE_PLUGIN_ROOT}/skills/supergoal/references/plan-pattern-library.md` for the full convention (absolute path; the citation is to a sibling skill's references/ directory).

For each prior plan:
1. Read the file. Extract: the proposed mechanism, the predicted size-of-effect, and (from the matching topic page or terminal doc) the measured outcome.
2. Tabulate as a "prior-arc ledger":

   | Plan date | Proposed mechanism | Predicted | Measured |
   |---|---|---|---|
   | 2026-05-07 | reqwest URL extraction | ≥30 HTTP_CALLS | 0 |
   | 2026-05-08 (D1) | handler resolution rework | ≥80% task-specific | 17.6% |

3. **The current plan must position against this ledger via Phase 3.6 field 5 (prior-plan-attribution).** If the current plan proposes a mechanism that any prior plan in the ledger has already proposed (under a different name or with a different shape) and not moved the metric, the current plan must explain — with new evidence, not new confidence — why this mechanism would succeed where the prior didn't.

**Why this exists:** the 2026-05-08 multi-plan arc shipped 4 consecutive PRs (#247, #255, #256, #257) each proposing a different mechanism for the same PSM HTTP_CALLS / IMPLEMENTS metrics, each carrying full confidence that *this* plan had finally identified the gap. None of them moved the metric. The single-arc memory check forces the new plan to confront the prior ledger before stamping its own confidence.

## Phase 3: Capability Assessment

Before planning HOW to do the task, establish WHAT IS POSSIBLE:

### Step 3.0: Query the manifest graph (if available)

**Substrate-guarded.** Skip silently if `~/.claude/manifests/query_engine.py` does not exist (Phase -1 probe `manifests:N`). Note in output: `PHASE 3.0 — Skipped (no manifest graph)`.

Before reading files manually for structural questions, check if the
manifest graph can answer directly. Run via Bash:

```bash
# What does the primary skill depend on? (tools, topics, rules, auth)
python3 ~/.claude/manifests/query_engine.py depends_on {skill_id}

# Can this be dispatched to a subagent?
python3 ~/.claude/manifests/query_engine.py auth_requirements {skill_id}

# What hooks enforce constraints for this workflow?
python3 ~/.claude/manifests/query_engine.py enforcement_chain "{tool_action}"

# What breaks if a dependency is unavailable?
python3 ~/.claude/manifests/query_engine.py impact_of_removal {component_id}

# Which rules lack mechanical enforcement? (prose-only constraints)
python3 ~/.claude/manifests/query_engine.py unenforced_rules
```

These return typed answers from the compiled graph — no prose reading
needed for dependency, auth, or enforcement questions. Use results to
populate the capability matrix below. Only read SKILL.md/topic files
for behavioral details manifests don't capture (workflow logic, scoring
criteria, edge case handling).

**Skip this step** if the task doesn't involve existing skills or tools
(e.g., building something entirely new).

### Tool capability matrix (fill in for detected domains):

```
| Action needed | MCP tool available? | Read-only? | Script needed? | Agent |
|--------------|--------------------|-----------|--------------:|-------|
| [from task]  | [yes/no]           | [yes/no]  | [yes/no]      | [name]|
```

### Known constraints (from loaded context + manifest queries):

- API rate limits, batch size limits, pagination gotchas
- Authentication requirements — `auth_requirements` query shows which skills need main_thread
- Write restrictions (which tools are read-only via MCP?)
- Enforcement gaps — `unenforced_rules` query shows which constraints are prose-only
- Platform constraints (Windows/Git Bash, encoding, path formats)

### Execution path options:

Consult the **Execution Path Options** table in `references/planning-framework.md` to select the right path (MCP direct, Python script, PowerShell, parallel dispatch, sequential pipeline, superpowers chain, or main thread inline).

## Phase 3b: Estimation and Ambiguity Resolution

Before constructing the plan, classify questions (Codebase Fact vs User
Preference vs Scope vs Requirement), scan for ambiguities, run
evidence-grounded option evaluation when choices depend on codebase
state, and estimate effort using XS/S/M/L/XL calibrated baselines.

See `references/estimation-and-ambiguity.md` for the full question
classification matrix, ambiguity scan procedure, Explore-agent option
evaluation protocol, and effort estimation tables with project-specific
calibrations.

### Lite-mode short-circuit

If `--lite` was passed OR the effort estimate is **XS** (≤15 min execution, no measurable property to baseline, no cross-domain coordination), emit a 3-line plan in this format and stop after this section:

```
Goal: <one sentence>
Steps:
  1. <action> — <tool/command>
  2. <action> — <tool/command>
  3. <action> — <tool/command>
Verification: <observable signal that the task is done>
```

Skip Phases 3.5, 3.6, 4c, 5a entirely. Do **not** persist a plan file (unless `--persist=always` was explicitly passed). The plan stays inline in the conversation, the same shape `/plan` would produce. The completion checklist items tagged `[size-of-effect]`, `[falsifier]`, `[refresh-then-decide]`, and `[prior-arc]` are inapplicable and not required.

This is the path that makes superplan never worse than `/plan` for trivial tasks.

## Phase 3.5 + 3.6: Size-of-Effect Baseline + Tiered Opportunity Gate

**Fires when** the plan claims to lift / improve / fix a measurable property of a
real target (codebase, indexed graph, service, metric, extractor).

**Skip when** the plan is purely greenfield, purely structural, or operational
(binary success).

When firing, both phases are MANDATORY before Phase 4. The full procedure
(Phase 3.5 baseline measurement + mechanism-correctness verification +
Phase 3.6's 6-field gate per implementation phase + derivation labels +
historical failure-mode catalog) is in
`references/size-of-effect-gate.md`. Read it before authoring any size-of-effect plan.

**Stop-gates** (cannot enter Phase 4):
- Phase 3.5: any size-of-effect prediction without a corresponding baseline measurement
- Phase 3.6: any implementation phase missing any of the 6 fields (substrate count, layer check, max recoverable lift, local→terminal ladder, prior-plan attribution, n-power budget)

Fields marked `N/A` require explicit justification (e.g. "field 5 N/A — first plan against this metric; verified via `Glob ~/Documents/knowledge-base/plans/ + grep`").

**Save the baseline as a plan artifact** at `~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>-baseline.md` (sibling of the plan file). Phase 4 cites this artifact; Phase 5 ships them together.
