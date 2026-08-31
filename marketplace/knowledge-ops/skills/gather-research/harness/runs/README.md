Raw per-run A/B transcripts land here (run_live.py). Git-ignored except this file — they're auditability artifacts, not committed baselines.

## Frozen baseline for CI

The file `sample-records-2026-05-31.json` is a **committed baseline** required by the CI test (`tests/test_gather_research_efficacy.py`). It contains the hand-labeled fixture claims and reference verdicts used for A/B efficacy measurement.

### Refreshing the baseline

When refreshing `results.json` via `python3 skills/gather-research/harness/run_live.py` (N=3 full run), the script writes raw transcripts as a LIST of `{run_idx, records}` to `transcripts-<timestamp>.json`. To update the frozen `sample-records-*.json` baseline:

1. Run the live A/B script to completion (writes new `results.json` and `transcripts-*.json`)
2. Extract the records from the `transcripts-*.json` and reshape to the baseline format: a DICT `{_about, runs: [{run_idx, records}]}` with `confidence` and `_text` fields stripped from each record
3. Commit the reshaped file as `sample-records-YYYY-MM-DD.json` and update the test's hardcoded filename

The baseline shape and committed results.json fixture_sha serve as CI's immutable verification point; the N-run transcripts themselves are ephemeral (git-ignored) but persisted locally for manual inspection.
