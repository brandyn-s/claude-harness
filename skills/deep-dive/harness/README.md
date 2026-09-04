# deep-dive efficacy harness

See `PROBLEM.md` for the full design (oracle, fixture, metrics, the frozen 2026-05-31
baseline and the v1 grader-bug correction).

## Files
- `fixture.json` — 15 questions (fact / false-premise / currency) with dated answer keys
  (`keys` with validity windows; `_revisions` records the lineage).
- `grade.py` — deterministic correctness + calibration analysis (imported by
  `run_live.py`, `regrade.py`, and `tests/test_deep_dive_efficacy.py`).
- `results.json` — the frozen, committed baseline (N=3, `claude-opus-4-8`, 2026-05-31). CI
  asserts against this file only; it is never overwritten.
- `run_live.py` — REQUIRES KEYS. Manual A/B runner; writes an explicit `--output`.
- `regrade.py` — offline re-grade of a transcripts or sample file with the current
  `grade.py`; never writes the frozen `results.json`.
- `runs/sample-records-<date>.json`, `runs/regrade-<date>.json` — committed, re-gradeable
  samples and their offline re-grades.
- `runs/transcripts-<ts>.json` — gitignored raw per-run records.

## Paused at this fixture (2026-09-04) — pending run-time keys

The A/B is paused, not retired. The `current-*` answer keys are being made
run-time-resolved on another branch; until that lands, the corrected grader scores both
arms 180/180 on both dates and the verdict is BLOCKED ON MEASUREMENT
(`docs/research-skills-root-cause.md` §4, §12.1; `PROBLEM.md` §9). `run_live.py` prints
the notice and refuses a real run unless `--acknowledge-retired-fixture` is passed;
`--plan-only` needs no acknowledgement and its receipt reports
`fixture_status: paused-pending-runtime-keys`.
