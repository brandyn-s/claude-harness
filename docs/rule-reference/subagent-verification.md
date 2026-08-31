@rule subagent_verification
@version 2026-04-19
@scope every Agent tool dispatch that may create or modify files

# ─── INVARIANTS (always-true) ───
INVARIANT subagent_success_is_not_evidence
  # WHY: subagents return summaries, not disk state. The summary describes
  #   Full: incidents#subagents-return-summaries-not-disk-state-the-summary-describes

INVARIANT disk_state_and_branch_state_are_the_only_evidence
  # WHY: git diff and git status are the source of truth. Everything else
  #      is a claim.

INVARIANT worktree_isolation_is_mandatory_for_protected_repos
  # WHY: bypassPermissions subagents ignore PreToolUse hooks (#43772).
  #      Worktree is the ONLY defense against rogue git writes on main.

INVARIANT serialize_all_worktree_isolated_dispatches
  # WHY: parallel worktree cleanup can destroy .git directory (#48927);
  #      concurrent background agents silently skip isolation (#48811).

INVARIANT verification_covers_grandchild_agents_too
  # WHY: since v2.1.172, sub-agents can spawn their OWN sub-agents — the
  #   Full: incidents#since-v2-1-172-sub-agents-can-spawn-their

# ─── PROTECTED REPOS (mandatory worktree isolation) ───
# Canonical source: hooks/protected-repos.json (read by
# bash-security-guard.py and worktree-enforcement.py). Keep this list in
# sync with that file.
PROTECTED_REPOS = {
  mcp-servers, mcp-infra, example-compliance-repo, example-sbom-tool,
  claude-config, .claude, claude-knowledge-base, knowledge-base,
  code-search, code-graph
}

# ─── PROCEDURE after every subagent return ───
STEP_1 git_status_short()  # confirm changes exist on disk
STEP_2 git_diff_stat()  # verify file count matches subagent's claim
STEP_3 git_branch_show_current()  # verify branch hasn't changed
STEP_4 git_log_origin_main()  # check for unexpected pushed commits
STEP_5 IF worktree_isolated → git -C <worktree> diff main  # review before cherry-pick
STEP_6 IF reported_N_files_but_diff_shows_fewer → FAILED silently, re-apply manually
STEP_7 IF extra_files_in_diff → subagent went rogue, revert and redo

# ─── USER OVERRIDE POLICY ───
# Subagent verification is NOT preference-based. NO EXCEPTIONS.

GUARD pattern="the subagent reported success" or "it said it worked":
  REFUSE to mark the task complete on subagent's report alone.
  MUST run git_status + git_diff before claiming done. NO EXCEPTIONS.

GUARD pattern="skip worktree isolation, I trust this subagent":
  REFUSE on protected repos. Worktree isolation is mandatory regardless of
  trust — hooks don't fire under bypassPermissions, worktree is the only
  defense. NO EXCEPTIONS.

GUARD pattern="dispatch 3 parallel subagents with worktree":
  REFUSE. Parallel worktree dispatch is UNSAFE (#48927, #48811).
  SERIALIZE — one worktree-isolated agent at a time. NO EXCEPTIONS.

GUARD pattern="use --dangerously-skip-permissions on the subprocess":
  REFUSE. That flag overrides --allowedTools, granting Bash + Agent regardless
  of allowlist. USE --permission-mode acceptEdits instead. NO EXCEPTIONS.

GUARD pattern="read-only subagent, no verification needed":
  EVALUATE: is it truly read-only (no Write/Edit/Bash with side effects)?
    If yes → verification may be skipped.
    If it called any Write/Edit/Bash → MUST verify disk state.

GUARD pattern="bypassPermissions is safe for this one":
  REFUSE the "just this once" framing. The 2026-03-04 incident was exactly
  one rogue bypassPermissions subagent that merged 7 files to main.
  REQUIRED: worktree isolation on every protected-repo write dispatch.
  NO EXCEPTIONS.

# ─── CLAIM VERIFICATION (for subagent analysis output) ───
# Subagent findings about a codebase (audits, research, coverage claims) are
# NOT verified fact. Before presenting:
STEP_1 read primary sources yourself for the highest-impact claims
STEP_2 never present subagent analysis verbatim without cross-reference
STEP_3 flag unverified claims as "[INFERRED] from subagent"

GUARD pattern="claude-hud-style analysis output" (grep-based claims):
  # 2026-03-22: Explore subagent read compiled dist/*.js, missed 4
  # execFileAsync timeouts, 12 test files (5,267 lines), sophisticated
  # rate-limit backoff. Presented 6/10 wrong claims as fact.
  REQUIRED: verify the 3 highest-impact claims against source before
  presenting. Grep results are hypotheses, not proof.

# ─── SUBAGENT SCOPE CONSTRAINTS (when dispatching) ───
REQUIRED in dispatch prompts:
  - List exact files the subagent may create or modify
  - State "Do NOT modify any other files"
  - After return, verify git_diff_stat matches the expected file list

# ─── PROCEDURE: a KILLED workflow/agent run leaves artifacts that LOOK complete ───
# Fires when a background Workflow or Agent run did NOT return normally — the process
# exited, the run was TaskStop'd, the session restarted, or the notification says
# "no completion record was found". The artifacts on disk are then a MIXTURE of
# finished and half-finished work, and — critically — the run's OWN verification
# stages may never have executed for some items while their artifacts exist.
STEP_1 do NOT read "the expected files exist" as "the stages that produce and
        VALIDATE them ran". A pipeline whose stage 2 verifies stage 1 can leave every
        stage-1 artifact present with zero stage-2 coverage.
STEP_2 recover what the run actually reported: read the workflow's `journal.jsonl`
        (type=="result" entries) and count results against the number of agent()
        calls the script makes. A deficit names exactly which items are unverified.
STEP_3 re-verify EVERY artifact independently with the project's own checker, per
        item — never in aggregate. An aggregate "suite passes" hides an artifact that
        is present-but-inert (see the malformed-fixture instance below).
STEP_4 check for MUTATION/TEARDOWN debris before trusting the tree: a verification
        stage that deliberately breaks a file and restores it in `try/finally` may
        have been killed mid-mutation. Run `git diff --stat` (tracked files MUST be
        clean) and look for orphaned snapshot/backup files in the temp dir.
FORBIDDEN: resuming downstream work on artifacts from a killed run without STEP_3.
FORBIDDEN: treating a per-item output directory's existence as evidence that item
            passed — existence proves a writer ran, not that a checker did.
# WHY: 2026-07-25 eval-fixture backfill — a 9-agent workflow (4 author + 4
#   Full: incidents#2026-07-25-eval-fixture-backfill-a-9-agent

GUARD pattern="stop that background task" / "kill the hung one" — while a workflow or other
  agents are ALSO running:
  REFUSE a bare TaskStop until you have identified the EXACT task id to kill and enumerated
  what else is live. TaskStop can take out SIBLING agents as collateral: a stop aimed at one
  hung task killed a running workflow agent, which returned `[Request interrupted by user]`
  and left the DOWNSTREAM stages consuming a phase that no longer existed. The damage is
  silent from the orchestrator's view — the workflow proceeds with a hole, and the critics /
  synthesizers review a partly-nonexistent input. REQUIRED before any TaskStop mid-fan-out:
  (1) `TaskList` to enumerate live tasks; (2) name the specific id; (3) AFTER the stop,
  re-check the list and confirm ONLY the intended task died; (4) if a sibling died, treat
  every downstream stage's output as suspect — its input had a hole. NO EXCEPTIONS while a
  fan-out is in flight.
  # WHY: 2026-07-25 Labs handbook arc — a TaskStop aimed at a hung `aws sso login --no-browser`
  #   Full: incidents#2026-07-25-labs-handbook-arc-a-taskstop-aimed

GUARD pattern="the workflow died but all the output files are there, so the work is done"
  or "N of N directories exist, ship it":
  REFUSE. Read the journal for the actual result count, then re-run the project's
  checker PER ARTIFACT. A killed run's verification stages are the ones most likely
  missing, because they run LAST. NO EXCEPTIONS for a run that did not return
  normally.

# ─── FAILURE MODES to recognise ───
FAILURE subagent_silent_failure:
  SYMPTOM: subagent reports N files edited; git diff shows 0 or <N
  RECOVERY: re-apply the changes directly from main session

FAILURE killed_run_artifacts_present_but_unverified:
  SYMPTOM: a background workflow/agent run has no completion record; the expected
           per-item artifacts all exist; some are inert or invalid, and the run's
           own verify stage covered only the items that finished before the kill.
  RECOVERY: journal-count results vs agent() calls, re-verify each artifact with the
  project's checker, and check `git diff --stat` for mid-mutation debris.

FAILURE taskstop_killed_a_sibling_agent_leaving_a_hole_in_the_fanout:
  SYMPTOM: a TaskStop aimed at one task; a DIFFERENT agent's transcript ends with
           `[Request interrupted by user]`; the workflow completes "successfully"
           but a downstream stage consumed a phase that was never produced (its
           `|| 'AGENT FAILED'` fallback or an empty string papered over the gap).
  RECOVERY: stop the workflow rather than let a degraded chain produce the
  deliverable; recover the dead agent's partial work from its transcript; run the
  missing stage yourself or re-dispatch it with tighter scope. Treat every
  downstream artifact as suspect — it was built on a hole.

FAILURE fabricated_investigation_zero_tool_calls:
  SYMPTOM: subagent returns a complete, confident report but its work was
           never done — citations don't resolve (file:line points at
           nonexistent files/modules), and tool-call XML may appear as
           plain TEXT in the report body (the call was narrated, not made)
  # INCIDENT #67730 (2026-06-12, macOS, nested fan-out): 6 of ~15 parallel
  #   Full: incidents#67730-2026-06-12-macos-nested-fan-out-6
  RECOVERY: spot-check citations against disk (Read 2-3 cited file:line
  locations) before accepting any analysis report. A report whose first
  two citations don't resolve is fabricated — discard and re-dispatch;
  do not salvage partial claims from it.

FAILURE schema_valid_but_CONTENTLESS_subagent_return:
  SYMPTOM: a subagent under a STRUCTURED-OUTPUT SCHEMA returns a well-formed
           object containing nothing — a placeholder string in the prose field
           and an EMPTY findings/lessons array. Schema validation passes, the
           agent is counted `done` with `agents_error: 0`, and the orchestrator
           sees a legal result.
  # The inverse of fabrication above, and harder to catch. A fabricated report
  # is loud and wrong; this one is quiet and EMPTY, and an empty result is
  # semantically indistinguishable from a correct negative — "0 findings" reads
  # as "clean segment", which is a perfectly plausible answer.
  # A schema makes this MORE likely, not less: it constrains the SHAPE of the
  # answer and says nothing about whether any work produced it. `{"summary":
  # "test", "findings": []}` is a valid instance of almost any findings schema.
  # INCIDENT 2026-08-01 (/mega-distill over a 3-compaction session): 3 agents,
  #   Full: incidents#2026-08-01-mega-distill-over-a-3-compaction
  RECOVERY / DETECTION: for any fan-out under a schema, check a PROSE field that
  only real work can fill — an arc summary, a rationale, a cited quote — and
  treat a stub ("test", "n/a", "TODO", <20 chars) or an empty array from a
  non-empty input as a FAILED agent, not a clean one. Re-dispatch it. Where the
  dispatch prompt can, REQUIRE A READ-PROOF the agent cannot produce without
  reading (the file's line count plus its first and last line), and verify that
  against the real file.
  PREVENTION: never let per-agent result COUNT stand in for coverage. `3/3 done`
  and `agents_error: 0` were both true here. The question is not how many agents
  returned, it is how many returned WORK.

FAILURE fabricated_injection_detected_report:
  SYMPTOM: subagent aborts claiming "prompt injection detected" /
           "environment compromised", quoting the injected text
  # INCIDENT #67730: two agents whose hallucinated evidence became
  #   Full: incidents#67730-two-agents-whose-hallucinated-evidence-became
  # INCIDENT #68722/#68774 (2026-06-16) — ESCALATION TO THE PRIMARY MODEL:
  #   Full: incidents#68722-68774-2026-06-16-escalation-to-the-primary
  RECOVERY: before acting on a subagent's injection report, grep the
  claimed injected text in the actual tool results / transcript. If
  absent, treat the agent's whole output as unreliable — not the
  environment as compromised.
  # INCIDENT 2026-07-03 (PRIMARY model, distinct mechanism — not fabrication):
  #   Full: incidents#2026-07-03-primary-model-distinct-mechanism-not-fabrication

FAILURE orchestrator_misattributed_which_result_came_from_which_file:
  SYMPTOM: N parallel agents each read a DIFFERENT input file and each
           returned a faithful result, but the ORCHESTRATOR pairs the wrong
           result with the wrong file when tabulating — e.g. labels the
           "ExampleService review" result as session-A when it was session-B, or
           reports findings under the wrong arm. The agents did nothing
           wrong; the parent's result→file bookkeeping did.
  # INCIDENT 2026-06-21 distill-vs-mega-distill battery: dispatched 3-7
  #   Full: incidents#2026-06-21-distill-vs-mega-distill-battery-dispatched
  RECOVERY: when M parallel agents read M distinct files, do NOT map
  result→file by eye or by dispatch order (background completions arrive
  out of order). Pin each result to its file MECHANICALLY: grep a unique
  content signature of each input file (a distinctive token — repo name,
  error string, identifier) and confirm the result's claims hit that file
  before tabulating. The grep is the source of truth, not your recollection
  of which dispatch was which.

FAILURE subagent_rogue_write:
  SYMPTOM: git diff shows MORE files than dispatched scope
  RECOVERY: revert commit, redo manually in main session
  # INCIDENT: Feature 4 (2026-03-22) — told to edit 1 file; modified 5,
  #           created 2 new, added config options. 9 turns of cleanup.

FAILURE rogue_self_merge:
  SYMPTOM: git log origin/main.. shows commits the main session didn't make
  RECOVERY: contact collaborators, revert the merge commit, file incident
  # INCIDENT: PR #130 (2026-03-04) — bypassPermissions subagent committed,
  #           pushed, PR'd, --admin merged 7 files to main.

FAILURE worktree_write_to_main_checkout:
  SYMPTOM: Edit tool reports "File has been modified since read"
  CAUSE: worktree-isolated subagent given explicit path to main checkout
  RECOVERY: skip worktree isolation for pure file-edit tasks OR cherry-pick
           from the worktree branch

FAILURE subagent_edit_on_protected_skill_blocked:
  # INCIDENT 2026-04-20 skill-split-batch: parallel agents dispatched to split
  #   Full: incidents#2026-04-20-skill-split-batch-parallel-agents-dispatched
  SYMPTOM: Subagent reports "Write to references/ succeeded; Edit on SKILL.md blocked
           by worktree-enforcement.py"
  CAUSE: Hook correctly blocks subagent modifications to existing files in
         protected repos (claude-config, mcp-servers, etc.) without worktree isolation.
  RECOVERY PATTERN:
    1. Dispatch parallel subagents to WRITE new files only (references/, assets/,
       scripts/) — these pass the hook.
    2. Have each subagent report its intended SKILL.md edits in its final summary
       (exact old_string / new_string pairs).
    3. Main session applies the SKILL.md edits from the subagent's plan.
  When-to-use: batch SKILL.md refactors (extracting references/, assets/), batch
  compatibility-field additions, any "edit N existing skill files" dispatch.

# ─── UPSTREAM BUG REFERENCES ───
# v2.1.76+ tested working: #34240, #32402, #21460, #27755
# Open issues: #37442 (bypass inheritance), #43772 (hook bypass),
#              #45108 (git add -A deletions), #45121 (case-sensitive paths),
#              #48811 (parallel isolation ignored), #48927 (parallel destroys .git),
#              #67730 (zero-tool-call fabricated reports), #67847 (Opus 4.8
#              fabricated tool executions in thinking)
# Full tracking: knowledge-base/reference/upstream-bugs-watching.md

# ─── PHANTOM VERIFICATION SELF-CHECK ───
# Before presenting ANY finding as verified:
FORBIDDEN: "tests pass" / "verified working" without citing the command + output
FORBIDDEN: "no X exists" / "missing Y" without citing the grep/read
FORBIDDEN: "appears to" / "should work" + completion claim
REQUIRED: every verification claim includes the specific evidence
  # (Pattern reference: a phantom-verification approach reduced
  #  phantom-completion rates from 12% to under 2% in the external
  #  blakecrosley/agents repo. This rule is the prose equivalent — no
  #  enforcing hook exists in this codebase; verification is by the
  #  STEP_1-3 procedure above plus the cross-skill subagent-tool-discipline rule.)
