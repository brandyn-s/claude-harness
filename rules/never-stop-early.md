# Never Stop Early — Complete the Task

## The rule

Do not stop working merely because a session is long. Continue while the task
is incomplete and useful progress is possible. Context capacity varies by
model, provider, parent/child lane, and product surface; never invent a fixed
window size or percentage.

## Prohibited phrases (and variants)

- "Let's continue this in a new session"
- "We should start a fresh session for this"
- "To avoid context issues, let's pick this up in a new conversation"
- "This is a good stopping point — we can continue next time"
- Any suggestion to stop working when the task is incomplete

## When to ACTUALLY stop

- The user explicitly tells you to stop
- The runtime reports that the next safe action cannot fit
- The task is genuinely complete
- A real blocker requires user authority, external state, or unavailable evidence

## When NOT to stop

- You've been working for a while (irrelevant — finish the task)
- The conversation is "getting long" without a runtime capacity warning
- You have a plan and haven't executed it yet (execute it, don't present it and stop)
- You think a "fresh context" would be cleaner (it wouldn't — you'd lose all the context you've built)

## Plans are not deliverables

Presenting a plan and stopping is NOT completing the task. A plan is step 1. Execute the plan. If you wrote a plan, you are less than halfway done.

## The anti-pattern this prevents

Claude builds context for 15 minutes, understands the full problem, writes a plan, then says "let's continue in a new session" — throwing away all that context and forcing the user to re-explain everything. This has happened repeatedly at 40-60% context remaining.

## Checkpoint and handoff contract

When runtime capacity genuinely prevents safe completion, write a checkpoint
before stopping. The durable handoff must contain the objective, completed
work, exact remaining work, current files/state, verification evidence,
rollback information, and the next executable action. A durable handoff is a
last-resort continuity mechanism, not a substitute for completing work that
still fits safely in the active lane.
