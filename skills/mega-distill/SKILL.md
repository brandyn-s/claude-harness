---

name: mega-distill
description: "Recover the COMPLETE record of a large auto-compacted session into a condensed signal slice, so /distill judges the whole session instead of only the post-compaction tail."
when_to_use: 'Use when a session is large or auto-compacted (>5000 lines, >=1 compaction boundary, or >15MB) and running /retro or /distill in-context would only see the ~10% that survives the post-compaction window. mega-distill is a COMPACTION-RECOVERY FRONT-END for /distill — it streams the full transcript, condenses it to the diagnostic signal (user turns, assistant text, tool calls in order, errors inline, compaction markers; drops thinking/images/success-tool-bodies/bookkeeping), splits it only if it exceeds a context window, hands the whole-session slice to /distill''s normal judgment, and auto-ships the resulting fixes. Trigger phrases: "mega-distill", "mega distill", "mega-retro", "full distill", "distill the whole transcript", "the session was too long for distill/retro". Do NOT use for normal-size single-context sessions (use /retro — its in-context view IS the whole session), for shipping artifacts (use /ship), or for multi-session review (use /retrospective).'
argument-hint: "[transcript-path | --corpus [--all|--min-size N|<file>] | omit for current session] [--max-tokens N]"
effort: high
metadata:
  author: example-security-engineering
  version: "1.1"
allowed-tools: Bash Read Glob Grep Skill mcp__claude_platform__count_message_tokens AskUserQuestion
compatibility:
  requires:
    - cli: python3
    - skill: distill
  optional:
    - mcp: claude_platform
      tools: [count_message_tokens]
      fallback: "Skip the real-token fit smoke; rely on the calibrated UTF-8-byte estimate (2.5 bytes/token), plus the prompt/output headroom left by the conservative 180K default"

---

# Mega-Distill — Compaction-Recovery Front-End for /distill

Give `/distill` the WHOLE session to judge — not the ~10% that survives auto-compaction.

**Why this exists.** `/distill` and `/retro` extract from the in-context conversation window. After
auto-compaction fires (measured ~10× on a 56MB session), ~90% of session history is gone from that
window, and compaction discards the `tool_result`s where errors live — so a long-session `/distill`
silently diagnoses only the surviving tail. mega-distill reads the file from disk and reconstructs the
complete session as a **condensed signal slice** small enough to fit a context window, so `/distill`
applies its NORMAL whole-session judgment to the WHOLE session.

**What it is NOT.** mega-distill is a *preprocessor for distill*, not a parallel retro engine.
Fanning context-isolated extractors over chunks produces a transcript CENSUS, not a diagnosis:
`/distill` is valuable precisely because it is LOSSY in the right direction (it keeps the
load-bearing few using WHOLE-SESSION context), chunking destroys the session ARC (goal → error →
pivot) that judgment needs, and frequency-ranking is not importance-ranking. Hence the design:
**condense, preserving the arc; then let distill judge.** The retired census apparatus
(`bin/transcript_{ground_check,reduce,synth_input,synth_shard,synth_check,meta}.py`) is dormant and
NOT invoked here (`references/run-history.md`).

**Core principle: condense, don't census.** Keep the diagnostic signal in chronological order; drop
the noise. The slice is ~4% of the raw file (measured: 56MB → 2.2MB, 65MB → 2.9MB) yet preserves
every user turn, assistant text, tool call, and error — the material distill needs to see the arc.

**Runtime-neutral skill dispatch:** whenever this document says to invoke `/name`,
in Claude Code use the Skill tool; in Codex load the exact available
`skills/name/SKILL.md` and execute it through Codex's skill mechanism. Do not
assume Codex exposes a callable Claude Skill tool.

---

## Step 0 — Mode routing + (single-session) size gate

**Corpus-mode fork (check FIRST).** If `--corpus` was passed, this is a CROSS-SESSION run over a
cohort of transcripts, not a single-session recovery — skip the rest of Step 0 and Steps 1-2 and go
to **Corpus Mode** below. The single-session path (no `--corpus`) continues here unchanged.

1. Resolve the transcript path:
   - If a path argument was given, use it.
   - Else select by **THIS session's id, NOT most-recent-by-mtime** — under concurrent sessions
     newest-by-mtime is frequently a DIFFERENT session's transcript:
     - **Claude Code:** glob `~/.claude/projects/*/*.jsonl`. Resolve the id from
       `$CLAUDE_CODE_SESSION_ID` (authoritative) — NOT a `tasks/<uuid>/` background-task path:
       after a `/clear`/session transition the task dir keeps the PRE-clear session id, resolving a
       DIFFERENT earlier transcript. Scope to
       `~/.claude/projects/$CLAUDE_PROJECT_ID/` when set.
     - **Codex:** use `$CODEX_THREAD_ID` when set. Otherwise call the Node REPL, inspect
       `nodeRepl.requestMeta`, and take `x-codex-turn-metadata.session_id` (fall back to
       `threadId`). Find the exact matching `rollout-*-<id>.jsonl` below `~/.codex/sessions/`;
       Codex does not set the Claude session-id variable and uses a different rollout schema.
     Never substitute a `tasks/<uuid>/` id. If neither runtime yields an id, mtime is only a
     candidate list, never proof. ALWAYS content-verify the selected file before condensing:
     session metadata, when present, must match the resolved id, and the first/last visible user
     messages MUST match this session. A wrong pick silently distills another session.
2. Size gate — mega-distill is for COMPACTED-or-context-overflowing sessions only. Its value is
   recovering content the in-context window LOST; if nothing was lost, /retro's in-context view IS
   the whole session and mega-distill gains nothing.
   - `wc -l` + `ls -la` the file; count compaction boundaries. Claude emits
     `isCompactSummary`. For Codex, count top-level `"type":"compacted"` records when
     present; only fall back to event-envelope `context_compacted` when no top-level
     records exist. **Do not add the paired counts**: current Codex emits one
     `context_compacted` mirror immediately after each top-level `compacted` record.
   - **Proceed** if compaction boundaries ≥ 1 OR lines > 5000 OR size > 15MB.
   - **Otherwise STOP** and report: "Session is uncompacted and fits in context — run /retro
     instead." Do NOT proceed on byte-size alone: a build-heavy but uncompacted session is mostly
     `thinking`/tool-output bytes, not conversational scale that overflowed — and there is nothing
     to recover (FLAW-8, `references/run-history.md`).
3. **Delta-since-last-recovery gate (FLAW-9).** The gate above keys on the file's
   STATIC properties (total boundaries / lines / bytes) — but on a SECOND `/retro` or `/mega-distill`
   in the SAME long session, all those boundaries are from the segment a PRIOR recovery ALREADY
   processed, and the only NEW work is the delta since then. Re-running here would re-condense the
   whole 36MB to surface lessons from a delta that is entirely IN-CONTEXT. So before fanning out:
   - Find the line of the LAST canonical top-level compaction boundary for either transcript:
     `jq -Rr 'fromjson? | select(.isCompactSummary == true or .type == "compacted") |
     input_line_number' <file> | tail -1`. Only if that produces no line, use the last
     event-envelope `context_compacted` line. Never let a paired mirror become a second boundary.
   - Compute `lines_after_last_boundary = total_lines − last_boundary_line`.
   - IF a prior recovery already ran this session (a `last-distill.json` owned by THIS session, OR
     you observably ran `/mega-distill`/`/retro` earlier this conversation) AND the entire new delta
     is AFTER the last boundary (`lines_after_last_boundary` covers all post-prior-recovery work,
     i.e. NO new compaction fired since) → **STOP and route to plain `/distill`**: the new work is
     in-context, mega-distill's recovery value (recovering compaction-LOST content) does not apply to
     an uncompacted delta. Report: "N boundaries exist but all predate the last recovery; the
     M-line delta since is in-context — running /distill directly."
   - IF a prior recovery ran AND a NEW boundary fired since it (`last_boundary_line` is
     GREATER than the prior recovery's line) → the gate does **NOT** exempt this run: the
     post-prior-recovery work spans a boundary, so part of it is compaction-LOST and
     mega-distill's recovery value applies. But do NOT re-condense the whole file either —
     **slice the delta first** and condense only that:
     locate the prior recovery's line (grep the `/retro` or `/mega-distill` command records),
     write `lines >= that` to a `*-delta.jsonl`, and pass THAT to `transcript_condense.py`
     (one slice instead of re-processing already-distilled segments).
   - OBSERVED PATTERN worth expecting: in a long session each `/retro` is frequently followed
     WITHIN A FEW HUNDRED LINES by a compaction boundary, because the retro's own reads are what
     tip the context. So on the Nth retro, assume a boundary sits just after the (N−1)th and
     slice from there.
   - This is the same "don't fan out when the in-context path handles it" judgment as the size gate,
     applied to the TIME axis (delta since last recovery) instead of the SIZE axis
     (measured runs: `references/run-history.md`).

---

## Step 0.5 — Queued-turn blind spots (read before trusting the slice's user-turn spine)

Four delivery shapes leave a user's mid-turn message OUT of the slice: a turn consumed by the
compaction it triggered (it survives only inside the boundary record's summary), the injected-context
wrapper the condenser drops, `type=="queue-operation"` records, and `attachment`/`queued_command`
records. The probes, the required deterministic sweep, and the reporting rules are in
`references/queued-turn-recovery.md`. Do NOT conclude "the user said nothing between X and Y" from
the slice alone, and do NOT report the slice `USER:` count as the session's ask count.

---

## Step 1 — Condense the full transcript to the signal slice

```bash
# Claude plugins expose their root; Codex resolves the directory from the
# exact path used to load this SKILL.md. Never use cwd for the bundled helper.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  MEGA_DISTILL_DIR="$CLAUDE_PLUGIN_ROOT/skills/mega-distill"
else
  MEGA_DISTILL_DIR="<directory-containing-this-loaded-SKILL.md>"
fi
CONDENSER="$MEGA_DISTILL_DIR/scripts/transcript_condense.py"
test -f "$CONDENSER" || {
  echo "missing bundled transcript condenser: $CONDENSER" >&2
  exit 1
}
RECOVERY_TMP="${TMPDIR:-${TEMP:-/tmp}}"
# Substitute the exact path resolved in Step 0:
TRANSCRIPT="<resolved-transcript-path>"
# TRANSCRIPT is the exact path resolved in Step 0; transcript_condense.py takes
# it as a positional argument (it does not read the transcript from stdin).
python3 "$CONDENSER" "$TRANSCRIPT" \
  --out-dir "$RECOVERY_TMP/mega-distill-<session8>" --max-tokens 180000
```

`transcript_condense.py` streams the file line-by-line (never loads it whole; ~33MB RAM on a 60MB
file) and normalizes both Claude and Codex rollout envelopes. It KEEPS, in chronological order:
visible user/assistant text, plaintext subagent reports, tool calls (name + one-line input), failed
tool outputs (capped), and `[COMPACTION BOUNDARY]` markers. It DROPS encrypted reasoning, injected
context messages, duplicate response messages, images, successful tool bodies, and bookkeeping.
Before writing any slice, it replaces recognized high-confidence credential shapes (JWTs, API
keys, GitHub tokens, AWS access keys, and Slack tokens) with fixed redaction markers while preserving the
surrounding diagnostic text.

The condenser auto-detects Claude's top-level `user`/`assistant` records and Codex's
`response_item` rollout records. Codex cleartext subagent findings and explicit failed MCP end
events are signal; encrypted agent payloads and mirrored event messages remain noise.

**Fail-closed gate:** a recognized transcript that produces zero diagnostic signals is a condenser
failure, not a clean session. Stop and repair or select the correct schema/path; never accept a
zero-part manifest as a successful complete-transcript recovery.

**Credential boundary:** slices are downstream agent inputs, not private transcript replicas. Never
hand a slice to `/distill` if a recognized credential shape survived condensation. The bundled
condenser must redact those shapes before splitting or writing; preserve source SHAs, error classes,
tool names, and other non-secret evidence so the diagnostic arc remains useful.

If the slice exceeds `--max-tokens` (estimated at 2.5 UTF-8 bytes/token), it prefers compaction
boundaries, then falls back to diagnostic-record boundaries so every part fits (NOT an N-way
raw-chunk fan-out). Order + boundary markers are preserved so the arc survives the split. Read
`condense-manifest.json` for the part count + per-part token estimate + signal counts
(user/asst/tool/error/compaction).
Downstream steps **enumerate only the paths listed in the manifest**; never glob the
session output directory, because the manifest is the authoritative run boundary.

If one rendered diagnostic record alone exceeds the budget, the condenser fails explicitly instead
of emitting an unreadable part. Reduce the source record or raise the budget only after confirming
the active model can accept it.

**Fit smoke (optional but preferred):** if `count_message_tokens` is available, real-token-count the
largest `slice_NNN.txt` to confirm it's under a window; if it's over, re-run with a lower
`--max-tokens`. The conservative 180K default leaves room for prompt, rules, and output; the
UTF-8-byte estimate (2.5 bytes/token) over-counts, so this rarely fires — but it's the same
instrument-soundness discipline the rest of the toolchain uses.

**Queued-turn sweep (REQUIRED after every condense).** Run the bundled helper against the manifest
just written and hand its output to /distill together with the slice (the four blind spots it closes:
`references/queued-turn-recovery.md`):

```bash
python3 "$MEGA_DISTILL_DIR/scripts/recover_queued_turns.py" "$TRANSCRIPT" \
  --manifest "$RECOVERY_TMP/mega-distill-<session8>/condense-manifest.json" \
  --output "$RECOVERY_TMP/mega-distill-<session8>/recovered_user_turns.txt"
```

It prints a JSON summary (`delivery_records`, `dropped_prompts`, `probe_state: verified`,
`unique_prompts`) on success and fails closed (`UNVERIFIED …`, exit 2) on any shape it cannot verify —
treat exit 2 as an unverified spine, never as zero dropped turns. State the corrected ask count
(slice `USER:` count + recovered) explicitly; the slice spine alone UNDERCOUNTS.

---

## Step 2 — Hand each slice to /distill with whole-session framing

For each `slice_NNN.txt` (one or more parts, each bounded by the 180K estimate), invoke `/distill`
through the runtime-neutral skill mechanism above
with the slice as explicit input and this framing:

> "This is a condensed-but-complete signal slice of a LARGE session that was auto-compacted N times
> — so it contains the FULL session arc (user turns, assistant text, tool calls in order, errors
> inline, compaction markers), including the ~90% that your in-context window lost to compaction.
> Read it fully and apply your normal /distill judgment: understand the session's goal and arc
> first, then extract the load-bearing lessons — real
> errors/misconfigurations/abandoned-approaches/user-corrections, each tier-classified with root
> cause + fix. The LOAD-BEARING FILTER is the governor, not a fixed count: surface every
> load-bearing lesson and SKIP working-as-intended guard friction (say 'skipped as noise: X'),
> don't list every occurrence. Scale your expectation to the recovered scope — substitute the real
> compaction count from `condense-manifest.json` (the `compaction` signal-count) for N: this slice
> spans N compaction segments, so a whole-session arc holds proportionally MORE distinct load-bearing
> lessons than a single context window would (target ~3-8 PER compaction segment, not 3-8 total;
> empirically a 5-compaction session yields ~2.5x the lessons of its post-compaction tail alone).
> Do NOT truncate to a single-window count — a fixed 3-8 cap silently discards real findings the
> recovered head contains. You are a diagnostician, not a transcriber."

When there are 2 slices: distill each, then briefly reconcile — merge duplicate lessons that span the
split, keep the union. distill's own dedup + tiering + rule-cross-reference (its Step 1d) do the
meta-analysis (rule-effectiveness gaps, cross-session recurrence) — that judgment lives in distill,
where the whole-session context and rule-corpus access exist, NOT in this preprocessor.

## Step 3 — Auto-ship the fixes (no approval gate — like /distill)

mega-distill completes the way /distill does: it **writes every tier automatically and ships the
result**, it does not stop to ask which lessons to apply. Invoking /mega-distill IS the authorization
(same contract as /distill auto-writing T0-T4 without asking, and /retro Step 5 shipping
session-produced artifacts). After Step 2 produces the tiered lessons:

1. **Write each lesson to its tier target automatically** — distill already does this (T1→rules,
   T2→MEMORY/auto-memory, T4→topic files, SKILL→the corrected skill, T0→staged hook). No "want me
   to apply these?" prompt. T5-skip writes nothing.
2. **Apply code fixes** the lessons name — for any lesson whose fix is a concrete, verified code
   change (a hook bug, a gate flaw, a misconfiguration), make the change, run its test, and include
   it. Verify the defect against source first (diagnose-before-fix) — a wrong auto-fix is worse than
   none — but do NOT defer a verified fix for approval.
3. **Ship via /ship** — branch + PR + auto-merge for every repo touched (claude-config for
   rules/skills/hooks, knowledge-base for capture entries), exactly as /retro Step 5 does. Auto-merge
   is armed; the user invoking /mega-distill is the commit signal.

The ONLY things that block: a fix that fails its own test (fix it or drop that one lesson, ship the
rest), or a destructive/irreversible change (those still confirm per security-confirmations). Pure
lesson-writes and verified non-destructive code fixes ship without asking — anything less makes the
lesson shelfware (the eval-shipping-discipline "no opt-ins" rule: a fix the user must remember to
apply is never applied).

---

## Corpus Mode — cross-session recurrence (`--corpus`)

A different entry point: a CROSS-SESSION run over a cohort of raw transcripts that ranks friction by
BREADTH (sessions affected, not occurrences) and hands each cluster's member-lessons, in breadth-rank
order, to /distill's judge-and-write loop — so the output is shipped diffs, not a table of counts.
Full procedure (Layer 1 friction spine, Layer 2 bounded semantic lessons, the ship step and its
instrument-validation gates): `references/corpus-mode.md`.

---

## Success Criteria

- Step 0 size gate routes small/uncompacted sessions to /retro; only large/compacted sessions
  proceed. No fan-out spent on a session the in-context path handles.
- The condensed slice preserves the full session ARC in chronological order (user turns + assistant
  text + tool calls + errors inline + compaction markers); noise (thinking/images/success-bodies/
  bookkeeping) is dropped. ~4% of raw bytes.
- Every slice is ≤180K estimated tokens, leaving prompt/output headroom; compaction boundaries are
  preferred and record boundaries are the safe fallback.
- /distill produces a load-bearing lesson set sized to the recovered scope (~3-8 PER compaction
  segment, NOT 3-8 total) with whole-session judgment — not a finding inventory. The load-bearing
  filter is the governor, not a fixed count; working-as-intended guard friction is skipped, not
  enumerated. A fixed single-window cap is NOT applied — it would discard real findings the recovered
  head contains (measured: ~2.5x more lessons on a 5-compaction session than its tail alone).
- distill's tiering/dedup/rule-cross-reference does the meta-analysis; this skill does not re-implement it.
- Step 3 auto-ships: every tier is written and verified code fixes are applied + PR'd WITHOUT an
  approval prompt (same contract as /distill). No "want me to apply these?" — invoking is authorizing.
- **Corpus mode ships DIFFS, not a report.** The cluster ranking prioritizes; /distill judges-and-writes
  each cluster's member-lessons (dedup against rules/ + write the specific fix). If corpus mode's output
  is a breadth table of counts rather than a set of shipped fixes, the ship step did NOT run — the
  clustering is input to distill, never a substitute for it.

## Examples

**Example 1 — 56MB / 10-compaction session**
`/mega-distill` → Step 0 detects 19,852 lines + 10 boundaries → condense to a 2.2MB slice (242 user
turns, 1,939 assistant texts, 2,338 tool calls, 93 errors) → splits into the minimum bounded set,
with every part ≤180K estimated tokens →
/distill reads every part, reconstructs the arc, yields ~5 load-bearing lessons (e.g. a diagnose-before-fix
violation the user had to correct twice, a security-write on an ambiguous instruction), and SKIPS the
recurring guard-blocks as working-as-intended.

**Example 2 — uncompacted session misroute (incl. big-but-uncompacted)**
`/mega-distill` on a 0-compaction session that fits context — whether 4.7MB or 5.4MB/3,105 lines (the
bytes are thinking/tool-output, not conversational overflow) → Step 0 reports "uncompacted and fits
in context, run /retro" and STOPS. Byte-size alone does not trip the gate (FLAW-8 fix).

**Example 3 — biggest sessions split**
`/mega-distill <65MB-path>` → condense → 2.9MB slice exceeds one window → requires at least seven
parts under the 180K estimate, preferring compaction boundaries and falling back to record
boundaries → /distill each → reconcile duplicate lessons across the split.

