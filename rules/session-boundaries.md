---
description: Sessions end at task boundaries, not at length — never abandon work because the context is long; close a finished task with a handoff so the next one starts clean
---

@rule session_boundaries
@version 2026-09-06
@scope every session; the boundary half of never-stop-early (deleted 2026-09-03), which outcome-over-verification's stop contract does not cover

# SESSION BOUNDARIES — DECISION CONTRACT

"Let's continue in a new session" names two behaviours: abandoning work because
the context feels full (prohibited) and closing a finished task so the next one
starts clean (required). `outcome-over-verification` says when to stop; this
says what to write before the next session starts.

## Invariants

INVARIANT never_stop_for_length_or_imagined_capacity
INVARIANT plans_are_not_deliverables_execute_them
INVARIANT a_completed_frame_ends_the_session_not_the_next_task
INVARIANT no_new_session_proposal_without_a_written_handoff
INVARIANT two_failed_corrections_means_rewrite_not_patch

## Required checks

1. **Length is not a reason.** Capacity varies by model, lane and surface; never
   invent a window size or percentage. Stop only when the user says so, the
   runtime reports the next safe action cannot fit, a blocker needs user
   authority or unavailable evidence, or the task is complete.
2. **Completion is a boundary.** When the done-criteria (INTENT.md, or the
   approved plan) are met and evidenced, say so with the evidence and stop. Do
   not begin the next task in this context; it gets a fresh session and frame.
   If the user continues here anyway, restate the new frame first.
3. **Two compactions → handoff.** Write `HANDOFF.md` in the working directory,
   copy it to `~/.claude/HANDOFF.md` (session-start shows it once at the next
   startup), then propose a fresh session. Keep working until the user answers.
4. **Two failed corrections → rewrite.** When the same correction has been made
   twice and the behaviour recurred, stop patching the conversation: write the
   lesson into the handoff (and the instruction file if it is standing) and
   propose a clean start.
5. **Handoff, one screen.** Objective and INTENT link · done, with evidence
   paths · open items and the exact next action · decisions and cuts since the
   last handoff · files touched · rollback point · first thing to verify. The
   acceptance ledger's entries go in verbatim.

# Enforcement: compaction-budget.py (PostCompact count → UserPromptSubmit nudge at 2);
# proceed-gate.py (bare continuations restate DO/NOT/CHECK). Advisory by design —
# the phrase-based Stop blocker stays demoted (docs/fresh-laptop-control-audit.md).
