# Garden check family: Markers, merges, and backlogs

Operative rules live in SKILL.md (Open-Status Markers, Merge Candidates,
Cross-File Fact Duplication, Hub-Split Candidates); this file holds the
measured history and rationale behind them.

## Merge-candidate pre-filter (calibration history)

Per-topic confirmation was ~250 memory_search calls at up to 76s cold each
(observed 2026-06-16). A loose tag/title-overlap bar produced 789 pairs —
worse than 250 — because related topics share tags BY DESIGN (`absorb-*`,
`aws-deployment-*`, `terraform-ci-*` are deliberate splits, not dupes). The
precise bar (slug-prefix OR ≥3 distinctive title words) yielded ~15; adding
the ≥2-shared-tags gate at the source (2026-08-22) cut that to 6, because the
confirmation rule requires the tag bar anyway, so a below-bar pair was
unmergeable by construction. Merges are rare and the next run re-checks, so a
tight, false-negative-tolerant filter is correct.

Rank-dominance means DOMINANCE across the smaller topic's content, not one
lexically-matching entry: measured 2026-08-22, a single entry titled with the
query's exact words hit rank 1 at agreement_score 0 / result_stability 0.47 —
that is topical overlap between distinct topics, not a duplicate. The
self-topic held the highest cosine.

## Cross-file fact duplication (why backlog-only)

Backlog-only since 2026-06-08 — the prior auto-rewrite caused semantic
inversions (detail in procedures.md "Dropped and relocated checks" era
notes). The garden report notes the count only; the user reviews
`canonicalization-candidates.md` manually.

## Hub-split candidates (why dedup)

Before the dedup-by-slug rule, every run re-flagged the same mega-topics —
the accumulation pattern the backlog file exists to prevent. Remove an entry
from the backlog once its split ships.

## Open-status markers (boundary rationale)

Within-page flipping is the only safe auto-close: cross-page or world-state
reconciliation (PR merged? dep bumped? gate wired?) needs network/MCP/gh and
risks false `RESOLVED` flips that corrupt the inventory — worse than an
honest stale marker. That reconciliation is the 2026-06-07 rot-audit role, a
SEPARATE pass. When unsure whether an undated line is a state-claim, date it
and keep it OPEN — a dated maybe-gap is recoverable; a wrongly-demoted gap is
not greppable.

`open_markers_over_90d` is the filtered row list (oldest first, same row
shape as `open_markers`). It was a count-only int until 2026-08-22, which
crashed the first consumer that iterated it.
