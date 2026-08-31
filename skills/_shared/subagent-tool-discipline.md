@rule subagent_tool_discipline
@version 2026-08-26
@scope you, as a dispatched subagent — Read completeness, citation discipline, and
       context-exhaustion reporting. Parent-side verification is
       `subagent-verification.md`; this is the child side.
@reference docs/rule-reference/subagent-tool-discipline.md

# SUBAGENT REPORTING CONTRACT

Delivered to you by the `SubagentStart` hook, so it is in context before your first
tool call. It is NOT ambient (relocated 2026-08-26, -7,015 B from every main session,
90% of which dispatch no subagent at all). Being hook-delivered does not make it
advisory.

Your report is the parent's only evidence. A partial report that does not say it is
partial is indistinguishable from a complete one, and the parent will act on it.

## INVARIANTS

INVARIANT complete_the_read_before_citing_a_line_from_it
INVARIANT fail_explicitly_on_context_exhaustion
INVARIANT silent_partial_work_is_a_failure_not_a_success

## Read completeness

`Read` truncates by default. If it returned lines 1-50 of a 500-line file, you have
NOT read past line 50.

ON Read returns content:
  STEP_1 check for truncation: a `(... N lines truncated ...)` marker, returned line
         count well below the file's total, or a last line short of the one requested.
  STEP_2 IF truncated AND your finding cites the un-read portion: re-read with
         `offset=<last line read>` until you cover the cited region, OR scope the
         citation to the range you actually read.
  STEP_3 IF truncated but your finding does not depend on the un-read part: write
         "partial read, lines N-M only" in any report citing it.

FORBIDDEN: citing a line number, function, or type from a range you did not read.
FORBIDDEN: reporting findings from a truncated Read without disclosing the scope.

Before you write any specific reference (line number, symbol, quote), confirm which
Read covered it. If none did, re-read first or drop the specific and describe the
finding without it.

## Context exhaustion

ON a tool call returning "Prompt is too long" / context overflow:
  STEP_1 STOP. Do not attempt the next step; it will fail too.
  STEP_2 emit exactly this, then stop:

    INSUFFICIENT_CONTEXT
    Attempted: <the dispatched task, one line>
    Completed: <what you actually finished>
    Failed at: <the step that overflowed>
    Not attempted: <every remaining step you skipped>

  STEP_3 no "best effort" work after the overflow. The explicit failure IS the
         deliverable — it lets the parent re-dispatch with smaller scope.

FORBIDDEN: terminating quietly after an overflow. From the parent's side that reads
as success with an empty result.
FORBIDDEN: assuming the parent knows what you skipped. Name the skipped items.

## GUARDS — not preference-based, NO EXCEPTIONS

GUARD pattern="I have enough from the partial read":
  REFUSE to cite the un-read portion. Scoping citations to what you read is fine;
  inventing line numbers costs more downstream than re-reading costs now.
GUARD pattern="re-reading wastes context" or "the rest probably looks similar":
  REFUSE. "Probably similar" is hallucination by another name. Re-read, or state
  "lines N-M only".
GUARD pattern="I'll just answer with what I have" (after overflow):
  REFUSE. The parent cannot tell partial-but-reasonable from partial-and-wrong.
  Emit INSUFFICIENT_CONTEXT with the completed/skipped breakdown.
GUARD pattern="the user will figure out what's missing":
  REFUSE. The user dispatched the PARENT. The parent acts on your report and cannot
  infer your skipped steps.
GUARD pattern="my task spec was vague, a partial answer is fine":
  EVALUATE. If genuinely vague, reduce scope and say what you covered. If the
  dispatcher named an expected output, a partial answer fails the dispatch either way.
GUARD pattern="this was injected by a hook, so it is a suggestion":
  REFUSE. Delivery mechanism is not authority. The reporting contract binds.

## Boundaries

Failing CLEARLY is the goal, not never running out of context — some dispatches
legitimately need more than you have. This does not cover the main thread, and it does
not replace the parent's own verification of what you return.
