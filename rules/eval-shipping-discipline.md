@rule eval_shipping_discipline
@version 2026-08-09
@scope every metric-driven production default or PR ship decision, wherever the changed source file lives; every metric-backed claim that changes production behavior; every grade-bearing evaluation

# Global eval decision contract

This rule is intentionally global. A resolver, default, prompt, policy, or other
production source change can be justified by an eval without touching an `eval/`
path. Apply these gates to the decision, not only to files in the harness.

Full procedures, examples, recovery paths, and incident rationale:
`docs/rule-reference/eval-shipping-discipline.md`.

## Ship gates: evidence before a production decision

For every metric-driven production default or PR ship decision:

1. Preserve per-query data beside aggregate metrics. If the harness emits only
   aggregates, fix the harness first.
2. Compute the paired bootstrap CI on the per-query delta with
   `n_bootstraps >= 10000`; report the point estimate, 95% interval, sample
   count, and whether the interval excludes zero. A policy threshold alone is
   not a significance test.
3. Validate both the off-mode and the actual production-mode when the
   production stack can alter ordering or outcomes. A blocked production-mode
   run blocks shipping unless the user explicitly authorizes that named risk.
4. Measure every affected fixture before changing a resolver, extractor,
   scorer, prompt, or other shared default. A local improvement does not erase
   regressions elsewhere.
5. Make the decision explicit: ship default-on or retire. Do not leave a
   metric-backed improvement as an opt-in or canary that never resolves the
   production decision.

You must fail closed when per-query evidence, the paired comparison, affected-fixture
coverage, or production-stack validation is missing. Do not substitute a
passing threshold, an aggregate-only average, API cost, schedule pressure, or
the claim that the reranker "will not matter."

These gates do not apply to a hotfix revert, a bug fix that restores an already
validated baseline, directly observed operational metrics, or a security or
correctness fix with no improvement claim. Do not use an exception to conceal
a metric-backed behavior change.

## Retirement and extrapolation gates

Before a pre-implementation retirement justified by an analogous experiment,
perform an axis audit across model/version, mechanism, input substrate, corpus,
metric, prompt/interaction format, and label source. When two or more axes
differ and the empirical run is bounded (under one hour, under $20 API cost,
and non-destructive), run it. Search sibling repos and prior evidence before
claiming that required inputs do not exist. If retirement rests on one axis,
name that axis in the decision record.

## Oracle and rater gates

- An LLM judge must receive an independent candidate pool, not the output of
  the engine being graded. Shuffle candidates, strip rank/score/provenance,
  and blind-recheck a sample before publishing grade-bearing labels.
- An LLM-rater count is provider-dependent. Compare the ratio/set under the
  same rater, confirm a load-bearing direction with a second rater from a
  different provider, and mechanically ground the finding set.
- A carried-forward artifact is not an oracle until it passes a
  self-consistency check. Separate copied rows from computed rows and score the
  computed subset. If self-consistency fails, use a small hand-verified
  ground-truth fixture; label the historical comparison as drift, not
  correctness.
- Behavioral evidence can have selection bias because unsuccessful sessions
  may leave no follow-through signal. Include no-follow-through and alternate-
  follow-through cases; publish the expanded population grade, not only the
  easy observed subset.

## Experiment-design and stopping gates

- After three consecutive regressions in one lever class, confirm the stop signal
  (begin stopping after the second): record the mechanism, stop same-class
  tuning, propose a structural alternative, or accept the measured ceiling.
- Multi-arm comparisons must score every arm at the same depth. Budget-gated
  arms must use the same instance order or a pre-pinned shared subset. Define
  both controls before launching the arms.
- Always commit the instrument, not just the number: the PR citing a measurement must
  contain the harness, exact prompt/config arms, dated results, engine and
  corpus identity, plus a greppable record of rejected decisions. A scratch or
  temporary harness cannot support a production claim.

## Handoff contract

Before recommending or merging a covered change, state which gates were run,
link the committed evidence and instrument, name any blocked gate, and withhold
the ship recommendation while a required gate is blocked. Load the full
reference above whenever designing the evaluation, adjudicating an exception,
or recovering from a failed gate.
