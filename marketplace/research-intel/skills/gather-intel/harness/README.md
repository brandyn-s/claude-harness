# gather-intel efficacy harness

See `PROBLEM.md` for the full harness design (fixture, metrics, frozen baseline).

## Files
- `fixture.json` — 15 hand-curated community claims + ground truth.
- `grade.py` — deterministic grounding + verdict-decision logic (imported by both
  `run_live.py` and `tests/test_gather_intel_efficacy.py`).
- `results.json` — the frozen, committed baseline (N=3, `claude-opus-4-8`,
  2026-05-31). CI asserts against this file only; never overwritten by CI.
- `run_live.py` — REQUIRES KEYS. Manual keyed refresh of `results.json`.
- `runs/sample-records-<date>.json` — a compact, committed re-gradeable sample
  (Phase-9 "REAL vs INSTRUMENT" check) that lets the test suite re-derive
  `results.json`'s metrics without live API calls.
- `runs/transcripts-<ts>.json` — gitignored raw per-run transcripts written by
  `run_live.py` (see `runs/.gitignore`); not committed.
- `regrade.py` — OFFLINE re-grade (no API calls, no fetches) of a transcripts or
  sample file with the current `grade.py`; writes a results-shaped
  `runs/regrade-<date>.json` and optionally the compact sample. Never writes the
  frozen `results.json`.
- `runs/regrade-2026-09-03.json` + `runs/sample-records-2026-09-03.json` — the
  2026-09-03 `claude-fable-5-1` rerun re-graded under the corrected oracle
  (`docs/research-skills-root-cause.md` section 12).

## Oracle revisions

`fixture.json` carries a `_revisions` lineage. The frozen `results.json` was measured
against fixture `6a017f97d139`; the 2026-09-03 revision marked
`three-workers-sweetspot` `groundable: false` (its `grounding_terms` were the verbatim
phrase from one repo that no arm ever cited: 0/11 supported records grounded across both
runs). The CI freshness test accepts a `fixture_sha` anywhere in the lineage, and the
reproducibility test compares the frozen sample to the frozen numbers except where the
revision's `frozen_sample_regrade` documents the change (grounding_precision
0.878/0.833 -> 1.0/1.0; the other four metrics are unchanged).

## Refreshing the committed sample after a live re-run

1. Run `run_live.py` (keyed) to produce a new `results.json` and a new
   `runs/transcripts-<ts>.json`.
2. `transcripts-<ts>.json` is a top-level LIST of `{"run_idx": N, "records": [...]}`.
   The committed sample format the tests read is a DICT: `{"runs": [<same run
   objects>]}`. Wrap the transcripts list under a `"runs"` key (dropping each
   record's `"_text"` field keeps the sample compact) and save as
   `runs/sample-records-<date>.json`:

   ```python
   import json
   t = json.load(open("harness/runs/transcripts-<ts>.json"))
   runs = [{"run_idx": r["run_idx"],
            "records": [{k: v for k, v in rec.items() if k != "_text"}
                        for rec in r["records"]]}
           for r in t]
   json.dump({"runs": runs}, open("harness/runs/sample-records-<date>.json", "w"),
             indent=2)
   ```

3. Delete the superseded `runs/sample-records-<old-date>.json` and commit the
   new one alongside the refreshed `results.json`.
4. If the verdict changed, update `EXPECTED_VERDICT` in
   `tests/test_gather_intel_efficacy.py` and the frozen-baseline table in
   `PROBLEM.md` / `SKILL.md`.

## Retired at this fixture (2026-09-04)

The A/B is retired at the current fixture: the baseline is at ceiling on Fable 5.1 and,
under the corrected oracle, the arms are identical on the primary metric
(`docs/research-skills-root-cause.md` §5, §12.2; `PROBLEM.md` §9). `run_live.py` prints
the notice and refuses a real run unless `--acknowledge-retired-fixture` is passed;
`--plan-only` needs no acknowledgement and its receipt reports `fixture_status: retired`.
The refresh procedure above stays valid for the day a discriminating fixture exists.
