---
name: validate-changes
description: "Validate architecture changes (skills, hooks, rules, MCP) with regression and A/B testing."
when_to_use: 'Use when architecture changes (skills, hooks, rules, memory, MCP servers) need validation before shipping. Runs regression, effectiveness, and A/B testing adapted to the change type. Trigger phrases: "validate changes", "test this", "A/B test", "regression test", "did the change work". Do NOT use for code testing (use pytest/TDD), deployment verification, or STIG verification.'
argument-hint: "[omit for full git-state auto-detection, or specify file paths]"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: AskUserQuestion Bash Glob Grep Read Skill mcp__memory-search__memory_check_duplicate mcp__memory-search__memory_search
---

## validate-changes

# Change Validation

Validate architecture changes with regression, effectiveness, and A/B testing.
Adapts the test protocol to the change type.

> **Methodology**: Read `~/.claude/skills/_shared/change-validation.md` for
> the full testing framework and reporting format.

---

## Step 1: Detect Changes

If arguments are provided, use them as the file list. Otherwise, auto-detect:

```bash
git fetch origin main --quiet
# VALIDATE_SKILL_ROOT is the directory containing this loaded SKILL.md.
python3 "$VALIDATE_SKILL_ROOT/scripts/change_contract.py" inventory \
  --repo "$(git rev-parse --show-toplevel)" --base origin/main
```

Use the returned `all_paths` from the `scripts/change_contract.py inventory`
command as the complete validation scope. It is the union
of the full multi-commit target range in `committed_paths`, `staged_paths`,
unstaged paths, and untracked paths. Record `base_oid`; if a later fetch,
rebase, or branch switch changes that base, rebuild the inventory and rerun the
broadest affected validation. `HEAD~1` and an unstaged-only diff are not valid
auto-detection oracles.

Classify each changed file:

| Path pattern | Change type |
|---|---|
| `skills/*/SKILL.md` | skill |
| `skills/*/references/*.md` | skill-reference |
| `skills/_shared/*.md` | shared-reference |
| `hooks/*.py` | hook |
| `rules/*.md` | rule |
| `agent-memory/topics/*.md` | topic-memory |
| `*-patterns.md` | pattern-memory |
| `*_mcp.py`, `*_mcp_server.py` | mcp-server |
| Other `.md` in memory paths | memory |

Present the detected changes:

```
Detected changes:
  [skill]  a separate skill (not included in this export)
  [skill]  skills/triage/SKILL.md
  [hook]   hooks/bash-security-guard.py
  [rule]   rules/context7-docs.md

Running validation for 4 changes (2 skill, 1 hook, 1 rule)...
```

---

## Step 1a: Vendor Contract Freshness Gate

When a change depends on Claude Code, an SDK, an API, or another vendor runtime
contract, internal green tests prove only repository self-consistency. Before
using them as release evidence, record the exact installed/runtime version and
reconcile the changed behavior against current first-party documentation,
schema, and effective wiring. If current first-party evidence is not already
available, report `CONTRACT UNVERIFIED`, route through the applicable vendor
gathering skill (for Claude Code, `/gather-claude`), and rerun validation. Do not
let a golden test that encodes obsolete semantics produce a SHIP verdict.

This is a release-evidence gate: **CONTRACT UNVERIFIED blocks SHIP** even when
regression, effectiveness, and A/B results are green. Carry the contract status
into Step 5 and use the executable verdict helper; do not downgrade it to an
issue-list note.

---

## Step 1b: Load Golden Test Cases

For each modified skill, check `~/.claude/tests/{skill-name}/` for pre-defined
test scenarios. These are YAML files with `must_happen`, `must_not_happen`,
`output_contains`, and `guards` assertions.

```
tests/
  triage/
    01-security-detection-triage.yaml
    02-code-related-finding-with-index.yaml
    03-code-related-finding-no-index.yaml
```

If golden tests exist for the modified skill:
- **Use them as the primary test source** — they define exactly what
  must/must-not happen for each scenario
- Run every scenario for the skill (not just one)
- Report per-scenario pass/fail

If no golden tests exist for the skill:
- Fall back to constructing tests ad-hoc (Steps 2-4 below)
- Note "No golden tests for {skill} — using ad-hoc validation"
- After validation, suggest adding test cases: "Consider adding golden
  tests to ~/.claude/tests/{skill-name}/ for future regression detection"

Golden test assertions map to validation phases:
- `must_happen` + `must_not_happen` → Regression (Step 2) + Effectiveness (Step 3)
- `output_contains` → Effectiveness (Step 3)
- `guards` → Regression (Step 2)
- `skip_ab` → Whether to run A/B (Step 4)

---

## Step 2: Regression Testing

For each change type detected, run the appropriate regression check from
the methodology reference.

**Skills**: For each modified skill, verify it loads by checking frontmatter
validity (name, description fields present and under limits). Then invoke
one related skill with a minimal scenario to confirm no cross-skill breakage.

**Hooks**: For each modified hook, run it against a known-clean input:
```bash
echo '{"tool_name":"Write","tool_input":{"file_path":"'"${TMPDIR:-/tmp}"'/test.md","content":"hello"}}' | python3 hooks/<hook>.py
```
Verify exit code 0 (allow) or expected behavior. Check that sibling hooks
on the same event still fire.

**Rules**: Verify the rule file parses as valid markdown. Grep other rules
and skills for references to this rule file — verify none are broken.

**Memory**: Run `mcp__memory-search__memory_search(query="<edited content summary>")`.
Verify it returns results. Run `mcp__memory-search__memory_check_duplicate`
on any new entries to catch unintended overlaps.

**MCP servers**: Write a quick verification script:
```python
import asyncio
from {service}.{service}_mcp import mcp
async def verify():
    tools = await mcp.list_tools()  # public API; matches _shared/change-validation.md
    print(f"Tools: {len(tools)}")
asyncio.run(verify())
```

Report: `"Regression: PASS/FAIL — {N} checks, {M} failures"`

---

## Step 3: Effectiveness Testing

For each change, construct a targeted test that exercises the specific
modification.

**Skill edits (new or modified steps)**:
1. Identify what the change is supposed to do (read the diff)
2. Construct a scenario that would trigger the new/modified step
3. Invoke the skill (or simulate the relevant phase)
4. Verify the new behavior fires — look for the specific tool calls,
   output sections, or decision points the change introduces
5. If the change adds a code-search/code-graph/memory-search call,
   verify the tool is actually called (not silently skipped due to
   missing index or guard condition)

**Hook edits**:
1. Create a test input that should trigger the new check
2. Pipe it to the hook
3. Verify it catches the issue (stderr output, non-zero exit code, or
   modified output)
4. Create a clean input that should NOT trigger
5. Verify no false positive

**Rule edits**:
1. Present a scenario in conversation that exercises the rule
2. Verify the response reflects the rule's guidance
3. Present a scenario that should NOT trigger the rule
4. Verify it doesn't over-apply

Report: `"Effectiveness: PASS/FAIL — {describe what was tested}"`

---

## Step 3b: Creative-Regression Mode (if change affects creative-discovery skills)

Fires when the change set includes any of `/scout-frontier`, `/brainstorm`, `/deep-dive`, `/refine`, OR when a model-migration is being evaluated against these skills.

Use the canonical fixture at `references/creative-test-prompts.md` (7 prompts modeled on the KINTAL Creative Benchmark). Each prompt is scored on two dimensions: distinctness (1-5) and grounding (1-5). Pass criterion: ≥80% of prompts score within 1 rubric-point of baseline on both dimensions.

Procedure:
1. For a model migration, pin the exact effective model IDs and runtime
   versions before generating outputs:

   ```bash
   python3 "$VALIDATE_SKILL_ROOT/scripts/change_contract.py" migration \
     --baseline-model <exact-model-id> \
     --treatment-model <exact-model-id> \
     --baseline-runtime <exact-runtime-version> \
     --treatment-runtime <exact-runtime-version>
   ```

   Do not infer either identity from a marketing family name, mutable alias,
   current default, or an old experiment. Hold prompts, tools, permissions,
   effort, context-compaction state, and sampling settings constant unless one
   is the declared treatment variable.
2. Run the skill pre-change or the recorded baseline identity on all 7 prompts.
   Capture outputs and the exact effective model IDs reported by the runtime.
3. Run the skill post-change or the recorded treatment identity on the same 7
   prompts. Capture outputs and effective identity again; a silent fallback is
   `CONTRACT UNVERIFIED`, not a treatment result.
4. Score each output mechanically per the rubric (`references/creative-test-prompts.md` "How to score outputs" section). Distinctness counts paraphrase clusters; grounding counts confidence + provenance + counterfactual signals per load-bearing claim.
5. Compare: per-prompt baseline-vs-treatment delta on each dimension.
6. Aggregate: ≥80% within-1-rubric-point on both dimensions → PASS.

Failure handling: do NOT block the change. Emit a structured report and let the user decide. The 80% threshold is a recommendation gate, not a hard block — some valid changes legitimately reshape the rubric.

Report format:
```
=== Creative-Regression ===
Fixture: 7 prompts (creative-test-prompts.md)
Baseline:  Distinctness avg 4.0 / Grounding avg 4.1
Treatment: Distinctness avg 3.6 / Grounding avg 4.3
Within-1-rubric-point: 6/7 prompts (85.7%) → PASS
Failed prompts: Prompt 3 (variation generation, mode-collapse on treatment)
Verdict: PASS — recommend ship; investigate Prompt 3 failure for follow-on
```

The historical Opus 4.7 versus 4.6 run is **Experiment 11** in the research
backlog (`~/Documents/knowledge-base/research/claude-code-research-intelligence.md`).
It is historical evidence only; use that pair only when it is the explicitly
requested migration, never as this protocol's implicit default.

---

## Step 4: A/B Comparison (if applicable)

**When to run**: Behavior changes (new workflow steps, modified logic,
new enforcement). **When to skip**: Metadata-only, description-only,
documentation, formatting.

For skills, the A/B test is:
1. Note the current behavior (baseline) — either from the diff's "before"
   or by reverting the change temporarily
2. Run the test scenario with the change applied (treatment)
3. Compare side by side
4. Report whether the change produces meaningfully better output

For hooks and rules, compare catch rates or behavior differences with
and without the change.

Report: `"A/B: PASS/SKIPPED — {describe comparison or skip reason}"`

---

## Step 5: Report

Present the validation report using the format from
`_shared/change-validation.md`:

```
=== Change Validation Report ===

Changes tested: {N} files ({list types})

Regression:    PASS | {N} checks, 0 failures
Effectiveness: PASS | {describe what was tested}
A/B:           PASS | {describe comparison} OR FAIL (no improvement) OR SKIPPED (metadata-only)
Contract:      CONTRACT VERIFIED | CONTRACT UNVERIFIED | NOT APPLICABLE

Issues found:  {N}
  - {description + severity + recommendation}

Verdict: SHIP | FIX FIRST | REVERT
```

Calculate the final gate after the phase results are known:

```bash
python3 "$VALIDATE_SKILL_ROOT/scripts/change_contract.py" verdict \
  --regression <PASS|FAIL> --effectiveness <PASS|FAIL> \
  --ab <PASS|FAIL|SKIPPED> \
  [--vendor-dependent --contract-status <VERIFIED|UNVERIFIED>]
```

If all phases pass and every applicable vendor contract is verified:
`"Verdict: SHIP — all validation passed."`
If a vendor-dependent contract is unverified:
`"Verdict: FIX FIRST — CONTRACT UNVERIFIED; refresh first-party evidence and rerun."`
If regression fails: `"Verdict: FIX FIRST — regression failures must be resolved."`
If effectiveness fails: `"Verdict: FIX FIRST — change does not produce intended behavior."`
If A/B shows no improvement: `"Verdict: REVERT — change adds complexity without measurable benefit."`

For skill and creative-regression changes, the PASS/FAIL and the SHIP/FIX FIRST/REVERT verdict are a *recommended* verdict derived from LLM judgment of the outputs, not a hard mechanical gate — the user decides whether to ship.

---

## Success Criteria

- All changed files detected and classified correctly
- Vendor-dependent changes are reconciled to the exact runtime version and
  current first-party contract before internal regression results support SHIP
- Model migrations record distinct exact baseline/treatment model IDs and
  runtime versions; mutable aliases and historical pairs are not defaults
- Regression tests run for every changed file type
- Effectiveness tests constructed from the actual diff (not generic), OR loaded as golden tests from `~/.claude/tests/{skill}/` when available (per Step 1b)
- A/B comparison run for behavior changes, skipped for metadata
- Report uses structured format with clear verdict
- Issues found are specific and actionable (not "needs more testing")

## Examples

**Example 1: Skill edits after tool integration**
User says: `/validate-changes`
Detected: 5 skill SKILL.md files modified (investigate, triage, security-alerts, mcp-forge-build, mcp-forge-audit)
Regression: invoke each skill with minimal scenario, verify frontmatter valid, no cross-skill breakage
Effectiveness: for investigate, construct a code-related finding scenario, verify codebase analysis step fires and calls get_index_status
A/B: compare investigate output on same finding with and without the codebase analysis step
Verdict: SHIP

**Example 2: Hook logic change**
User says: `/validate-changes hooks/bash-security-guard.py`
Regression: pipe known-clean Bash command, verify exit 0. Pipe known-blocked command, verify exit 2.
Effectiveness: pipe the specific new pattern the hook should catch, verify it blocks
A/B: compare block rate with old hook vs new hook on a set of 10 test inputs
Verdict: SHIP

**Example 3: Rule wording strengthened**
User says: `/validate-changes rules/context7-docs.md`
Regression: verify file loads, grep for references from other rules — all resolve
Effectiveness: present an API integration scenario, verify response references the "Never guess" section
A/B: SKIPPED (wording change, not logic change)
Verdict: SHIP
