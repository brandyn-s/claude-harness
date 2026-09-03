---

name: retro
description: "Session wrap-up — runs /distill and /capture (using /mega-distill and /mega-capture for compacted sessions), then lands session artifacts through /ship."
when_to_use: 'Session review that runs /distill then /capture sequentially with shared context, then SHIPS uncommitted artifacts produced by the current session via /ship. Distill extracts errors and operational fixes. Capture records strategic insights, skipping incidents already distilled. Ship commits, opens a PR, and durably queues what the session wrote (rules, skills, docs, reports). Use when a session is wrapping up and its lessons should be persisted in one pass. Trigger phrases: "retro", "session review", "wrap up session", "end of session". Do NOT use for multi-session strategic review (use /retrospective), single-purpose error capture (use /distill), single-purpose knowledge capture (use /capture), or repo cleanup beyond what this session produced — stale branches, stuck PRs, other dirty trees (use /pr-fix).'
argument-hint: "[omit for auto-review; --full to extract from the COMPLETE transcript on large/compacted sessions]"
effort: high
metadata:
  author: example-security-engineering
  version: "2.4"
allowed-tools: Bash Read Edit Glob Grep Skill mcp__memory-search__memory_search AskUserQuestion
---

## retro

# Retro -- Session Review

Run `/distill` then `/capture` in sequence, sharing context between them so
capture skips re-extracting pain points that distill already processed.

**Scope**: this skill is about session-end knowledge persistence — extracting
it AND landing it. Persistence is not complete until the writes are committed,
so Step 5 ships the artifacts THIS session produced. Repo cleanup beyond that
(other sessions' dirty trees, stuck PRs, stale branches) lives in `/pr-fix`.
Architecture-level audits (harness pruning, absorb pattern review) live in
`/garden`. /retro pulls knowledge out of the conversation; it does not
audit the architecture.

(Pared 2026-05-03 from a previous design that included mandatory
"audit the architecture" steps. Transcript audit of 26 prior /retro runs
showed the dirty-repo scan ran 0% of the time, the absorb pattern review
ran 42% but produced 0 violation-log entries across 11 absorb profiles in
30+ days. Strong wording did not work. The mandatory steps were moved to
/pr-fix and /garden where they have clearer scope and better completion
characteristics.

Amended 2026-06-11 by user directive: a SHIP step was restored — see Step 5.
The 0%-completion failure above was the unbounded "scan dirty repos" sweep;
Step 5 is bounded to artifacts this session itself wrote, which are already
enumerated in the conversation by the time retro runs. General sweeps remain
in /pr-fix.)

Resolve `STATE_ROOT` once: use `$HOME/.codex` when `$CODEX_THREAD_ID` is set,
otherwise `$HOME/.claude`. Resolve `CONFIG_ROOT` once: prefer the claude-config
Git worktree this session edited, then `$CLAUDE_CONFIG_ROOT`, then
`$HOME/.claude`. This is the canonical source repo for rules, skills, hooks,
and agent memory; a Codex installed-skill copy under `$HOME/.agents` is not a
substitute for the editable source.

**If this session ALREADY REMOVED its config worktree, do not accept the
`$HOME/.claude` fallback — cut a fresh worktree from `origin/main` first.**
The fallback is silent and lands distill's rule/skill/memory writes in a
checkout that is routinely dirty with a parallel session's work and far behind
`origin/main` (measured 2026-08-29: 273 commits behind, ~20 topic files dirty
with another session's staged edits). Writing there mixes this session's
lessons into someone else's uncommitted tree, and Step 5 then cannot ship a
clean scoped PR. `worktree-by-default` Step 7 clears a worktree once its PR is
terminal, which is *before* retro runs — so a session that shipped and cleaned
up is exactly the session that hits this. Verify with
`git -C "$CONFIG_ROOT" status --short` and
`git -C "$CONFIG_ROOT" rev-list --count HEAD..origin/main`; a dirty tree or a
nonzero count means cut a new worktree rather than writing in place.

**Runtime-neutral skill dispatch:** whenever this document says to invoke `/name`,
in Claude Code use the Skill tool; in Codex load the exact available
`skills/name/SKILL.md` and execute it through Codex's skill mechanism. Do not
assume Codex exposes a callable Claude Skill tool.

---

## Session Write Ledger (establish before persistence writes)

Build a per-repository provenance ledger from evidence already present in this
session before `/distill` or `/capture` adds more writes. Resolve the **first
pre-write HEAD** observed in this session from the worktree receipt or the
earliest transcript-confirmed `git rev-parse HEAD` before this session's first
write. Also retain exact paths and commit OIDs produced by this session's tool
results. The HEAD at `/retro` invocation time is not a substitute: it cannot
distinguish an older clean-ahead commit from one created during this session.

If no authoritative pre-write OID exists for a repository, mark its
`session_provenance` as `UNVERIFIED`. Do not infer provenance from commit dates,
branch names, `git status`, or `origin/main..HEAD` membership.

---

## Step 0: Large-session detection (complete-transcript extraction)

`/distill` and `/capture` extract from the **in-context conversation window**.
That is correct for a normal session — but after auto-compaction fires (measured
~10x on a 60MB / 48hr session), ~90% of session history is gone from context, and
compaction discards the `tool_result`s where errors/failures live. On such a
session, retro's distill+capture silently see only the surviving ~10%.

**Detect and route:**

1. Find this session's transcript and **select by THIS session's id — do not trust
   most-recent-by-mtime alone**:
   - **Claude Code:** resolve `$CLAUDE_CODE_SESSION_ID` (authoritative), then find the exact
     `<id>.jsonl` below `~/.claude/projects/` (scoped to `$CLAUDE_PROJECT_ID` when set). Do not
     scrape a `tasks/<uuid>/` background path; it can retain a pre-clear session id.
   - **Codex:** use `$CODEX_THREAD_ID` when set. Otherwise inspect `nodeRepl.requestMeta` with
     the Node REPL and take `x-codex-turn-metadata.session_id` (fall back to `threadId`), then
     find the exact `rollout-*-<id>.jsonl` below `~/.codex/sessions/`.
   Never substitute a `tasks/<uuid>/` id. If neither runtime yields an id, mtime is only a
   candidate list, never proof. Under concurrency the newest transcript is frequently a
   different task. ALWAYS content-verify before condensing: session metadata, when present,
   must match the resolved id, and the file's first/last visible user messages must match this
   session.
2. Measure size and lines with `ls -la` and `wc -l`. Count Claude
   `isCompactSummary` boundaries **by PARSING each record and testing the field is
   `true` — never with `grep -c`.** A grep counts every line where the string
   appears, and the string appears in message CONTENT: this SKILL.md contains it,
   so any session that ran `/retro` has ≥1 phantom hit, and rules quoting
   compaction mechanics (`transcript-over-summary`) add more. A grep count is
   therefore guaranteed to over-report on exactly the sessions that invoke this
   step, and over-reporting fires an unnecessary `/mega-distill` fan-out.

   ```bash
   python3 -c "
   import json,sys
   n=sum(1 for l in open(sys.argv[1],errors='replace')
         if 'isCompactSummary' in l
         and (lambda r: r.get('isCompactSummary') is True)(json.loads(l) if l.strip().startswith('{') else {}))
   print(n)" <transcript>
   ```

   Corroborate a nonzero count against `'This session is being continued from a
   previous conversation'` — but that phrase ALSO appears in quoted rule text, so
   it is a cross-check, not a second count. For Codex, count top-level
   `"type":"compacted"` records when present; only fall back to event-envelope
   `context_compacted` when no top-level records exist.
   **Do not add the paired counts**: current Codex emits one `context_compacted`
   mirror immediately after each top-level `compacted` record.
   (2026-07-29: `grep -c` returned 2 on a 0-boundary session — both hits were this
   file's own text plus the reply quoting it. Parsing showed 0 real boundaries;
   1,648 lines and 2.9 MB were both under gate, so the correct route was plain
   `/distill`.)
3. **Trigger the complete-transcript path** when the transcript has ≥ 1 compaction boundary,
   OR > 5000 lines, OR is > 15MB. `--full` does not override this suitability gate:
   it requires authoritative transcript resolution and complete coverage, but a
   small, uncompacted transcript is already complete in the live context and needs no
   recovery fan-out. (Byte-size alone < 15MB does NOT trigger — a build-heavy but
   uncompacted session is mostly thinking/tool-output bytes, not lost context;
   /mega-distill's own Step 0 gate matches this. FLAW-8, 2026-06-21.)

**When triggered:** invoke `/mega-distill` through the runtime-neutral skill mechanism
above with this session's transcript.
It condenses the COMPLETE file into the fewest bounded chronological signal slices, preserving
visible user/assistant text, tool calls, failures, plaintext subagent findings, and compaction
boundaries while dropping large successful-result and reasoning noise. It then runs `/distill`
over the recovered whole-session arc. Retain its reconciled lesson table and metrics;
Step 1 is already complete, so continue at Step 2 without invoking distill again.
In Step 3, invoke `/mega-capture` with the same authoritative transcript and bridge table so strategic-theme
coverage is whole-session too. Distill and capture do not independently rediscover the transcript
path.

**When NOT triggered** (small, uncompacted session): proceed to Step 1 normally —
the in-context window IS the session, and the fan-out cost is unwarranted. For a
small, uncompacted `--full` request, report that the verified full transcript already
fits this path, then run plain `/distill`; do not invoke `/mega-distill` and do not
mark Step 1 complete before `/distill` actually returns.

---

## Step 1: Run Distill

Unless Step 0 already completed distill through `/mega-distill`, invoke the
`/distill` skill through the runtime-neutral mechanism above. Let it complete fully — it will extract
errors, classify to tiers, write operational fixes, and produce the session
metrics and lessons table.

If distill reports "nothing to distill" (clean session), note this and
proceed to Step 2 — capture may still find strategic knowledge worth
recording.

**NEVER end a turn on a step-transition sentence.** A turn containing no tool
call yields control and abandons /retro mid-run with distill's artifacts
uncommitted — which is exactly the state Step 5 exists to prevent. Writing
"Proceeding to Step 2" is not
proceeding; it reads like progress in the transcript, which is why it survives
self-review. Emit the Step 2 bridge table and the Step 3 capture invocation in
the SAME turn as the sentence announcing them, or say nothing and just do it.
(2026-07-29: ended a turn on the literal words "Proceeding to Step 2 — bridging
context to capture." with no tool call; the session ended, the user had to
restart it, and 3 distill artifacts sat dirty. Same class as git-hygiene's
"writing the command is not running it", applied to skill orchestration —
step boundaries are the highest-risk place to yield.)

---

## Step 2: Bridge Context

After distill completes, build a structured handoff for capture so capture
does not re-extract the same incidents as pain-point narratives:

```
DISTILL HANDOFF — {N} lessons processed

| # | Lesson Title | Tier | Target |
|---|---|---|---|
| 1 | {exact title from distill table} | T{N} | {file} |
| 2 | ... | ... | ... |

(Include one row per **persisted** lesson; omit T5 rows.)

Capture guidance: These operational fixes are already persisted.
Focus on strategic insights, architectural decisions, and patterns.
Do NOT re-extract the error-fixing narrative for these incidents.
```

**Dedup check**: For each lesson title, run
`mcp__memory-search__memory_search(query="<lesson title>", limit=3)`. If any
result has cosine similarity > 0.85, append `[KB overlap]` to that row —
capture must not re-extract the same insight in a different form.

---

## Step 3: Run Capture

For a normal session, invoke the `/capture` skill through the runtime-neutral mechanism above with the
bridge table above as explicit guidance. For a complete-transcript session, invoke
`/mega-capture` with the same transcript and bridge guidance instead; its coverage
ledger and capture gates replace the plain capture path. State clearly:

> "The following incidents were already processed by /distill and written
> to operational persistence (rules, hooks, memory, topic files). When
> extracting knowledge from this session, SKIP these as pain-point
> narratives. Focus on architectural decisions, strategic insights,
> cross-cutting patterns, and lessons that belong in the knowledge base
> as reference material rather than operational guardrails."

If distill found nothing, invoke the selected capture path with no filter:
`/mega-capture` for a complete-transcript session, otherwise `/capture`.

---

## Step 4: Quick Postmortem (conditional)

**Trigger**: distill produced **3+ lessons** OR any single incident
consumed **10+ turns** (visible in distill's metrics: dead-end turns,
abandoned approaches, retries on one problem).

**Skip when**: distill found nothing, session was clean, or all lessons
were T5 (skip).

**Generate from `references/postmortem-templates.md` (Quick Postmortem section)
and emit it inline in chat — do NOT write a file. /retro does not persist
the postmortem to disk; it appears once in the chat transcript and lives
there.** Fields:

- **What Happened**: 1-2 sentences from the distill summary
- **Timeline**: 3-5 key moments (first error, wrong hypothesis, pivot,
  root cause found, resolution). Use turn numbers.
- **Root Cause**: the actual cause from distill's lesson, not the symptom
- **Fix**: Immediate (what resolved it) + Persistent (cite the distill
  tier and target file where the lesson was written)
- **Lessons**: 1-2 actionable bullets that go beyond the distill entry —
  what would you do differently if this happened again?

If the user wants the postmortem persisted, they can copy the chat
output into a file themselves, or invoke the Standard Postmortem or
5 Whys templates in `references/postmortem-templates.md` manually and
save the result. For deeper analysis, point to those templates.

---

## Step 5: Ship Session Artifacts (mandatory)

Knowledge persistence is not complete until the writes are committed. Capture
ships its own KB entries (its Step 5 includes the PR flow), but distill's
targets (rules, skills, hooks, memory in `~/.claude`) and artifacts earlier
skills left "uncommitted for user review" (e.g. /gather-claude findings the
user already APPROVED at that skill's approval gate) are still sitting in
dirty working trees. The user invoking /retro is the commit signal — by this
point every in-scope artifact has already passed its producing skill's
approval gate.

**Ship rule — exactly this scope, nothing broader:**

1. Enumerate each repo THIS SESSION wrote to from the Session Write Ledger
   (typically the active claude-config worktree or `$CLAUDE_CONFIG_ROOT`, plus
   `~/Documents/knowledge-base`). Do not assume `$HOME/.claude` is the active
   worktree in Codex.
2. Fetch the target base and run
   `skills/ship/scripts/outgoing_payload.py --base origin/main --session-start
   <oid>` using the ledger's first pre-write HEAD. Require
   `session_provenance: VERIFIED` before treating `session_commits` as current
   session output. Keep `pre_session_ahead_commits` separate. A clean status
   alone never proves "nothing to ship." Use
   `git log --oneline origin/main..HEAD` as a human-readable outgoing-history
   cross-check, never as proof that every ahead commit came from this session.
3. EXCLUDE: files the user explicitly deferred in-conversation, hook-managed
   logs owned by other processes, and any dirty file this session did not
   touch — list those and leave them for `/pr-fix`. Also exclude
   `pre_session_ahead_commits` from automatic session scope. If current-session
   commits depend on those older commits, either transplant the verified
   session payload onto a fresh target-base worktree and rerun affected tests,
   or obtain explicit destination-and-full-payload approval before including
   the combined history.
4. If the helper reports `session_provenance: UNVERIFIED`, **do not label ahead commits as session-produced**. Session-proven uncommitted paths may still be
   isolated and shipped, but any ahead history requires explicit
   destination-and-payload approval.
5. For each repo with in-scope changes, invoke
   `/ship --queue-only --session-start <oid>` through the runtime-neutral
   mechanism above. `/ship` owns branching, explicit staging, required
   validation, the PR, and the durable merge-queue handoff. Do not hand-roll or
   duplicate its merge helper here.
6. Report per repo: PR URL + terminal ship state (`QUEUED`, or `MERGED` if the
   platform completed it first), or "nothing to ship". `QUEUED` is a verified
   handoff, not a claim that the PR has merged. On a repo that CANNOT hold an
   auto-merge request (no protected-branch rules — the merge helper reports
   terminal `UNQUEUEABLE`, exit 7), `QUEUED` is unreachable by construction:
   the valid terminal reports there are `MERGED` (merge directly once checks
   are green) or `OPEN + named owner` (e.g. /pr-fix) when checks are blocked
   by something outside this session — such as a red main another session
   introduced. Do not poll past one bounded wait for external breakage.
   Expect the generated-marketplace treadmill on claude-config: any PR open
   alongside another session's PR WILL go DIRTY on their merge; either park
   early with an owner or re-cut from fresh origin/main (measured 2026-08-22:
   three re-cut cycles in one retro).

Run independent repo invocations in one turn when the runtime supports it; do
not serialize them merely to watch remote merge polling.

**Skip ONLY when**: zero session-produced uncommitted changes and zero
session-produced clean-ahead commits exist, or the user said not to ship this
session. "It can wait" is not a skip condition. `/retro` authorizes committing
its own new artifacts; it
does not silently authorize transmission of an anomalously large pre-existing
clean-ahead payload. `/ship` owns that destination-and-payload approval gate.

---

## Step 6: Brief Summary and Next-Step Pointer

Distill, capture, and ship each print their own outcome. /retro adds a
one-line suggestion at the end:

```
Retro complete. /distill wrote {N} lesson(s); /capture appended {M} entry/entries
across {P} topic page(s); shipped {Q} PR(s): {urls / "nothing to ship"}.

For repo work beyond this session's artifacts — stuck PRs, stale branches,
other sessions' dirty trees — run /pr-fix. For staged hook specs in
hooks/staged/, install via /ship-hook (nothing surfaces them
automatically; check manually with `ls "$CONFIG_ROOT/hooks/staged/"`).
For weekly architecture-level audits (harness pruning, absorb
violations, broken wiki-links), run /garden.

Session continues — what's next?
```

The "session continues" cue signals that retro is done but the session is
not. Maintain full working effort on subsequent messages: grep files,
measure distributions, read implementations. Do not reduce thoroughness
because the review phase is finished.

---

## Success Criteria

- `/distill` runs to completion before `/capture` starts (sequential, not parallel)
- Bridge table built with one row per **persisted** distilled lesson (T0-T4) before capture invocation. T5 (skip) rows are filtered out before the table is built — even if distill emits a T5 row in its output table, retro omits it from the bridge. T5 lessons are never forwarded to capture, because distill persists nothing for T5 and forwarding them as suppressions would block capture from re-extracting knowledge that was never persisted.
- `/capture` does not re-extract incidents that distill already classified
- Both skills write to their respective persistence targets (no dry-run)
- Step 5 ships provenance-verified session artifacts via `/ship --queue-only --session-start <oid>` (or reports "nothing to ship"); older ahead commits, user-deferred files, hook-managed logs, and dirt this session did not produce are excluded and routed to /pr-fix
- Quick Postmortem fires only when triggered (3+ lessons or 10+ turns on one issue)
- /retro itself produces no extra files on disk; persistent outputs come from /distill, /capture, and the Step 5 /ship PRs only. The optional postmortem is emitted inline in chat — not written to a file.
- No duplicate entries created across distill's tiers and capture's topic pages

---

## What This Skill Does NOT Do

- Does NOT run general dirty-repo sweeps (other sessions' messes, stale branches, stuck PRs) → use `/pr-fix`. Step 5 ships ONLY artifacts this session produced.
- Does NOT check for staged hooks → run `ls "$CONFIG_ROOT/hooks/staged/"` manually if needed; install via `/ship-hook`
- Does NOT audit harness pruning candidates → `/garden` does this comprehensively on a weekly cadence
- Does NOT review absorb pattern violations → moved to `/garden` (mature lifecycle audit, not per-session)
- Does NOT generate a unified status summary covering everything; that previously fabricated content in 96% of runs (transcript audit 2026-05-03)

---

## Examples

**Example 1: Mixed session (errors + insights)**

Session debugged ECS deployment issues and discovered a new architecture pattern.

- Distill: 3 lessons (T1: ECS stop reason rule, T4: boto3 pattern, T5: skip)
- Capture: 1 entry appended to `ecs-deployment-patterns.md`
- Postmortem: triggered (3 lessons), emitted inline in chat
- Ship: 1 PR (claude-config: rule edit) durably queued via `/ship --queue-only`; capture's KB PR already merged by capture itself
- Pointer: standard

**Example 2: Clean session, strategic work only**

Session designed a new MCP server.

- Distill: "Nothing to distill — clean session."
- Capture: 2 entries (new `mcp-server-design.md` + append to `mcp-gateway-architecture.md`)
- Postmortem: skipped (no triggers)
- Ship: nothing to ship (capture shipped its own KB PRs)
- Pointer: standard

**Example 3: Painful session, all operational**

Session where 40% of turns were dead ends.

- Distill: 5 lessons (T0-hook: 1, T1: 2, T4: 1, T5: 1 skip)
- Capture: "No strategic knowledge to capture — session was operational."
- Postmortem: triggered (5 lessons + dead-end concentration), emitted inline in chat
- Ship: this session's 2 rule updates + staged hook spec durably queued via `/ship --queue-only`; PRIOR-session distill artifacts also found dirty in claude-config — excluded (not this session's), flagged for /pr-fix
- Pointer: standard
