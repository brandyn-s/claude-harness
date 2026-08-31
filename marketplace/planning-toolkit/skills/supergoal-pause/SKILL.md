---

name: supergoal-pause
description: "Pause an active supergoal loop without losing prior-arc lineage."
when_to_use: Use when an active supergoal loop must pause without losing the prior-arc lineage. Trigger phrases - "supergoal pause", "pause supergoal", "pause the loop", "halt supergoal". Records `paused_at` in the state file; the verification hook checks this flag at the start of each Stop and returns ok=false with reason `paused` until /supergoal-resume is invoked. Use instead of Ctrl-C when intermediate state must be inspected or the plan amended. Pattern from jthack/claude-goal. Do NOT use for hard-stopping a runaway loop (Ctrl-C is correct for that — pause expects future resume), inspecting state without halting the loop (use /superplan-status), or one-off mid-loop edits (just edit then /supergoal-resume).
argument-hint: "[plan-slug]  (omit to pause the current session's loop; e.g., \"2026-05-27-fix-flaky-test\")"
allowed-tools: Bash
effort: low
---

## supergoal-pause

Find the active supergoal state file:
- If `$0` (plan-slug) is given → `~/.claude/supergoal/$0/state.json`
- Otherwise → resolved via `~/.claude/supergoal/.active` pointer or most-recently-modified `*/state.json`

Run:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/supergoal/scripts/state_io.py --pause "${1:-}"
```

(arg is optional; empty arg = auto-resolve. The CLI atomically sets `paused_at`, emits one `paused` event to events.jsonl, and is idempotent — double-pause is a no-op.)

Report what `state_io.py --show` returns: which plan was paused, current turn (from --show), plus the last decision from events.jsonl.

The verification hook will keep the loop alive but the type:agent prompt's pause gate (which runs BEFORE Step 0, where Step 0 is the `stop_hook_active` gate per `${CLAUDE_PLUGIN_ROOT}/skills/supergoal/references/verification-hook.md`) returns `{ok: false, reason: "paused"}` every turn until `/supergoal-resume` clears the flag. Plan attestation is preserved; lineage is preserved; wallclock_used_seconds does NOT advance during paused intervals.

To resume from a different plan version: re-run `/superplan` to produce an updated plan, then re-invoke `/supergoal` (will re-attest).

## Example

```
User: /supergoal-pause
  → state.json updated: paused_at=2026-05-27T14:32:00Z
  → verification hook will return {ok: false, reason: "paused"} on next Stop
Result: Loop is paused. Use /supergoal-resume to continue, or edit the plan
        first and re-run /supergoal for a fresh arc.
```

## Examples

**Example 1:** `supergoal pause` — records `paused_at` in the state file; the verification hook returns ok=false/paused until resumed.
**Example 2:** Pause instead of Ctrl-C when intermediate state must be inspected before amending the plan.

## Success Criteria

- Sets `paused_at` without losing prior-arc lineage.
- The verification Stop hook honors the flag (returns `reason=paused`) until `/supergoal-resume` runs.
