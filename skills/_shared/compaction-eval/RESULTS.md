# Compaction priorities A/B: results

Measured 2026-09-04, `claude-fable-5-1` (requested `claude-fable-5-1`; qualification
`valid`, refusal `not_refused`, fallback
`not_used`), 3 paired runs, summarizer effort
`medium`, reader effort `low`, `--max-tokens 16000`.
Fixture `a7b9e97e16b2` (66 turns, 19,581 transcript tokens exact, 22 questions); hook
text `1027327f407a` (1557 bytes). Producer `run_live.py`, scorer `grade.py`,
verdict rule `skills/_shared/stats.py` paired bootstrap on overall recall. Both arms
receive the transcript as real alternating messages plus Claude Code 2.1.260's own
compaction prompt (`compact_prompt.py`); the with_priorities arm appends the hook's
stdout exactly where production does (`Additional Instructions:`).

## Verdict: **keep**

Overall recall (share of the 22 planted facts a reader recovered from the
`<summary>` body alone, answering UNKNOWN when absent):

| arm | run 1 | run 2 | run 3 | mean |
|---|---|---|---|---|
| baseline (default compaction prompt) | 0.864 | 0.909 | 0.909 | 0.894 |
| with_priorities (default + hook text) | 1.000 | 1.000 | 0.955 | 0.985 |

Paired deltas +0.136, +0.091, +0.045 (mean +0.0909); 95% CI [0.0454, 0.1364], n=3, which excludes 0 in the
favorable direction, so the shared CI rule says keep.

## Per-category recall (mean over 3 runs)

| category (questions) | baseline | with_priorities |
|---|---|---|
| identifiers (6) | 0.944 | 0.944 |
| errors (4) | 0.750 | 1.000 |
| questions (3) | 1.000 | 1.000 |
| root_causes (3) | 1.000 | 1.000 |
| hypotheses (2) | 1.000 | 1.000 |
| decisions (3) | 1.000 | 1.000 |
| subagent (1) | 0.000 | 1.000 |

Baseline missed: err4 (3/3), id3 (1/3), sub1 (3/3). with_priorities missed: id3 (1/3).
`err4` is the verbatim final `ERROR:` line of the failed Docker build; `sub1` is
the `214` test modules that only the Explore subagent reported. Those are two of
the five priorities the hook adds (quote error lines verbatim; carry subagent
reports forward). `id3` (the regression commit sha) was dropped once by each
arm: shared noise, not a treatment effect. Everything else -- the other ids,
file:line root causes, unanswered questions, ruled-out hypotheses and A-vs-B
decisions -- was already preserved by the default template on this transcript,
so those categories cannot show a difference here.

## Replication

- Run 1 (same day, same settings, 3 paired runs, $4.81): baseline
  0.909 | 0.909 | 0.909, with_priorities 1.000 | 1.000 | 1.000; baseline missed
  err4 and sub1 on every run, with_priorities missed nothing. Its fixture differed
  from the committed one only in the `[gwN]` xdist worker tags of 16 log lines: the
  generator used `hash(name) % 4`, which Python salts per process, so that run's
  fixture sha (`7220f95d7103`) cannot be rebuilt. The bug is fixed (crc32) and
  guarded by `test_fixture_is_deterministic_across_processes`; run 2 above is the
  committed measurement.
- Smoke (one run, `--max-tokens 4000`, $0.92): BOTH arms truncated on max_tokens
  (Fable 5.1's thinking shares the budget). Baseline was cut inside section 2;
  with_priorities was cut before `<summary>` opened, so its `<analysis>` block was
  what the reader saw and it scored 0.64 vs 0.23 -- an artifact, not a result.
  Truncated summaries are now invalid trials and the default budget is 16000.

## What it costs

- Prompt: about 500 extra input tokens per compaction (with_priorities prompt
  7,538 chars vs 5,955).
- Summary: 13,810 vs 12,026 chars on average
  (+15%), 9,799 vs 9,201 summarizer output tokens
  including thinking (+6%). The longer summary is the mechanism and
  also the price: it occupies more of the post-compaction window.
- Measurement spend: run 2 $4.71 (170,254 input,
  60,246 output tokens, 12 calls; worst-case estimate $11.92
  against a $15 cap), run 1 $4.81, smoke $0.92; total $10.44.

## Caveats

1. One synthetic fixture. Realistic in shape and size, but a single session; the
   two recovered categories are the ones this fixture plants hardest (a long shell
   error line, a number buried in one tool result). Other sessions move other
   questions.
2. Ceiling. Baseline already recovers 20 of 22, so the headroom was two questions
   and the hook took both; the effect cannot exceed the headroom.
3. n=3 (plus a 3-run replication) with identical outcomes: consistent directional
   evidence, not a population estimate. A point-width CI means zero sampling
   variance on this fixture, nothing more.

## Recommendation

Ship on by default. The hook is 1,557 static bytes, always exits 0, costs about
500 prompt tokens and a roughly 15% longer summary per compaction, and across
both 3-run samples recovered the verbatim error line and the subagent number in
six of six paired trials, with no category mean lower than baseline. Re-run
`run_live.py` (about $5) when the compaction template or the hook text changes.
