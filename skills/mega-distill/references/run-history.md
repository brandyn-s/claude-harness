# mega-distill — run history

Dated measurements and incidents behind the rules in SKILL.md. The rule lives in
SKILL.md; the evidence lives here.

## Design history — the retired census (2026-06-21 red team)

An earlier version fanned ~79 context-ISOLATED subagents over the transcript and
emitted ~995 disconnected findings — a transcript CENSUS, not a diagnosis. The
red team established why that failed: `/distill` is valuable precisely because it
is LOSSY in the right direction (it discards ~99% of noise and keeps the
load-bearing few, using WHOLE-SESSION context to judge what matters). Chunking
destroyed the session ARC (goal → error → pivot) that judgment needs, and
frequency-ranking (a guard firing 24×) is not importance-ranking (one
data-sovereignty violation > 24 working-as-intended guard blocks). The
map/synthesis/meta apparatus from that era
(`bin/transcript_{ground_check,reduce,synth_input,synth_shard,synth_check,meta}.py`)
is left dormant, not deleted.

The same red team found the corpus-mode Phase-C failure: summarizing a cluster
("auto-ship a T1 rule with N/M as its WHY") emitted a frequency report and buried
the shippable specifics — a stale-but-already-fixed lesson and a real one-line
hook-message bug were both invisible at the cluster level and only surfaced when
distill's loop ran on the member-lessons.

## Step 0 — size gate (FLAW-8, 2026-06-21)

The old `size > 5MB` OR-clause over-triggered on a 5.4MB / 0-compaction /
3,105-line session whose 451KB condensed slice distill could read in-context
directly. Byte-size alone is not the signal — compaction or line-scale is.

## Step 0 — delta-since-last-recovery gate (FLAW-9, 2026-06-22)

- 2026-06-22: a second /retro on a 36MB/5-boundary session had a 1,491-line delta
  entirely post-last-boundary; full mega-distill would have re-processed the whole
  file for an in-context delta.
- 2026-07-28, a 4th-retro run: full file 11,607 lines / 22 MB / 4 boundaries, but
  the un-distilled delta was 3,423 lines / 6.7 MB / 2 boundaries → one 173K-token
  slice instead of re-processing three already-distilled segments.
- Observed pattern: each `/retro` is frequently followed within a few hundred
  lines by a compaction boundary (retro at 2496 → boundary 2846; 5396 → 5466;
  8196 → 8303), because the retro's own reads are what tip the context.

## Step 0.5 — the boundary summary is the only record (verified 2026-07-28)

The observed boundary record's `message.content` was one 17,916-char string.
Patching the condenser to ALSO emit user text carried on the boundary record
produced a **byte-identical** slice, because the text is in the summary prose,
not on a user content block. The patch was reverted as a fix for a defect that
does not exist.

## Second blind spot — mid-turn messages dropped as injected context (2026-07-30)

Both verified in one session: `"Make sure to collect all of the logs to ensure we
have observability"` was in context and `grep`-absent from the slice; and
`"Can you do 24, 48, 72 hours?"` was in the transcript but NEVER reached context —
only the following `"Proceed with 24, 48, 72hrs"` did, so a QUESTION was acted on
as a DIRECTIVE and the constraint that answered it was found after execution
began.

## Third blind spot — `queue-operation` records (2026-07-30, session f8491918)

The pivot turn *"This is not recoverable in our local session prompts? v2 judge
prompt"* — which refuted a conclusion already shipped in a recommendation and
redirected the remainder of the session — was stored as **four
`type=="queue-operation"` records plus one `type=="attachment"`**, carried NO
`"sent a new message while you were working"` wrapper, and was absent from the
condensed slice (`grep -c` on the slice = 0). A refinement filtering to
`type=="user"` returned a confident **0**. The wrapper grep returned a nonzero
count composed entirely of phantom self-referential hits — this document
describing the pattern.

## Fourth blind spot — `attachment` / `queued_command` (2026-08-01, session c9f95428)

1 boundary, 2,197 lines: **5 mid-turn user asks were absent from the slice**, and
the documented probes found NONE of them. `grep -c "sent a new message while you
were working"` returned **2 — both phantom** (this SKILL.md's own text plus the
reply quoting it); exactly **1** was a real `type=="user"` record. The 5 real ones
were carried as `type=="attachment"` with `attachment.type == "queued_command"`,
and **3 of the 5 had NO `queue-operation` twin at all**. Three were the session
PIVOTS: the user diagnosing the agent's own RTR automation as rebooting the
subject's machine.

Slice `USER:` counts vs true ask counts: 66 against 71 in one case, and **91
against 103** on 2026-08-03 (12 dropped, of which 2 predated the compaction and
appeared in no summary: a sanctions-scope correction and a named-entity /
OEM-subsidiary directive, both of which had reshaped the rubric).

## Example 1 — validated 2026-06-21

The 56MB / 10-compaction session in SKILL.md Example 1 (19,852 lines; 2.2MB
slice with 242 user turns, 1,939 assistant texts, 2,338 tool calls, 93 errors)
was the validation run for the condense-then-distill design.
