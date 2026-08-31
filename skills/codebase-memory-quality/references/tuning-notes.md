# Tuning Notes

See `~/.claude/skills/_shared/tuning-notes.md` for the format and
discipline. Append a dated row when you change a threshold.

## Threshold: file-coupling score (current value: 0.5)

**Used by**: the `FILE_CHANGES_WITH` edge filter —
`WHERE r.coupling_score >= 0.5 RETURN ... ORDER BY r.coupling_score DESC LIMIT 20`
**Effect**: a coupling_score of 0.5 means file A and file B changed
together in roughly half of A's (or B's) commits. Raising (0.7+) surfaces
only strongly-coupled pairs (likely hidden dependencies); lowering (0.3)
surfaces noisier pairs (formatting sweeps, mass renames).

### Evidence
- (none — inherited)

### Open questions
- Is 0.5 anchored to a corpus measurement, or to the LIMIT 20 implicit
  display budget (i.e., "0.5 happens to surface ~20 pairs on our repos
  so the LIMIT doesn't truncate")? If the latter, both numbers should
  move together.
- Coupling has different signal across repos. The mcp-servers monorepo
  has many shared-utility files that change with everything; a 0.5
  threshold there flags noise. A per-repo override would be useful.
