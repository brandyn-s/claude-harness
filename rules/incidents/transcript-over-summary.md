---
paths:
  - "**/rules/transcript-over-summary.md"
  - "**/rules/incidents/transcript-over-summary.md"
---

# transcript-over-summary: Incident Narratives

Extracted from `rules/transcript-over-summary.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## the-rendered-conversation-context-is-lossy-compaction-replaces

```
WHY: the rendered conversation context is LOSSY. Compaction replaces
     earlier turns with a summary; each successive compaction summarizes
     the PRIOR summary plus new work, so early phases compress toward
     zero while the most-recent work dominates. The on-disk transcript
     (~/.claude/projects/<project>/<session-id>.jsonl) is the COMPLETE,
     append-only record — every user message, tool call, and pr-link,
     with timestamps. It has no compaction loss.
```

## a-summary-is-one-model-s-lossy-compression-of

```
WHY: a summary is one model's lossy compression of the record, written
     to survive context-overflow — NOT an authoritative ledger. Treating
     it as the session's history silently truncates scope to the last
     boundary's window. INCIDENT 2026-06-19: a 46h / 64-PR / 4-compaction
     session was characterized from the LAST summary alone — the answer
     captured only the final ~6h (the Bedrock migration) and missed the
     first ~40h (the regex→whole-session-judge pivot, durability arc,
     investigation-UX layer, single-user architecture, UEBA). The raw
     transcript's user-message chain + pr-link ledger were the ground
     truth the summaries had decayed away from.
```

## with-2-compaction-boundaries-the-recursive-summary-decay-is

```
WHY: with ≥2 compaction boundaries the recursive-summary decay is
     severe — the current-context summary is a summary-of-a-summary.
     One boundary may be tolerable for a quick recap; two or more makes
     the transcript mandatory for any scope/history claim.
```

## the-user-message-chain-pr-link-ledger-the-spine

```
WHY: the user-message chain + pr-link ledger (the "spine," STEP_4) nails
     the session ARC — what was asked, what shipped. But the agent's OWN
     mid-turn errors (a secret leaked via `ps -o command`, a one-time
     external egress, a refuted measurement) appear ONLY in assistant
     text + tool_result bodies — NEVER in a user message or a pr-link. So
     a spine-mine is STRUCTURALLY blind to exactly the failures a
     self-audit / "where were we wrong" report most needs. INCIDENT
     2026-06-22: a "terminal report reflective of the COMPLETE transcript"
     was built from a 382-user-msg + 225-doc spine mine; a full-content
     fan-out then found 3 misleading items + ~12 omissions — all of them
     the agent's own mid-execution errors (2 self-inflicted CONFLUENCE-
     token leaks, 1 egress of real secrets, the refuted ~1,744 recall
     gap), none of which any user message mentions. A spine-mine answers
     "what did we DO"; it cannot answer "where were WE wrong."
```

## compaction-summarises-at-the-granularity-of-work-done-not

```
WHY: compaction summarises at the granularity of WORK DONE, not of ASKS
     MADE — so a user turn that carried two clauses can survive as one.
     The half you DID becomes "the request"; the half you did NOT do stops
     existing in your context, which means the ordinary
     complete-the-whole-instruction self-check CANNOT FIRE: you re-read a
     request that no longer contains the unmet part and correctly conclude
     you finished it. This is strictly worse than forgetting a phase,
     because nothing feels missing.
```

## 2026-07-30-airlock-the-framing-ask-was-review

```
INCIDENT 2026-07-30 Airlock: the framing ask was "Review our entire
     implementation … AND I want to use this output and brainstorm better
     approaches to deploying, managing, using Airlock at scale that best
     fits my company." The review shipped (a ~50-finding register); the
     brainstorm never ran. The summary rendered the turn as the review
     alone, and ALSO dropped 6 other earlier user turns — it listed 9 of 14
     real asks, opening at "Measure all, do all" when the session actually
     began with a blocked-executable ticket 8 turns earlier. Only the
     transcript's user-turn spine showed the missing clause.
THEREFORE: an instruction-completeness check is only valid against the
     TRANSCRIPT'S user-turn spine. Checking it against the summary grades
     you on a truncated version of your own instructions.
```

## 2026-07-26-example-labs-handbook-retro-claude-code

```
WHY 2026-07-26 (Example Labs handbook /retro): $CLAUDE_CODE_SESSION_ID
resolved 7f3f0d10 = 547 lines, 2 user messages — BOTH of them the
compaction summary plus "/retro". The real 12-user-message arc (Labs
paved-road assessment → handbook → red-team → warchest) was 3,594 lines
under the PRE-boundary id ed249a2d, named in the summary's own handoff
line. Newest-by-mtime picked the same near-empty tail, so the STEP_3
fallback would NOT have caught it either — only the first/last
user-message content check did. Distilling the tail alone would have
extracted lessons from a transcript containing no work.
```

## 2026-07-30-the-summary-enumerated-9-of-14

```
WHY: 2026-07-30 — the summary enumerated 9 of 14 real user turns, and
rendered a two-clause ask ("review … AND brainstorm better approaches at
scale") as the review alone. The brainstorm was never delivered and nothing
in context indicated it had been asked for.
```

## 2026-06-19-this-rule-s-origin-built-a

```
INCIDENT 2026-06-19 (this rule's origin): built a "what did we do this
session" retrospective from the final compaction summary. Reported the
last ~6h (Bedrock) as "the session"; the transcript showed 46h / 64 PRs /
5 phases starting 2 days earlier with a different ask. Corrected only when
the user said "you should be able to read the full local session
transcript as well."
```
