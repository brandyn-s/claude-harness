---

name: superplan-status
description: "Report the current state of an active supergoal loop in-conversation (read-only)."
when_to_use: "Report the current state of an active supergoal loop in-conversation. Reads ~/.claude/supergoal/[slug]/state.json and the last 5 entries of events.jsonl; emits a compact summary. Read-only; does not modify state. Pattern from OthmanAdi/planning-with-files /plan-status. Use when checking on an in-flight loop without halting it. Do NOT use for halting the loop (use /supergoal-pause), monitoring on a cadence (use /superplan-loop), or modifying state (the skill is read-only by design)."
argument-hint: "[plan-slug]  (omit for the active loop; e.g., \"2026-05-27-fix-flaky-test\")"
allowed-tools: Bash Read
effort: low
---

## superplan-status

Run (cross-skill helper — the script lives in the `supergoal` skill and is reused here):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/supergoal/scripts/state_io.py --show "${1:-}"
```

(empty arg auto-resolves via `~/.claude/supergoal/.active` pointer or most-recently-modified `*/state.json`.)

Then also tail the last 5 lines of `~/.claude/supergoal/<slug>/events.jsonl` to surface the decision history.

### What `state_io.py --show` emits

The command emits a JSON object with these fields (only these — anything else listed below must be derived by the agent or read from a different file):

- `plan_slug` — slug of the active plan
- `plan_path` — absolute path to the plan file
- `paused_at` — ISO timestamp if paused, else null
- `exit_reason` — terminal exit reason if exited, else null
- `turn_used` — turns consumed (computed as `turn_budget_total - turn_budget_remaining`)
- `turn_total` — total turn budget
- `wallclock_used_seconds` — wallclock seconds consumed
- `consecutive_blocks` — count of consecutive Stop-hook blocks
- `consecutive_no_progress` — stuck-streak count
- `prior_arc_count` — number of prior arcs detected
- `last_verified_at` — ISO timestamp of last verification

Fields NOT emitted by `--show` (the agent must surface them separately if asked):
- Baseline `currently` / `expected` counts → live in plan file frontmatter or per-metric state
- `METRIC CMDS` / `GUARD CMDS` / `FALSIFIERS` / `ARTIFACT PROBE` / `FORBIDDEN ACTIONS` counts → derived from the plan file (parsed once by `parse_plan.py`)
- `max_stuck` threshold → configured in the plan file
- `wallclock_budget` → configured in the plan file
- Lineage / last-entry filename → from `events.jsonl` tail

The agent MUST format the JSON output for the user (compact, ≤200 tokens) — `state_io.py --show` emits raw JSON only, so formatting is the agent's responsibility, not the script's. Use this exact shape:

```
PLAN: <plan_path>
SLUG: <plan_slug>
STATUS: active | paused | exited(<exit_reason>)
TURNS: <turn_used>/<turn_total>  WALLCLOCK: <wallclock_used_seconds>s
CONSEC BLOCKS: <consecutive_blocks>  STUCK STREAK: <consecutive_no_progress>
LAST VERIFIED: <last_verified_at>
PRIOR ARCS: <prior_arc_count>

LAST 5 EVENTS:
  turn=N  decision=<allow|block>  reason="<short>"
  ...
```

If state.json is missing, the helper exits 1 (informative message on stderr, no traceback, no side effects) — `no active supergoal state found in ~/.claude/supergoal` when nothing auto-resolves, or `no state at <path>` when an explicit slug/path has no state file. Treat that exit-1 as the normal no-loop case, not an error, and report "no active supergoal loops in ~/.claude/supergoal/".

If paused, prepend "PAUSED at <paused_at>" and recommend `/supergoal-resume`.

Read-only — do not write to state.json or events.jsonl from this command.

## Example

```
User: /superplan-status
  → state_io.py --show resolves to the active loop (~/.claude/supergoal/.active)
  → Reads state.json + tails events.jsonl
  → Emits:
    PLAN: docs/superpowers/plans/2026-05-27-fix-flaky-test.md
    SLUG: 2026-05-27-fix-flaky-test
    STATUS: active
    TURNS: 12/40  WALLCLOCK: 412s
    CONSEC BLOCKS: 1  STUCK STREAK: 0
    LAST VERIFIED: 2026-05-27T14:30:00Z
    PRIOR ARCS: 0
    LAST 5 EVENTS:
      turn=12  decision=allow  reason="metric pass 7/10"
      ...
Result: User sees in-flight loop state without halting it.
```

```
User: /superplan-status fix-cache-headers
  → state_io.py finds ~/.claude/supergoal/fix-cache-headers/state.json
  → paused_at = 2026-05-27T15:00:00Z (loop is paused)
  → Emits:
    PLAN: docs/superpowers/plans/2026-05-27-fix-cache-headers.md
    SLUG: fix-cache-headers
    PAUSED at 2026-05-27T15:00:00Z
    STATUS: paused
    TURNS: 7/30  WALLCLOCK: 245s
    LAST 5 EVENTS: ...
Result: Use /supergoal-resume to continue, or edit the plan first.
```

## Examples

**Example 1:** `superplan-status` — reads `~/.claude/supergoal/<slug>/state.json` + the last 5 `events.jsonl` entries and prints a compact summary (turn count, stall streak, budget %).
**Example 2:** Mid-run, check an in-flight supergoal's progress without halting the loop.

## Success Criteria

- Emits the current turn / stall-streak / budget summary from `state.json` **without modifying state**.
- Handles the no-loop case: when no active loop exists the helper exits 1 with `no active supergoal state found in ~/.claude/supergoal` (or `no state at <path>`); the agent translates that into a "no active supergoal" report instead of surfacing an error.
