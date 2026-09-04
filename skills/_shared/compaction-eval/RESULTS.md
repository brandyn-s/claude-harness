# Compaction priorities A/B: results

Two planted-fact fixtures, same question shape (22 questions in 7 categories), same
arms, same grader. Both measured 2026-09-04 with `claude-fable-5-1` (requested
`claude-fable-5-1`; qualification `valid`, refusal `not_refused`, fallback
`not_used`), 3 paired runs each, summarizer effort `medium`, reader effort `low`,
`--max-tokens 16000`; hook text `1027327f407a` (1557 bytes). Producer
`run_live.py --fixture {coding,incident}`, scorer `grade.py`, verdict rule
`skills/_shared/stats.py` paired bootstrap on overall recall, pooled verdict
`combine_results.py`. Both arms receive the transcript as real alternating
messages plus Claude Code 2.1.260's own compaction prompt (`compact_prompt.py`); the
with_priorities arm appends the hook's stdout exactly where production does
(`Additional Instructions:`).

| fixture | files | transcript | tokens (exact) | what it is |
|---|---|---|---|---|
| coding (`a7b9e97e16b2`) | `fixture.py`, `results.json` | 66 turns | 19,581 | flaky integration test in a Python/Postgres service |
| incident (`68d5e4346975`) | `fixture_incident.py`, `results-incident.json` | 64 turns | 27,089 | production 5xx incident: Helm release, Redis `maxclients`, Istio, RBAC |

## Combined verdict: **keep** (both fixtures, pooled CI excludes 0)

Overall recall = share of the 22 planted facts a reader recovered from the
`<summary>` body alone, answering UNKNOWN when absent. Reproduce the tables with
`python3 skills/_shared/compaction-eval/combine_results.py results.json results-incident.json --markdown`
(run from this directory).

| fixture | n | baseline mean | with_priorities mean | delta mean | 95% CI | verdict |
|---|---|---|---|---|---|---|
| coding (`a7b9e97e16b2`) | 3 | 0.894 | 0.985 | +0.0909 | [0.0455, 0.1364] | keep |
| incident (`68d5e4346975`) | 3 | 0.879 | 1.000 | +0.1212 | [0.0909, 0.1818] | keep |
| **pooled** | 6 | 0.886 | 0.992 | +0.1061 | [0.0758, 0.1439] | **keep** |

Pooled paired deltas (with_priorities minus baseline, run by run): +0.136, +0.091,
+0.045 (coding), +0.182, +0.091, +0.091 (incident). Every one of the six paired runs
favours the hook; the smallest delta is one question (+0.045). The pooled lower
bound, +0.076, is about 1.7 of the 22 planted facts per compaction.

| category (questions) | coding baseline | coding with | incident baseline | incident with | pooled baseline | pooled with |
|---|---|---|---|---|---|---|
| identifiers (6) | 0.944 | 0.944 | 1.000 | 1.000 | 0.972 | 0.972 |
| errors (4) | 0.750 | 1.000 | 0.333 | 1.000 | 0.542 | 1.000 |
| questions (3) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| root_causes (3) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| hypotheses (2) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| decisions (3) | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| subagent (1) | 0.000 | 1.000 | 1.000 | 1.000 | 0.500 | 1.000 |

The two fixtures lose different things at baseline and the hook recovers both:
verbatim error lines on both transcripts (the whole incident effect), and the
subagent-only number on the coding transcript. Identifiers, unanswered questions,
file:line root causes, ruled-out hypotheses and A-vs-B decisions were already
preserved by the default template on both transcripts, so those categories cannot
show a difference here (ceiling), and none moved down.

## Fixture 1: coding (`results.json`)

| arm | run 1 | run 2 | run 3 | mean |
|---|---|---|---|---|
| baseline (default compaction prompt) | 0.864 | 0.909 | 0.909 | 0.894 |
| with_priorities (default + hook text) | 1.000 | 1.000 | 0.955 | 0.985 |

Paired deltas +0.136, +0.091, +0.045 (mean +0.0909); 95% CI [0.0454, 0.1364], n=3,
which excludes 0 in the favorable direction, so the shared CI rule says keep.

Baseline missed: err4 (3/3), id3 (1/3), sub1 (3/3). with_priorities missed: id3 (1/3).
`err4` is the verbatim final `ERROR:` line of the failed Docker build; `sub1` is the
`214` test modules that only the Explore subagent reported. Those are two of the five
priorities the hook adds (quote error lines verbatim; carry subagent reports
forward). `id3` (the regression commit sha) was dropped once by each arm: shared
noise, not a treatment effect.

## Fixture 2: incident (`results-incident.json`)

| arm | run 1 | run 2 | run 3 | mean |
|---|---|---|---|---|
| baseline (default compaction prompt) | 0.818 | 0.909 | 0.909 | 0.879 |
| with_priorities (default + hook text) | 1.000 | 1.000 | 1.000 | 1.000 |

Paired deltas +0.182, +0.091, +0.091 (mean +0.1212); 95% CI [0.0909, 0.1818], n=3;
verdict keep.

Baseline missed only error lines: err2 (3/3, the Envoy `upstream connect error ...
delayed connect error: 111` text), err4 (3/3, the kubectl `Error from server
(Forbidden): pods "session-store-0" is forbidden ...` line), err1 (1/3, the Redis
`max number of clients reached` line) and err3 (1/3, the Helm `another operation
(install/upgrade/rollback) is in progress` line). The default template's summaries
paraphrased them, which the verbatim grader correctly rejects: a resumed session
cannot grep for a paraphrase. with_priorities quoted all four in 3/3 runs. Unlike
the coding transcript, the baseline kept the subagent-only number here (the `1731`
sessions sat in a short, prominent report), so that category shows no gap on this
fixture.

## Replication and smoke history (coding fixture)

- Run 1 (same day, same settings, 3 paired runs, $4.81): baseline
  0.909 | 0.909 | 0.909, with_priorities 1.000 | 1.000 | 1.000; baseline missed
  err4 and sub1 on every run, with_priorities missed nothing. Its fixture differed
  from the committed one only in the `[gwN]` xdist worker tags of 16 log lines: the
  generator used `hash(name) % 4`, which Python salts per process, so that run's
  fixture sha (`7220f95d7103`) cannot be rebuilt. The bug is fixed (crc32) and
  guarded by `test_fixture_is_deterministic_across_processes`; run 2 (the committed
  `results.json`) is the measurement in the tables above.
- Smoke (one run, `--max-tokens 4000`, $0.92): BOTH arms truncated on max_tokens
  (Fable 5.1's thinking shares the budget). Baseline was cut inside section 2;
  with_priorities was cut before `<summary>` opened, so its `<analysis>` block was
  what the reader saw and it scored 0.64 vs 0.23 -- an artifact, not a result.
  Truncated summaries are now invalid trials and the default budget is 16000.

## What it costs

- Prompt: about 500 extra input tokens per compaction (with_priorities prompt
  7,538 chars vs 5,955, both fixtures).
- Summary length: coding 13,810 vs 12,026 chars (+15%), 9,799 vs 9,201 summarizer
  output tokens including thinking (+6%); incident 13,627 vs 10,437 chars (+31%),
  9,437 vs 7,554 output tokens (+25%). The longer summary is the mechanism and also
  the price: it occupies more of the post-compaction window, more so when the
  transcript carries many long error lines to quote.
- Measurement spend: coding run 2 $4.71 (170,254 input, 60,246 output tokens, 12
  calls; worst-case estimate $11.92 against a $15 cap), run 1 $4.81, smoke $0.92;
  incident $4.83 (212,073 input, 54,276 output tokens, 12 calls; worst-case
  estimate $12.37 against a $15 cap). Total $15.27.

## Caveats

1. Two synthetic fixtures. Realistic in shape and size and from two different
   domains (a coding session and an infrastructure incident), but both authored by
   the same hand with the same seven fact classes; real sessions plant facts in
   other shapes. The categories the hook recovered are the ones these transcripts
   bury hardest: long shell/proxy error lines, and a number in one tool result.
2. Ceiling. Baseline already recovers 19-20 of 22 on both transcripts, so the
   headroom was two to four questions per fixture and the hook took all of it; the
   effect cannot exceed the headroom, and five of seven categories are at 1.0 in
   both arms on both fixtures.
3. n=3 per fixture, 6 pooled (plus a 3-run replication on the coding fixture with
   identical outcomes): consistent directional evidence across domains, not a
   population estimate.

## Recommendation

Ship on by default. The hook is 1,557 static bytes, always exits 0, costs about
500 prompt tokens and a 15-31% longer summary per compaction, and across nine
paired trials on two transcripts recovered every verbatim error line and the
subagent number, with no category mean lower than baseline anywhere. Re-run
`run_live.py --fixture coding` and `--fixture incident` (about $5 each) when the
compaction template or the hook text changes, then `combine_results.py` for the
pooled verdict.
