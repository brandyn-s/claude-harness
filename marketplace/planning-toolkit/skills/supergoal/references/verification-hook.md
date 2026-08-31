# Verification hook — design and operational contract

## Why `type:agent`, not `type:command`

Three Stop-hook types exist:

- `type: prompt` — what built-in `/goal` uses. A small/fast model (Haiku) reads the transcript and decides. **Tool-blind.**
- `type: command` — runs a shell script that returns `{decision, reason}` JSON. Can shell out to tools but can't reason; structured output requires careful prompt engineering of the calling skill.
- `type: agent` — runs a full agent with up to 50 turns of Read/Grep/Glob/Bash access, returns `{ok, reason}`. **Tool-using AND reasoning.**

supergoal uses `type: agent`. The hook runs metric/guard commands using real Bash, evaluates falsifiers against current state, and decides — all with the same primitives the main agent has. No transcript parsing, no command-output regexing.

## Resolution: where the active state lives

The hook reads `~/.claude/supergoal/.active` (single line, absolute path to the active `state.json`). If `.active` doesn't exist OR points to a missing file, the hook returns `{ok: true, reason: "no-active-supergoal"}` immediately — no loop is running, nothing to verify.

State and event log live in a per-plan directory: `~/.claude/supergoal/<slug>/state.json` + `events.jsonl`. The schema is in `plan-parsing.md`. All reads/writes go through `state_io.locked_state()` (fcntl LOCK_EX + atomic rename).

## Hook prompt contract

The hook prompt (canonical version in `SKILL.md` frontmatter) walks an agent through these steps in order:

**Pause gate.** If `state.paused_at` is non-null, return `{ok: false, reason: "paused"}` immediately. `/supergoal-resume` clears the flag.

**Step 0 — `stop_hook_active` gate (CRITICAL).** If the hook fires with `stop_hook_active=true`, return `{ok: true, reason: "stop_hook_active"}` without running checks. anthropics/claude-code#55754 documents this as the #1 hook-design mistake — without it, supergoal compounds a harness-forced continuation into a cascading block-storm.

**Step 1 — plan-tampered (mtime-keyed cache).** `stat plan_path`; compare mtime to `state.plan_mtime`. If unchanged, reuse `state.plan_sha256`. If changed, re-hash. Mismatch → `{ok: true, reason: "plan-tampered"}` (halt; Step 7 records the tamper).

**Step 2 — metric_commands (verify-FIRST).** Bash exec each. Capture exit code (authoritative — 0 = pass, non-zero = regress or scorer crash) and final line matching `^METRIC <name>=<value>` (advisory). If any command exits with a code in `state.scorer_broken_codes` (default `[2, 126, 127, 137]`) → `{ok: true, reason: "scorer-broken: <which>"}` (HALT — verifier itself failed, needs human review).

**Step 3 — guards with skip-on-no-progress.** If no metric improved past `baseline.expected_M`, SKIP `guard_commands` this turn (saves ~50% guard cost on non-improving turns — autoresearch's explicit rule). Append a `progress` event to `events.jsonl` with current metrics. Continue to decision.

If at least one metric improved past `expected_M`, run `guard_commands` with retry-N=3 (exit on first pass — adaptive self-consistency for flaky tests). Any consistent non-zero = guard failure.

**Step 4 — falsifier evaluation.** For each falsifier, evaluate its observation clause (run cited check command, or grep/read as specified). Trigger = halt.

**Step 5 — Decide.**

Define `metric_improved_this_turn` as: at least one metric_command's measured value moved strictly closer to its `expected_M` versus the value recorded on the previous turn (or the baseline, if turn 1). "Demo-achieved" implies improvement; "no metric improved" is the negation.

| Condition | Decision | `consecutive_blocks` | `consecutive_no_progress` |
|-----------|----------|---------------------|--------------------------|
| scorer-broken (in Step 2) | `{ok: true, reason: "scorer-broken: <which>"}` | — (halt) | — (halt) |
| guard failure | `{ok: false, reason: "guard: <which failed>"}` | `+= 1` | unchanged |
| falsifier triggered | `{ok: true, reason: "halt: falsifier <name>"}` | — (halt, Step 7 writes terminal doc) | — (halt) |
| all metrics ≥ `expected_M` (demo-achieved) | `{ok: true, reason: "demo achieved: <values>"}` | reset to 0 | reset to 0 |
| `turn_budget_remaining <= 0` OR `wallclock_used_seconds >= time_budget_seconds` | `{ok: true, reason: "budget-exhausted"}` | — (halt) | — (halt) |
| `consecutive_no_progress >= state.max_stuck` (default 3) | `{ok: true, reason: "stuck-no-progress"}` | — (halt) | — (halt) |
| progress, `metric_improved_this_turn=true` (some metrics still below but moved closer) | `{ok: false, reason: "progress: <which still below>"}` | `+= 1` | reset to 0 |
| progress, `metric_improved_this_turn=false` (no metric moved this turn) | `{ok: false, reason: "progress: <which still below>"}` | `+= 1` | `+= 1` |

Note: `consecutive_blocks` is incremented on every block decision (guard or progress) — its job is to track the harness's 8-block force-stop. `consecutive_no_progress` is distinct: it tracks turns where no metric moved. The two counters fire independently.

**Step 6 — per-turn commit (if `state.git_commits_enabled`).** On block decisions, `git add -A && git commit -m "supergoal turn $TURN: $REASON" --no-verify` — gives a monotonic-improvement floor. If next turn's metric is WORSE than the just-committed baseline, the next invocation runs `git revert HEAD --no-edit` before continuing. Requires clean working tree at supergoal start.

**Step 7 — persist state + event.** Append one line to `events.jsonl`: `{turn, ts, decision, reason, metric_values, guard_results, falsifier_evals, exit_codes}`. Update `state.json` per the counter side-effects in the Step 5 table above (the table is authoritative; this paragraph just lists the other fields touched here): `turn_budget_remaining -= 1`, `wallclock_used_seconds` (real elapsed since `last_verified_at`), `last_verified_at = now`. Re-emit the prior-arc ledger line (≤200 tokens) into the hook's response context so retired hypotheses stay visible even after auto-compaction strips skill content.

## Block-cap handling (two guards, both needed)

Anthropic force-stops Stop hooks after 8 consecutive blocks by default (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP=8`). Longer bounded runs would silently die at turn 8 without intervention.

1. **Budget-derived env override (skill body Step 4):** set `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` to the selected turn budget plus two before invoking `/goal`.
2. **`stop_hook_active` check (Step 0 above):** even with the cap raised, if the harness forces a continuation, the flag is set and the hook must allow-and-exit, not block. anthropics/claude-code#55754.

Both guards are needed. The budget-derived override raises the cap; it doesn't disable the flag or authorize more turns than the selected supergoal budget.

## Why falsifier-triggered returns `ok: true` (allow stop), not `ok: false` (block)

A falsifier is a *halt* signal — the plan's hypothesis has been observationally disproven; continuing the loop into a known-bad state is wasted effort. Allowing `/goal` to stop hands control back to supergoal Step 7, which writes the terminal doc with `re-diagnosis` and `retired hypothesis` sections. Blocking would keep the loop running on a dead hypothesis.

## Why guard failure blocks (not halts)

Guard failures are *fixable* within the loop. Block → next turn the model sees the guard failure and patches. Halting on guard failure would mean every flaky test kills the loop.

The distinction `autoresearch` v2 codified: metrics are progress signals (block until improved); guards are regression signals (block until restored); falsifiers are hypothesis signals (halt — no amount of more turns will fix this).

## Tokens are advisory only

`state.tokens_used_advisory` and `state.token_budget_advisory` are recorded but NOT enforced. Per-turn token usage is not reliably exposed to Claude Code skills (jthack/claude-goal documents this). The authoritative budgets are `turn_budget_remaining` and `wallclock_used_seconds`. The terminal doc captures the advisory total at exit for post-mortem.

## Timeout

Default 120s per hook invocation (set in frontmatter `timeout: 120`). If your `metric_commands` includes a long-running test suite (>2 min), raise this. The hook itself is allotted 50 turns of tool use, so the bottleneck is usually wall-clock for the verification commands, not agent reasoning.

## Failure modes

| What goes wrong | What happens | What to do |
|----------------|--------------|------------|
| Hook times out | `/goal` continues without verification this turn; budget still ticks | Raise `timeout` in frontmatter or reduce `metric_commands` scope |
| `.active` points to a missing state file | Hook returns `{ok: true, reason: "no-active-supergoal"}`; loop exits | Re-run `parse_plan.py` to rebuild state and resume |
| State file corrupt (malformed JSON) | `state_io.locked_state` archives to `state.json.corrupt-<ts>` and raises | Re-run `parse_plan.py --reset` |
| `metric_commands` always fail to parse | Hook returns `progress` every turn; budget exhausts | Fix the commands' output format; re-run |
| Tool budget exhausted inside hook (50-turn limit) | Hook returns whatever partial decision it has; budget ticks | Simplify the verification logic, or raise hook budget |
| Scorer crashes (exit in `scorer_broken_codes`) | Hook halts with `scorer-broken: <which>`; needs human review | Fix the metric command; do not auto-retry |
