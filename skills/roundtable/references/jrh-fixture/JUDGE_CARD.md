# /roundtable JRH Judge Card — 2026-06-14

> **Historical evidence — frozen model slate.** The model identifiers, prices,
> results, and conclusions below describe the dated 2026-06-14 run. They are not
> evidence that the current production defaults have passed the same gates.

First execution of `judge-reliability-protocol.md`. Tests the per-juror **single-pass**
judging operation (Round-1-style independent verdict) — the standard JRH design — against
the three deployed jurors. NOT the full 5-round roundtable (that would be hundreds of
dollars across the fixture; the protocol's cost note + eval-shipping-discipline scope it).

## Result

| Juror | Stochastic (noise floor) | Position-flip | Position-correct | Paraphrase-stable | Verbosity-correct |
|---|---|---|---|---|---|
| claude-opus-4-8 | 3/3 (100%) | 0/3 (0%) | 3/3 | 3/3 (100%) | 3/3 (100%) |
| grok-4.20-0309-reasoning | 3/3 (100%) | 0/3 (0%) | 3/3 | 3/3 (100%) | 3/3 (100%) |
| gpt-5.5-pro | 3/3 (100%) | 0/3 (0%) | 3/3 | 3/3 (100%) | 3/3 (100%) |

Gates: position-flip <10% · paraphrase ≥80% · verbosity ≥80% · stochastic ≥80%.
**All three jurors pass all four gates.** Cost: $1.43 / $20 budget. 81 calls, 0 failures, 0 unparseable verdicts.

## What this validates

- The JRH harness works end-to-end (parse, noise-floor, 4 transforms) — instrument-audited:
  verdict tokens varied `{A:15,B:12,REFUTED:30,SUPPORTED:15}`, zero `None` parses, position
  test confirmed to track *content* across the A/B label swap (not the slot).
- No gross order/paraphrase/verbosity bias on clear-cut targets; 0% stochastic noise floor
  even at deployment temps (Grok 0.3, Opus default) — verdicts are deterministic here.
- Every verdict matches gold — the jurors are correct, not just invariant, on these items.

## What this does NOT validate (the ceiling caveat)

This is a **ceiling-bound** result: n=6 with deliberately unambiguous gold. A 100%/0%-flip
outcome on easy items cannot discriminate a well-calibrated judge from a lucky one — the
same saturation seen in the gather-research efficacy eval. The JRH bias literature finds
flips on **near-tie** cases (AgentProp-Bench κ=0.049 on hard items); this fixture has none.
**It does not validate `/roundtable`'s reliability on the methodologically-subtle targets it
is actually used for.**

## Next step (documented, not yet run)

Build a **discriminating fixture** of near-tie items where gold is defensible-but-non-obvious,
then re-run. Risk: set gold wrong and you measure disagreement-with-author, not bias — so the
gold must be independently defensible (cite a rule/standard per item). Only if jurors still
pass there is `/roundtable`'s subtle-target verdict reliability established.

## Reproduce

```bash
python3 ~/.claude/skills/roundtable/scripts/jrh_harness.py   # loads keys from Keychain, $20 cap
# outputs: /tmp/claude/jrh-results/{judge_card.json,raw.jsonl}
```

Deviation from deployment: GPT-5.5-pro ran at `reasoning_effort="medium"` (the adapter/deployed
default is "high"; "low" is rejected by the model — smoke-test 400). Per SKILL.md, medium is
1 AA-index point below high. Re-run at high if exact-deployment fidelity is required.
