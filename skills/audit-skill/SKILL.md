---
name: audit-skill
description: "Audit a skill (or all skills) for external-contract drift, content hygiene, and behavior gaps."
when_to_use: Audit a skill (or all skills) for external-contract drift, content hygiene, and behavior gaps. Three-phase audit — a mechanical lint, then deeper agent checks (literal command execution from docs, deployed-path verification, error-path probes, cross-script format alignment, invariant verification, references drift), then oracle re-gating of findings before any are actioned. Use when shipping a skill, after a multi-file change, or as a periodic hygiene pass. Trigger phrases - "audit skill", "check skill drift", "verify skill before ship". Do NOT use for one-line fixes that touch no contracts (the --strict mode in pre-commit handles those), or for brand-new skills before frontmatter validation has been run.
argument-hint: "[skill-name]|--all"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
  body-cap: exempt
  body-cap-reason: "PERIODIC: a hygiene audit run before shipping a skill or as a corpus pass; the routine part is bin/audit-skill.py in pre-commit, not this body"
allowed-tools: Agent Bash Edit Read Grep Write AskUserQuestion
---

## audit-skill

Audit one skill (or all of them) against a fixed test-battery. Three phases: a mechanical lint first (cheap, deterministic), then agent-driven scenario checks (interpretation needed), then oracle re-gating before any finding is actioned.

The categories are stable; the per-skill scenarios are constructed by the agent from the skill's own contents.

> **Runtime policy:** Resolve the effective model and attach the requested /
> effective runtime receipt to qualification events per
> `../_shared/model-runtime-policy.md`.

## When to use

- Before shipping a skill (or a multi-file change to one)
- After changing schemas, hook prompts, or any contract a skill describes in prose
- Periodic hygiene pass across the repo
- After bulk changes to `marketplace/` or `skills/` that may have desynced

## When NOT to use

- For a one-line fix that touches no contracts and no docs (`--strict` mode of the mechanical script in pre-commit handles that)
- For brand-new skills not yet wired in (frontmatter validation comes first)

## Eight-component harness map

audit-skill is the reference implementation of the eight-component harness pattern (proposer, oracle, context, tool surface, orchestration, memory, failure-detection middleware, observability). The full component map — where each lives in this skill and why other skills should study it before adding their own harness — is in `references/harness-map.md`.

## Procedure

> **Three-phase contract — all phases are MANDATORY.** Invoking
> `/audit-skill <name>` means: Phase 1 (mechanical lint) → Phase 2
> (agent-driven scenario audit) → Phase 3 (oracle gating). For
> `/audit-skill --all`, run Phase 1 across the whole tree, then
> dispatch Phase 2 agents per skill (parallel), then run Phase 3 on
> the combined findings before reporting anything actionable.
>
> Stopping after Phase 1 misses semantic drift, aspirational features,
> and invariants-with-no-enforcement (see "Known limitations of Phase 1"
> below). Stopping after Phase 2 ships stale/hallucinated findings to fix
> tasks (`references/run-history.md`). Phase 3 closes that gap.

### Phase 1: Mechanical lint (always)

```bash
~/.claude/bin/audit-skill.py <skill-name>
```

Reports H1 (phantom citations), H2 (orphan references), H4 (cross-skill citation broken), H5 (backtick-wrapped doc-citation preceded by a read-verb that doesn't resolve against skill / skills / repo — catches the class of broken citation that H1/H4 miss because they only see the references/ shape), D3a (missing script paths), D3b (non-canonical path prefixes), D3c (dead-code scripts), C1 (POSIX-only Python imports without fallback), C2 (POSIX-only paths in bash docs), C3 (.sh-only scripts dir), C4 (literal `$HOME` strings in Python source), C5 (file-I/O without `encoding='utf-8'` — cp1252 crash class), C6 (argparse `help=` with unescaped `%X` — `--help` TypeError), C7 (script with `__main__` + `sys.argv` but no `--help` short-circuit), C8 (BSD-vs-GNU shell divergence in `*.sh` — `sed -i` without backup arg, `date -d`, `xargs -r`), C9 (`/tmp/` literal in Python source — POSIX-only path; use `tempfile.gettempdir()`), C10 (bare `subprocess.run(['bash', ...])` without resolving via `_resolve_bash` helper — Windows resolves `bash` to the WSL launcher), M1 (argument-hint/manifest drift), M2 (dead MCP tool declarations), M3 (`manifest.yaml` ships with `# TODO` scaffold placeholders), M4 (SKILL.md `allowed-tools` and manifest `requires_tools` should agree modulo wildcards — info severity; `requires_tools` feeds topic auto-loading, not runtime tool gating), T1 (phantom MCP tool references), B1 (scripts ship without tests/), B2 (hook ships without a corresponding `hooks/test-hooks/test_<name>.py`; repo-wide check), P1 (unresolved template placeholders — see `known-tools.yaml` for the catalog), Q1 (SKILL.md exceeds 5000-word limit), Q2 (description exceeds 1024-char Claude Code limit), Q3 (description missing WHEN / Do NOT use for sections), S1 (audit-suppress.yaml entry past its `expires:` date — it no longer suppresses, so the underlying finding fires again; remove it or extend after re-confirming), S2 (orphaned suppression — matches no finding the mechanical checks produced this run; scoped to the script's own codes since suppress files also carry /audit-fix agent-campaign codes the script can't observe). These are structural — no execution needed.

Under `--all`, an additional **repo-wide** pass runs C5/C6/C7/C9/C10 against `bin/*.py`, `hooks/*.py` (non-test), `manifests/*.py`, `scripts/*.py`, and root-level `*.py` — plus C8 against every shipped `*.sh` (excluding vendored / generated trees and the audit-skill fixture *.sh files) — plus B2 (every `hooks/<name>.py` must have a matching `hooks/test-hooks/test_<name>.py`). Findings appear under the synthetic skill name `__repo__` (the per-skill audit only scans the skill's own `scripts/` + `references/`, so anything outside the skills tree needs this pass).

T1 reads `known-tools.yaml` in this skill's directory: any reference to a name in `known_phantom` is flagged as drift. Pass `--strict-tools` to additionally flag references not in `known_real` (off by default — the registry is incomplete and would false-positive on per-user MCP configs).

**Other flags**: `--parallel=N` (ProcessPoolExecutor over per-skill audits — CPU-bound regex+AST work needs processes, not threads; findings re-ordered to the deterministic skill sequence; see `references/harness-map.md` component 5), `--strict` (drift causes non-zero exit), `--check-marketplace` (also verify marketplace/ is in sync — implied by `--all` unless `--no-marketplace-check` is passed), `--no-marketplace-check` (skip marketplace freshness verification, useful for fast iteration), `--json` (machine-readable output for CI tooling — one JSON object per skill on stdout), `--sarif` (SARIF 2.1.0 for GitHub code-scanning / VS Code Problems pane), `--changed[=BASE]` (narrow to skills touched in `git diff BASE...HEAD`, default `origin/main` — pairs with PR CI to audit only what the PR modifies), `--fix[=CODES]` (apply mechanical fixes for the listed codes, default `C5,C7` — writes files in place; re-run audit afterward to verify), `--surface-map` (emit the deterministic Phase-2 surface map as JSON and exit, no lint — per-skill `tier` (deep/light), `has_scripts`/`has_cli`, `bash_block_count`, `references_count`, and which A1/B/D1/D2/D4 categories are applicable vs n-a; A3/F2/F3 are tagged `review` since they depend on prose claims that can't be ruled out mechanically).

Read the output and **always** continue to Phase 2 — never report
audit results to the user without running Phase 2. The Phase 1 OK is
not "the skill is clean"; it's "no mechanical drift detected." Phase 2
is where semantic bugs surface.

### Known limitations of Phase 1 (mechanical lint)

The mechanical lint catches structural drift but cannot catch semantic
drift. The following classes require Phase 2 (agent judgment):

- **Prose drift**: Success Criteria bullets that say one thing while the
  Procedure says another (e.g., "all 9 gates checked" vs "run all 7
  gates" elsewhere in the body). A mechanical noun-phrase comparison
  produces too many false positives because natural-language
  paraphrasing is normal.
- **A3 invariant claims**: "X is idempotent", "Y does not advance during Z" —
  truth-of-claim requires constructing a reproducer scenario.
- **Cross-skill behavioral coupling**: skill A documents that skill B
  produces output of shape S; if S changes, A goes stale. Phase 2 only.
- **Agent-loadable references**: an `argument-hint` that promises a
  fallback only resolvable by reading prose. Mechanical can verify the
  bracket convention (M1), not whether the fallback documented in the
  body is real.

### Dispatching Phase 2 (execution model)

**How Phase 2 runs depends on whether the audit target is a protected repo** — the "dispatch Phase 2 agents per skill (parallel)" line in the contract above is the *non-protected* path, and it is blocked for a self-audit.

- **Protected-repo targets (`claude-config`/`.claude`, `mcp-servers`, … — the default when auditing this repo's own skills): run Phase 2 in the MAIN session, not via subagent dispatch.** The Agent-dispatch gate refuses *any* Bash-capable subagent (`general-purpose`, `Explore`, `worker` — Bash is a write vector, so the gate can't tell read-only intent from write intent) against a protected repo unless `isolation: "worktree"` is set, and parallel worktree dispatch is forbidden (`subagent-verification.md`). Worktree isolation is also wrong here: A1 resolves documented commands against `~/.claude/skills/<name>/`, but a worktree checkout relocates the skills, so deployed-path verification breaks. The main session is authorized to run Bash/Read against the protected repo without the gate, and main-session execution keeps you as the primary-source reader (no subagent-fabrication risk — see issue #67730).
- **Non-protected targets: dispatch one read-only `Explore` agent per skill (parallel).** `Explore` has Bash/Read/Grep/Glob but no Edit/Write/Agent, so it cannot mutate the repo or spawn grandchildren — parallel-safe on macOS at the engine-pool cap.

**For `--all` (corpus mode), tier the work — do NOT give every skill the full category battery:**

1. **Map the surface first.** A skill with executable scripts (`scripts/`, `harness/`, `bin/`) or ≥5 fenced bash blocks has real A1/B/D1/D2/F2/F3 surface; a prose/orchestration skill (no scripts, few bash blocks) does not — for it, B/D1/D2/F2/F3 are **N/A**, and only A1 (the few documented commands), A3 (invariant claims), and prose-drift apply. Roughly a third of the corpus is script-bearing. Run `~/.claude/bin/audit-skill.py --all --surface-map` (or `<skill> --surface-map`) to emit this tiering as JSON instead of deriving it by hand — each entry gives the `tier`, the raw signals (`has_scripts`, `has_cli`, `bash_block_count`, `references_count`), and a per-category applicable/n-a/review map.
2. **Deep tier** (script-bearing): full A1/B/D/F scenario construction.
3. **Light tier** (prose-only): A3 + Success-Criteria↔Procedure prose-drift; mark the script-dependent categories N/A explicitly.
4. **Batch with a distinct skill list per agent/pass** (near-identical prompts maximize the parallel-fan-out duplication/fabrication failure mode), require every finding to **quote the source line it cites and carry a machine-checkable reproducer** (no fabrication), and verify the running-agent count matches what you dispatched.

The executable A1/B sweep is cheap to run corpus-wide from the main session directly: `--help` + no-arg probes of every script CLI plus `bash -n` on every `*.sh` catches the entry-point class without per-skill agents.

### Phase 2: Agent checks

**Before starting**, read `audit-context.md` in this skill's directory.
It documents repo-wide ground truth (which env vars are actually set,
which MCP tool names are real, which paths resolve at deployment) so
you don't reason from scratch about every skill. Without this context
audit agents false-flag patterns that are fine — e.g., `$CLAUDE_PROJECT_ID`
is actually exposed by most Claude Code surfaces; not every reference
to it is a bug.

**Suppressions**: if the target skill has an `audit-suppress.yaml`
file, treat the listed findings as known-OK and don't re-surface them.
Each suppression has a reason; respect it unless you have new evidence
the reason no longer applies.

**Label every finding as `[behavior-fix]` or `[doc-fix]`**:
- `[behavior-fix]` = fixing changes the skill's user-visible output. The
  bug must come with a constructed reproducer (input → observed wrong
  output → expected output). If you can't construct one, demote to
  `[unverified]` and recommend a check rather than asserting a bug.
- `[doc-fix]` = fixing changes only the docs (clarify prose, align
  Success Criteria with procedure, fix a typo). Useful for future
  readers but does not change runtime. These should be `info`, not
  `drift`, unless they break an LLM-readable citation.

**Optional: dual-agent verification** for medium+ findings. Dispatch
two independent agents on the same skill; only surface findings both
report. Cuts false-positive rate at 2× token cost. Use for the
highest-stakes skills (security/compliance critical ones); skip for
routine ones.

For the target skill, construct scenarios from its own SKILL.md and code, then verify. Categories:

#### A. External contract verification

**A1. Literal commands run as documented.** Extract every command-shaped line from fenced `bash` / `sh` blocks in SKILL.md. For each:

1. Resolve the command against the *deployed* path (`~/.claude/skills/<name>/`), not the repo path. If the skill is not symlinked into `~/.claude/skills/`, create the symlink first:
   ```bash
   ln -sf /home/user/claude-config/skills/<name> ~/.claude/skills/<name>
   ```
2. Run the command as documented (literal arg strings, including any `$0`-style placeholders bound to a representative test fixture).
3. Report any non-zero exit AND any python traceback in stderr — both are external-contract bugs.

**A3. Invariants hold.** Read SKILL.md and references/ for prose invariant claims. Examples of claim-shapes that need testing:
- "X does not advance during Y" (e.g., "wallclock excludes pause intervals")
- "X is idempotent" (e.g., "double-pause is a no-op")
- "X refuses when Y" (e.g., "resume refuses on plan-tampered")
- "X is reset on Y" (e.g., "consecutive_no_progress resets on demo-achieved")

For each claim, design a minimal scenario that would *expose* a violation, run it, verify the claim holds. Flag any unmet claim with the scenario as a reproducer.

#### B. Error paths

For each CLI mentioned in the skill, invoke with:
- No args → usage hint, non-zero exit
- Nonexistent input file → clean "not found" message, no traceback
- Malformed input (e.g., bad JSON) → clean error + recovery hint, no traceback
- Stub input missing required field → clean error naming the field, no traceback
- Wrong arg shape → usage hint

Flag any raw traceback in stderr or silent success on bad input.

#### D. Cross-component contracts

**D1. Writer/reader format alignment.** Identify scripts that produce content another script consumes (terminal-doc → ledger-parser; parser-output → hook-input). Open both. Compare the writer's output format to the reader's regex/parser. Flag mismatches (the kind of bug where `**Exit reason**:` is written but `Exit reason:` is parsed).

**D2. Schema-vs-consumer alignment.** If a script writes a state file, list every field it writes. List every field every consumer reads. Flag any consumer-required field not written, and any field written but never read (with lower severity).

**D4. References describe current code.** For each `references/X.md`, identify what code/contract it describes. Read both. Flag stale field names, retired mechanisms, paths that no longer exist, contradictions with the actual code.

#### E. External-artifact claim verification

**E1. Rules and knowledge-base topics accurately describe this skill.**
Grep `rules/*.md`, `agent-memory/topics/*.md`, and (if reachable)
`~/Documents/knowledge-base/topics/*.md` for `/<skill-name>` mentions
(match the invocation form with the leading slash — a bare substring
match on the skill name picks up unrelated English-word noise). For
each hit that makes a factual claim about the skill's behavior or
ownership (not a routing pointer like "run /X next") — verify it
against the skill's CURRENT SKILL.md:

- **Ownership claims** ("X handles Y", "X's job is Z") — confirm the
  skill's own scope section actually covers Y/Z. A responsibility that
  moved to a different skill (a split, a refactor) leaves the OLD claim
  stranded in whichever file asserted it first.
- **Capability claims** ("X was created to do Y", "X supports Z mode") —
  confirm the capability exists on disk (a directory, a flag, a
  documented step), not just in the narrative.
- **Structural KB content** (frontmatter `description:`, the blockquote,
  a `## Current understanding` section) is held to a currently-accurate
  bar — flag any mismatch as drift. A **dated** KB entry describing OLD
  behavior is not itself a bug (KB dated entries are historical record
  by design) — flag it only if the claim was FALSE even at the time it
  was dated (e.g. "created X" when X never shipped), or if a
  Current-Understanding section repeats the stale claim.

This category is agent-judgment-only (no mechanical detector) — same
reason A3/F2/F3 have no Phase 1 equivalent: it depends on reading prose
claims scattered across files this skill doesn't own. Label findings
`[doc-fix]` for a wrong external claim (the fix lands in the file making
the claim — usually NOT this skill's own files) or `[behavior-fix]` only
if the skill's OWN SKILL.md misrepresents its own behavior.

(E1 is the rule/KB-to-skill direction: D4 only covers a skill's own
`references/*.md`, and "cross-skill behavioral coupling" only covers
skill-to-skill claims. The gaps it closed: `references/run-history.md`.)

#### F. Real-data integration

**F2. Threshold enumeration.** If the skill describes thresholds ("1-2 → warn, 3+ → refuse, +force-override → proceed"), construct a scenario at each threshold and confirm behavior. Off-by-one bugs and missing override paths surface here.

**F3. Output variants.** If the skill has discrete output modes (e.g., each `exit_reason` value), exercise each. Flag any variant that errors or produces incomplete output.

#### G. Deployment context

**G1. Test from the deployed path.** Already covered by A1's symlink step — but if the skill expects to live at `~/.claude/skills/<name>/`, the test fixture for A1 must run from there. Tests that pass against `/home/user/claude-config/skills/<name>/` but fail against `~/.claude/skills/<name>/` indicate a path-resolution bug.

**G1a. Verify the transitive runtime dependency closure.** A composed or
orchestration skill is not deployable merely because its own directory matches
source. Read its `manifest.yaml`, recursively expand `requires_skills`, and
verify every dependency from the runtime's deployed root (`~/.agents/skills/`
in Codex, `~/.claude/skills/` in Claude Code). Report drift per dependency;
never collapse a green root plus stale children into a passing G1 verdict.

In `claude-config`, use the executable closure check rather than reconstructing
the graph by hand:

```bash
python3 bin/sync-codex-skills.py --check --with-dependencies <skill-name>
```

#### I. Live execution

**I1. Invoke the skill for real and diff observed vs. documented behavior.**
Every other category tests an *extracted piece* of the skill (a literal
command, a threshold scenario, a claim in prose). I1 instead runs the
skill's actual, full invocation and watches what happens end to end —
catching bugs that only manifest when the documented steps run together
in their natural order, against real state.

1. **Classify invocation safety.** Does the skill mutate state (writes
   files, opens PRs, merges, sends messages, deletes, schedules)? If the
   skill documents its own safe mode (an audit/dry-run flag, a
   discovery-only phase, an analysis-only stop point before persistence),
   use that. If it has no safe mode and is destructive with no sandbox
   target available, mark I1 N/A and say why — don't force a live run
   that would have real side effects just to satisfy this category.
2. **Invoke against a real target**, not a synthetic fixture — fixtures
   under-exercise exactly the bugs this category exists to catch: a wrong
   env-var check, a stale target path, a silent no-op on real data shapes.
3. **Watch execution against the documented Procedure**, step by step.
   For each step SKILL.md claims happens, confirm it actually fired, in
   the claimed order, producing the claimed effect.
4. **Flag any divergence** — a step that doesn't run, references a target
   that doesn't exist, silently no-ops, or produces output the docs don't
   describe — the same way other categories do:
   `[behavior-fix]` if the skill's own behavior is wrong,
   `[doc-fix]` if the skill is fine but SKILL.md describes it incorrectly.

This category is agent-judgment-only (no Phase 1 mechanical equivalent) —
same reason A3/E1/F2/F3 have none: what "the documented steps actually
ran, in order, with the claimed effect" means can't be checked without
executing and watching.

(None of A1/F2/F3/G1 invoke the skill's full workflow against a real
target — they test extracted pieces of it. I1 is "run it for real"; E1 is
"claims made about it elsewhere are accurate" — two different drift
directions. The live-only findings that motivated it: `references/run-history.md`.)

### Phase 2.5: Backfill + contract-check (before oracle gating)

When Phase 2 produces findings (or when reviewing an existing tracker),
run two cleanup passes before Phase 3:

```bash
python3 ~/.claude/skills/audit-skill/scripts/backfill_reproducers.py \
    AUDIT-TRACKERS/<tracker>.findings.yaml
~/.claude/bin/audit-skill-oracle.py contract-check \
    AUDIT-TRACKERS/<tracker>.findings.yaml --strict
```

`backfill_reproducers.py` converts mechanically-detectable patterns
(e.g., "cites `X.md` — file doesn't exist") into auto-checkable
reproducers and demotes the label of remaining manual findings to
`unverified` per the Phase 2 contract. `contract-check` then asserts
the two-way pairing: `type: manual` ⟺ `label: unverified`.

Without the backfill, Layer A's gate is decorative
(`references/run-history.md`).

### Phase 3: Oracle gating (always)

Before any finding becomes a fix task, it must be re-verified by the
audit-skill oracle (Layer A — `reverify`). The oracle takes each
finding's Reproducer and runs it against the live tree. The verdict
gates whether the finding ships to the report:

- **STILL-FIRES**: keep — the Reproducer's deterministic predicate
  evaluated to True against the working tree right now.
- **STALE**: drop — the Reproducer evaluated to False. Either the bug
  was already fixed elsewhere, or the Reproducer is too narrow to
  catch the actual bug class. Either way, do not act on this finding
  without revisiting it.
- **MANUAL**: surface for human review. The Reproducer is type=manual
  (no automated predicate); the oracle has made no verification claim.
- **ERROR**: report as an instrument problem. The Reproducer crashed.
  Do not act; fix the Reproducer.

For `[behavior-fix]` findings specifically, also run **Layer D
(fix_loop)** when a fix is proposed:
- Pre-fix run: Reproducer MUST fire (STILL-FIRES) — confirms the bug
  exists.
- Post-fix run: Reproducer MUST NOT fire (STALE) — confirms the fix
  resolved the predicate.
- VERIFIED → proceed. STALE-PRE or FIX-INEFFECTIVE → re-diagnose.

Each Phase 2 finding therefore must include a machine-checkable
**Reproducer** when at all possible. The Reproducer shape:

```yaml
reproducer:
  type: grep | grep_absent | bash | python | file_exists | file_missing | manual
  command: |
    grep -q 'workspace_name:' skills/<skill>/manifest.yaml
  # OR
  path: skills/<skill>/references/missing-ref.md
  expected_exit: 0    # for bash: the exit code that means "bug is present"
```

Manual descriptions are accepted (type=manual) when no deterministic
predicate is feasible, but findings labeled manual cannot be auto-
verified and must remain `[unverified]` until someone provides one.

Run the oracle:

```bash
~/.claude/bin/audit-skill-oracle.py reverify <findings.yaml> --json
~/.claude/bin/audit-skill-oracle.py verify-fix <findings.yaml> \
    --finding-id <id> --pre-ref <sha> --post-ref <sha>
```

See `references/new-check-checklist.md` for Reproducer authoring
guidance and `_shared/oracle/SPEC.md` for the full verdict semantics + tier
classification per layer. The oracle's calibration set lives at
`tests/golden-findings/calibration/` and runs in CI; TPR/TNR are
reported in SPEC.md §"Calibration results."

### Phase 3.5: Pre-action gate (MANDATORY before any fix-batch)

Any time a workflow turns Phase 2 findings into fix tasks — whether
manual edits or dispatched fix-agents — it MUST first run:

```bash
~/.claude/bin/audit-skill-oracle.py act-on <findings.yaml|tracker.md> \
    --out worklist.yaml
```

This re-runs Layer A reverify against every finding in the source,
drops STALE ones, and emits a worklist containing only findings that
still fire (STILL-FIRES + MANUAL + ERROR). The fix-batch then
dispatches against `worklist.yaml`, not the raw tracker.

**Why this matters.** A static markdown tracker is a snapshot, not live
state: between Phase 2 discovery and Phase 4 action the tree moves, and
parallel fix-batches resolve each other's findings as side-effects (38% of
one campaign's attempted fixes targeted already-resolved findings —
`references/run-history.md`). The oracle is the only authoritative answer to
"does this bug still exist?", and `act-on` is its mandatory invocation point
before every action. Full diagnosis: `_shared/oracle/ROOT-CAUSE-ANALYSIS.md`.

### Phase 4: Report

Bundle Phase 1 + Phase 2/3-survived findings into one numbered report.
The bundling is mechanical — run the oracle's `report` subcommand
against the NDJSON Phase 1 captured by `audit-skill.py --ndjson=` and
the worklist YAML produced by `oracle act-on --out`:

```bash
~/.claude/bin/audit-skill.py --all --ndjson=/tmp/phase1.ndjson > /dev/null
~/.claude/bin/audit-skill-oracle.py act-on AUDIT-TRACKERS/<tracker>.findings.yaml \
    --out /tmp/worklist.yaml
~/.claude/bin/audit-skill-oracle.py report \
    --phase1 /tmp/phase1.ndjson \
    --phase2 /tmp/worklist.yaml \
    --out AUDIT-TRACKERS/<run>-report.md
```

Either input is optional; pass only what you have. `--format json`
emits the same data structured for machine consumers.

Each report row carries:

- **Code**: H1/H2/H4/H5 (hygiene), A1/A3 (contract), B (error path), D1/D2/D4 (alignment), E1 (external-claim drift), F2/F3 (real-data), G1 (deployment), I1 (live execution). Note: Phase 1 also uses `B1` for "scripts ship without tests/" — namespace overlap is intentional; the Phase context disambiguates.
- **Severity**: drift (contract violation) / behavior-bug (something doesn't work) / info (hygiene-only)
- **Location**: `path:line` if known
- **Reproducer**: kind + payload (Phase 2/3 rows only)
- **Oracle verdict**: STILL-FIRES / MANUAL (STALE findings already dropped in Phase 3)
- **Action**: needs-fix / needs-human-judgement / info

Findings with closed triage statuses (FIXED, STALE, FALSE_POSITIVE,
DEFER) are excluded from the report — they're not actionable.

## Skipping vs flagging

If a skill genuinely has no relevant surface for a category (e.g., no error paths because it has no CLI), say so explicitly: `B. Error paths — N/A (no CLI)`. Don't silently skip; the absence of a category-result should be intentional, not accidental.

## Suppression file (`audit-suppress.yaml`)

A skill can suppress known false-positives by adding an `audit-suppress.yaml` file in its directory. Each suppression has a code, an optional target pattern, and a required reason explaining WHY this finding is expected here. Reviewer sees the suppression file in PR review and can challenge the reason.

Schema:

```yaml
suppressions:
  - code: M2
    target: "mcp__[server]__[tool]"
    reason: invoked via references/search-waves.md (not yet detected by M2's reference scan)
  - code: C2
    reason: bash-only workflow; /tmp/ is intentional for POSIX deployments
  - code: M1
    reason: brackets are decorative; manifest required:true is correct because body has no fallback path
  - code: C5
    path: scripts/legacy_*.py
    reason: vendored utility module read in cp1252-default test env; encoding=utf-8 would corrupt tests
  - code: C7
    path: scripts/run.py
    line: 42-50
    reason: hand-rolled --help on the inner sub-parser, AST detector can't see it
```

Fields:
- `code` (required) — the audit-skill code (`M1`, `M2`, `C2`, etc.)
- `target` (optional) — literal match or shell-glob against the finding's target (for M2, the MCP tool name; for D3a, the path)
- `path` (optional) — literal or shell-glob against the finding's file path. Paths normalize to forward slashes, so `path: scripts/run.py` matches both POSIX and Windows-style paths.
- `line` (optional, requires `path`) — single int (`line: 42`) or inclusive range (`line: 40-45`). Without `path` the line is ambiguous (which file?), so it's a schema error to set `line` alone.
- `reason` (required) — short explanation; if omitted, suppression is reviewable but unjustified

Without a `target`, `path`, or `line`, the suppression applies to all findings of that code in this skill. Add discriminators when you want to suppress at one specific call site, not the whole skill.

## Adding a new check

When adding a new check to `~/.claude/bin/audit-skill.py`, read `references/new-check-checklist.md` first. It pins the contract every check must satisfy (severity tier, path+line in Finding, suppression key, fixture trigger, docstring entry, SKILL.md prose mention) and the §0 "verify the existing mechanism first" preamble.

## Discipline-to-implementation mapping

`references/discipline-implementation.md` maps each audit and dev-tooling discipline lesson to its current implementation status (test, code, or doc). Use it as the quarterly hygiene check — untracked lessons signal discipline drifting back to folklore.

## Composition with other tools

- **Before this**: `python3 scripts/build-marketplace.py` (rebuild) if you suspect marketplace drift is the main issue — the audit's own `--check-marketplace` / `--all` pass already verifies freshness
- **After this**: fix the findings; re-run `audit-skill <name>` to confirm green
- **Sibling skills**: `audit-architecture` (cross-skill structure), `audit-rules` (rule consistency), `code-review` (diff-level review). `audit-skill` is specifically about one skill's internal + external contracts.

## Examples

**Example 1 — Auditing a freshly-written skill before merge**
```
User: /audit-skill new-thing
1. Phase 1 mechanical lint:
   - H1 OK (no phantom citations)
   - Q2 FIRES: description 1,210 chars (>1024 Claude Code limit)
   - M1 OK (argument-hint matches manifest)
   - T1 OK (no phantom MCP tool references)
2. Phase 2 agent checks:
   - A1 OK (no hardcoded literal commands)
   - A3 FIRES: Phase 2 invariant "always reads ground-truth file first"
     not tested by any reproducer.
3. Phase 3 oracle gating: 2 STILL-FIRES findings; emit worklist.yaml
   with reproducers ready for /audit-fix.
Result: Worklist with 2 findings; user runs /audit-fix or addresses manually.
```

## Success Criteria

- Mechanical lint ran (Phase 1)
- Every Phase 2 category either ran or was explicitly marked N/A
- Every finding has a file location and a reproducer
- No category was silently skipped
- A user reading the report can act on each finding without re-deriving context

## Completion checklist

- [ ] `~/.claude/bin/audit-skill.py <skill>` ran; output captured
- [ ] A1 literal commands extracted from SKILL.md and executed against deployed path
- [ ] G1 transitive runtime dependency closure expanded from `requires_skills` and checked from the deployed root
- [ ] A3 invariant claims identified and tested
- [ ] B error paths probed (or N/A noted)
- [ ] D1 writer/reader pairs identified and checked
- [ ] D2 state schema cross-checked between producer + consumers
- [ ] D4 references files read alongside the code they describe
- [ ] E1 rules/ + agent-memory/topics/ + knowledge-base/topics/ checked for `/<skill-name>` claims and verified against current behavior
- [ ] F2 threshold branches exercised (or N/A)
- [ ] F3 output variants enumerated (or N/A)
- [ ] I1 skill invoked live (or its documented safe/dry-run mode) against a real target; observed behavior diffed against the documented Procedure (or N/A noted with why no safe invocation exists)
- [ ] All findings reported with location + reproducer
