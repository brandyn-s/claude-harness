# Tuning Notes

See `${CLAUDE_PLUGIN_ROOT}/skills/_shared/tuning-notes.md` for the format and
discipline. Append a dated row when you change a threshold.

## Threshold: candidate match (current value: 0.7 cosine)

**Used by**: Step 3 — "A semantic match > 0.7 cosine is a candidate even if
keywords don't overlap."
**Effect**: lowering pulls in more weak candidates (more reading, more
false-merges); raising risks missing valid matches that use different
vocabulary.

### Evidence
- (none — inherited)

### Open questions
- No precision/recall data exists for this gate. Worth a one-time sample
  measurement: for the next ~50 captures, log whether the 0.7 candidate
  was a true match (would have led to dedup or contradiction) vs a false
  positive (different topic, just shared vocabulary). After 50 samples,
  decide whether to tighten or loosen.

## Threshold: skip-as-duplicate (current value: 0.85 cosine)

**Used by**: Step 3 dedup gate — "If a result scores > 0.85 cosine
similarity covering the same concept: skip and report 'Skipped: [title] —
equivalent to [matched title]...'"
**Effect**: lowering causes legitimate updates to be silently skipped
(near-misses on different aspects of the same topic); raising causes
near-duplicates to slip through into the knowledge base.

### Evidence
- (none — inherited)

### Open questions
- The 0.55–0.85 "read and decide" band is the safety net; the open
  question is whether the band is wide enough or too wide. A maintainer
  reviewing 10 consecutive skip decisions for false-skip risk would
  resolve this.

## Threshold: contradiction-search match (current value: 0.65 cosine)

**Used by**: Step 4a contradiction check — query with the new claim
phrased as its opposite; for each result with cosine > 0.65 sourced
from the same topic page, read and determine if contradiction.
**Effect**: lowering increases false-contradiction alarms (you spend
review time on entries that aren't really contradictions); raising
misses real contradictions phrased in different language.

### Evidence
- (none — inherited)

### Open questions
- Why this threshold differs from the 0.7 candidate-match threshold is
  undocumented. The lower value here might reflect that opposite-phrased
  queries embed further from the source than direct queries — but that's
  speculative. A measurement comparing the two would either confirm the
  delta or argue for unifying them.
