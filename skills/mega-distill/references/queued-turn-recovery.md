# Queued-turn recovery — the four blind spots of the condensed slice

Relocated verbatim from `skills/mega-distill/SKILL.md` on 2026-09-04 (docs/skill-cap-decisions.md),
except that the inline heredoc sweep in the fourth section is replaced by the bundled
`scripts/recover_queued_turns.py`. All four sections serve one procedure: recover the mid-turn user
messages the condenser drops, and never report the slice `USER:` count as the session's ask count.

## Step 0.5 — A turn that TRIGGERED a compaction is not in the slice; read the boundary summary for it

**Structural blind spot — NOT a bug to fix in `transcript_condense.py`.** A message the
user sends WHILE a turn is still running is queued, and if it is what pushes the context
over the limit, the compaction consumes it: the verbatim turn then exists **nowhere** in
the transcript as a standalone `type=="user"` record. It survives only as a line item
inside the boundary record's own generated summary prose (an `isCompactSummary` record
whose `message.content` is one long string). The condenser is RIGHT not to emit that
summary — the slice exists precisely to replace it — and emitting user text from the
boundary record produces a byte-identical slice (`references/run-history.md`). A message
urgent enough to be sent mid-turn is disproportionately likely to be the session's PIVOT
— a correction, an objection, a stop — exactly the turn a recovery pass most needs.

**REQUIRED when a slice's user-turn spine ends abruptly, or the arc changes direction
with no visible cause:** read the boundary record's summary directly and mine its
enumerated user-message list. Extract the `isCompactSummary` records' `message.content`
with a small Python script (select `r.get("isCompactSummary")`, print `message.content`).

Treat that list as the ONLY record of those turns. Do NOT conclude "the user said
nothing between X and Y" from the slice alone — report "the slice has no user turn
there; the boundary summary enumerates N" and quote the summary.

---

### Second blind spot: a MID-TURN user message is dropped as injected context

Distinct mechanism from the boundary case above, same consequence. A message the user
sends WHILE a turn is running is delivered wrapped (`"The user sent a new message while
you were working:"`), which `transcript_condense.py` classifies as an **injected context
message** and DROPS. So it can be present in the live context and ABSENT from the slice —
the inverse of the boundary case, and invisible unless you look for it.

Worse, the queued-delivery path can strip a turn's ANTECEDENT: a bare `Proceed with X`
may be the tail of a question you never received, so the slice's spine is the only place
the question survives.

**REQUIRED before treating a slice's user spine as complete:**

```bash
# 1. mid-turn messages the condenser dropped
grep -c "sent a new message while you were working" <transcript>
# 2. compare the slice's spine to the transcript's own user records
grep -c "^USER: " <slice>
```

If the transcript has mid-turn deliveries the slice lacks, extract them from the raw
transcript and hand them to /distill alongside the slice. Do NOT report a user-turn count
from the slice as the session's ask count.

(Both shapes verified in one session — `references/run-history.md`.)

---

### Third blind spot: a mid-turn message delivered as `type=="queue-operation"`

The Step 0.5 probe above (`grep -c "sent a new message while you were working"`) does not
find every mid-turn message, and it fails in the most misleading way: on a transcript
containing this SKILL.md's own text, that grep returns a NONZERO count composed entirely
of **phantom self-referential hits** while the real message goes unfound. A session pivot
has been stored as `type=="queue-operation"` records with no wrapper at all
(`references/run-history.md`).

**REQUIRED — validate the probe against a known-positive, do not merely run it.** Recall a
message you know you answered, grep the raw transcript for a distinctive phrase, and
inspect the record `type`:

```bash
grep -c "<phrase you remember answering>" <transcript>   # present in the transcript?
grep -c "<phrase you remember answering>" <slice>        # did the slice keep it?
```

Then print the `type` of each matching record. Any type OTHER than `user` —
`queue-operation`, `attachment` — is a delivery shape the condenser drops; extract those
and hand them to `/distill` alongside the slice.

Do NOT report a user-turn count from the slice as the session's ask count, and do NOT
treat a nonzero wrapper-grep as proof the probe works: filter its hits to real
`type=="user"` records first, or you are counting this file.

### Fourth blind spot: `attachment` / `queued_command` — and why the phrase-probe misses it

The three probes above all require you to REMEMBER a phrase to grep for. That is the weak
link: the turns most likely to be dropped are the ones a compaction ate, which are exactly
the ones you cannot recall a phrase from. **Replace the recall-based probe with a
deterministic sweep.**

Mid-turn asks are also carried as `type=="attachment"` with
`attachment.type == "queued_command"`, often with NO `queue-operation` twin — so a probe
keyed on `queue-operation` (blind spot 3) misses them too, and the phrase-probes found none
of five dropped asks in the measured session (`references/run-history.md`).

**REQUIRED after every condense — run this; do not grep for a remembered phrase:**

**`attachment.prompt` is NOT always a string** — it is `str` on some records and a
`list` (of strings, or of `{type, text}` blocks) on others, within the SAME
transcript. A sweep that assumes `str` dies with
`AttributeError: 'list' object has no attribute 'split'`, and — the dangerous part —
wrapping that in a blanket `except Exception: continue` (as the retired inline sweep did) turns the crash
into a silent **zero recovered turns**, which reads exactly like a clean sweep.
Flatten defensively; never `try/except` around the flatten.

```bash
# Bundled, tested sweep (hooks/test-hooks/test_recover_queued_turns.py). It reads the condenser's
# manifest, verifies every listed slice, scans the raw transcript for `queue-operation` deliveries
# and `attachment`/`queued_command` prompts, flattens str | list[str] | list[{type,text}] payloads,
# and writes the prompts the slices lack. It fails CLOSED: an unsupported shape or a manifest that
# does not match the slices prints `UNVERIFIED: queued-turn evidence could not be verified` and
# exits 2 — never a silent zero.
python3 "$MEGA_DISTILL_DIR/scripts/recover_queued_turns.py" "$TRANSCRIPT" \
  --manifest "$OUTDIR/condense-manifest.json" \
  --output "$OUTDIR/recovered_user_turns.txt"
# stdout on success: {"delivery_records": N, "dropped_prompts": D, "probe_state": "verified", "unique_prompts": U}
```

Pass **both** the slice and `recovered_user_turns.txt` to `/distill`, and state the
corrected ask count explicitly (slice `USER:` count + recovered), because the slice
spine UNDERCOUNTS the session asks and `/distill` will otherwise reason about an arc
missing its pivots.

**Do NOT report the slice `USER:` count as the session ask count** — measured
undercounts of 5 and 12 asks, some of which had reshaped the session's rubric
(`references/run-history.md`).

**Sanity-check the sweep itself before trusting a zero.** A `DROPPED total: 0` on a
compacted session is more likely a broken sweep than a clean one — confirm the script
printed a nonzero `unique prompts` count first. That is the same
validate-on-a-known-positive discipline the rest of this file applies to the condenser.
