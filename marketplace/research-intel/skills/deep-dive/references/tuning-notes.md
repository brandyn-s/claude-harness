# Tuning Notes

See `${CLAUDE_PLUGIN_ROOT}/skills/_shared/tuning-notes.md` for the format and
discipline. Append a dated row when you change a threshold.

## Threshold: new-rate convergence gate (current value: 30%)

**Used by**: "Continue if new rate > 30%" / "Stop if new rate < 30% for
two consecutive waves." The new-rate is the fraction of sources surfaced
in this wave that were not in any prior wave.
**Effect**: raising (e.g., 50%) makes the skill more decisive — fewer
waves, more chance of premature stop. Lowering (e.g., 15%) means more
waves and diminishing-returns risk; could spend significant budget on
the last 5% of coverage.

### Evidence
- (none — inherited)

### Open questions
- Is 30% calibrated against any real research-quality outcome (e.g., did
  3-wave runs vs 5-wave runs measurably differ in finding HIGH-priority
  insights)? Worth a 5-run A/B at 30% vs 50% to decide.
- The "two consecutive waves" requirement is a sliding-window dampener.
  Is one wave enough? Three? Unclear.
