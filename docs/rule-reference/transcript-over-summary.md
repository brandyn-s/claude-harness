@rule transcript_over_summary
@version 2026-08-05
@scope every claim about what happened earlier in THIS session — retrospectives, "what did we build/decide/do", session characterizations, self-audits, /distill + /capture extraction, postmortems, and any answer whose evidence is "the conversation so far". Fires hardest when a compaction boundary is present.

# ─── INVARIANTS (always-true) ───

INVARIANT the_local_jsonl_transcript_is_the_primary_source_for_session_history
  # WHY: the rendered conversation context is LOSSY. Compaction replaces
  #   Full: incidents#the-rendered-conversation-context-is-lossy-compaction-replaces

INVARIANT primary_does_NOT_mean_complete
  # Valid JSONL can omit assistant prose without a parse error. The transcript
  # remains better than a compaction summary for history, but completion claims
  # also require artifact/runtime evidence.
  # Evidence: https://github.com/anthropics/claude-code/issues/84153

INVARIANT a_compaction_summary_is_a_secondary_account_not_the_record
  # WHY: a summary is one model's lossy compression of the record, written
  #   Full: incidents#a-summary-is-one-model-s-lossy-compression-of

INVARIANT multi_compaction_sessions_REQUIRE_the_transcript
  # WHY: with ≥2 compaction boundaries the recursive-summary decay is
  #   Full: incidents#with-2-compaction-boundaries-the-recursive-summary-decay-is

INVARIANT a_spine_mine_is_blind_to_the_agents_OWN_mid_execution_errors
  # WHY: the user-message chain + available pr-link records (the "spine,"
  #   STEP_4) recover useful history but cannot prove a complete event set.
  #   Full: incidents#the-user-message-chain-pr-link-ledger-the-spine

INVARIANT a_summary_can_drop_a_CLAUSE_of_a_multi_part_instruction_making_an_unmet_ask_invisible
  # WHY: compaction summarises at the granularity of WORK DONE, not of ASKS
  #   Full: incidents#compaction-summarises-at-the-granularity-of-work-done-not
  # INCIDENT 2026-07-30 Airlock: the framing ask was "Review our entire
  #   Full: incidents#2026-07-30-airlock-the-framing-ask-was-review

# ─── WHAT THE TRANSCRIPT GIVES YOU THAT THE SUMMARY DOESN'T ───
# - The best available user-message chain — usually verbatim and ordered, and
#   materially stronger than the last window's slice. It is still subject to
#   the queued-message and writer blind spots below; never infer completeness
#   merely because every line parses.
# - Available pr-link records (type=="pr-link") — deduplicatable candidates
#   for shipped work, with timestamps and repos. Their presence is not merge
#   proof and their absence is not proof that nothing shipped; verify remotely.
# - tool_use distribution — what was actually done (Bash/Edit/Write counts,
#   AskUserQuestion density, research-wave MCP calls).
# - True start time + duration — a summary states neither.

# ─── PROCEDURE: before answering any session-history / retrospective question ───
STEP_1 detect compaction: does the current context begin with (or contain) a
        message starting "This session is being continued from a previous
        conversation that ran out of context"? Count how many such boundaries
        are present.
STEP_2 IF zero boundaries AND the session is short → the rendered context IS
        the available conversational record; answer history questions from it
        (transcript optional). Completion still requires artifact/runtime checks.
STEP_3 IF ≥1 boundary → READ THE TRANSCRIPT before claiming session scope.
        Locate it: glob ~/.claude/projects/*/*.jsonl and SELECT BY THIS
        SESSION'S ID ($CLAUDE_CODE_SESSION_ID, authoritative) — do NOT trust
        newest-by-mtime under concurrent sessions: it is frequently a DIFFERENT
        session's transcript (2026-06-25: `ls -t` grabbed a parallel session's
        88MB/11-compaction file; this session's was the 760KB/0-boundary
        <id>.jsonl). mtime is a fallback ONLY when no id is available;
        content-verify before mining. The boundary message does NOT carry the
        path — find it on disk. (Same detection mechanics the /retro +
        /mega-distill skills document.)
STEP_3b A COMPACTION BOUNDARY CAN MINT A NEW SESSION ID — so
        `$CLAUDE_CODE_SESSION_ID` may resolve ONLY the post-boundary TAIL, and
        the pre-boundary arc lives on disk under the OLD id. The id being
        "authoritative" (STEP_3) makes it the right FIRST pick, NOT a complete
        one. So after selecting by id, CHECK WHETHER THE FILE IS THE WHOLE
        SESSION: extract its first + last user messages. IF the FIRST user
        message is itself a compaction summary ("This session is being
        continued from a previous conversation…"), the file is a CONTINUATION
        SEGMENT, not the session — the earlier segment(s) are separate .jsonl
        files. Recover them: the compaction summary usually NAMES the prior
        transcript path (read it), else glob the project dir and content-verify
        each candidate's first/last user messages against the known arc. Then
        condense EVERY segment and concatenate in chronological order before
        mining. The tell that you got it wrong: a segment whose only
        user-visible content is the summary plus the command you just typed.
  # WHY 2026-07-26 (Example Labs handbook /retro): $CLAUDE_CODE_SESSION_ID
  #   Full: incidents#2026-07-26-example-labs-handbook-retro-claude-code
STEP_4 mine the transcript with a script, do NOT read 28MB raw into context:
        - extract the user-message chain (type=="user", filter tool_result/hook noise)
        - extract available pr-link records (type=="pr-link"), dedup, sort by timestamp
        - read first + last timestamps for true duration
        - count tool_use by name for an activity profile
        - COUNT AND REPORT malformed lines; never `except: continue` silently.
          The transcript writer has an unsynchronized-writer race (upstream
          #81843: four writer domains append with no shared lock, so a record
          can be spliced mid-write). Measured upstream: 30 bad lines across 23
          of 10,949 files, 2026-01..07, 16 CC versions — still present on
          2.1.220. Skipping a spliced line is correct; skipping it SILENTLY is
          not, because a dropped record makes the mine quietly partial in
          exactly the way a summary is. `scripts/transcript_condense.py` reports `malformed_lines` in its
          manifest and warns on stdout; any hand-rolled mine must do the same.
        - A zero malformed-line count does NOT prove content completeness.
          Valid JSONL can omit assistant prose (#84153), which produces no
          parser signal. Reconcile claimed actions with durable artifacts,
          repository/test evidence, structured tool results, and runtime state.
STEP_4b transcript persistence is INCREMENTAL as of v2.1.220 (#79188, verified
        2026-08-01: a live session's .jsonl grew 554,968 -> 565,026 bytes in 6s
        mid-session). Before that it was buffered and flushed at exit, so a
        mid-session read of the CURRENT session could legitimately come back
        absent or short. Incremental persistence narrows that failure to the
        tail; it does not prove that every valid assistant message was written
        (#84153).
STEP_4c BEFORE any instruction-completeness claim, run a deterministic queued-
        turn sweep over EVERY recovered transcript segment. At minimum, inspect
        recognized Claude records where `type=="attachment"` and
        `attachment.type == "queued_command"`, plus `type=="queue-operation"`
        records; flatten string/list/object prompt shapes defensively, dedup,
        and supplement the ordinary `type=="user"` spine with recovered asks.
        Also inspect compaction-boundary summaries when the arc changes without
        a recorded cause. Record unsupported or malformed delivery shapes. If
        the sweep cannot run cleanly or a delivery cannot be reconstructed,
        instruction-completeness remains unverified. The transcript user rows
        alone are insufficient for a post-compaction ask count.
STEP_5 reconstruct the arc from the user-message chain (the spine), THEN layer
        available PR-link records + your context knowledge on top. The transcript is the
        primary history source and the summary is a cross-check. For any claim
        that work completed, verify the named artifacts and effective runtime
        state independently of both narratives.
STEP_6 IF the question is a SELF-AUDIT ("where were we wrong / insufficient",
        "what flaws", a postmortem, a "complete + honest" terminal report) —
        the spine-mine is NECESSARY BUT NOT SUFFICIENT (see the spine-mine-
        blindness invariant). The agent's own mid-execution errors live in
        assistant text + tool_result bodies, not the spine. Route to a
        FULL-CONTENT pass: invoke `/mega-distill` (condense-then-distill over
        the whole .jsonl) or its condense step, and label any spine-only
        output "ARC-recovered from available transcript; self-error and
        artifact completeness unverified" rather than "reflective of the
        complete transcript."

# ─── USER OVERRIDE POLICY ───
# This is NOT preference-based. The summary's convenience does not override
# the transcript's primacy for history/scope claims. Its own gaps must be
# reported, not papered over. NO EXCEPTIONS for
# multi-compaction sessions.

GUARD pattern="the summary is right here, just use it" or "reading the transcript is overkill":
  REFUSE for any scope/history/retrospective claim on a session with ≥1
  compaction boundary. The summary is lossy by construction; one scripted
  transcript mine (user-chain + available pr-link records) is cheap and materially more
  complete than the summary. Report parser/writer gaps and verify artifacts.
  NO EXCEPTIONS for ≥2 boundaries.

GUARD pattern="I remember what happened, I was here the whole time":
  REFUSE. "Here the whole time" is false across a compaction — earlier turns
  were REPLACED by the summary; you no longer hold them. Memory of the
  rendered context IS the lossy summary. Read the transcript. NO EXCEPTIONS.

GUARD pattern="the transcript is 28MB, it'll blow context":
  REFUSE the raw read; do NOT skip the transcript. Mine it with a Python
  script (user-chain + pr-link + timestamps + tool counts) and read only the
  extracted signal — kilobytes, not megabytes. The size is an argument FOR
  scripting, not for trusting the summary. NO EXCEPTIONS.

GUARD pattern="I resolved the transcript by session id, so I have the whole session"
  (when the file is small / has few user messages / its first user message is a compaction summary):
  REFUSE that conclusion. The session ID can CHANGE at a compaction boundary, so the
  id-resolved file may be only the post-boundary TAIL while the arc sits under the OLD
  id. Selecting by id is correct and INSUFFICIENT. VERIFY: extract first + last user
  messages; a first message that IS a compaction summary means this is a continuation
  segment — find the earlier segment(s) (the summary usually names the path) and condense
  ALL of them. NO EXCEPTIONS when the id-resolved file's user-message count is
  implausibly low for the work you remember doing.
  # WHY: 2026-07-26 — id resolved a 547-line tail whose 2 user messages were the summary
  # + "/retro"; the real 3,594-line arc was under the pre-boundary id. See STEP_3b.

GUARD pattern="just a quick recap, full rigor isn't needed":
  EVALUATE: zero boundaries + short session → rendered context is fine.
  ANY boundary + a scope/"what did we do across the session" question →
  read the transcript. "Quick" does not lower the completeness bar when a
  boundary has already dropped history.

GUARD pattern="I re-read the user's request and I did all of it" (on a session with
  ≥1 compaction boundary — i.e. the request you re-read came from a SUMMARY):
  REFUSE the completeness verdict. You cannot audit instruction-completeness
  against a lossy rendering of the instructions: a summary drops CLAUSES, so the
  ask you re-read may no longer contain the part you skipped, and the check
  passes for the wrong reason. REQUIRED: run STEP_4c first, then extract the
  best-available user-turn spine from ordinary and recovered queued-turn records
  and re-read YOUR OWN asks at clause granularity — count the asks and compare
  to the count the summary enumerated. A deficit names what to go finish. NO
  EXCEPTIONS for a "did I complete the task?" claim after a boundary. Then
  verify the deliverables, tests, repository state, and effective runtime;
  transcript prose is not evidence that the named result exists.
  # WHY: 2026-07-30 — the summary enumerated 9 of 14 real user turns, and
  #   Full: incidents#2026-07-30-the-summary-enumerated-9-of-14

# ─── FAILURE MODES to recognise ───

FAILURE characterized_session_from_last_summary_missed_earlier_phases:
  # INCIDENT 2026-06-19 (this rule's origin): built a "what did we do this
  #   Full: incidents#2026-06-19-this-rule-s-origin-built-a
  RECOVERY: read the transcript, re-extract the user-message chain + available
  pr-link records, rebuild the arc from the spine, and state plainly which earlier
  phases the summary had dropped.

FAILURE trusted_summary_pr_or_decision_list_as_complete:
  # A summary lists "the PRs" or "the decisions" from memory of its window.
  # Available pr-link records have sometimes shown 5-10x more, across more repos.
  RECOVERY: dedup the pr-link entries for a candidate shipped-list,
  then verify each PR/merge against repository or remote state; never present
  a summary- or transcript-derived list as complete without that check.

# ─── RELATION TO OTHER RULES / SKILLS ───
# - /capture + /distill already carry compaction-boundary DETECTION mechanics
#   (find the boundary, glob for the .jsonl) — to SUPPLEMENT thin context.
#   This rule sets the PREFERENCE: for history/scope claims the transcript is
#   PRIMARY, not just a supplement. It is not a completeness oracle. Same
#   detection, stronger mandate.
# - verify-before-assuming.md: "act on the record, not an assumption." A
#   compaction summary is an assumption about the session; the transcript is
#   the primary record, qualified by durable artifact/runtime evidence.
# - grading-discipline.md / red-team-rubric-discipline.md: a session
#   self-audit graded from the summary grades against a truncated scope —
#   read the transcript first so the axes cover the recoverable session scope,
#   then qualify gaps and artifact/runtime evidence.

# ─── WHAT DOES NOT REQUIRE THIS RULE ───
# - Single-segment sessions with no compaction boundary (rendered context is
#   available directly; completion claims still require artifact/runtime evidence).
# - Questions about the CURRENT turn / most-recent few turns (in-context, post-boundary).
# - Forward-looking work ("what should we do next") that doesn't claim session history.
# - Reading a DIFFERENT session's transcript is governed by the same mining
#   discipline (script it, don't raw-read), but this rule's PREFERENCE is about
#   THIS session's own history vs its own summary.


GUARD pattern="about to publish a VERBATIM QUOTE, a filename, or a named artifact in a
  deliverable (report, PR body, brief, finding) on a session with >=1 compaction boundary":
  RE-VERIFY EVERY QUOTED STRING AGAINST SOURCE FIRST. After a boundary, a quote you
  "remember" is a RECOLLECTION, not a record — the turn it came from was replaced by a
  summary, and a summary paraphrases. The failure is silent and self-confirming: a
  remembered quote reads fluent, attributes to a real person, and sits plausibly in the
  narrative, so nothing in it looks wrong. MEASURED 2026-08-01: of 5 quotes/artifacts
  carried across ONE boundary into a forensic report, **3 failed re-verification** — a
  quote with ZERO hits in a 384-message corpus plus every mined endpoint file, a filename
  absent from the upload set, and a "shared with the team, improves detections ~2x" claim
  whose real source was a zip built locally and never sent.
  REQUIRED, mechanically, before the deliverable ships:
    grep -F "<the exact quoted string>" <the source corpus>
  A quote returning 0 hits is REMOVED, not softened. Derive the probe string from the
  SOURCE, never from your paraphrase (see verify-before-assuming's paraphrased-probe
  GUARD — the mirror failure).
  ALSO RE-CHECK ATTRIBUTION, not just presence: a line can verify verbatim and still be
  mis-attributed. The same pass found a quote correctly present but authored by the
  SUBJECT relaying his manager, not by the manager — in a forensic document that is a
  different fact about a different person.
  NO EXCEPTIONS for a quotation in an artifact that leaves the session.
  # WHY: 2026-08-01 insider-threat report. The 3 bad claims had survived a full prior
  # revision and would have shipped to HR/Legal. Re-verification cost ~4 tool calls.
