# Change Validation Methodology

> Reference for validating architecture changes (skills, hooks, rules, memory,
> MCP servers). Used by `/validate-changes` (standalone) and `/ship`
> (Change Validation Gate). Other skills that make architecture changes
> should reference this file.

---

## Three-Phase Validation

Every architecture change requires three types of testing. Skipping any
phase means the change is unverified.

### Phase A: Regression Testing (nothing broke)

Verify that existing behavior still works after the change.

| Change type | Regression test |
|---|---|
| Skill edit | Invoke 1-2 related skills with a simple scenario. Verify they load, execute, and produce expected output structure. |
| Hook edit | Trigger the hook event on a known-good file. Verify it still fires (exit code, stderr output). Check that OTHER hooks on the same event still work. |
| Rule edit | Verify the rule file loads without syntax errors. Grep for cross-references from other rules/skills — verify those references still resolve. |
| Memory/topic edit | Run `memory_search` for the edited content. Verify it surfaces with reasonable similarity score (>0.5). Check `memory_check_duplicate` for unintended overlaps. |
| MCP server edit | Run the server's tool list verification (FastMCP `list_tools()` or `fastmcp list`). Verify tool count hasn't changed unexpectedly. |

**Pass criteria**: All existing functionality works exactly as before.
**Failure action**: Fix the regression before proceeding to Phase B.

### Phase B: Effectiveness Testing (the change works)

Verify the change does what it claims. This is the test most often skipped.

| Change type | Effectiveness test |
|---|---|
| Skill edit (new step) | Construct a scenario that exercises the new step specifically. Invoke the skill. Verify the new step fires and produces output (not silently skipped). |
| Skill edit (modified step) | Invoke with the same scenario as before the change. Verify the output differs in the expected way. |
| Hook edit (new check) | Create a test file that triggers the new check. Run the hook. Verify it catches the issue (blocks or warns). Then test with a clean file — verify no false positive. |
| Hook edit (modified check) | Run against the file that previously triggered the old behavior. Verify the new behavior fires instead. |
| Rule edit | Present a scenario (in conversation) that would have triggered the old behavior. Verify the new rule changes the response. |
| Memory edit | Search for the specific knowledge added. Verify it surfaces as the top result for a relevant query. |
| MCP server edit | Call the specific tool(s) that changed. Verify the response matches expectations. |

**Pass criteria**: The change demonstrably alters behavior in the intended direction.
**Failure action**: The change is cosmetic or broken — fix or revert.

### Phase C: A/B Comparison (before vs after)

Compare the quality of output with and without the change. This phase is
optional for low-risk changes (metadata, descriptions) but mandatory for
behavior changes (new workflow steps, modified logic, new enforcement).

| Change type | A/B test |
|---|---|
| Skill edit | Run the same test scenario twice: once reverting the change (git stash/checkout), once with it. Compare outputs side by side. Does the change produce meaningfully better results? |
| Hook edit | Run the triggering scenario with and without the hook registered. Does the hook add value beyond what rules already catch? |
| Rule edit | Present the same scenario to two contexts: one with the old rule, one with the new. Does behavior actually differ? |
| Memory edit | Search for the same query with and without the new content indexed. Does retrieval improve? |

**Pass criteria**: The change produces measurably better output than without it.
**Skip criteria**: Metadata-only changes, documentation updates, formatting fixes.

---

## Quick Validation Matrix

For rapid reference when deciding what to test:

| Change | Regression | Effectiveness | A/B |
|---|---|---|---|
| New skill step | Invoke related skills | Invoke with triggering scenario | Compare with/without |
| Hook logic change | Trigger on clean file | Trigger on target file | Compare catch rate |
| Rule wording change | Verify loads cleanly | Present target scenario | Optional |
| New memory entry | Check dedup | Search for it | Optional |
| Tool parameter change | List all tools | Call changed tool | Compare responses |
| Description-only edit | Verify loads | N/A | N/A |
| New file (no behavior) | N/A | Verify discoverable | N/A |

---

## Reporting Format

After validation, present results as:

```
=== Change Validation Report ===

Changes tested: {N} files ({list types: skill, hook, rule, memory, MCP})

Regression:    PASS | {N} checks, 0 failures
Effectiveness: PASS | {describe what was tested and the result}
A/B:           PASS | {describe comparison} OR SKIPPED (metadata-only)

Issues found:  {N}
  - {description + severity + recommendation}

Verdict: SHIP | FIX FIRST | REVERT
```
