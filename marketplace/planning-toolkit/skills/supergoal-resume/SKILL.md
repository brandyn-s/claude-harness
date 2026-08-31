---

name: supergoal-resume
description: "Resume a paused supergoal loop after verifying the plan is untampered."
when_to_use: Resume a paused supergoal loop. Verifies the plan SHA-256 still matches (refuses if tampered while paused), clears `paused_at` in the state file, and emits a `resumed` event. Pattern from jthack/claude-goal. Use when continuing a /supergoal-pause-d loop. Do NOT use for starting a fresh loop (use /supergoal), or for re-running a completed loop (use /supergoal with --force-rerun).
argument-hint: "[plan-slug]  (omit to resume the current session's paused loop; e.g., \"2026-05-27-fix-flaky-test\")"
allowed-tools: Bash
effort: low
---

## supergoal-resume

Run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/supergoal/scripts/state_io.py --resume "${1:-}"
```

The CLI:
1. Re-hashes the plan file; refuses if `plan_sha256` mismatched (returns non-zero exit). To recover: re-run `/superplan` to update + re-attest, then re-invoke `/supergoal`. Auto-resume into a different plan is intentionally blocked.
2. If hash matches: atomically clears `paused_at`, emits `{turn, ts, event: "resumed"}`, prints `RESUMED <slug> at turn N (M turns remaining)`.
3. Idempotent on a non-paused state (prints "not paused; nothing to do").

Then run `state_io.py --show "${1:-}"` (the command prints a JSON projection to stdout with fields: `plan_slug`, `plan_path`, `paused_at`, `exit_reason`, `turn_used`, `turn_total`, `wallclock_used_seconds`, `consecutive_blocks`, `consecutive_no_progress`, `prior_arc_count`, `last_verified_at`). Parse the JSON and report a human-readable summary: plan slug, turns used/remaining, wallclock used, consecutive_blocks/no_progress, last_verified_at. The user sees where the loop is restarting from.

Budget continues from where it was paused — wallclock_used_seconds did not advance during pause; the turn budget remaining (turn_total minus turn_used) is unchanged.

## Example

```
User: /supergoal-resume
  → SHA-256 check passes (plan unchanged since pause)
  → state.json updated: paused_at=null, resumed event emitted
  → state_io.py --show: plan_slug=fix-flaky, turn_used=12/40, wallclock=412s
Result: Loop resumed; next Stop will run metric_command + guard_command.
```

## Examples

**Example 1:** `supergoal resume` — verifies the plan SHA-256 still matches, clears `paused_at`, and emits a `resumed` event.
**Example 2:** Resume a loop paused earlier in the session to continue from the prior arc state.

## Success Criteria

- Refuses to resume if the plan file was tampered with while paused (SHA-256 mismatch).
- Clears `paused_at`; the loop continues from prior arc state.
