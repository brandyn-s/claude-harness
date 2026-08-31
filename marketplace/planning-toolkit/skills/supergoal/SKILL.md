---

name: supergoal
description: "Drive a superplan plan-file to completion autonomously with tool-backed verification."
when_to_use: "Use when a superplan plan-file should be driven to completion autonomously. Wraps Claude Code's built-in /goal with plan-aware termination (derives condition from Demo line + falsifiers), tool-backed per-turn verification (a `type:agent` Stop hook runs metric_commands and guard_commands using real Bash + checks falsifiers, returning {ok, reason} — bypasses /goal's conversation-only evaluator), prior-arc check (refuses re-litigation by default), turn AND token budget enforcement, block-cap-aware loop control (handles Anthropic's 8-consecutive-block Stop-hook limit), and terminal-doc-on-exit. Supports headless mode (`claude -p \"/supergoal [plan]\"`). Pairs with superplan. Do NOT use for interactive feature work (let the user drive turn-by-turn), one-shot scripts without a plan file (just use /goal directly), or plans that lack a Demo line + falsifiers (write /superplan first)."
argument-hint: "[plan-file-path] [--force-rerun] [--budget-turns=N] [--budget-tokens=M] [--headless]"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Bash mcp__memory-search__memory_search AskUserQuestion Read Write
hooks:
  Stop:
    - hooks:
        - type: agent
          prompt: |
            You are supergoal's per-turn verification hook. Read the active state file path from ~/.claude/supergoal/.active (single line, absolute path). If .active doesn't exist OR points to a missing file, return {ok: true, reason: "no-active-supergoal"} immediately (no loop is running). Acquire fcntl LOCK_EX before read; atomic-rename after write. Schema in references/plan-parsing.md.

            CHECK PAUSE GATE: if state.paused_at is non-null, return {ok: false, reason: "paused"} without running any checks. /supergoal-resume clears the flag.

            STEP 0 — stop_hook_active gate (CRITICAL):
              If `stop_hook_active` is true on this hook invocation, return {ok: true, reason: "stop_hook_active"} immediately. Do not run checks. anthropics/claude-code#55754 documents this as the #1 hook-design mistake — without this gate, supergoal compounds a harness-forced continuation into a cascading block-storm.

            STEP 1 — plan-tampered check (mtime-keyed cache):
              stat plan_path; compare mtime against state.plan_mtime. If unchanged → reuse state.plan_sha256. If changed → re-hash, compare to state.plan_sha256. Mismatch → {ok: true, reason: "plan-tampered"}.

            STEP 2 — Run metric_commands FIRST (verify-before-guard).
              For each entry, Bash exec. Parse final line matching `^METRIC [name]=[value]` (advisory) and exit code (authoritative — exit 0 = pass, non-zero = regress or scorer crashed). If ANY metric_command exits with code matching state.scorer_broken_codes (default: 2, 126, 127, 137) → {ok: true, reason: "scorer-broken: [which]"} (HALT — verifier itself failed, needs human review).

            STEP 3 — Guard skip-on-no-progress.
              If no metric improved past baseline.expected_M, SKIP guard_commands this turn (saves ~50% guard cost on non-improving turns — autoresearch's rule). Append a `progress` event to events.jsonl with current metrics. Continue to decision.
              If at least one metric improved past expected_M, run guard_commands. Wrap each guard in retry-on-fail (N=3, exit on first pass — adaptive self-consistency for flaky tests). Any consistent non-zero = guard failure.

            STEP 4 — Falsifier evaluation.
              For each falsifier, evaluate its observation clause (run cited check command, or grep/read as specified). Trigger = halt.

            STEP 5 — Decide. Define metric_improved_this_turn := at least one metric_command's measured value moved strictly closer to its expected_M versus the value recorded on the previous turn (or baseline on turn 1).
              - scorer-broken → {ok: true, reason: "scorer-broken: [which]"} (handled in step 2, halt — no counter changes)
              - guard failure → {ok: false, reason: "guard: [which failed]"} — consecutive_blocks += 1; consecutive_no_progress unchanged
              - falsifier triggered → {ok: true, reason: "halt: falsifier [name]"} — halt; supergoal Step 7 writes terminal doc
              - all metrics at or above expected_M (demo-achieved) → {ok: true, reason: "demo achieved: [values]"} — reset BOTH consecutive_blocks AND consecutive_no_progress to 0
              - turn_budget_remaining at 0 or below OR wallclock_used_seconds at or above time_budget_seconds → {ok: true, reason: "budget-exhausted"} (halt)
              - consecutive_no_progress at or above state.max_stuck (default 3) → {ok: true, reason: "stuck-no-progress"} (halt — agent is looping without advancing)
              - progress AND metric_improved_this_turn → {ok: false, reason: "progress: [which metrics still below]"} — consecutive_blocks += 1; reset consecutive_no_progress to 0
              - progress AND NOT metric_improved_this_turn → {ok: false, reason: "progress: [which metrics still below]"} — consecutive_blocks += 1 AND consecutive_no_progress += 1

            STEP 6 — Per-turn commit (if state.git_commits_enabled).
              On block decisions (progress/guard), `git add -A && git commit -m "supergoal turn $TURN: $REASON" --no-verify` — gives monotonic-improvement floor. If next turn's metric is WORSE than just-committed baseline, the next invocation runs `git revert HEAD --no-edit` before continuing. Requires clean working tree at supergoal start (verified by Step 4 of skill body).

            STEP 7 — Persist state + event.
              Append one line to events.jsonl: {turn, ts, decision, reason, metric_values, guard_results, falsifier_evals, exit_codes}. Update state.json per the counter side-effects in STEP 5 above (authoritative). Also update: turn_budget_remaining-=1, wallclock_used_seconds (real elapsed since last_verified_at), last_verified_at=now. Re-emit prior-arc ledger line into the hook's response context (≤200 tokens) so the next turn sees retired hypotheses even after auto-compaction strips skill content.

            Note on tokens: per-turn token usage is NOT reliably exposed to Claude Code skills (per jthack/claude-goal's documented limitation). state.token_budget_advisory is a SOFT advisory only; the authoritative budget gates are turn_budget_remaining + wallclock_used_seconds.

            Note on stop_hook_active reset semantics: supergoal also honors $CLAUDE_CODE_STOP_HOOK_BLOCK_CAP. The skill body Step 4 derives this cap from the selected turn budget before /goal invocation so we don't fight Anthropic's 8-block default or permit a hidden unbounded loop. The hook STILL must check stop_hook_active for correctness — env override raises the cap, doesn't disable the flag.
          timeout: 120
---
> **Compaction continuity:** Claude Code reattaches only the first 5,000
> tokens of an invoked skill after compaction, within a 25,000-token shared
> newest-first budget. If compaction occurs, re-invoke this skill before
> continuing; if model invocation is disabled, stop and ask the user to invoke
> it. Do not rely on tail instructions until the full body is restored.


## supergoal

# Supergoal — Plan-aware autonomous execution loop

Built-in `/goal` keeps Claude running across turns until a condition holds, but per Anthropic's official docs ([code.claude.com/docs/en/goal](https://code.claude.com/docs/en/goal)): "the evaluator does not call tools, so it can only judge what Claude has already surfaced in the conversation." This is the limitation supergoal addresses — a `type:agent` Stop hook that runs real verification with real tools, so the gate is deterministic evidence rather than transcript inference.

**Mental model**: superplan produces a plan with a `Demo:` line, a `## Falsifiers` section, and a Phase 3.5 baseline. supergoal turns that artifact into a measurably verifiable end-state, runs tool-backed checks between turns (via a `type:agent` hook — Anthropic's native primitive, not transcript-injection), and stops the loop cleanly — success, falsifier-triggered, or budget-exhausted — and writes a terminal doc explaining why.

## Key design choices (with rationale)

1. **`type:agent` Stop hook, not `type:command`.** Anthropic ships agent hooks with 50 turns of tool access. Running verification *inside* the hook with real Bash + Read is strictly cleaner than running a script and parsing its stdout, or injecting a `SUPERGOAL_CHECK:` block into the transcript for `/goal`'s Haiku evaluator to read. We use the native primitive. **No other Claude Code skill in the field does this** (surveyed 18 implementations).
2. **Block-cap-aware (budget-derived override + stop_hook_active).** Anthropic force-stops Stop hooks after 8 consecutive blocks (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP=8`). Step 4 derives the cap from the selected turn budget before invoking `/goal`. The hook ALSO honors the `stop_hook_active` flag — anthropics/claude-code#55754 documents the missing-stop-hook-active-check as the #1 hook-design mistake. Both guards needed.
3. **Verify / Guard split, verify-first ordering.** `metric_commands` (must improve past baseline) and `guard_commands` (existing tests must still pass) are separate fields. Verify runs first; guards SKIP if no metric improved that turn (saves ~50% guard cost on non-improving turns — `autoresearch`'s explicit rule).
4. **Append-only event log + atomic state file.** `~/.claude/supergoal/<slug>/events.jsonl` (append-only history) + `~/.claude/supergoal/<slug>/state.json` (atomic snapshot) — both maintained in the plan-specific state directory (NOT `/tmp` — other procs can wipe it; claude-code#28923 documents single-file state-corruption with 369 backup files/day from concurrent writes). Atomic write-temp+rename, fcntl LOCK_EX on every read+write cycle.
5. **Headless mode is a first-class path.** `claude -p "/supergoal <plan>"` is the production invocation per Anthropic's `/goal` docs. Interactive mode is for development.
6. **Mechanical re-load of prior-arc ledger each turn.** Per Anthropic skill docs ([code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)): "Claude Code does not re-read the skill file on later turns" — and after auto-compaction only the first 5k tokens survive. Our prior-arc check could silently evaporate mid-loop. The hook re-emits a ≤200-token ledger line into its decision context every turn, so retired hypotheses stay visible regardless of context compaction.
7. **Soft token budget, honest about it.** Per-turn token usage is NOT reliably exposed to Claude Code skills (jthack/claude-goal documents this). `--budget-tokens` is advisory only; the authoritative budgets are `--budget-turns` and `--budget-wallclock`.
8. **Goodhart probe at exit.** Verification per turn measures the metric; at exit, a separate `artifact_probe[]` set observes the artifact (different surface area). Catches metric-gaming. Source: mpt.solutions Goodhart's-Law post documenting `/goal` shipping a 960×540 space shooter with 3 starfield pixels because conversation-eval passed.

## When to use

- Executing a superplan-produced plan file (typical case)
- Driving an autonomous loop where success is **measurable by running a command**
- Tasks where a guaranteed turn+token budget exit is required

## When NOT to use

- Free-text goal conditions with no measurable verification — use plain `/goal`
- Trivial tasks (XS effort) — just do them; don't pay the wrapper overhead
- When no plan file exists — invoke superplan first
- **Any plan with an in-loop human gate** — an AskUserQuestion decision, an operator-run
  apply/login, or a classifier-gated operation. The Stop-hook evaluator cannot answer a
  question or refresh the operator's SSO; the loop stalls at the first gate. Execute
  directly and keep the metric/falsifier discipline inline. (Measured 2026-08-23: a
  close-out program hit four such moments in one run.)
- **Checklist-shaped programs** — N heterogeneous close-outs whose "progress" is items done,
  not a climbing metric. Supergoal verifies gradients, not checklists.
- **The user is present and interactive** — the loop's value is unattended verification;
  inline execution with the plan's Metric Commands as the completion gate gives the same
  rigor without the wrapper.

## Procedure

### Step 1: Parse plan + write state.json + events.jsonl

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/supergoal/scripts/parse_plan.py "$0" --state-dir ~/.claude/supergoal/
```

Resolves the per-plan state directory as `~/.claude/supergoal/<plan-slug>/`, then writes:
- `state.json` — snapshot (current state of the loop)
- `events.jsonl` — append-only event log (one line per turn, never rewritten)
- Initial event entry: `{turn: 0, ts, event: "started", plan_sha256, baseline}`

Extracts from the plan markdown:
- `demo`: the `Demo:` line (success criterion)
- `falsifiers[]`: each falsifier observation + re-diagnosis action
- `metric_commands[]`: commands that must improve past baseline (cited in plan's `### Metric Commands` or `Verification:` section)
- `guard_commands[]`: commands that must continue to pass (cited in `### Guard Commands` — separate from falsifiers)
- `artifact_probe[]`: commands that observe the artifact (NOT the metric) — run only at exit as Goodhart probe (cited in `### Artifact Probe`)
- `forbidden_actions[]`: tool-call patterns the agent must NOT take (cited in `### Forbidden Actions` — Devin-playbook convention)
- `baseline`: Phase 3.5 baseline (`currently_N`, `expected_M`)
- `effort`: XS/S/M/L/XL → drives default budgets
- `metric_names[]`: named metrics for prior-arc lookup
- `plan_mtime`, `plan_sha256` — for mtime-keyed attestation cache
- Defaults: `consecutive_blocks: 0`, `consecutive_no_progress: 0`, `turn_budget_remaining: <derived>`, `time_budget_seconds: <derived>`, `wallclock_used_seconds: 0`, `max_stuck: 3`, `scorer_broken_codes: [2, 126, 127, 137]`, `git_commits_enabled: false` (opt-in via `--per-turn-commit`)

If `demo`, `falsifiers`, or `metric_commands` is empty/missing, fail loudly: tell the user the plan isn't supergoal-ready and recommend re-running superplan to add what's missing. Do not synthesize defaults.

`artifact_probe[]` empty → warn (Goodhart probe disabled — metric-gaming undetectable). `forbidden_actions[]` empty → warn (policy axis disabled).

**Same-surface probe warning (the Goodhart probe must differ from the metric in SURFACE, not just in file).** The artifact_probe defends against metric-gaming ONLY if it observes a DIFFERENT surface than `metric_commands`. If BOTH the metric and the probe only test artifact PRESENCE (`[ -f X ]`, `grep -q symbol`, `test -d`, line-count `> N`) — even on different files — the probe adds zero protection: a stub that satisfies the metric satisfies the probe too. Before invoking `/goal`, inspect the two sets: if EVERY metric_command AND EVERY artifact_probe command is a presence/count check and NONE exercises a real run (executes the artifact, asserts on output only the real path produces, or crosses a deploy seam), WARN explicitly: "metric + probe test the same surface (existence); Goodhart protection is nominal — neither verifies the artifact WORKS or DEPLOYS." For a BUILD-phase plan whose artifact is a deployed component, this warning means the plan will green with the artifact undeployed (2026-06-26 detector-expansion: `phases_complete=7` on file-existence while judge_hardening.py was absent from the Lambda image; the artifact_probe only checked catalog row-count — same presence surface — so it caught nothing). The durable fix is upstream in /superplan's `[deploy-seam]` check (author a metric that crosses the real sink); this warning is the downstream backstop.

**Non-executable (pseudocode) metric_commands** (lesson 2026-06-15): a plan can pass this readiness check (demo + falsifiers + ≥1 metric_command present) while its metric_commands are PSEUDOCODE — e.g. `METRIC gold_scan_ratio=<view_bytes / gold_bytes>`, or commands referencing scripts/files that don't exist yet. Those scorer-break the `/goal` loop every turn (the `<...>` tokens / missing files exit non-zero → `scorer-broken` halt). Before Step 6, scan metric_commands for `<…>` placeholders or unresolved file refs; if any are non-executable, **do NOT invoke `/goal`** — execute the plan manually phase-by-phase, and at the END write `exit_reason` + measured `metric_values` to `state.json` (else the `type:agent` Stop hook blocks every Stop with "plan never invoked through supergoal metric loop"). The upstream fix belongs in /superplan: author metric_commands that run as-is and print `METRIC name=<number>`.

See `references/plan-parsing.md` for the field schema and failure modes.

### Step 2: Prior-arc check (always-inject; hard-stop only at 3+ failed arcs)

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/supergoal/scripts/check_prior_arcs.py ~/.claude/supergoal/<slug>/state.json
```

Globs `~/Documents/knowledge-base/plans/*-terminal.md` and greps for the plan's metric names. New semantics (revised from "refuse-by-default" per academic research on Reflexion's empirical lift):

- **Always inject the prior-arc ledger into context**, even on first-attempt. Hook re-emits it each turn (per Key Design Choice #6).
- **Soft warn** if 1-2 prior arcs exist: emit ledger; proceed.
- **Hard refuse** only if 3+ prior arcs against the same metric have all failed. Override with `--force-rerun` requires explicit user opt-in. This is the structural-ceiling signal (Phase 3.6 field 3 of superplan); past 3 attempts the plan must demonstrate max-recoverable-lift before continuing.

Skip silently if `~/Documents/knowledge-base/plans/` does not exist (substrate absent).

Also retrieves matching `~/Documents/knowledge-base/plan-patterns/*.md` templates via memory-search if any have been written — top-k=3 patterns similar to this plan's purpose. Patterns surface as scaffolding suggestions (not mandatory). See `references/plan-pattern-library.md` for the design spec; **the write side (terminal-doc pattern extraction on `exit_reason == "success"`) is not yet implemented in `write_terminal.py`**, so the corpus stays empty until that's built. The retrieval side here is safe to run today — with no patterns persisted, it just returns zero hits.

See `references/prior-arc-check.md`.

### Step 3: Compute budget (turn + wallclock authoritative; token advisory)

Defaults from effort estimate (overridable via `--budget-turns=N`, `--budget-wallclock=Ss`, advisory `--budget-tokens=M`):

> **Frontmatter `size:` is NOT parsed.** `parse_plan.py` extracts effort only from an
> `Effort: XS|S|M|L|XL` line in the body; a superplan that declares `size: L` in YAML
> frontmatter silently defaults to M (40 turns/2h). Measured 2026-08-23 (zero-ceremony plan:
> `size: L` → effort M). Until parse_plan reads frontmatter, check the plan's declared size and
> pass explicit `--budget-*` overrides when it differs from the parsed effort.

| Effort | Turns | Wallclock | Tokens (advisory) |
|--------|-------|-----------|-------------------|
| XS | 5 | 300s | 50k |
| S | 15 | 1800s (30m) | 200k |
| M | 20 | 3600s (1h) | 400k |
| L | 40 | 7200s (2h) | 800k |
| XL | 80 | 14400s (4h) | 2M |

XL requires explicit user opt-in by passing both `--budget-turns` and
`--budget-wallclock`; the effort label alone is not authorization for an XL loop.

**Authoritative**: `turn_budget_remaining` + `wallclock_used_seconds`. First to hit → `budget-exhausted`.

**Advisory**: `token_budget_advisory` is recorded but not enforced — Claude Code skills don't expose per-turn token usage reliably (Key Design Choice #7). Terminal doc captures it at exit for post-mortem.

Stored in `~/.claude/supergoal/<slug>/state.json`. See `references/budget.md`.

### Step 4: Env-export for block-cap override

```bash
turn_budget=<selected turn budget from Step 3>
block_cap=$((turn_budget + 2))
export CLAUDE_CODE_STOP_HOOK_BLOCK_CAP="$block_cap"
```

(SHA-256 attestation was already written by `parse_plan.py` at Step 1 to `~/.claude/supergoal/<slug>/plan.sha256` AND the sibling `<plan>.md.attestation`.)

The env-export raises Anthropic's 8-consecutive-block force-stop only enough to fit the selected turn budget. The hook ALSO checks `stop_hook_active` independently for correctness (env override raises the cap; it doesn't disable the flag — both guards needed). Mid-loop tamper is detected by the hook's mtime-keyed re-hash; mismatch triggers `{ok: true, reason: "plan-tampered"}` and Step 7's terminal-doc.

### Step 5: Confirm with user (interactive mode only)

Show parsed state (demo, metric_commands count, guard_commands count, falsifier count, artifact_probe count, forbidden_actions count, prior arcs, budget) and ask go/no-go via `AskUserQuestion`. **Skip this step in headless mode** (`--headless` or invoked via `claude -p`).

### Step 6: Invoke /goal

**`/goal` is a UI/headless command — the AGENT cannot invoke it programmatically** (the skill-invocation path rejects it: "goal is a UI command, not a skill"). So Step 6 is NOT an agent action like Steps 1-5. Either: the USER types the `/goal` line below (interactive), OR the run is launched headless as `claude -p "/supergoal <plan>"` (the production path). The agent completes Steps 1-5 (parse, prior-arc, budget, env-export, confirm), then EMITS this command for the user / headless wrapper and hands off. Note the `type:agent` Stop hook is already installed by this skill's frontmatter, so the verification loop runs regardless of HOW the loop was started — if the agent simply continues working toward the demo, the hook gates each Stop on the metric exactly as `/goal` would. (2026-06-21: agent attempted to invoke `/goal` programmatically mid-conversation and was refused; the loop still ran because the hook enforces it.)

```
/goal <demo-line>, verified by metric_commands per ~/.claude/supergoal/<slug>/state.json,
      or stop after <N> turns or <wallclock>s
```

The Stop hook (in this skill's frontmatter, `type:agent`) fires after every turn. Its decision tree, in order (see hook prompt for the canonical sequence):

1. **`stop_hook_active` gate** — exit immediately if the harness force-continued (anthropics/claude-code#55754)
2. **Plan-tampered check** — mtime-keyed SHA-256 re-hash; halt on mismatch
3. **metric_commands** (verify-FIRST) — Bash exec each; scorer-broken codes [2,126,127,137] → halt-needs-human
4. **Guard skip-on-no-progress** — if no metric improved past `expected_M`, SKIP guard_commands (saves ~50% guard cost). Otherwise run guards with retry-N=3 (adaptive self-consistency for flaky tests)
5. **Falsifier evaluation** — each falsifier's observation clause against current state; trigger = halt
6. **Decide**: scorer-broken→halt | guard-fail→block | falsifier→halt | demo-achieved→halt-success | budget-exhausted→halt | stuck-no-progress (consecutive_no_progress ≥ max_stuck)→halt | progress→block
7. **Per-turn commit** (if `--per-turn-commit`): `git commit -am "supergoal turn $TURN: $REASON" --no-verify` on block decisions; `git revert HEAD --no-edit` on metric-regress detected next turn
8. **Persist state + event** — atomic+locked write to `state.json`; append one line to `events.jsonl`

Because the hook is `type:agent`, all of this runs **with real tools** — no transcript parsing, no Haiku-evaluator-on-conversation-text fragility.

See `references/verification-hook.md` for the hook's internal contract.

### Step 7: Terminal doc on exit

When the goal clears (any allow reason from the hook), run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/supergoal/scripts/write_terminal.py ~/.claude/supergoal/<slug>/state.json <exit-reason>
```

Writes `~/Documents/knowledge-base/plans/<slug>-terminal.md` (sibling of the plan file, with optional date prefix if the plan filename has one) via the same git+PR flow superplan Step 5a uses. Sections:

- **Exit reason**: `success` | `falsifier-<name>-triggered` | `budget-exhausted` | `plan-tampered` | `scorer-broken` | `stuck-no-progress`
- **Per-phase freshness verdict**: which baselines were still valid at exit (re-measured by the hook just before)
- **Re-diagnosis**: if a falsifier triggered, what the new observation means
- **Retired hypothesis**: what mechanism the plan proposed that didn't move the metric
- **Named next-plan target**: what a successor plan would have to investigate
- **`lineage:`**: chain of prior arcs (from Step 2 check) — visible to next session's superplan Phase 2d

Skip silently if `~/Documents/knowledge-base/plans/` does not exist; exit reason still surfaced in conversation.

Two measured Step 7 gaps (2026-08-23, zero-ceremony run):

- **Inline execution produces a SKELETAL terminal doc.** When the loop ran as the agent working
  directly (hook-gated Stops, `/goal` never invoked), `events.jsonl` has no per-turn rows, so the
  generated doc reads `Turns: 0/N`, `Wallclock: 0s`, and an empty freshness section. The doc IS
  written and `exit_reason` IS stamped — but before shipping it, ENRICH it with the measured
  facts from the conversation (final metric values, per-phase evidence, Goodhart-probe results).
  A skeletal terminal doc poisons the next session's prior-arc read.
- **The git+PR step aborts on a contended KB checkout.** `write_terminal.py` switches branches in
  the main `~/Documents/knowledge-base` checkout; untracked twins from other sessions make git
  refuse ("would be overwritten by checkout") AFTER the doc and state stamp are written. Recovery:
  do not reconcile the contended checkout mid-run — copy the plan, its `.attestation`, and the
  terminal doc into a fresh `git worktree` cut from `origin/main` and run the branch/PR flow there.

See `references/terminal-doc.md` for the section schema.

## Headless mode

For long autonomous runs, invoke supergoal via `claude -p` (non-interactive):

```bash
claude -p "/supergoal ~/Documents/knowledge-base/plans/2026-05-24-fix-extractor.md --budget-turns=100 --budget-tokens=2M"
```

In headless mode:
- Step 5 (user confirmation) is skipped — invocation implies consent
- `--force-rerun` must be set explicitly if 3+ prior arcs exist; otherwise supergoal exits 21 with the ledger. 1-2 prior arcs emit a soft-warn ledger and proceed (exit 0).
- The terminal doc is still written; the headless process exits with the exit reason as its last stdout line

This is the production invocation. Interactive mode is for development / first runs.

See `references/headless.md` for invocation patterns and exit-code semantics.

## Composition with superplan

```
1. /superplan "<task>"
   → produces plan + Demo + falsifiers + metric_commands + guard_commands + Phase 3.5 baseline
   → persisted to ~/Documents/knowledge-base/plans/<slug>.md
   → SHA-256 attestation written

2. claude -p "/supergoal ~/Documents/knowledge-base/plans/<slug>.md"
   → parses plan → status.json → prior-arc check → budget → /goal loop
   → type:agent Stop hook runs metric+guard+falsifier each turn
   → writes <slug>-terminal.md on exit

3. Next session: /superplan picks up <slug>-terminal.md in Phase 2d's
   prior-arc ledger; new plan must position against the prior mechanism +
   measured outcome (terminal doc's lineage: chain visible).
```

## Substrate detection

supergoal inherits superplan's substrate-aware behavior:

- `~/Documents/knowledge-base/plans/` missing → Step 2 (prior-arc) and Step 7 (terminal doc) silently skip
- `mcp__memory-search__memory_search` unavailable → Step 2 falls back to filesystem glob only
- Plan missing required sections (demo, falsifiers, metric_commands) → Step 1 errors and asks the user to re-run superplan

The verification hook (Step 6) always runs — it depends only on Bash + the plan's own cited commands.

## Examples

**Example 1 — Driving a single-Demo plan to completion**
```
User: /supergoal docs/superpowers/plans/2026-05-27-fix-flaky-test.md
1. Step 0: Parse plan. Demo line: "tests pass 10/10 consecutive runs".
   Falsifier: "any single failure resets the counter".
2. Step 1: Set up state.json with metric_command + guard_command +
   wallclock budget (3600s) + turn budget (20).
3. Step 2: Begin loop. Each turn:
   - Stop hook runs metric_command, increments counter on pass.
   - Guard_command checks no new flakes introduced elsewhere.
4. Step 6: After 10 consecutive passes, exit_reason=success.
Result: Plan demo verified; state.json shows exit_reason=success,
turn_used=12, wallclock_used_seconds=412. /superplan-status confirms.
```

**Example 2 — Loop pauses for plan amendment, then resumes**
```
User: /supergoal docs/superpowers/plans/2026-05-27-cache-headers.md
... (12 turns in) ...
User: /supergoal-pause
  → state.json gets paused_at=2026-05-27T14:32:00Z
User edits plan to add a new falsifier ("CDN edge cache rule reapplied").
User: /supergoal-resume
  → SHA-256 check: plan hash changed; loop refuses to resume with
    "Plan was modified during pause. Re-run /supergoal to start a new arc."
Result: Lineage preserved (events.jsonl unchanged); user starts a fresh
loop on the revised plan.
```

## Success Criteria

- Plan parsed; status.json has demo + falsifiers + metric_commands + guard_commands
- Prior arcs checked; user explicitly OK'd `--force-rerun` if any prior arc exists
- Budget set (turn + token), displayed, and enforced
- Plan attested via SHA-256
- `type:agent` verification hook installed (in this skill's frontmatter)
- Block-cap prophylactic prevents the 8-consecutive-block force-stop
- /goal exits cleanly via demo-achieved / falsifier / budget-exhausted / plan-tampered
- Terminal doc written and committed (if substrate present)
- Headless mode supported; exit code maps to exit reason

## Completion checklist

- [ ] `parse_plan.py` produced status.json with all required fields
- [ ] Prior-arc check ran; ledger displayed if any prior arc exists
- [ ] Budget (turn + token) computed and stored
- [ ] SHA-256 attestation file written
- [ ] User confirmed (or `--headless` was set)
- [ ] /goal invoked with derived condition
- [ ] `type:agent` Stop hook installed (visible in this skill's frontmatter)
- [ ] Block-cap prophylactic verified. `consecutive_blocks` is reset to 0 only on the demo-achieved decision (all metrics >= expected_M) per the Step 5 decision table — on every progress and guard-failure decision it increments. The prophylactic against Anthropic's 8-block force-stop is the budget-derived `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` from skill body Step 4, NOT a per-turn counter reset. Verify the env-export was performed before /goal was invoked. (See `references/verification-hook.md` Step 5 for the authoritative counter side-effects table; `consecutive_no_progress` is separate and resets on metric-improvement, not `consecutive_blocks`.)
- [ ] On exit, terminal doc written + committed (or skipped with reason if no substrate)
- [ ] Exit reason surfaced in conversation; headless exit code matches
