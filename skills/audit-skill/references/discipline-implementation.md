# Discipline → implementation mapping

The lessons in `~/.claude/agent-memory/topics/engineering-philosophy.md`
"Audit + dev-tooling discipline (2026-05 audit retro)" describe what
went wrong in the May 2026 audit session and what we learned. This
file pins each lesson to its current implementation status — code,
test, or doc — so the disciplines don't drift back into prose-only
folklore.

When you add a new lesson to engineering-philosophy.md, add a row
here and link to the test/check that enforces it. If you can't
encode it mechanically, say so and explain why.

| Lesson | Implementation | Status |
|---|---|---|
| Pre-build discovery: audit existing tools before building new ones | `references/new-check-checklist.md` §0 (required preamble). Not mechanically enforced — judgment call at design time. | doc-only |
| New detection rules must validate against a fixture corpus before commit | `tests/test_audit_skill_fixtures.py::test_every_finding_code_has_a_fixture_trigger`. Enforced: every Finding code emitted by audit-skill.py must be triggered by at least one fixture under `tests/fixtures/`. | test |
| Reasoned-about ≠ tested | B1 check in `bin/audit-skill.py` (info-level finding when a skill has scripts/ but no tests/). Surfaces tracker-02 candidates automatically. | check |
| Labels: `[behavior-fix]` vs `[doc-fix]` | Phase 2 prose in `SKILL.md` requires the agent to label findings; severity tier (`drift` vs `info`) encodes the same distinction at the Phase 1 level. Mechanical Phase 1 lint can't tell behavior-fix from doc-fix beyond severity. | doc + severity tier |
| Before deleting a file, grep CI workflows and other skills for callers | D3c check extended to scan `.github/workflows/*.yml` and the skill's own `tests/` directory — a script reachable from either is not "dead." | check |
| Detection rules that scan SKILL.md only will miss reference-delegated invocations | M2 (and T1) scan body + `references/*.md`. Reference-delegated tool calls (e.g., gather-research → search-waves.md) are not falsely flagged. | check |
| Tools must self-audit | CI step `audit-skill self-test` runs `bin/audit-skill.py audit-skill` and `--all`, plus the helper + fixture test suite. An edit to audit-skill.py that breaks its own contract fails the PR. | CI |
| **Latent code paths** (added 2026-05-25) — code behind a flag that CI doesn't run | `test_every_cli_flag_is_exercised_in_tests` enforces that every `--flag` in main() appears in some test, the validate workflow, or SKILL.md. | test |
| **Output schema stability** (added 2026-05-25) — CI parsers / dashboards depend on the text shape | `test_output_schema_for_clean_fixture_is_stable` + `test_output_schema_for_dirty_fixture_is_stable`. Any change to the report header or finding-line format breaks the test. | test |
| **New check needs documentation** (added 2026-05-25) — Phase 2 prose drifts from Phase 1 categories | `test_skill_md_documents_every_finding_code_emitted_by_audit_py` asserts every Finding code is documented in SKILL.md / known-tools.yaml / audit-context.md. | test |
| **Suppression schema must reject typos** (added 2026-05-25) — a typo like `target_pattern:` silently fails | `_load_suppressions` validates keys against `SUPPRESSION_VALID_KEYS`. Tests in `test_audit_skill_helpers.py` pin both the typo-rejection and the missing-`reason:` rejection. | code + test |

## Skill-authoring discipline mapping

From `~/.claude/agent-memory/topics/skill-authoring.md`:

| Lesson | Implementation | Status |
|---|---|---|
| `{baseDir}` placeholder is not substituted | P1 check flags any unresolved `{baseDir}`, `{projectRoot}`, `{skillDir}` placeholder in body. | check |
| `argument-hint: "[X]"` brackets vs `required: true` | M1 check (existing) | check |
| `<your-claude-project>` resolves to nothing | P1 check also catches `<your-X>` placeholders | check |
| SKILL.md should stay under 5000 words | Q1 info-level check | check |
| Description under 1024 chars | Q2 drift-level check (Claude Code truncates above this) | check |
| Description includes WHAT / WHEN / Do NOT use for | Q3 info-level check (heuristic on description text) | check |

## How to use this file

Before adding a new lesson to engineering-philosophy.md or
skill-authoring.md, ask:

1. Can this be mechanically encoded as a check?
2. If yes — add the check, link from here.
3. If no — document why in this file under a "doc-only" row, and add
   it to the relevant SKILL.md/CONTRIBUTING.md prose so the discipline
   is at least visible to maintainers.

Periodic re-check (quarterly suggested): scan engineering-philosophy.md
for new bullets and verify each has a row here. Untracked lessons
suggest a discipline that's drifted back to folklore.
