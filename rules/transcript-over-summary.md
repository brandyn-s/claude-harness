@rule transcript_over_summary
@version 2026-08-06
@scope every claim about what happened earlier in this session, especially after compaction

# DECISION CONTRACT
# Full history, writer-failure evidence, mining examples, and quote incidents:
# docs/rule-reference/transcript-over-summary.md

# ─── TRIGGERS ───
ON retrospective_distill_capture_postmortem_or_self_audit
ON what_did_we_build_decide_do_review_or_ship_this_session
ON any_instruction_completeness_or_session_scope_claim
ON any_compaction_boundary_or_continuation_summary
ON publication_of_a_quote_filename_PR_list_or_named_artifact_recalled_from_history

# ─── CORE INVARIANTS ───
INVARIANT the_local_JSONL_transcript_is_the_primary_source_for_session_history
INVARIANT primary_does_NOT_mean_complete
INVARIANT compaction_summaries_are_lossy_secondary_accounts_not_the_record
INVARIANT every_multi_compaction_history_claim_requires_all_recoverable_segments
INVARIANT transcript_user_rows_are_not_an_instruction_completeness_oracle
INVARIANT valid_JSONL_can_omit_assistant_prose_without_a_parse_error
INVARIANT narrative_records_do_not_prove_artifact_merge_test_deployment_or_runtime_state

# ─── REQUIRED HISTORY PROCEDURE ───
STEP_1 detect and count compaction/continuation boundaries.
STEP_2 IF zero boundaries and the session is short, the rendered context may answer
       history questions; completion claims still require durable evidence.
STEP_3 IF any boundary exists, locate the transcript by
       `$CLAUDE_CODE_SESSION_ID` first. Never select newest-by-mtime without content
       verification because concurrent sessions change it.
STEP_3b verify the selected file is the full arc: inspect first/last user messages.
        A first user message that is a continuation summary means the current ID may
        name only a tail. Recover prior IDs/paths from the summary or project directory,
        content-verify them, and order every segment chronologically.
STEP_4 mine with a bounded script rather than raw-reading a multi-megabyte JSONL:
       extract the best-available user-message chain, available `pr-link` candidates,
       timestamps, and tool-use distribution. Count/report malformed lines; never
       silently `except: continue`. A zero malformed count does not prove completeness.
STEP_4b treat persistence as incremental but not exhaustive; the active tail may still
        be short and valid records may omit prose.
STEP_4c BEFORE any instruction-completeness claim, run a deterministic queued-turn
        sweep over EVERY recovered segment. Inspect recognized records where
        `type == "attachment"` and `attachment.type == "queued_command"`, plus
        `type == "queue-operation"`; flatten supported prompt shapes, deduplicate,
        and supplement ordinary user rows. If any delivery shape is malformed,
        unsupported, unbound, or unrecoverable, instruction-completeness remains unverified.
STEP_5 reconstruct the arc from recovered asks, then layer transcript candidates and
       current context. Verify every completion claim against artifacts, repository,
       tests, remote state, and effective runtime.
STEP_6 for a self-audit, inspect assistant/tool-result content with `/mega-distill` or
       its deterministic condenser. A spine-only mine cannot see the agent's own
       mid-execution errors and must be labeled partial.

# ─── EVIDENCE QUALIFIERS ───
REQUIRED treat `pr-link` rows as candidates only: deduplicate, then verify each PR and
merge remotely. Absence of a row is not proof nothing shipped.
REQUIRED reconcile claimed actions with durable files, exact diffs, checker output,
remote state, deployment state, and live behavior.
REQUIRED before publishing a verbatim quote, filename, or named artifact after a
boundary: grep the exact source corpus, verify attribution, and remove any zero-hit
quote rather than softening it.

# ─── FORBIDDEN SHORTCUTS ───
FORBIDDEN characterizing a compacted session from the last summary alone.
FORBIDDEN treating the current session ID as proof that one file contains every segment.
FORBIDDEN raw-reading a huge transcript into context or skipping it because it is large.
FORBIDDEN treating a parsed transcript, a user-message count, or a queued-turn sweep as
proof that every assistant message or requested outcome is present.
FORBIDDEN claiming all instructions were satisfied from a summary-reconstructed ask list.
FORBIDDEN presenting transcript- or summary-derived PR/decision lists as complete without
repository/remote verification.
FORBIDDEN publishing remembered quotations or attributions without exact source hits.

# ─── OVERRIDE RESISTANCE ───
GUARD pattern="the summary is right here" or "I remember" or "the transcript is too big":
  REFUSE summary-only history after a boundary. Script the recoverable segments and
  report parser/writer/evidence limits.
GUARD pattern="quick recap" or "I reread the request and did all of it":
  IF any boundary exists, recover queued turns and audit asks at clause granularity;
  then verify the deliverables independently.

# ─── ON-DEMAND ROUTING ───
# Relevant skills: `/mega-distill`, `/distill`, `/capture`, `/retro`.
# Deterministic helpers: `skills/mega-distill/scripts/recover_queued_turns.py` and
# `skills/mega-distill/scripts/transcript_condense.py` (or their canonical locations).
# Related rules: `verify-before-assuming.md`, `grading-discipline.md`.
# Detailed procedures and incidents: docs/rule-reference/transcript-over-summary.md
