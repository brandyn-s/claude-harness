# triage efficacy harness

See `PROBLEM.md` for the full design (oracle, fixture, metrics, the frozen 2026-05-31
baseline).

## Files
- `fixture.json` — 12 abstracted findings with the expert ranking and correlation groups.
- `grade.py` — Spearman + correlation-group precision/recall/F1 and the verdict logic
  (imported by `run_live.py` and `tests/test_triage_efficacy.py`).
- `results.json` — the frozen, committed baseline (N=3, `claude-opus-4-8`, 2026-05-31). CI
  asserts against this file only; it is never overwritten.
- `run_live.py` — REQUIRES KEYS. Manual A/B runner; writes an explicit `--output`.
- `runs/sample-records-<date>.json` — compact, committed, re-gradeable sample.
- `runs/transcripts-<ts>.json` — gitignored raw per-run records.

## Retired at this fixture (2026-09-04)

The A/B is retired at the current fixture: N=3 runs of a 12-item ranking cannot resolve
the 0.02 Spearman delta between the arms, and the framework arm is a two-sentence prompt,
not the constitution (`docs/research-skills-root-cause.md` §7; `PROBLEM.md` §9).
`run_live.py` prints the notice and refuses a real run unless
`--acknowledge-retired-fixture` is passed; `--plan-only` needs no acknowledgement and its
receipt reports `fixture_status: retired`. Reopening needs the worked example removed from
`SYSTEM_WITH` and N ≥ 10.
