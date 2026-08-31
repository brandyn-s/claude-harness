# Plan: Implementation of 2026-04-28 Gather-Research Findings

```
Created: 2026-04-29
Author: you (drafted by Claude via /superplan)
Source research: ~/Documents/knowledge-base/research/claude-code-research-intelligence.md (last update 2026-03-28)
                 + Phase C report from 2026-04-28 gather-research run on focus area "LLM-driven novel
                   technique / frontier idea discovery for systems where the user is not the domain expert"
Target ship: 5 PRs across example-org-Dev/claude-config (protected repo)
Total size: L (~14-20 working hours; one PR per session recommended)
Status: Awaiting execution
```

## How to execute this plan

This plan is designed to be picked up by a fresh Claude Code session with minimal context.
The session that drafted this plan accumulated ~250K tokens of research context; trying to
execute all 5 PRs in one session compounds context cost and risks Edit conflicts.

**Recommended execution flow (per PR):**

1. Start a fresh Claude Code session in `~/.claude/`
2. Read this plan file (`Read` on the path above)
3. Run `/superplan` Phase 4b critical review gate against this plan to check for staleness:
   - `git log --oneline --since="2026-04-29"` — has anything changed in claude-config since plan was written?
   - Confirm the protected-repo status of claude-config in `git-hygiene.md` is unchanged
   - Confirm the prior-session research report appended successfully (PR #1 verification step)
4. Create tasks via TaskCreate for the chosen PR's phase steps
5. Execute the phase end to end, marking tasks completed as you go
6. Commit per the PR's branch + auto-merge instructions
7. Stop after the PR merges; start a new session for the next PR

**Stop-and-ask gates during execution:**
- Hit a blocker (missing file, manifest validation fails, hook test fails): STOP, raise to user
- Plan step produces unexpected output: STOP, re-evaluate
- Verification fails on 2+ consecutive steps: STOP, question the plan
- DO NOT force through blockers

---

## Goal

Operationalize the 10 findings + 3 threads from the 2026-04-28 gather-research run into the
Claude Code architecture as 5 PRs that ship combinational-variation-at-scale-with-verification
capability across skills, hooks, rules, and documentation, while preserving the
`validate-to-improve.md` discipline (metadata vs behavior PR separation).

## Program-level Demo

Post-PR-#5 merge, a user types "I want to find frontier improvements to my code-graph engine":

1. `skill-routing-hint.py` suggests `/scout-frontier`
2. The user runs `/scout-frontier`
3. Output shows VS-style probability assignments, ordinary personas (NOT "Steve Jobs"), and
   abstraction-then-mapping discipline; candidate diversity is measurably higher than pre-merge baseline
4. Every recommendation carries confidence + provenance + counterfactual signals
5. The new `creative-output-grounding-check.py` PostToolUse hook verifies grounding silently
6. If the user later attempts model migration (`/validate-changes` against Opus 4.X), the
   creative-regression A/B test fires against the canonical fixture and gates the migration

## Domains

| Designation | Domain | Topic file |
|---|---|---|
| **Primary** | Architecture / Claude Code config | `architecture.md` |
| Supplementary | Skill authoring | `skill-authoring.md` |
| Supplementary | Knowledge management | `recall.md` (via /capture, /recall pattern) |
| Supplementary | Hook development | `hook-design.md` |

## Constraints (loaded from ambient rules)

- **`check-before-change.md`**: Every file modification requires reading the current state first. Memory of prior reads is not evidence.
- **`skill-standards.md`**: SKILL.md ≤100 lines (split trigger to references/), description ≤1024 chars (front-load triggers in first 250), Examples + Success Criteria sections required, `compatibility:` block recommended.
- **`claude-md-quality.md`**: CLAUDE.md ≤120 lines total, ≤20 lines per section.
- **`rule-authoring.md`**: New ambient rule must use DSL or constitutional format with explicit GUARD blocks naming common override patterns ("trust me," "small change," "urgent").
- **`validate-to-improve.md`**: Metadata-only changes ship in different PRs from behavior changes. NEVER mix.
- **`platform-constraints.md`**: Python files require `encoding='utf-8'` + `sys.stdout.reconfigure(encoding='utf-8')`. YAML files use `write_bytes` to avoid CRLF translation. Forward slashes in paths.
- **`git-hygiene.md`**: claude-config is in PROTECTED_REPOS (per example-org transfer 2026-04-26). Feature branch + PR + auto-merge mandatory. NO `--admin` (retired). NO direct push to main.
- **`subagent-verification.md`**: PROTECTED_REPOS includes claude-config. Subagent dispatch with `isolation: worktree` is mandatory IF dispatching at all. Parallel worktree-isolated subagents are FORBIDDEN (#48927 + #48811).
- **`verify-effectiveness.md`**: Two-part validation required. Plumbing tests (does it parse) AND outcome tests (does it actually do what it claims). Hook addition requires retroactive replay against historical transcripts.
- **`scope-discipline.md`**: Ship existing-tooling deliverable before building new infrastructure. Prefer extension over new skill.

## Session Context (decisions made, rationale)

**Why 5 PRs and not 1:**
`validate-to-improve.md` mandates separating metadata changes from behavior changes. PRs #1, #5, and Track 5/7 artifacts are pure metadata; PRs #2, #3, #4 are behavior changes that each need independent regression review. Mixing them was a documented incident category (skills-polish 2026-03-20).

**Why sequential PR execution and not parallel subagent dispatch:**
- claude-config is in PROTECTED_REPOS per `subagent-verification.md`; any subagent that writes must use `isolation: worktree`
- Parallel worktree-isolated subagents are forbidden per #48927 (data-loss) and #48811 (silent isolation skip)
- Therefore: serialize all writes to claude-config in main thread

**Why the new hook is `warn` and not `block`:**
- `scope-discipline.md` says don't enforce speculative patterns; `warn` allows observation of false-positive rate before tightening
- `verify-effectiveness.md` Procedure for hook retroactive testing requires historical replay; if the hook would block >10% of historical creative-skill outputs, criteria must be tuned before block-mode

**Why a new ambient rule and not embedded skill steps:**
- `skill-standards.md` Cross-Skill Pattern Enforcement section: rules embedded as steps in one skill don't fire when a different skill is invoked
- The output-grounding pattern applies across `/scout-frontier`, `/brainstorm`, `/deep-dive`, `/refine` — single-skill embedding would miss 3 of 4 skills
- Therefore: ambient rule + hook is the correct integration tier (Tier 4: Decision gate)

**Why `/oblique-discovery` is NOT being built:**
- `compare-by-need.md`: there is no documented friction yet from the absence of this skill
- The original chat was speculative ideation, not response to a real failure
- `/scout-frontier` + Verbalized Sampling patch closes the genuine gap
- Decision deferred to post-PR-#2 friction observation; if `/scout-frontier` proves insufficient on real problems, build then

**Why MINES invariant inference is deferred:**
- `scope-discipline.md`: don't build infrastructure ahead of documented friction
- The user's "code-graph engine I no longer understand" pain hasn't manifested as a blocker in conversation history
- Experiment 9 design is captured in research report; build fires when friction observed

**Open questions (to raise during execution if relevant):**
- PR #3 hook: PostToolUse with `Skill` matcher is the available approximation. There is no `PostSkillExecution` event. Confirm this targeting works during testing.
- PR #4: should Experiment 11 (creative-regression A/B for Opus 4.7 vs 4.6) be drafted before or after the test fixture lands? Default: AFTER.
- PR #3: ordinary-persona prompting was identified in baseline (2026-03-28) as a research insight but never operationalized. PR #2 introduces it. Should we add to existing `/brainstorm` too? Default: NO — keep PR #2 scoped to `/scout-frontier`; revisit in follow-on if useful.

**Files explored during planning** (already read in source session, will need re-reading in execution sessions):
- `~/.claude/ARCHITECTURE.md` — current state of skills/hooks/rules inventory
- `~/.claude/projects/<your-claude-project>/CLAUDE.md` — delegation table format
- `~/.claude/agent-memory/topics/security.md` — example topic file format
- `~/.claude/hooks/skill-rules.json` — routing regex format (601 lines)
- All ambient rules in `~/.claude/rules/` — DSL/GUARD format and override-policy patterns
- 2026-04-27 frontier research files (`generic-framework-2024plus.md`, `spotting-frameworks-claims-verification.md`, `delta-to-synopsis.md`)
- Existing `~/Documents/knowledge-base/research/claude-code-research-intelligence.md` — append target
- Phase C research report (in source session conversation, NOT yet a file — must be reconstructed from this plan if needed)

---

## Phase A — Knowledge Capture (PR #1)

**Branch**: `docs/research-2026-04-28-creative-discovery`
**Demo**: `/recall "hyperpolation"` returns the new KB topic; `/recall "knowledge asymmetric"` returns the new KB topic; the research report contains a 2026-04-28 dated section with 10 findings + 3 threads.

### Steps

**A1. Snapshot the existing research report**
```bash
cp ~/Documents/knowledge-base/research/claude-code-research-intelligence.md \
   ~/Documents/knowledge-base/research/2026-04-28-research-intelligence-snapshot.md
```
- Depends on: none
- Gotcha: forward slashes only; cp on Git Bash works fine
- Verify: `ls -la ~/Documents/knowledge-base/research/2026-04-28-*` shows the snapshot

**A2. Append Phase C report as new dated section**
- Tool: Edit (find existing end-of-Citations marker, insert before)
- Depends on: A1
- Content: section header `## New Findings (2026-04-28 — Creative Discovery & Knowledge-Asymmetric Collaboration Focus)` with 10 findings, 3 threads, and citation entries. Findings detail captured below in **Appendix A** of this plan.
- Add 3 entries to Experiment Backlog:
  - **Experiment 9**: MINES-style invariant inference for code-graph engine (deferred build)
  - **Experiment 10**: Verbalized Sampling A/B on `/scout-frontier` (fires after PR #2)
  - **Experiment 11**: Creative-regression A/B for Opus 4.7 vs 4.6 (fires after PR #4)
- Gotcha: existing file is ~1200 lines; use Edit not Write to preserve prior content
- Verify: file grew by ~400 lines; `grep -c "## New Findings (2026-04-28" claude-code-research-intelligence.md` returns 1

**A3. Update Architecture Component Index in the report**
- Tool: Edit
- Depends on: A2
- Add row to Architecture Component Index table: `| Creative ideation & discovery | Findings 1, 4, 7, 8, 10 + Threads A, B, C |`
- Verify: index has the new row

**A4. Add 3 entries to Active Research Questions section**
- Tool: Edit
- Depends on: A2
- Questions:
  - "When does Opus 4.7 mode-collapse on creative variation, and do diversity primitives (VS, ordinary personas) restore range?"
  - "What output-level proxies for RADAR's mechanistic recall-vs-reasoning detection are achievable through API alone?"
  - "Does MINES-style invariant inference produce explanations the user can actually audit on a black-box code-graph engine?"
- Verify: 3 new bulleted questions in section

**A5. Write 3 new KB topic files**
- Tool: Write × 3
- Depends on: none (parallelizable with A1-A4 if executing in same session)
- Files:
  - `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md` — interpolation/extrapolation/hyperpolation framing, source attribution (Salvi et al. 2604.13242, Lewis-Mitchell 2402.08955), implications for skill design
  - `~/Documents/knowledge-base/topics/knowledge-asymmetric-collaboration.md` — Hybrid Intelligence quality model (van der Stappen et al. Springer 2026, 7 attributes + 16 measures), three-layer defense, verification-centric design
  - `~/Documents/knowledge-base/topics/opus-4-7-creative-tradeoffs.md` — KINTAL benchmark T4 mode-collapse, Thematic Generalization regression (80.6% → 72.8%), MRCR multi-needle regression, "personality discontinuity" community reports, when to use 4.6 vs 4.7
- Format: existing KB topic format (frontmatter + H2 entries with dates per `garden` skill convention)
- Each: 50-150 lines
- Verify: `ls -la ~/Documents/knowledge-base/topics/` shows 3 new files; first line of each is YAML frontmatter

**A6. Update `MEMORY.md` index with one-line pointers to the new KB topics**
- Tool: Edit
- Depends on: A5
- Add 3 lines under "## Reference" section:
  - `- [LLM Creativity Ceiling](references/llm-creativity-ceiling.md) — interpolation/extrapolation/hyperpolation distinction; LLMs cannot do hyperpolation`
  - `- [Knowledge-Asymmetric Collaboration](references/knowledge-asymmetric-collaboration.md) — Hybrid Intelligence quality model + three-layer defense pattern`
  - `- [Opus 4.7 Creative Tradeoffs](references/opus-4-7-creative-tradeoffs.md) — KINTAL T4 mode-collapse, Thematic Generalization regression, when to use 4.6 vs 4.7`
- Gotcha: MEMORY.md is capped at 200 lines per claude-md-quality.md; check current line count first (`wc -l MEMORY.md`)
- Gotcha 2: pointer paths reference `knowledge-base/topics/` not `references/` — adjust per actual MEMORY.md format
- Verify: 3 new index lines; total file ≤200 lines

**A7. Commit, push, PR, auto-merge**
- Per `git-hygiene.md` flow:
  ```bash
  git checkout -b docs/research-2026-04-28-creative-discovery
  git add <files from A1-A6>
  git commit -m "docs(research): append 2026-04-28 creative-discovery findings"
  git push -u origin docs/research-2026-04-28-creative-discovery
  gh pr create --title "docs(research): 2026-04-28 creative-discovery findings" --body "<concise summary>"
  gh pr merge --auto --squash --delete-branch
  ```
- Depends on: A1-A6
- Verify: `gh pr view <num>` shows merged; `git checkout main && git fetch origin main && git rebase origin/main`

**Phase A dependency summary**: `[A1 | A5] → [A2 → A3 → A4] → A6 → A7`

---

## Phase B — `/scout-frontier` Skill Enhancement (PR #2)

**Branch**: `feat/scout-frontier-verbalized-sampling`
**Demo**: User runs `/scout-frontier` on a real problem; output shows VS-style probability assignments, ordinary personas, abstraction-then-mapping. Output candidates measurably more diverse than pre-merge baseline.

### Steps

**B1. Read current `~/.claude/skills/scout-frontier/SKILL.md`**
- Tool: Read (full file)
- Depends on: none
- Per `check-before-change.md` STEP_1: never edit without reading current state first
- Verify: full skill body in context

**B2. Read current `~/.claude/skills/scout-frontier/manifest.yaml`**
- Tool: Read
- Depends on: none
- Verify: manifest structure understood (triggers, requires_tools, references)

**B3. Read existing `references/` directory contents**
- Tool: Glob `~/.claude/skills/scout-frontier/references/*`
- Depends on: B1
- Verify: existing reference files are known so the new file doesn't conflict

**B4. Write new reference file with VS template**
- Tool: Write
- Depends on: B1, B2, B3
- File: `~/.claude/skills/scout-frontier/references/verbalized-sampling-template.md`
- Content sections (lead with "Critical Gotchas" per skill-standards.md):
  - **Critical Gotchas**: tail-sample factuality risk; 3× cost; prompt sensitivity; probability-gaming failure mode (model assigns 0.01 to everything)
  - **VS prompt template**: "Generate N candidate approaches with probabilities; assign probabilities between 0.02 and 0.09; require different style, structure, or viewpoint"
  - **Ordinary-persona instruction**: list of acceptable personas ("an analyst," "a maintenance engineer," "a careful reviewer"); explicit prohibition on creative-celebrity personas (Jobs/Eno/Bezos)
  - **Factuality filter spec**: post-sampling step that grounds each candidate against literature retrieval (Tavily + Exa) and rejects unverifiable claims
  - **Abstraction-then-mapping pattern (YARN)**: decompose target system into structural units → abstract each → map onto distant domain → translate back; explicit prohibition on end-to-end "make a bio analogy"
  - **Counterfactual-test pattern (Lewis-Mitchell)**: for each surviving candidate, generate the inverted counterfactual; reject if the analogy collapses
- Gotcha: use `Write` tool but ensure the file uses LF line endings (Write should be fine on Windows; verify with `file` or `od -c` if uncertain)
- Verify: new reference file exists, ~80-120 lines, lead section is "Critical Gotchas"

**B5. Edit SKILL.md to add 5 new steps in workflow body**
- Tool: Edit (multiple targeted edits, NOT Write/full-replace)
- Depends on: B1, B4
- Insert points (per existing /scout-frontier workflow structure):
  - VS step at candidate generation phase
  - Ordinary-persona instruction in same step
  - Factuality filter before synthesis phase
  - Abstraction-then-mapping in cross-domain phase
  - Counterfactual-test in verification phase
- Each step references `references/verbalized-sampling-template.md` via Tier 2 (one-line pointer per skill-standards.md Rule Integration Tiers)
- Gotcha: SKILL.md must stay ≤100 lines per skill-standards.md split trigger; if exceeded, extract MORE to references/
- Verify: `wc -l SKILL.md` ≤100; new steps appear in body; references/ pointer present

**B6. Update SKILL.md frontmatter `description` field**
- Tool: Edit
- Depends on: B5
- Front-load triggers in first 250 chars: "creative discovery for systems where the user is no longer the domain expert," "combinational variation at scale," "cross-domain analogy generation," "oblique reframing"
- Add Do-NOT-use-for: "hyperpolation / transcendent novelty (LLMs cannot do this — outputs are drafts subject to user verification)"
- Total description ≤1024 chars
- Verify: `grep -A1 "description:" scout-frontier/SKILL.md` shows updated content; first 250 chars contain trigger phrases

**B7. Update Examples section in SKILL.md**
- Tool: Edit
- Depends on: B5
- Add canonical positive example: code-graph engine improvement (concrete prompt + expected output shape)
- Add canonical negative example: NOT for "frontier-discovery oracle" / "transcendent novelty"
- Verify: 2 new examples in Examples section

**B8. Update manifest.yaml**
- Tool: Edit (or Write if structure changes are large)
- Depends on: B2, B4
- Add new reference file to `references` field
- Update `triggers` to include new trigger phrases (oblique, cross-domain analogy, frontier technique, novel approach for system I don't understand)
- Verify: manifest references the new file; triggers include new phrases

**B9. Run `compile.py` to validate manifests**
- Bash: `python ~/.claude/manifests/compile.py`
- Depends on: B8
- Gotcha: compile validates `requires_tools` against actual MCP references; if VS template references a new MCP tool not in original manifest, must add to manifest
- Verify: zero validation errors; `git diff ~/.claude/manifests/graph.json` shows expected updates

**B10. Smoke-test the enhanced skill**
- Bash: invoke skill with a test prompt, e.g.:
  ```bash
  echo "Find frontier improvements for retrieval-augmented generation in a polyglot monorepo" | claude --skill scout-frontier
  ```
  (or via interactive `/scout-frontier` invocation)
- Depends on: B5-B9
- Verify: output shows VS-style probability assignments, uses ordinary persona (not Jobs/Eno), shows abstraction-then-mapping discipline, includes counterfactual test
- If smoke test fails to show new behavior: re-read SKILL.md to verify edits landed in workflow section, not just references/

**B11. Commit, push, PR, auto-merge**
- Branch: `feat/scout-frontier-verbalized-sampling`
- Commit message: `feat(scout-frontier): add Verbalized Sampling + ordinary personas + abstraction-then-mapping`
- Depends on: B1-B10
- Verify: PR merged; local main rebased

**Phase B dependency summary**: `[B1 | B2 | B3] → B4 → B5 → [B6 | B7 | B8] → B9 → B10 → B11`

---

## Phase C — Trust Calibration Architecture (PR #3)

**Branch**: `feat/output-grounding-rule-and-hook`
**Demo**: A creative-skill output without confidence/provenance/counterfactual triggers a hook warning in the session log. The new ambient rule loads on session start and is referenced by `/scout-frontier`, `/brainstorm`, `/deep-dive`, `/refine`.

### Steps

**C1. Read existing rules to identify naming/format conventions**
- Tool: Read × 2 (e.g., `~/.claude/rules/validate-to-improve.md`, `~/.claude/rules/verify-effectiveness.md`)
- Depends on: none
- Per `check-before-change.md`: never edit without reading existing state first
- Verify: confirmed DSL + GUARD format conventions for new rule

**C2. Read existing hook for format reference**
- Tool: Read `~/.claude/hooks/result-injection-guard.py`
- Depends on: none
- Verify: hook structure (input parsing, decision logic, exit codes, environment vars) understood

**C3. Read existing hook manifest for format reference**
- Tool: Read `~/.claude/hooks/manifests/result-injection-guard.yaml`
- Depends on: none
- Verify: manifest fields (event, matcher, action_type, enforcement_targets) understood

**C4. Write new ambient rule**
- Tool: Write
- Depends on: C1
- File: `~/.claude/rules/output-grounding.md`
- Content (per `rule-authoring.md` DSL + GUARD format):
  - `@rule output_grounding`
  - `@scope every output from creative-discovery skills (/scout-frontier, /brainstorm, /deep-dive, /refine)`
  - INVARIANT block: every recommendation labeled with confidence band (HIGH/MEDIUM/LOW); every claim traces to source URL or `[INFERRED]`; counterfactual offered for at least one recommendation per output
  - PROCEDURE block: structured output format requirements
  - GUARD blocks for the 5 universal override patterns:
    - "trust me, the output is fine"
    - "user already knows the context"
    - "small change, no need for grounding"
    - "creative tasks shouldn't need verification"
    - "the model already self-verified"
  - FAILURE MODES section: documented incidents (AI Scientist v2 57% false-data rate, KINTAL T4 mode-collapse, hyperpolation ceiling)
- Total: ~120-180 lines
- Verify: rule loads; GUARD blocks present; cites WHY for every restriction

**C5. Write rule manifest**
- Tool: Write
- Depends on: C4
- File: `~/.claude/rules/manifests/output-grounding.yaml`
- Fields:
  - `enforcement_coverage: partial` (becomes `full` after C7 hook lands)
  - `applies_to: [/scout-frontier, /brainstorm, /deep-dive, /refine]`
  - `enforcement_hooks: [creative-output-grounding-check]`
- Verify: manifest validates against schema

**C6. Write the new PostToolUse hook**
- Tool: Write
- Depends on: C2, C4
- File: `~/.claude/hooks/creative-output-grounding-check.py`
- Behavior: scan creative-skill outputs for confidence + provenance + counterfactual signals; if ≥1 missing, emit warning (NOT block, NOT exit 2)
- Modeled on `result-injection-guard.py`
- Constraints (per `platform-constraints.md`):
  - `# -*- coding: utf-8 -*-` header
  - `sys.stdout.reconfigure(encoding='utf-8')` after imports
  - All `open()` calls use `encoding='utf-8'`
  - Handle missing fields gracefully (no `KeyError` crashes)
  - Exit 0 on warning (warning ≠ block); only exit 2 on configuration error
- Detection logic:
  - Scan output for confidence indicators (HIGH/MEDIUM/LOW labels, % values, "uncertain"/"likely"/"confident")
  - Scan for provenance (URL patterns, `[INFERRED]` tags, citation markers)
  - Scan for counterfactual ("if X were", "what if", "alternative", "counterfactual")
- Output: structured warning to stderr if signals missing
- Verify: ~80-120 lines; runs without import errors; `python -c "import creative-output-grounding-check"` succeeds (or equivalent module test)

**C7. Write hook manifest**
- Tool: Write
- Depends on: C3, C6
- File: `~/.claude/hooks/manifests/creative-output-grounding-check.yaml`
- Fields:
  - `event: PostToolUse`
  - `matcher: Skill`  *(or appropriate regex for the 4 target skills)*
  - `action_type: command`
  - `enforcement_targets: [output-grounding]`
- Verify: manifest validates

**C8. Write hook test file**
- Tool: Write
- Depends on: C6
- File: `~/.claude/hooks/test-hooks/test-creative-output-grounding-check.py`
- Test cases:
  - Positive: all 3 layers present → exit 0, no warning
  - Negative 1: missing confidence → warning emitted
  - Negative 2: missing provenance → warning emitted
  - Negative 3: missing counterfactual → warning emitted
  - Edge: malformed JSON input → exit 0 with "could not parse" warning
  - Edge: non-Skill tool call → exit 0 (matcher should not have fired)
- Verify: `python ~/.claude/hooks/test-hooks/test-creative-output-grounding-check.py` passes all cases

**C9. Register hook in `settings.json`**
- Tool: Edit
- Depends on: C6, C7
- Add hook entry to `PostToolUse` array in `settings.json`
- Use `if:` field per platform-constraints / hook design pattern to scope spawning to Skill calls only
- Gotcha: `settings.json` is LIVE runtime state; broken syntax locks all tools (per `platform-constraints.md`). BEFORE saving, validate JSON syntax via separate test:
  ```bash
  python -c "import json; json.load(open('/c/Users/you/.claude/settings.json'))"
  ```
- Recovery if broken: `git checkout main -- settings.json` from terminal (NOT Claude Code, since tools would be locked)
- Verify: hook registered; JSON validates; new session loads without "settings.json invalid" error

**C10. Test hook against historical session transcripts**
- Bash: replay hook against 1-2 weeks of `~/.claude/projects/<your-claude-project>/*.jsonl`
  ```bash
  python ~/.claude/hooks/test-hooks/replay-creative-output-grounding-check.py \
    --transcripts ~/.claude/projects/<your-claude-project>/ \
    --since "$(date -d '14 days ago' +%Y-%m-%d)" \
    --report
  ```
  (Pattern modeled on `verify-effectiveness.md` hook retroactive testing procedure; the replay harness may need to be written as part of this step.)
- Depends on: C9
- Verify: warn rate <10% historically (per hook retroactive testing rule)
- If >10%: tune detection criteria (loosen confidence-indicator regex, broaden counterfactual triggers); re-test before merge

**C11. Update 4 skill files to cite the new rule (Tier 2 reference)**
- Tool: Edit × 4
- Depends on: C4
- Files:
  - `~/.claude/skills/scout-frontier/SKILL.md`
  - `~/.claude/skills/brainstorm/SKILL.md`
  - `~/.claude/skills/deep-dive/SKILL.md`
  - `~/.claude/skills/refine/SKILL.md`
- Add one-line: `Follow ~/.claude/rules/output-grounding.md for output grounding requirements.`
- Place under existing rule references or in skill body near output construction
- Verify: 4 skills cite the rule; none exceed SKILL.md ≤100 line cap

**C12. Run `compile.py` to validate manifest graph**
- Bash: `python ~/.claude/manifests/compile.py`
- Depends on: C5, C7, C11
- Verify zero dangling references; `graph.json` updated; new rule + new hook appear in graph

**C13. Commit, push, PR, auto-merge**
- Branch: `feat/output-grounding-rule-and-hook`
- Commit message: `feat(rules,hooks): add output-grounding rule + creative-output-grounding-check hook`
- Depends on: C1-C12
- Verify: PR merged; hook fires on next session start

**Phase C dependency summary**: `[C1 | C2 | C3] → C4 → [C5 | C6 → [C7 | C8]] → C9 → C10 → C11 → C12 → C13`

---

## Phase D — Validation Infrastructure (PR #4)

**Branch**: `feat/validate-changes-creative-regression-protocol`
**Demo**: User invokes `/validate-changes` with creative-regression mode; output shows pass/fail per task with diff scoring against the canonical fixture.

### Steps

**D1. Read current `~/.claude/skills/validate-changes/SKILL.md`**
- Tool: Read
- Depends on: none

**D2. Read current `~/.claude/skills/validate-changes/references/`**
- Tool: Glob
- Depends on: none
- Verify: existing reference files known

**D3. Write canonical creative test prompt set**
- Tool: Write
- Depends on: D1, D2
- File: `~/.claude/skills/validate-changes/references/creative-test-prompts.md`
- 5-7 prompts (modeled on KINTAL benchmark structure, but compressed):
  1. **Cross-domain analogy** — "Map this code-graph optimization problem onto a non-software domain. Show structural alignment."
  2. **Brief-to-pitch** — "Given this requirement: <X>, identify the buried strongest idea and pitch it over the obvious alternatives."
  3. **Variation generation** (KINTAL T4 style — the failure mode) — "Generate 5 distinctly different approaches to <Y>. Distinct means different underlying psychology, not surface words."
  4. **Constraint extraction** — "From this code sample, infer 3 invariants the system relies on. Audit-able by a non-domain-expert."
  5. **Oblique reframing** — "Restate this problem so a biologist would recognize it. Keep the structural problem intact."
  6. **Counterfactual probe** — "Given this recommendation: <Z>, generate the inverted counterfactual and assess whether the recommendation still holds."
  7. **Persona diversity** — "Generate 3 perspectives on <W> from ordinary professionals (not creative celebrities). Each must offer a distinct lens."
- Each prompt has rubric: distinctness (1-5), grounding (1-5), pass threshold (≥3/5)
- Each has expected behavior signature (what good output looks like)
- Verify: ~150-200 line fixture; rubric scoring is mechanical, not vibes-based

**D4. Add creative-regression test protocol step to SKILL.md**
- Tool: Edit
- Depends on: D3
- New step: "When validating model migration affecting creative-output skills (`/scout-frontier`, `/brainstorm`, `/deep-dive`, `/refine`), run the creative-regression protocol against the test set in `references/creative-test-prompts.md`"
- Pass threshold: ≥80% of tasks score within 1 rubric-point of baseline
- Failure handling: do NOT block migration; emit structured report; user decides
- Gotcha: keep SKILL.md ≤100 lines
- Verify: skill body updated; under line cap

**D5. Add hyperpolation-ceiling explainer to `/scout-frontier` and `/brainstorm`**
- Tool: Edit × 2
- Depends on: D3 (for consistency of language)
- One-line addition near skill output: "Note: LLMs perform interpolation/extrapolation, not hyperpolation; outputs are drafts subject to user verification (see `~/Documents/knowledge-base/topics/llm-creativity-ceiling.md`)"
- Verify: 2 skills updated; line cap preserved

**D6. Update `/validate-changes` manifest**
- Tool: Edit
- Depends on: D3
- Add new reference file to `references` field
- Verify: manifest references creative-test-prompts.md

**D7. Run `compile.py` validation**
- Bash
- Depends on: D6
- Verify: clean compile

**D8. Smoke-test by running `/validate-changes` with a creative-regression invocation**
- Test: trigger creative-regression mode against the fixture (with mock baseline data so the test is deterministic)
- Depends on: D4-D7
- Verify: protocol fires correctly; fixture loads; rubric scoring produces structured comparison

**D9. Commit, push, PR, auto-merge**
- Branch: `feat/validate-changes-creative-regression-protocol`
- Commit message: `feat(validate-changes): add creative-regression protocol + canonical test fixture`
- Depends on: D1-D8

**Phase D dependency summary**: `[D1 | D2] → D3 → [D4 | D5 | D6] → D7 → D8 → D9`

**Note**: This PR depends on PR #2 having merged, because D5 references the trigger language introduced in PR #2 and the test fixture exercises VS-aware behavior.

---

## Phase E — Architecture Documentation + Routing (PR #5)

**Branch**: `docs/architecture-creative-discovery-section`
**Demo**: A user typing "I want to find frontier improvements to my code-graph engine" sees `skill-routing-hint.py` suggest `/scout-frontier`. ARCHITECTURE.md describes the new section. CLAUDE.md delegation table includes the new trigger.

### Steps

**E1. Update `~/.claude/ARCHITECTURE.md`**
- Tool: Edit
- Depends on: PRs #2, #3 merged (this section describes their shipped state)
- Add new section "Creative Discovery and Knowledge-Asymmetric Collaboration" after the "Self-Improvement Loop" section
- Document:
  - Three-layer defense (confidence + provenance + counterfactual)
  - Hyperpolation ceiling and what it means for skill design
  - `/scout-frontier` enhancement (Verbalized Sampling, ordinary personas, abstraction-then-mapping, counterfactual-test)
  - `output-grounding.md` ambient rule + `creative-output-grounding-check.py` hook
  - Reference to KB topics from PR #1
- Length: ~30-50 lines
- Verify: section coherent; references real files; doesn't duplicate existing content

**E2. Update `~/.claude/projects/<your-claude-project>/CLAUDE.md` Delegation Rules table**
- Tool: Edit
- Depends on: PR #2 merged (skill exists with new triggers)
- Add row to the Skills table:
  ```
  | creative discovery, oblique reframing, cross-domain analogy, frontier technique, novel approach for system I don't understand | `/scout-frontier` | Combinational variation at scale with verification |
  ```
- Gotcha: CLAUDE.md is capped at 120 lines per `claude-md-quality.md`; check with `wc -l CLAUDE.md` first; if at or near cap, condense an existing row to make room
- Verify: 1 new table row; total file ≤120 lines

**E3. Update `~/.claude/hooks/skill-rules.json`**
- Tool: Edit
- Depends on: E2
- Update `/scout-frontier` regex to add new trigger phrases:
  - "oblique"
  - "cross-domain analogy"
  - "frontier technique"
  - "novel approach"
  - "system I don't understand"
- Gotcha: `skill-rules.json` is JSON; test syntax before saving:
  ```bash
  python -c "import json; json.load(open('/c/Users/you/.claude/hooks/skill-rules.json'))"
  ```
- Verify: regex pattern accepts the new triggers; JSON validates

**E4. Test routing on canonical phrases**
- Bash:
  ```bash
  python ~/.claude/hooks/test-routing.py "find frontier improvements for the code-graph engine"
  python ~/.claude/hooks/test-routing.py "I want an oblique reframing of this problem"
  python ~/.claude/hooks/test-routing.py "novel approach for a system I no longer understand"
  ```
- Depends on: E3
- Verify: each routes to `/scout-frontier`

**E5. Commit, push, PR, auto-merge**
- Branch: `docs/architecture-creative-discovery-section`
- Commit message: `docs(architecture): add creative-discovery section + update routing for /scout-frontier`
- Depends on: E1-E4

**Phase E dependency summary**: `[E1 | E2] → E3 → E4 → E5`

---

## Phase F — Deferred Artifacts (no PR)

**F1. Experiment 9 design (MINES invariant inference)** — captured in PR #1 / Step A2 (Experiment Backlog append)

**F2. Decision artifacts (Track 7) for user disposition** — present as text in chat session when relevant:
- **7.1**: Opus 4.7 creative-skill migration → blocked on PR #4 + actual A/B test run; do NOT migrate creative skills until A/B test passes ≥80% threshold
- **7.2**: RADAR-paradigm output proxies → defer to monitor; revisit if RADAR or comparable mechanistic-interpretability tooling becomes API-accessible
- **7.3**: `/oblique-discovery` as future skill → defer until friction observed post-PR-#2; criteria for build = 3+ documented sessions where `/scout-frontier` is insufficient
- **7.4**: Hybrid Intelligence design checklist → captured as KB topic in PR #1 (knowledge-asymmetric-collaboration.md); revisit codification as ambient rule if checklist proves repeatedly useful

---

## Program-Level Dependency Summary

```
PR #1 (Knowledge capture) ──────────────────┐
                                              │
PR #2 (/scout-frontier) ─────┬─→ PR #4 ───┐  │
                              │             │  │
PR #3 (Trust calibration) ───┴───────────┐ │  │
                                          │ │  │
                                          ↓ ↓  ↓
                                          PR #5 (Documentation + routing)
```

**Recommended execution sequence**:
1. **PR #1** (cheapest, unblocks nothing structurally) — ~1 session
2. **PR #2** (highest leverage; behavior change) — ~1 session
3. **PR #3** (parallel-eligible with #2 but FORBIDDEN per parallel-worktree GUARD; serialize) — ~1 session
4. **PR #4** (after #2 merges) — ~1 session
5. **PR #5** (after #2 and #3 both merge) — ~1 session
6. **F2 decisions** — present in chat as needed; no implementation

## Verification (Per PR)

| PR | Verification command | Pass criteria |
|---|---|---|
| #1 | `gh pr checks <num>` + `git log --oneline -5` + verify new files exist | PR merged; 4 new files; research report grew by ~400 lines |
| #2 | Smoke test `/scout-frontier` + `python ~/.claude/manifests/compile.py` | Output shows VS structure; manifest validates; SKILL.md ≤100 lines |
| #3 | `python ~/.claude/hooks/test-hooks/test-creative-output-grounding-check.py`; replay against transcripts | All test cases pass; warn rate <10% historically |
| #4 | Run protocol with mock baseline | Test fixture loads; rubric scoring works; structured report produced |
| #5 | `python ~/.claude/hooks/test-routing.py "<canonical phrase>"` × 3 | All 3 phrases route to `/scout-frontier` |

## Error Map

| Error | Trigger | Handler | User sees |
|---|---|---|---|
| `compile.py` validation fails | Manifest references missing tool/topic | Fix YAML schema reference; re-run | "manifest validation failed: <reason>" |
| Hook warn rate >10% historically | Detection pattern too aggressive | Tune detection criteria; re-test | "X% of historical commands would have warned" |
| `settings.json` syntax error | Missed comma after hook entry | Test JSON syntax BEFORE saving; if broken, `git checkout main -- settings.json` from terminal | All tools locked; recovery via terminal-only |
| Pre-commit hook blocks commit | ruff or py_compile failure on new files | Fix lint/syntax, re-stage; do NOT use `--no-verify` | "ruff: <issue>" or "py_compile: <issue>" |
| CI fails (gitleaks, codeql) | False positive on test fixture | Add allowlist or refactor; do NOT bypass | "PR check Analyze failed" |
| Edit fails "File has been modified" | Concurrent session edited same file | Re-read, re-edit (per `platform-constraints.md` edit recovery) | "File has been modified since read" |
| Skill description >1024 chars | Adding too many trigger phrases | Trim or move detail to `references/` | "description too long" |
| SKILL.md exceeds 100 lines | New steps inflate body | Extract more content to `references/` per skill-standards.md split trigger | warning at session start |
| Routing test fails | Regex doesn't match expected phrase | Adjust pattern; test against multiple phrasings | "no skill matched test phrase" |
| `/scout-frontier` smoke test produces unchanged output | Edits didn't land in workflow section, only `references/` | Re-read SKILL.md; verify new steps are in workflow section | Output looks like pre-merge baseline |
| Hook PostToolUse + Skill matcher doesn't fire | Skill outputs route through different event | Investigate event surface; consider UserPromptSubmit alternative | Hook silently never fires |

## Dependency Failure Analysis

| Dependency | If down | If timeout | If bad data |
|---|---|---|---|
| `~/.claude/manifests/compile.py` | Cannot validate manifest changes; option to ship metadata-only PRs without it (PRs #1, #5) but BLOCK behavior PRs (#2, #3, #4) | N/A (local script) | Read error output; fix YAML; do NOT bypass |
| Pre-commit hooks (ruff, py_compile, gitleaks) | Cannot ship until restored; investigate failure root cause | Investigate hung process | Read hook output; fix |
| GitHub Actions CI (codeql) | PR queued; will retry on push | Re-push to retrigger | Read CI log; fix |
| Git remote (push/PR) | Local commits preserved; retry push when restored | Same | Same |
| `~/.claude/manifests/graph.json` | Some hooks won't load enrichment context; non-blocking for these PRs | N/A | Re-run `compile.py` |
| `mcp__memory-search__memory_search` | Not used in execution; only Phase 2c (planning) | N/A | N/A |

## Out of Scope (Explicit)

- Building `/oblique-discovery` as a new top-level skill (deferred per F2.7.3)
- Migrating creative skills to Opus 4.7 (deferred until PR #4 A/B test passes per F2.7.1)
- Implementing MINES invariant inference (Experiment 9, deferred to friction observation)
- Building RADAR-paradigm output proxies (defer-to-monitor per F2.7.2)
- Touching the code-graph engine source code itself
- Running parallel subagent worktree-isolated dispatches (forbidden per #48927/#48811)
- Modifying `/triage`, a separate skill (not included in this export), `/superplan`, `/capture`, `/recall`, `/garden` (out of focus area scope)

## Plan Quality Checks (passed)

- ✅ Every step references a specific tool, file path, or command
- ✅ Known gotchas surfaced (CRLF, settings.json sync, MEMORY.md cap, SKILL.md cap, parallel-worktree GUARD)
- ✅ Independent steps marked via `[A | B | C]` notation within each phase
- ✅ Verification step in each phase
- ✅ Phases used because total step count is 11 + 11 + 13 + 9 + 5 = 49 steps
- ✅ Demo statement per phase
- ✅ Error map and dependency failure analysis included (L-sized program)
- ✅ Primary/supplementary domains documented
- ✅ No subagent dispatch (rejected per parallel-worktree GUARD; serialize all writes to claude-config)
- ✅ Each PR isolates metadata vs behavior changes per `validate-to-improve.md`
- ✅ Session Context section present for fresh-session continuity

## Citation Sources for Plan-Level Decisions

The 10 findings + 3 threads referenced in Phase A2 are drawn from:

1. KINTAL Creative Benchmark, April 16 2026 — https://www.kintal.co/insights/we-put-opus-47-through-our-creative-benchmark-is-it-worth-experimenting-with
2. AIWorkflows.tools Opus 4.7 Review, April 17 2026 — https://aiworkflows.tools/blog/claude-opus-4-7-review-benchmarks-features-2026
3. GitHub anthropics/claude-code Issue #51440, April 21 2026 — https://github.com/anthropics/claude-code/issues/51440
4. Vera Calloway operator field report, April 20 2026 — https://www.veracalloway.com/blog/ai-autopsy/claude-opus-4-7-regression-operator-field-report/
5. Claude Directory field report, April 16 2026 — https://www.claudedirectory.org/blog/claude-opus-4-7-deep-reasoning
6. Kattamuri et al. "RADAR" arXiv:2510.08931 (Oct 2025)
7. van der Stappen et al. "Hybrid Intelligence Quality Model" Springer, AAMAS 40(10) Feb 2026 — https://link.springer.com/article/10.1007/s10458-025-09730-8
8. Salvi et al. "On the Creativity of AI Agents" arXiv:2604.13242 (April 2026)
9. byteiota "AI Scientist v2 Passes Peer Review—But 57% Is False Data" March 2026 — https://byteiota.com/ai-scientist-v2-passes-peer-review-but-57-is-false-data/
10. "Why LLMs Aren't Scientists Yet" arXiv:2601.03315 (2026)
11. Zhang et al. "MINES: Explainable Anomaly Detection through Web API Invariant Inference" arXiv:2512.06906 (Dec 2025)
12. Zhang et al. "Verbalized Sampling: How to Mitigate Mode Collapse and Unlock LLM Diversity" arXiv:2510.01171 (Oct 2025, ICLR 2026)
13. Anthropic "Introducing Claude Opus 4.7" April 16 2026 — https://www.anthropic.com/news/claude-opus-4-7

Plus the 2026-04-27 frontier reports already in the architecture's `~/Documents/knowledge-base/research/`.

---

## Appendix A — Phase C Report Findings (for Step A2 content)

For Step A2 (append to research report), the new dated section needs the following content. This is the substance to write; format it consistent with existing sections in `claude-code-research-intelligence.md`.

### Section header

```markdown
## New Findings (2026-04-28 — Creative Discovery & Knowledge-Asymmetric Collaboration Focus)
```

### Findings to include (full content captured in source-session Phase C report)

1. **[HIGH] Opus 4.7 Creative Capability Has Documented Regressions** — Thematic Generalization 80.6% → 72.8%; KINTAL T4 mode-collapse; "personality discontinuity"; confidence miscalibration. Sources: KINTAL, AIWorkflows, GitHub #51440, Calloway, Claude Directory.

2. **[HIGH] RADAR: Mechanistic Detection of Recall-vs-Reasoning** — 93% accuracy distinguishing recall from reasoning via 37 mechanistic features. Cannot directly apply to closed APIs but inspires output-level proxies. Source: Kattamuri et al. arXiv:2510.08931.

3. **[HIGH] "Hybrid Intelligence" Quality Model for Knowledge-Asymmetric Collaboration** — 7 attributes + 16 measures from 50 HI researchers. Direct fit for the user's "I no longer understand the system" scenario. Source: van der Stappen et al. Springer 2026.

4. **[HIGH] LLMs Cannot Do Hyperpolation** — Interpolation/extrapolation/hyperpolation distinction; LLMs do the first two, not the third. Outputs are combinational creativity, not transcendent novelty. Source: Salvi et al. arXiv:2604.13242.

5. **[HIGH] AI Scientist v2 Independent Eval: 57% False-Data Rate** — Confirms the verification gap: non-experts cannot detect this class of failure. Sources: byteiota, Pebblous, "Why LLMs Aren't Scientists Yet" arXiv:2601.03315.

6. **[HIGH] MINES: Explainable Anomaly Detection via API Invariant Inference** — For "system grew beyond comprehension" scenarios. Adapt the paradigm for code-graph engine. Source: Zhang et al. arXiv:2512.06906.

7. **[MEDIUM] Verbalized Sampling Production Limitations** — 1.6-2.1× diversity gain confirmed but with 3× compute cost, prompt sensitivity, factuality risk in tail samples. Sources: Zhang et al. arXiv:2510.01171 + 4 practitioner guides.

8. **[MEDIUM] Opus 4.7 Self-Verification Behavior** — New behavior: "devises ways to verify its own outputs before reporting back." Adds Verify phase between Execute and Report. Sources: Anthropic announcement; Vercel, Hex partner testimonials.

9. **[MEDIUM] Opus 4.7 Adaptive Thinking Self-Deployment** — Self-deploys extended reasoning on hard tasks in default mode without prompting. Source: KINTAL benchmark observation.

10. **[MEDIUM] Three-Layer Defense Model** — Calibrated uncertainty + provenance trails + counterfactual explanations; explanations alone don't reliably improve trust calibration. Source: Tavily research synthesis (47 sources).

### Threads to include

- **Thread A**: "Opus 4.7 Trades Creative Range for Engineering Reliability" — focused upgrade for coding/agentic, NOT broad capability sweep. Coding gains come at cost of creative regressions and long-context multi-needle.
- **Thread B**: "Knowledge-Asymmetric Collaboration Has a Canonical Architecture" — HI quality model + three-layer defense + verification-centric design + RADAR-style proxies. Convergent across 2025-2026 work.
- **Thread C**: "LLM Creativity Has a Hyperpolation Ceiling — Plan Around It" — independent convergence across academic + practitioner sources. Architect around the ceiling, don't wait for it to lift.

### Experiments to add to backlog

- **Experiment 9**: MINES-style invariant inference for code-graph engine. Hypothesis, control, treatment, success criteria, sample size, rollback per existing experiment template. Status: deferred until friction observation.
- **Experiment 10**: Verbalized Sampling A/B on `/scout-frontier`. Fires after PR #2 merges. Measure diversity delta on representative prompts.
- **Experiment 11**: Creative-regression A/B for Opus 4.7 vs 4.6 using the canonical fixture from PR #4. Pass threshold ≥80% within-1-rubric-point. Gates any blanket migration.

---

## End of Plan

To execute: pick a PR, start fresh session, follow Phase 4b critical review gate, execute steps. Don't skip the verification step at the end of each phase. Don't dispatch parallel subagents on this repo.
