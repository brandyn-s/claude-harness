---
name: monitor
description: "Start a real-time flaw AND observation tracker for the current session — log two event types THE MOMENT they surface: FLAWs (mistakes, refuted assumptions, bad instruments, wrong approaches — we-were-wrong) and OBSERVATIONs (lessons/realizations that are NOT mistakes — a missed-but-not-wrong factor, a discovered constraint, a mid-plan course-correction worth recording). The in-session alternative to batching everything at end-of-session /distill. Trigger phrases: \"monitor\", \"track flaws\", \"log observations\", \"real-time flaw log\", \"log lessons as we go\", \"flaw tracker\". Do NOT use to retrieve PAST flaws (that's a read; this is the write side), to recall prior decisions (use /recall), or to wrap up a session (use /retro)."
when_to_use: "Use at the START of any non-trivial, multi-step, or risky work (a measurement run, a migration, an infra change, a long execution) to activate same-turn flaw logging for the rest of the session — every flaw gets appended to a session flaw-log the moment it's discovered, not reconstructed at /distill. This is the standalone, any-session form of superplan's mandatory real-time-flaw-log discipline (which only fires inside /superplan); invoke /monitor when you want that same discipline WITHOUT running a superplan. The write half of the flaw loop; /distill reads what it produces at session end."
argument-hint: "[work description]  (e.g., \"oracle accuracy measurement run\", \"migrate MCP tool names\")  — optional; inferred from context if omitted"
effort: low
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  optional:
    - skill: distill
      fallback: "Flaw-log is still written; it just won't be auto-read at session end unless /distill or /retro runs."
allowed-tools: Read Write Edit Glob Bash
---

## monitor

# Monitor — Real-Time Flaw & Observation Tracker

Activate same-turn logging for the rest of this session. Capture TWO event types the moment
they surface, each as a dated entry in the session log, rather than waiting for end-of-session
`/distill`:

- **FLAW** — something we relied on was **WRONG**: a refuted assumption, a tool that behaved
  differently than expected, a bad instrument, a wrong number, a flawed approach, a missing
  prerequisite. (The original /monitor discipline.)
- **OBSERVATION** — a **lesson or realization that is NOT a mistake**: a factor we missed but
  weren't wrong about, a constraint discovered mid-execution, a premise that shifted, a
  course-correction worth recording for next time. The thing a flaw-only log throws away —
  a clean run with zero flaws can still produce valuable observations.

Append the moment EITHER surfaces, in the same turn, before proceeding.

**Why real-time, not batched at /distill:** by session end the specific trigger, the exact
error string, and the corrected value have faded, and a flaw found early is forgotten by a
late phase. Capturing at the moment of discovery is what keeps root-cause classes and exact
error strings intact (established 2026-06-20: a measurement run surfaced 9 flaws across its
phases; logging each as it occurred — not reconstructing at distill — preserved the detail
and even caught a wrong flaw-entry that was retracted same-session).

This is the standalone form of the real-time-flaw-log discipline embedded in `/superplan`
(see that skill's `execution-discipline` reference) — `/monitor` makes it available in ANY session, with
no superplan required. It is the **WRITE** half of the flaw loop: `/monitor` captures during
execution; `/distill` reads the log and routes durable lessons to rules at session end;
`/superplan` Phase 2c (or future retrieval) surfaces past flaws before similar work.

---

## Step 1: Open the flaw-log (once per session)

Resolve the work being tracked (from the argument, or inferred from the recent conversation —
state it in one line). Create the flaw-log file if it does not yet exist:

- **Path**: `~/Documents/knowledge-base/plans/<YYYY-MM-DD>-<work-slug>-flaws.md`
  (a sibling of any plan file; `plans/` is the indexed corpus the read-side searches). If
  `~/Documents/knowledge-base/` is absent, fall back to `/tmp/claude/<work-slug>-flaws.md`
  and note that it won't be retrievable later.
- **Header** (write once):
  ```
  # Flaw & observation log — <work description>

  Real-time log captured during execution (per /monitor). Two event types:
  FLAW — an ASSUMPTION, INSTRUMENT, or APPROACH that was WRONG.
  OBSERVATION — a lesson/realization that is NOT a mistake (missed-but-not-wrong factor,
  discovered constraint, mid-plan course-correction worth recording).
  Feeds /distill's lessons at session end. Started <YYYY-MM-DD>.
  ```
- Tell the user: "Real-time flaw tracking ON for: <work>. I'll append a flaw-log entry the
  moment one surfaces — `<path>`." Then continue the actual work.

Pass the date in (the harness has no `Date.now`); use the session's known current date.

---

## Step 2: Append a flaw THE MOMENT it surfaces (the core discipline)

For the rest of the session, whenever execution reveals a flaw — a refuted assumption, a
reachability/invocability miss, a swallow-and-continue instrument, a wrong number, a flawed
approach, a missing prerequisite — **append an entry IN THE SAME TURN, before proceeding with
the fix.** Do not batch; do not wait for /distill.

**Entry format** (generalized from superplan's plan-flaw format to any work):
```
## <phase/step> — <one-line flaw> (YYYY-MM-DD)
- WHAT WE ASSUMED/EXPECTED: <the assumption / instrument / number relied on>
- WHAT EXECUTION FOUND: <the reality + the EXACT error string / measured value>
- ROOT CAUSE CLASS: assumption | reachability | instrumentation | approach | number-stale | my-diagnosis
- WHY IT WASN'T CAUGHT EARLIER: <e.g. "only surfaces on real invoke; not a reasoning flaw">
- FIX APPLIED THIS SESSION: <the in-session correction> | DEFERRED: <why>
- DURABLE LESSON → <rule/skill/topic file the lesson should land in at /distill>
```

**What counts as a flaw** (log as FLAW): the world matched your belief and the belief was WRONG —
not "the world changed." A tool returning a real error you mishandled, an assumption execution
refuted, a number that turned out stale, an approach that didn't work, a diagnosis of your own
that was wrong (retract it in the log — self-correction is a valid entry).

## Step 2b: Append an OBSERVATION when a lesson surfaces that is NOT a mistake

The flaw stream above only fires on "we were wrong." But execution constantly surfaces
**lessons that aren't mistakes** — and a flaw-only log throws them away. Log an OBSERVATION
the moment one surfaces (same in-turn discipline):

- A **premise shifted** mid-plan and you adapted — not because the premise was *wrong* when
  made, but because new information changed the right move (e.g. "planned to reuse the batch
  primitive; on reading it, its rubric is per-blob, so this task needs a different rubric" —
  the reuse plan wasn't a *mistake*, but the realization is a durable lesson).
- A **factor you missed but weren't wrong about** — a constraint, dependency, or interaction
  that didn't break anything yet but will matter next time.
- A **non-obvious thing that worked** and why — a positive lesson worth repeating, which a
  flaw-only log never captures.
- A **scope or requirement change** the user introduced — record it as an OBSERVATION (it's
  context for the session's arc), NOT silently dropped.

**OBSERVATION entry format:**
```
## OBSERVATION: <phase/step> — <one-line lesson> (YYYY-MM-DD)
- WHAT WE NOTICED: <the realization / missed factor / shifted premise>
- WHY IT MATTERS: <the consequence — what it changes now or next time>
- ACTION TAKEN / NONE: <what we did with it, or "noted only">
- DURABLE LESSON → <rule/skill/topic file it should inform at /distill, if any>
```

**Flaw vs Observation — the test:** "Were we WRONG about something?" → FLAW. "Did we LEARN
something (without having been wrong)?" → OBSERVATION. A refuted assumption is a FLAW; a
premise that was reasonable-when-made but shifted on new info is an OBSERVATION. When genuinely
ambiguous, log it as a FLAW (the stronger record); don't agonize over the boundary.

**What does NOT count** (skip either type): routine first-try successes with no reusable lesson;
the world legitimately changing under you with no insight to carry forward. Don't manufacture
entries — but the bar for an OBSERVATION is LOWER than for a flaw: a clean run with zero flaws
can and often should carry observations.

---

## Step 3: Discipline reminders during the session

- Every stop-and-fix that resolves to "we were wrong" (not "the world changed") MUST produce an
  entry BEFORE the fix proceeds. The entry is cheap; the lost detail is not.
- If you SHIP a flaw entry that later proves wrong, RETRACT it in place (mark it RETRACTED with
  why) rather than deleting — the retraction is itself a lesson (single-instance over-generalization
  is a real failure mode; see `symmetric-evidentiary-burden.md`).
- Keep entries concise but keep the EXACT error string / measured value — that is the perishable
  part distill cannot reconstruct.

---

## Step 4: Hand off to /distill (session end)

`/monitor` does not need an explicit close. At session end, `/distill` (or `/retro`) reads the
`*-flaws.md` as its pre-collected pain-point list and routes durable lessons to rules/skills.
Real-time capture FEEDS end-of-session routing; it does not replace it. If neither runs, the
flaw-log still stands as a durable artifact in `plans/`.

---

## Examples

**Example 1 — measurement run**
User: `/monitor oracle accuracy measurement run`
→ Step 1 creates `plans/2026-06-20-oracle-accuracy-flaws.md`, confirms tracking is on.
→ Mid-run a model listed ACTIVE fails to invoke → I append a `reachability` entry with the exact
`ResourceNotFoundException` string IN THAT TURN, then substitute the working model and continue.
→ At /retro, /distill reads the log and routes the lesson to `verify-before-assuming.md`.

**Example 2 — clean run that still yields an OBSERVATION**
User: `/monitor migrate the config loader`
→ Tracking on; the migration goes cleanly, ZERO flaws. But mid-migration I notice the loader
silently falls back to a default when the env var is unset — not a bug I hit, but a factor the
next consumer must know. → I append an OBSERVATION ("env-unset → silent default; downstream
callers should set it explicitly"), even though nothing went wrong. A flaw-only log loses this.

**Example 3 — premise shift mid-plan (OBSERVATION, not FLAW)**
→ Planned to reuse an existing batch primitive; on reading its source its rubric is per-record,
but this task needs per-session, so I adapt. The reuse plan was reasonable when made (not a
mistake), but the realization is a durable lesson → OBSERVATION. Had I assumed the rubric
WITHOUT reading and shipped a broken run, THAT would have been a FLAW.

**Example 4 — self-retraction (FLAW)**
→ I log a flaw ("the judge emits no severity"), then further reading shows I read 1 of 2 judges.
I RETRACT the entry in place (mark RETRACTED + why) rather than deleting — the over-generalization
is itself the durable lesson.

---

## Success Criteria

- Creates a `<date>-<slug>-flaws.md` in `plans/` (or notes the /tmp fallback) and confirms tracking is on.
- Appends each FLAW and each OBSERVATION IN THE SAME TURN it surfaces, in its structured format, with the EXACT error/value or realization.
- FLAWs are genuine we-were-wrong events; OBSERVATIONs are not-a-mistake lessons (missed factor, shifted premise, what-worked). A clean run with zero flaws may still carry observations.
- Routes ambiguous cases to FLAW (the stronger record); never silently drops a scope-change or a mid-plan course-correction — those are OBSERVATIONs.
- Retracts-in-place rather than deletes an entry that later proves wrong.
- Writes the log; does NOT replace /distill (which reads it at session end). Distinct from /recall and /retro.
