# evaluate-repos efficacy harness

See `PROBLEM.md` for the full design (oracle, fixture, metrics, the frozen 2026-05-31
baseline and its `fix` finding).

## Files
- `fixture.json` — 14 neutrally described external patterns with hindsight dispositions.
- `grade.py` — deterministic decision grader + keep/trim/fix logic (imported by
  `run_live.py` and `tests/test_evaluate_repos_efficacy.py`).
- `results.json` — the frozen, committed baseline (N=3, `claude-opus-4-8`, 2026-05-31).
  CI asserts against this file only; it is never overwritten.
- `run_live.py` — REQUIRES KEYS. Manual A/B runner; writes an explicit `--output`.
- `runs/sample-records-<date>.json` — compact, committed, re-gradeable sample.
- `runs/transcripts-<ts>.json` — gitignored raw per-run records.

## Minimum N

`PROBLEM.md` section 4 sets the protocol at **N >= 3 runs, mean + spread**. The
noise-aware verdict rules in `grade.decide_verdict` use `max(0.05, stdev)` as the noise
floor; with one run the stdev is 0, the floor collapses to the flat 0.05 bar, and a
single flipped decision out of 14 (0.071) fires a verdict.

That is what happened on 2026-09-03: the research-skill A/B rerun on `claude-fable-5-1`
ran this harness with `--runs 1` (the other four harnesses ran N=3) and reported `fix`
(over-adoption 0.143 vs 0.0) on exactly one record, `checklist-imperatives`, a decision
that had also flipped in 1 of the 3 frozen-baseline runs without moving the N=3 mean past
the floor. See `docs/research-skills-root-cause.md` section 8.

`run_live.py` therefore refuses `--runs` below `MIN_RUNS = 3`. Pass `--allow-low-n` for a
smoke or diagnostic run; the plan receipt and the written results then carry
`low_n_override: true`, and such a verdict must not be cited as a measurement.

## Validity caveat

The framework arm is an LLM auto-synthesis of the advocate/skeptic arguments. The skill as
shipped forbids that (`SKILL.md` Rules: the human is the decider), so this harness measures
a proxy, not the skill; `PROBLEM.md` section 6 records the boundary.

## Retired at this fixture (2026-09-04)

Because of that caveat the decision A/B is retired at the current fixture
(`docs/research-skills-root-cause.md` §8; `PROBLEM.md` §9). `run_live.py` prints the
notice and refuses a real run unless `--acknowledge-retired-fixture` is passed;
`--plan-only` needs no acknowledgement and its receipt reports `fixture_status: retired`.
Reopening means changing the measured unit to the advocate/skeptic arguments themselves.
