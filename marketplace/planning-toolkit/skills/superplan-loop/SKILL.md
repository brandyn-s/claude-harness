---

name: superplan-loop
description: "Re-check supergoal progress on a cadence and surface concerning signals (read-only)."
when_to_use: "Compose with native Claude Code /loop to re-check supergoal progress on a cadence. Re-runs /superplan-status every N minutes (default 10) and surfaces any concerning signals (stall streak rising, prior-arc count at 3 or more, wallclock budget over 70% spent). Read-only nudge layer; does not modify state. Pattern from OthmanAdi/planning-with-files /plan-loop. Use when monitoring an in-flight supergoal run from a separate terminal. Do NOT use for one-shot status checks (use /superplan-status), driving the loop itself (use /supergoal), or interactive editing (use /supergoal-pause then edit)."
argument-hint: "[interval (default 10m)] [plan-slug]"
allowed-tools: Bash Read
effort: low
---

## superplan-loop

Compose with the native `/loop` primitive instead of duplicating its scheduler:

```
/loop $0 /superplan-status $1
```

Where `$0` is the interval (default 10m) and `$1` is the optional plan-slug.

The skill itself does NOT install a scheduler. It instructs you to invoke `/loop` with `/superplan-status` as the recurring command. This is the pwf composition pattern (their `/plan-loop` wraps native `/loop` rather than building a separate cadence engine).

After the wrapper runs, also emit one-time advisory checks:
- If `prior_arc_count >= 3` → suggest user review the lineage chain before continuing
- If `wallclock_used_seconds / time_budget_seconds > 0.7` → suggest user inspect progress; consider `/supergoal-pause` and amend
- If `consecutive_no_progress >= max_stuck - 1` (streak at N-1, halt pending on next no-progress turn) → flag explicitly

These advisories surface in the conversation each loop tick alongside the status block, so the user has a chance to intervene before the hook auto-halts.

To stop the recurring status checks: cancel the cron job via `CronDelete` with the job ID from `CronList` (or ask Claude to cancel the loop).

## Example

```
User: /superplan-loop 5m
  → /loop schedules /superplan-status on a 5-minute cadence
  → Each tick: read state.json, emit STATUS block + advisories
  → Advisory fires when consecutive_no_progress >= max_stuck - 1
Result: Recurring status updates; cancel via CronDelete with the job ID from CronList.
```

## Examples

**Example 1:** `superplan-loop` (composed with `/loop`) — re-runs `/superplan-status` every N minutes (default 10) and surfaces stall/budget signals.
**Example 2:** Monitor an in-flight supergoal run from a separate terminal without driving it.

## Success Criteria

- Read-only: never modifies loop state.
- Surfaces concerning signals (stall streak rising, prior-arc ≥ 3, wallclock > 70%) without halting the loop.
