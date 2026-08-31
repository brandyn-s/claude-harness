# Budgets — turns and tokens

## Defaults per effort tier

| Effort | Turns | Tokens | Rationale |
|--------|-------|--------|-----------|
| XS | 5 | 50k | Trivial task; loop almost shouldn't be needed |
| S | 15 | 200k | Short refactor; ~3-5 model decisions per turn |
| M | 20 | 400k | Medium feature; bounded multi-component coordination |
| L | 40 | 800k | Large change; substantial debug + verification |
| XL | 80 | 2M | Exceptional investigation; requires explicit turn and wallclock opt-in |

Pulled from the plan's `Effort:` line (set by superplan's Phase 3b). Override at invocation with `--budget-turns=N --budget-tokens=M`.
An XL plan must also receive both explicit `--budget-turns` and
`--budget-wallclock` arguments; its effort label does not start an XL loop by itself.

## Why both turns AND tokens

`/goal` natively tracks both ("turn count" + "token spend" in status). Tracking only turns misbehaves when turns are cheap: a 5-turn budget can do nothing useful if each turn is 100 tokens. Tracking only tokens misbehaves when turns are expensive: one runaway 100k-token turn exhausts a 200k budget instantly.

Turn count or wallclock time triggers `budget-exhausted` (the first to hit). Tokens are advisory only (Key Design Choice #7 — tokens are not reliably exposed per-turn). Plan-and-decide budgets fail in both directions if you pick the wrong dimension.

## How the hook tracks

State file has `turn_budget_remaining`, `turn_budget_total`, `tokens_used_advisory`, `token_budget_advisory`, `wallclock_used_seconds`, and `time_budget_seconds`. The hook:

- Decrements `turn_budget_remaining` by 1 each turn
- Increments `wallclock_used_seconds` by actual elapsed time since last turn
- Exits with `budget-exhausted` when `turn_budget_remaining` reaches 0 or `wallclock_used_seconds` reaches `time_budget_seconds`

The terminal doc captures the final values, so a future plan author can see whether prior arcs ran out of turns vs tokens.

## Token parsing

`--budget-tokens` accepts `50000`, `50k`, `2M`, `1.5M` — anything `_parse_token_count` understands.

## Block-cap budget vs supergoal budget

These are separate:
- **Anthropic block-cap**: 8 consecutive Stop-hook blocks → force-stop. Step 4 sets `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` to the selected turn budget plus two. The hook resets `consecutive_blocks` to 0 only on demo-achieved (metrics at baseline), not prophylactically.
- **supergoal budget**: total turns/wallclock regardless of block pattern. Exhaustion triggers `budget-exhausted` exit.

A run with steady progress is constrained by the supergoal budget. A run stuck blocking has both budgets ticking; the derived block cap prevents premature termination without creating a second, much larger allowance.

## When budgets exhaust

- Terminal doc records `Exit reason: budget-exhausted` and the final turns/tokens consumed
- "Retired hypothesis" section names the plan's mechanism (didn't move the metric within budget)
- "Named next-plan target" section is filled in by the next session's author after reviewing what stalled

The pattern: budget-exhausted is the *good* failure mode — it means the loop stopped on a known deadline rather than running indefinitely. The terminal doc forces a re-diagnosis before the next attempt.
