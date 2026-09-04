# gather-research efficacy harness

See `PROBLEM.md` for the full design (oracle, fixture, metrics, the frozen 2026-05-31
baseline).

## Files
- `fixture.json` — 15 hand-labeled research claims in 4 categories + ground truth.
- `grade.py` — deterministic grounding + verdict-decision logic (imported by `run_live.py`
  and `tests/test_gather_research_efficacy.py`).
- `results.json` — the frozen, committed baseline (N=3, `claude-opus-4-8`, 2026-05-31). CI
  asserts against this file only; it is never overwritten.
- `run_live.py` — REQUIRES KEYS. Manual A/B runner; writes an explicit `--output`.
- `runs/sample-records-<date>.json` — compact, committed, re-gradeable sample.
- `runs/transcripts-<ts>.json` — gitignored raw per-run records.

## Retired at this fixture (2026-09-04)

The A/B is retired at the current fixture: both arms score 180/180 on Opus 4.8 and on
Fable 5.1, so the fixture cannot distinguish them (`docs/research-skills-root-cause.md`
§6; `PROBLEM.md` §9). `run_live.py` prints the notice and refuses a real run unless
`--acknowledge-retired-fixture` is passed; `--plan-only` needs no acknowledgement and its
receipt reports `fixture_status: retired`. Reopening needs a fixture on which the baseline
is below 1.0 and a label-level metric.
