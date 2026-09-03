---

name: superplan
description: "Plan any non-trivial task — load operational knowledge and tools, produce a context-aware plan."
when_to_use: Use when planning any non-trivial task that involves MCP tools, agents, scripts, or cross-domain work. Loads accumulated operational knowledge, identifies available tools, estimates effort with ambiguity resolution, and produces context-aware implementation plans saved to ~/Documents/knowledge-base/plans/ (persistence configurable). Auto-detects available substrate (topic files, KB, MCP servers, manifest graph) and silently skips phases whose substrate is absent — degrades to a /plan-equivalent draft when nothing is installed. Also use when executing a plan from a prior session (triggers critical review gate). Pass `--lite` for XS-effort short-form, `--persist=never|auto|always` to control plan-file persistence. Works for ANY domain. Do NOT use for simple one-shot queries or brainstorming (use brainstorm instead).
argument-hint: "[task description] [--lite] [--persist=auto|never|always]"
effort: max
metadata:
  author: example-security-engineering
  version: "1.1"
allowed-tools: AskUserQuestion Bash Edit Grep Read mcp__codebase-memory-mcp__* mcp__memory-search__memory_search
---

## superplan

# Superplan Constitution — Context-Aware Planning

Produce implementation plans informed by everything this system knows: MCP tool capabilities, agent memory, topic files, knowledge base decisions, architecture constraints, accumulated gotchas.

NOT brainstorming. This is: **assess what we have → load what we know → plan how to do it → route to the right execution path.**

Use for any task touching MCP tools, agents, or accumulated operational knowledge. Domain-agnostic.

## User overrides

When the user asks to skip a phase, shorten a check, or accept a fixture, do it.
Record the skipped step in the plan header as an accepted risk and continue; a
plan that stalls to argue with its user is worse than one with a documented gap.
Prefer plans that resolve within the session: if a step genuinely needs elapsed
time or an external approval, write it down as a terminal artifact rather than an
in-plan gate, and hand the plan back.

---

## Phase -1: Substrate Detection (always runs first)

superplan was designed for a substrate (~/.claude/agent-memory/, ~/Documents/knowledge-base/, manifest graph, MCP servers). When run outside that substrate it must **degrade gracefully** to `/plan`-equivalent behavior, not error or produce empty phase outputs.

### Detection probes

Run these probes silently as the first step. Each one toggles whether a later phase fires.

| Probe (bash) | Toggles |
|--------------|---------|
| `test -d ~/.claude/agent-memory/topics` | Phase 2 step 1 (topic files) |
| `test -d ~/.claude/projects/$CLAUDE_PROJECT_ID/memory` | Phase 2 step 2 (deep reference) |
| `test -f ~/.claude/rules/mcp-tool-names.md` | Phase 2 step 3 (MCP inventory) |
| memory-search MCP listed in available tools | Phase 2b + 2c + 2d (semantic / KB / prior-arc) |
| `test -d ~/Documents/knowledge-base/plans` | Phase 2d (prior-arc glob) + Step 5a (persist) |
| `test -d ~/Documents/knowledge-base/plan-patterns` | Phase 2e (plan-pattern scaffolding) |
| `test -f ~/.claude/manifests/query_engine.py` | Phase 3.0 (manifest graph) |
| `test -d ~/Documents/knowledge-base` | Step 5a default persist path |

### Substrate matrix

Emit one line summarizing detection, e.g.:

```
PHASE -1 — Substrate: topics:Y deep-ref:Y mcp-names:Y memory-search:Y kb:Y patterns:Y manifests:Y
                 (full superplan; no degrade)
```

or

```
PHASE -1 — Substrate: topics:N deep-ref:N mcp-names:N memory-search:N kb:N patterns:N manifests:N
                 (degraded mode: /plan-equivalent; phases 0/2/2b/2c/2d/2e/3.0/5a skipped)
```

### Lite-mode trigger

If the user passed `--lite` as an argument, **or** Phase 3b sizes the task as XS (≤1 hour execution), short-circuit after Phase 3b: emit a 3-line plan (Goal + Steps + Verification), skip Phases 3.5 / 3.6 / 4c / 5a, do not persist (unless `--persist=always` was explicitly passed). The plan goes inline in the conversation, same as `/plan` would emit.

Forced override: `--lite` always wins, even on M-or-larger tasks. Use when the user wants the lighter output deliberately.

### Persistence override

Argument `--persist=never|auto|always` overrides Step 5a default behavior:
- `auto` (default): persist when substrate exists AND plan is M-or-larger AND not in lite mode
- `never`: skip Step 5a entirely; plan stays in conversation
- `always`: persist even on XS/lite plans (forces the git+PR flow)

### Permission posture (read-only by default)

Through Phase 4, superplan uses only read tools (Bash for grep/ls/test, memory-search, code-search, code-graph, AskUserQuestion). Step 5a is the **one** write-tool escalation (file creation + git+PR). For hard enforcement of read-only through planning, **invoke superplan from inside `/plan` mode** — the harness then blocks writes until you exit plan mode and accept Step 5a's commit.

---

## Phase 0: Empirical Preflight

**Fires when**: the user's request names a specific function, file path, skill, hook, rule, MCP tool, API endpoint, or other concrete entity that the plan will reference.

**Skip when**: the request is purely greenfield ("build a new X"), high-level brainstorm ("how might we approach Y"), or names no specific existing entity.

**Substrate-aware skips**: skill/hook/rule/topic-file verification rows below silently skip when the corresponding directory (e.g., `~/.claude/skills/`, `~/.claude/hooks/`) doesn't exist. Function/file/grep rows always run — they only need Bash. So Phase 0 remains useful even in a stripped substrate.

### What to verify

Extract every named entity from the request and grep/read it before Phase 1. The goal is to surface divergence between what the user assumes exists and what currently exists, BEFORE the plan is built around the assumption.

| Entity type | Verification |
|-------------|-------------|
| Function/method name | `Grep` for the symbol; if found in multiple files, note location; if not found, list nearest matches |
| File path | `ls` or `Read` first 5 lines; confirm it exists and is what the user thinks |
| Skill (`/skill-name`) | Check `~/.claude/skills/<name>/` exists and read its frontmatter description |
| Hook | Check `~/.claude/hooks/<name>.py` exists and read its docstring |
| Rule | Check `~/.claude/rules/<name>.md` exists |
| MCP tool | Confirm via `~/.claude/rules/mcp-tool-names.md` (do not guess names) |
| API endpoint | Check indexed API docs via `mcp__codebase-memory-mcp__search_code` first; fall back to live docs only if not indexed |
| Topic file / KB page | Confirm `~/.claude/agent-memory/topics/<x>.md` or `~/Documents/knowledge-base/topics/<x>.md` exists |

### Detail subsections

The mandatory mechanical verification procedure, the baseline freshness
check (24h gate + 20% drift threshold + per-metric re-baseline commands),
and the why-Phase-0-exists rationale are in
`references/phase-0-preflight.md`. Read before authoring any plan that
cites entities or metric values.

### Stop-and-ask gate

If preflight surfaces:
- Any **✗ NOT FOUND** for an entity load-bearing to the plan, OR
- Any **⚠ ambiguous** entity (multiple matches without obvious correct one), OR
- A `[confirmed]` topic-file fact older than 60 days that contradicts the request's assumption, OR
- A baseline-freshness divergence > 20% relative (per the freshness check)

→ **STOP and ask the user** before proceeding to Phase 1. Don't write a plan that depends on a stale assumption.

If preflight surfaces only ✓ entries, note "Phase 0 clean" in one line and proceed to Phase 1.

### Reality-check report format

```
PHASE 0 — Reality Check
  ✓ /superplan exists at ~/.claude/skills/superplan/SKILL.md (667 lines)
  ✓ rules/agent-delegation.md exists, last updated 2026-04-19
  ✗ /writing-plans NOT FOUND (sunset 2026-05-03 in PR #829, redirects to /superplan)
  ⚠ function `dispatch_agent` exists in 2 files: hooks/run-hook.py:42, scripts/team-spawn.py:88
        — plan must specify which one
```

---

## Phase 1: Domain Detection

From the task description (`$ARGUMENTS` or user prompt), identify which domains are involved using the **Domain Detection Matrix** in `references/planning-framework.md`.

### Primary vs supplementary domains

When a task matches multiple domains, designate one as **primary** and
others as **supplementary**:

- **Primary domain**: The domain most central to the task's goal. Gets full
  context loading (agent memory + supplementary files + topic patterns +
  agent capabilities).
- **Supplementary domains**: Supporting domains. Get lighter context loading
  (topic pattern file only, skip agent memory supplementary files).

If it's ambiguous which domain is primary, **ask the user** before
proceeding to Phase 2. Example: "This task touches Security, Infrastructure,
and Identity. Which is the main focus — hardening endpoints, configuring
network rules, or tightening Entra policies?"

### If no domain matches

Skip to Phase 3 with no domain-specific context. Not everything needs agent
memory. The plan will rely on general knowledge and the user's task
description.

## Phase 2: Context Loading

Per-domain topic reads + Phase 2b/2c/2d/2e (semantic memory, KB
context, prior-arc plans, Voyager plan-pattern retrieval). Each
sub-phase is substrate-guarded against Phase -1 probes.

Full procedure: [`references/phase-2-and-3-detail.md`](references/phase-2-and-3-detail.md).

## Phase 3: Capability Assessment

WHAT IS POSSIBLE before HOW. Sub-phases:
- 3.0 (manifest-graph query) and 3 (capability matrix + constraints +
  execution-path selection) — full procedure in
  [`references/phase-2-and-3-detail.md`](references/phase-2-and-3-detail.md)
- 2c (knowledge-base context load) — see
  [`references/phase-2c-kb-context.md`](references/phase-2c-kb-context.md)
- 3b (estimation + ambiguity resolution) — see
  [`references/estimation-and-ambiguity.md`](references/estimation-and-ambiguity.md)
- 3.5 / 3.6 (size-of-effect baseline + tiered opportunity gate) — see
  [`references/size-of-effect-gate.md`](references/size-of-effect-gate.md)

## Phase 4: Plan Construction

Produce a plan that accounts for everything loaded in Phases 1-3b.

### Self-contained-session constraint (mandatory)

Every plan must resolve in a single session. Before writing any step:

1. **Reject calendar gates** — no step may say "wait N days", "after N days of telemetry", "weekly during evaluation window", "30-day clean-run", or any temporal threshold between steps. Calendar time is never a plan gate.
2. **Reject external-approval gates** — no step may say "requires <reviewer> sign-off", "pending <team> approval", "after <external-event> lands" as a precondition for subsequent steps. External reviews are not in-plan gates.
3. **Replace temporal/approval gates with one of three in-session paths**:
   - **Generate**: synthesize the data (fixture, golden set, synthetic adversarial input, simulated workload). The plan generates what calendar time would have produced.
   - **Test**: run a signal-based gate (test battery, classification threshold, measurable evidence) on the generated or existing data. The signal closes the same risk a calendar wait would have.
   - **Glean**: mine prior session transcripts, JSONL logs, git history, KB entries, or existing measurement runs for the same answer. Past data is available now; future data is not.
4. **External reviews become artifacts, not gates** — if a step would have waited on an external reviewer, the plan instead produces an evidence pack / writeup / decision memo as a terminal artifact. The user takes that artifact into the external process themselves; the plan does not block waiting for it.

For each step, before finalizing, ask: "Could the implementer execute this end-to-end in this session, or are they blocked on time / a person?" If blocked, rewrite using one of the three paths above.

### Refresh-then-decide framing (mandatory when a phase depends on a measurement-bearing assumption)

When any phase depends on a measurement, a CI, a bootstrap result, or an empirical observation that was taken in a PRIOR session (>4h ago), the phase's FIRST STEP must be **"refresh the measurement"** — not "act on the measurement, with refresh as a side-check."

The framing matters. Two ways to write the same phase:

| Wrong (act-then-refresh) | Right (refresh-then-decide) |
|---|---|
| "Phase G: Ship `{"assetman/":20}` override. Verify CI still excludes zero post-ship." | "Phase G: Re-run paired bootstrap on current HEAD. IF CI still excludes zero in favorable direction → ship `{"assetman/":20}`. ELSE drop Phase G." |
| "Phase A: Apply fix X based on the 2026-05-09 measurement of N=890 trait failures." | "Phase A1: Re-measure trait failures on current HEAD. A2: IF count is within ±20% of 890 → apply fix X. ELSE re-diagnose substrate before fix." |

The wrong framing treats the prior measurement as load-bearing fact; the right framing treats it as a hypothesis pending re-validation. Under the wrong framing, the plan ships if the refresh "comes back fine" but commits to ship if the refresh isn't run. Under the right framing, the plan cannot proceed without the refresh, AND the ship-decision is structurally conditional on the refresh's result.

**Discipline check for every phase**: read the phase's first step. If it begins with an action that depends on a prior measurement (apply, ship, fix, lift), insert a refresh step BEFORE it. Renumber the rest of the phase. The first action becomes "if refresh holds, do X; if not, document and drop."

INCIDENT 2026-05-10 (Phase G assetman override): parent plan framed Lever 1 as "ship `{"assetman/":20}` based on 2026-05-09 CI." Refresh was Phase A1, BUT the framing implied "Phase G ships, Phase A is the verification side-check." On execution, refreshed CI showed assetman CI now includes zero — the original ship intent was dead. The falsifier-driven design correctly handled this (Phase G dropped), but the FRAMING burned conversational confidence on a measurement that hadn't been re-validated yet. Correct framing would have been "Phase A refreshes CI; Phase G fires IF CI still excludes zero. Default expectation: undetermined."

This is a discipline fix, not a new gate. Phase 4b's per-phase freshness re-check (>24h gate) catches stale measurements at execution time. Refresh-then-decide framing catches the same risk at plan-authoring time — by structurally writing the phase so that "act on the measurement" is impossible without "refresh the measurement" first.

### Load-bearing-mechanism verification (mandatory — fires Phase-4-wide, NOT gated on a lift claim)

A plan phase whose step **trusts an existing mechanism to do what its name/docstring/your-recollection implies** carries a silent-defect risk independent of any metric-lift claim. Before presenting ANY plan, scan every phase for a load-bearing dependency on an existing function / tool / flag / field / endpoint ("leverage X", "X already handles this", "rely on X's behavior"); for EACH:

1. **Read the mechanism at file:line BEFORE presenting** — the actual function body / tool contract, not its name or your memory. Cite the file:line in the step.
2. **Assert contract == reality** for the INPUTS the plan feeds it. Handling case A is not proof it handles the case B the step depends on.
3. **If it diverges → fix the phase at authoring time** (build the missing path + a contract test, or honestly re-scope the step) — NOT at a later red-team. When the plan IS size-of-effect, escalate to Phase 3.5 step 3a's full synthetic contract test. Rationale + the 2026-06-22 worked incident (doc-42 Phase C `extract_values()` defect, shipped past a non-firing Phase 3.5, caught only at red-team): `references/size-of-effect-gate.md` step 3a.

**Product-intent gate for audit-led plans:** an audit ranks release risk; it does
not define the product roadmap. Before promoting audit findings into a build
plan, state and validate the intended user loop, product mode, and explicit
non-goals. If those are absent or ambiguous, the first phase is intent validation,
not implementation. A user-owned policy choice is removed from mandatory scope;
it must not be converted into a required declaration, proxy field, or deterministic
score unless the user explicitly selects that mode.

### Plan structure:

Use the **Plan Structure Template** from `references/planning-framework.md`. Every plan must include: Goal, Domains (with primary/supplementary), Constraints, Execution Path, Execution Budget, Steps (with tool/agent/dependencies/gotcha/expected output per step), Dependency Summary, Verification, and Execution routing.

**Execution budget (mandatory):** emit the default `execution_budget` block with
`repair_cycles: 1`, `full_suite_runs: 1`, `live_probes: 1`, and
`nonblocking_findings: backlog`. These are maxima, not goals. A plan may raise a
value only for a named concrete risk or mandatory external gate and must explain
the exception in Known Constraints. Passing the demo plus mandatory gates is
terminal; later improvement ideas are backlog, not new in-plan canaries.

**Plan-type — MEASUREMENT RUN**: if the request is "measure / validate / assess the accuracy of X to a scientific standard" and the DELIVERABLE is *numbers + a trustworthiness verdict* (not a feature build or a metric-lift ship — signal phrases: "this is a measurement run", "oracle", "ground truth", "untrusting of our own judgement"), the default size-of-effect template does NOT fit. Load `references/measurement-run-plantype.md` and use its required sections (objectives + pre-registered hypotheses · test-don't-trust assumptions · data fields · ORACLE design + contamination + n_eff · harness/instrument-soundness · infra/throttling · metrics/checkpoints · methodology guards). This is the structural home for the rigor a measurement request demands; the 2026-06-20 accuracy run is the worked example.

**Scope tag per step (mandatory)**: tag every proposed change Critical / High / Nice / Skip per `rules/scope-discipline.md`. Skip-tagged items are DROPPED from the plan, not carried as steps; default-bias toward the smallest correct change. This curbs the "build everything" overengineering pattern at plan-authoring time.

**Phase-type + execution-mode tag per phase (mandatory)**: tag each phase `BUILD`/`MEASURE`/`WRITE`, and an execution-mode **HEADLESS > DURABLE > LOCAL-FAST** — prefer HEADLESS (bulk API/model work as an async batch, e.g. Bedrock `create_model_invocation_job`: submit, laptop OFF, collect later); where a phase can't be headless (irreducible operator/human judgment) it MUST be DURABLE (detached + checkpoint-resume + `.done`/`.fail` markers, resumable). **FORBIDDEN: a laptop-tethered run >~30 min that is neither HEADLESS nor DURABLE.** Sequence BUILDs that don't depend on a long MEASURE FIRST (capability not blocked on measurement). Size before calling a MEASURE long (API calls = minutes at parallelism; only operator/human labor is the real long-pole). Multi-mode systems: each phase declares which incompatible target (recall-sensitivity vs precision) it serves, never damaging the other. Full procedure + worked example: `references/phase-4-construction.md` "Phase-type + execution-mode".

**Demo statement (for each task)**: Include a `Demo:` line describing
what can be demonstrated when the task is complete. This makes completion
observable and testable. If a task has no demo-able output, it may need
restructuring into a vertical slice that delivers observable value.

Example: `Demo: "User runs /triage and sees Devil's Advocate challenges
in the output for medium+ findings."`

**Deploy-seam check (mandatory for any BUILD phase whose artifact is a DEPLOYED
component — Lambda module, ECS service, hook, scheduled job).** "File exists + tests
pass" is NOT completion for a deployed artifact; the Demo + `### Metric Commands` MUST
assert it reaches its **real sink** (in the deploy boundary / wired into the running
entrypoint / one real invocation crosses every seam), not presence (`[ -f X ]` /
`grep -q symbol` measure authoring — an autonomous loop greens them undeployed). Full
procedure + placement rule + the 2026-06-26 incident: `references/phase-4-construction.md`
"Deploy-seam check". (`verify-effectiveness.md` multi-seam invariant.)

**Deployment-pin trace:** for every partition/account/region/tenant/audience/principal/endpoint,
trace source variable → repository variable or secret → workflow environment → saved plan → live
readback, with a source-level test. A missing link means the plan is not deployable, even if direct
local Terraform accepts the value.

### Phase 4 detail

The detailed Phase 4 disciplines (Demo constraints for size-of-effect phases,
default phase ordering for observable systems, cross-component coordination
check for new signals, mandatory Falsifiers section for M/L/XL plans, phase
grouping rules, dependency notation, engineering review sections with
Error map + Dependency failure analysis) are in
`references/phase-4-construction.md`. Read before authoring any non-trivial plan.

Quick-reference summary:
- Demo line cites Phase 3.5 baseline (`currently N → expected M`); synthetic-fixture passes are regression evidence, not the standalone demo
- Production-stack verification required for default-flip phases (both off-mode + on-mode), per `rules/eval-shipping-discipline.md`
- Observable-system plans default to instrument → investigate → implement → verify
- New signals (log prefix, env-var, JSON field, metric label) must grep for downstream consumers in the same edit batch
- M/L/XL plans require `## Falsifiers` section + Error map + Dependency failure analysis
- Phase grouping mandatory for plans with >8 steps; arrow-notation dependency summary required

## Phase 4b: Critical Review Gate (for plans from prior sessions)

Fires only when executing a plan loaded from a file or carried over from a
previous session. Skip for plans just constructed in Phase 4.

The full procedure (read-completely-then-check-stale gate, 6 stop-and-ask
triggers during execution, per-phase baseline-freshness re-check on >24h
in-flight plans, per-bucket falsifier measurement discipline) is in
`references/execution-discipline.md`. Always read it before executing a
prior-session plan.

Quick-reference summary:
- Read the plan file completely, check stale assumptions (tools, codebase, rules)
- Stop if: blocker, unexpected output, 2+ consecutive verification failures, observed < 0.3× predicted, falsifier trigger, >24h baseline drift >20%, per-bucket measurement misframed

## Phase 4c: Context Capture into Plan

> Selectively cloned from tobihagemann/turbo `/capture-context` pattern.

Before saving and presenting the plan, scan the conversation for accumulated
knowledge that should be preserved in the plan file itself:

1. **Files explored and their relevance** — which files were read during
   planning, what was learned from each
2. **Decisions made with rationale** — "chose X because Y, rejected Z
   because W"
3. **Constraints discovered** — limitations found during context loading
   (tool unavailable, API quirk, platform constraint)
4. **Open questions** — unresolved items that implementation will need to
   address

Write these as a `## Session Context` section at the top of the plan,
before the implementation steps. Phase 5 Step 5a then saves the plan
including this section.

**The test**: Could someone reading only the plan file implement without
the original conversation? If no, the Session Context is incomplete.

Skip this phase for simple plans (<5 steps) where the plan itself contains
all necessary context.

## Phase 5: Execution Routing

Based on the plan, recommend the right execution path using the **Execution Routing Matrix** in `references/planning-framework.md`.

### Step 5a: Save plan to disk and commit (conditional)

**Fires when** `--persist=auto` (default) AND substrate exists (Phase -1 probe `kb:Y`) AND plan is not lite-mode, OR `--persist=always` was explicitly passed.

**Skip when** `--persist=never` was passed, OR `--persist=auto` AND (substrate absent OR lite-mode). Note in output: `STEP 5a — Skipped (persist=never)` or `STEP 5a — Skipped (no KB / lite-mode; plan stays inline)`.

Persist the plan (including any `## Session Context` from Phase 4c) to
`~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>.md`, then commit + PR +
auto-merge via the standard git flow from inside the knowledge-base repo.

### Step 5a.1: SHA-256 plan attestation

Immediately after writing the plan file (before the git commit), compute and persist its SHA-256:

```bash
(cd ~/Documents/knowledge-base/plans && sha256sum YYYY-MM-DD-<slug>.md) \
  > ~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>.md.attestation
```

The output format is `<sha>  <basename>` (e.g., `abc123def  2026-06-14-plan.md`), which matches the format written by supergoal's parse_plan.py at bootstrap time.

The attestation locks the plan against mid-loop tamper. supergoal's verification hook checks the plan's mtime each turn; when mtime has changed, it re-hashes and aborts the loop with `plan-tampered` if the hash differs. Without this, a silently-mutated plan would let the prior-arc ledger lie.

Intentional updates: stop supergoal, re-run superplan to update the plan (which re-attests), re-invoke supergoal. Do not edit the plan file directly during an active loop.

Pattern from `OthmanAdi/planning-with-files`'s `/plan-attest`. The mtime-keyed cache avoids re-hashing on every turn (~99% I/O savings when the plan is unchanged) — see `~/.claude/skills/supergoal/references/verification-hook.md` Step 1 for the full procedure.

### Step 5a.2: Plan template — required new sections

Beyond the existing Goal / Constraints / Steps / Verification structure, plans must now include:

**`execution_budget`** — a YAML block that caps repair cycles, full-suite runs,
and live probes and routes nonblocking findings to backlog. It prevents a green
vertical slice from expanding into open-ended review or validation work.

**`### Metric Commands`** — explicit code block of shell commands whose output (final line matching `^METRIC <name>=<value>`) is the authoritative measurement. supergoal parses these; conflating with `Verification:` legacy is still supported but emit the explicit section if possible. Pattern from `autoresearch`.

**`### Guard Commands`** — code block of commands that must continue to pass (existing tests, lints). Separate from metric — guards catch regressions, metrics drive progress. autoresearch v2's lesson: conflating them lets the model succeed by regressing tests.

**`### Artifact Probe`** — code block of commands that observe the *artifact* (not the metric). Different surface area. Run only at exit as a Goodhart probe. Source: mpt.solutions Goodhart's-Law post documenting `/goal` shipping a 960×540 space shooter with 3 starfield pixels because conversation-eval passed. Without this section, supergoal warns and disables the probe; metric-gaming becomes undetectable.

**`### Forbidden Actions`** — list of tool-call patterns the agent must NOT take during the loop. Convention from Devin playbooks. supergoal's hook can be extended to refuse these. Examples:
- `Bash(rm *)`
- `Edit(file_path=/etc/*)`
- `Bash(git push --force *)`

If omitted, supergoal warns and disables the policy axis.

**Falsifier format is a parser contract:** `## Falsifiers` must be markdown
LIST ITEMS — a table parses as zero falsifiers and `parse_plan.py` exits 20
(measured 2026-08-24; the dry-run below is what catches it pre-commit).

**Readiness self-check (supergoal-bound plans).** Nothing verifies superplan's OWN output matches this template, so a deviating plan (prose `## Verification` instead of an executable `### Metric Commands` block; bolded `**Demo:**`; sentence-final baseline) ships clean and fails only at supergoal parse-time. Before declaring ready, dry-run: `python3 ~/.claude/skills/supergoal/scripts/parse_plan.py <plan> --state-dir /tmp/claude/sp-check/ --reset` — exit 0 with `metric_commands: N≥1` = ready; exit 20 = fix the named section. The metric block must RUN as-is in the not-yet-built state (guard with `[ -f X ] &&`) and print a real `METRIC name=<number>`, not a `<placeholder>`. (2026-06-21 mega-capture miss; parser made tolerant in #1416.)

**A metric that reads a remote-tracking ref MUST `git fetch` inside the metric block.** `git -C "$REPO" show origin/main:<path>` reads the LOCAL remote-tracking ref, so after a PR merges the metric reports the world as of the last unrelated fetch. Measured 2026-08-24: `librechat_confluence_config_sites` still printed **0** after its PR merged — local `origin/main` was `fa87c87b`, actual was `a0a9bbc8`; adding `git fetch origin main -q` to the top of the block made the same command print **2** with no other change. The reason this survives plan authoring is structural: at baseline the true value and the stale-ref value are BOTH the baseline, so a metric verified only at baseline cannot reveal a staleness bug — the two agree exactly until the first real change lands. Emit the fetch for every repo the block reads, and treat "verified at baseline" as unverified for any metric whose source is a ref.

### Step 5a.3: Plan-pattern library write (on successful supergoal exit only)

When a downstream supergoal run exits with `success`, the terminal-doc writer extracts a reusable pattern template and writes it to `~/Documents/knowledge-base/plan-patterns/<pattern-slug>.md`. See `~/.claude/skills/supergoal/references/plan-pattern-library.md` (absolute path to the sibling supergoal skill's references/ directory) for the template schema. Phase 2e reads from this dir for the next plan.

### Step 5a.4: Parallel-dispatch routing recommendation

If the plan has ≥3 vertical slices that are independent at the file level (no shared mutable state between slices), Step 5b's execution-path recommendation should suggest **Task-tool parallel dispatch** instead of sequential `/supergoal`. Pattern from `evanflow/skills/evanflow-writing-plans` ("Parallelization Check") and `obra/superpowers/skills/dispatching-parallel-agents`. Sub-tasks each get **scoped context** (their slice + the relevant plan steps), NOT the full plan — context inheritance corrupts subagent reasoning and explodes token cost (Roo Code Boomerang convention).

**Full procedure** (mkdir, slug generation, Write, readback verification,
`git checkout -b plan/<slug>` → `git add` → commit → push → gh pr create →
gh pr merge --auto --squash --delete-branch, plus failure-mode handling)
is in `references/save-plan.md`. Always run immediately after Step 4
readback succeeds — deferring causes the session-start auto-checkpoint hook
to absorb the file onto a `checkpoint/<timestamp>` branch with no PR path
(5-10 turn recovery cost).

### Step 5b: Present and route

Present the plan, mention the saved file path, and ask: **"Ready to execute? Which path?"** —
but route the RECOMMENDATION through the supergoal gate below first. Do not offer supergoal as a
co-equal default on every plan; recommend exactly one path and say why.

### Supergoal routing gate (recommend it for the right jobs only)

Recommend **`/supergoal`** ONLY when ALL four hold:

1. **Unattended intent** — the user wants to walk away (headless `claude -p`, overnight, "keep
   going until"), or explicitly asked for an autonomous loop.
2. **Metric-climbing shape** — progress IS a machine-checkable number that must move over many
   iterations (a failing-test count, a benchmark score, a coverage ratio). Supergoal's whole
   value is tool-backed between-turn verification of that number.
3. **Zero in-plan human gates** — no AskUserQuestion decision, no operator-run apply/login, no
   classifier-gated destructive op. A headless loop STALLS FOREVER at the first one; its
   evaluator cannot answer a question or run the operator's SSO login.
4. **One coherent optimization target** — not a program of N heterogeneous close-outs. A
   close-out program's "metric" is a checklist, not a gradient; the loop adds ceremony, not
   verification.

Otherwise recommend **direct execution** (main thread, or parallel dispatch per Step 5a.4) and
KEEP supergoal's disciplines inline: run the plan's `### Metric Commands` as the completion gate
and honor the falsifiers. Mention supergoal only as the resumption vehicle if an unattended
residue emerges later.

Measured basis (2026-08-23): a 7-phase close-out program executed directly hit FOUR moments a
headless loop could not have crossed (a user policy decision, two classifier denials requiring
operator handoff, an SSO expiry) — while the inline metric gate still verified completion. The
same session's zero-ceremony build, by contrast, was a genuine supergoal shape (one demo metric,
no human gates) and ran under the loop's hook. Both routings were right; offering the loop for
both would not have been.

### Step 5c: Terminal-doc-on-undershoot contract (mandatory after plan execution)

**Fires when** plan execution completes AND any phase falsifier triggered OR observed lift was < 0.3× the predicted lift OR the combined falsifier triggered.

The terminal-doc-on-undershoot contract (four named sections: per-phase
freshness verdict, re-diagnosis, retired hypothesis, named next-plan target,
versioned anchor file) plus the DROP-vs-DEFER framing matrix and the
ceiling-claim enumeration check are in `references/execution-discipline.md`.

Quick-reference summary:
- Fires on falsifier trigger OR observed-lift < 0.3× predicted
- Writes `YYYY-MM-DD-<slug>-terminal.md` sibling file via same git+PR flow as Step 5a
- 3 framing options for incomplete phases: DEFER (revisit later) / DROP-ON-ZERO-SUBSTRATE (plan's estimate was wrong) / REDUNDANT (already implemented)
- "Structural ceiling" claims require enumerating orthogonal mechanisms first

## Phase 6: Re-Plan (when the user says "that won't work")

If the user rejects the plan or provides new constraints:

1. **Preserve loaded context** — do NOT re-run Phases 1-2. The domain
   detection and context loading are still valid.
2. **Identify what changed** — ask: "What specifically is wrong? New
   constraint, wrong assumption, or different goal?"
3. **Patch the plan** — revise only the affected steps. Don't rebuild
   from scratch unless the goal changed.
4. **Re-validate** — run Phase 4 quality checks on the revised plan.
5. **Re-present** — show the revised plan with changes highlighted.

This preserves the depth of context loading while allowing fast iteration
on plan structure.

---

## Examples

See `references/examples.md` for three worked examples covering cross-domain security automation, single-domain finance tasks, and MCP development.

## Success Criteria

- Plan produced includes all required sections (Goal, Domains, Constraints, Execution Budget, Steps, Dependencies, Verification)
- Execution budget defaults to one repair cycle, one full-suite run, one live probe, and backlog for nonblocking findings
- Every step references a specific tool, agent, or execution method
- Known gotchas from agent memory or topic files are surfaced at relevant steps
- User receives a clear execution path recommendation
- 0 steps reference read-only tools for write operations
- Plans with >8 steps are grouped into phases
- Independent steps are identified as parallelizable
- Primary vs supplementary domains are designated for multi-domain tasks
- Plan saved to `~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>.md` and the path surfaced in the in-conversation summary

## When NOT to Use This Skill

- Simple one-shot queries ("how many open CrowdStrike detections?") — just ask, no plan needed
- Brainstorming / design exploration — use `superpowers:brainstorming` instead
- Pure research / learning — just explore, don't plan
- Tasks the user already fully understands — if the user says "just do X," do X. Don't impose ceremony on a clear instruction.

For the previously-listed "urgent tasks where planning overhead exceeds execution time" case, **use `--lite`** instead of avoiding the skill. Lite mode short-circuits after Phase 3b with a 3-line plan and no persistence, matching `/plan`'s overhead.

## Completion Checklist

Read `references/completion-checklist.md` before declaring the plan complete — it is the full per-phase checklist (substrate detection through execution routing) and MUST be walked item-by-item at the end of every /superplan run.
