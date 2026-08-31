# subagent-tool-discipline: Evidence and Boundaries

Extracted 2026-08-26 when the contract moved out of the ambient tier to
`skills/_shared/subagent-tool-discipline.md`, delivered by the `SubagentStart` hook.
The contract keeps what a dispatched agent must DO; this file keeps the measured
evidence, the boundary discussion, and the delivery rationale.

Failure-mode narratives with verbatim traces: `rules/incidents/subagent-tool-discipline.md`.

## Measured failure rates — Exp 6, 2026-04-29

Fifteen failing subagent traces were classified against MAST modes:

| mode | shape | share of failing traces |
|---|---|---|
| 3.1 | silent termination on context exhaustion | **6 of 15 (40%)** |
| 3.2 | cited lines from a partial read | **4 of 15 (27%)** |

Together these are **two thirds of observed subagent failures**, and both are
*reporting* failures rather than capability failures — the agent had the tools it
needed and returned something that looked like an answer.

Verbatim from the traces (full quotes in the incidents file):

- 3.1 — "Agent terminated with 'Prompt is too long' after only one Glob and one failed
  Read on a directory, without exploring source files."
- 3.2 — "Agent produced final markdown table with line numbers (e.g. `types.ts:262`)
  inferred from a partial Read of types.ts that only returned ~10 visible lines
  (255-264 truncated); never re-read the rest."

The 3.2 quote is the load-bearing one for the citation rule: the output was a clean
markdown table. Nothing about its shape signalled that the line numbers were inferred.

## Why explicit failure is cheaper

The cost of an explicit `INSUFFICIENT_CONTEXT` report is **one re-dispatch** at reduced
scope. The cost of a silent partial is the parent **acting on incorrect data** — and
because the parent's next step usually consumes the child's report as fact, the error
propagates rather than surfacing.

That asymmetry is the whole argument. It does not depend on how often overflow happens.

## Why this rule is hook-delivered and its siblings are not

The three subagent-adjacent rules had identical measured utilization (45/438 sessions,
10.3%) but do **not** share a delivery story:

| rule | side | can a hook deliver it in time? |
|---|---|---|
| `subagent-tool-discipline` | CHILD | **YES** — `SubagentStart` fires before the child's first tool call |
| `subagent-verification` | PARENT | No — `SubagentStart` injects into the CHILD; the parent needs it when reviewing the return |
| `agent-delegation` | PARENT | No — the delegate/don't-delegate decision precedes any subagent existing, so no subagent-scoped event can precede it |

This is why utilization alone does not authorise a relocation. All three waste the
same number of bytes per session; only one has a mechanism that arrives in time.

## Delivery budget

`hooks/subagent-start-context.py` enforces `INJECTION_BUDGET_CHARS = 9_550`. Over-budget
hook output is silently replaced by the platform with a ~2KB preview plus a file path,
so an unbudgeted injection does not arrive and nothing says so (measured 2026-08-15 on
`auto-topic-loader.py`, where `msgraph.md` at 10,067 chars had been stubbed on every
injection).

The contract is deliberately compact for this reason. Injecting the original 7,015-byte
rule would have consumed ~73% of the budget and crowded out the topic files a worker
needs for its actual task — the relocation would have preserved the rule by degrading
every dispatch. The contract is injected FIRST because a dropped topic leaves a loud
pointer the agent can act on, whereas a dropped reporting contract leaves the agent
unaware it was supposed to follow one.

## Boundaries

- **Not the main thread.** Read truncation in the main session is the parent's own
  problem, managed through context budgeting.
- **Not a replacement for `subagent-verification.md`**, which is the parent-side
  requirement to verify a child's diffs and claims against disk. This contract governs
  the child before it returns; that rule governs the parent after.
- **Not a promise that context never runs out.** Some dispatches legitimately need more
  context than the child has. The goal is to fail CLEARLY, not to never fail.
