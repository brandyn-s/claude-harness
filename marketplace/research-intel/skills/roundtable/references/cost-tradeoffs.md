# Cost / time tradeoffs

> **Historical evidence — do not use as a current quote.** These measurements
> preserve the model slate and prices used by the dated experiments. Re-run the
> cost and reliability harness before applying them to the current defaults.

Empirical from v1 + v2 experiments (target: /persona + /plateau-diagnose review, ~5,000-word context). Measured with Opus 4.7 as the Anthropic agent and the pre-2026-08 Grok/GPT pins. The current default slate (Fable 5 $10/$50, Grok 4.6 $2/$6, GPT-5.6 Sol $5/$30 per MTok) prices differently in every column — notably Grok dropped ~60x and GPT ~6x versus the rates behind this table — so treat the totals as protocol-shape evidence only. The harness PRICING constant (harness.py) carries the current rates.

## Baseline costs per round

| Round | Phase | Opus 4.7 | Grok 4.20-r | GPT-5.5-pro | Total |
|---|---|---:|---:|---:|---:|
| 1 | main | $0.06 | $0.20 | $0.80 | $1.06 |
| 2 | main | $0.50 | $1.90 | $0.77 | $3.16 |
| 3 | prereg | $0.44 | $1.86 | $0.47 | $2.77 |
| 3 | main | $0.74 | $2.79 | $0.78 | $4.30 |
| 4 | prereg | $0.63 | $2.74 | $0.77 | $4.14 |
| 4 | main | $0.86 | $3.58 | $1.08 | $5.51 |
| 5 | prereg | $0.81 | $3.69 | $0.93 | $5.43 |
| 5 | main | $1.12 | $4.73 | $1.23 | $7.08 |

Costs grow because cumulative round history grows in each prompt (R5 main prompts are ~150K chars).

## Total cost by configuration

| Configuration | Cost | Wall time | Notes |
|---|---:|---:|---|
| 5 rounds, no prereg, no Agent D | ~$13 | ~12 min | v1 baseline |
| 5 rounds, prereg R3-R5, Agent D R1 | ~$32 | ~25 min | v2 baseline |
| 5 rounds, prereg R3-R4 only, Agent D | ~$25 | ~20 min | recommended default (R5 prereg dropped) |
| 4 rounds, auto-stop, no Agent D | ~$15-20 | ~12 min | budget-conscious |
| 3 rounds, no prereg, no Agent D | ~$8-10 | ~8 min | minimum useful |
| 5 rounds, star topology | ~$19-25 | ~22 min | `--topology=star`: ~25% cheaper. Drops Grok-GPT direct cross-exposure (they only see Opus). Untested empirically; dynamics may differ |

## What each addition buys

| Addition | Cost | Value |
|---|---:|---|
| Pre-reg R3-R4 | +$3-5 | Conformity-vs-correctness diagnostic. High value first time; lower for repeat targets where the user trusts the protocol. |
| Agent D null-control | +$0 (R1 is small) | Confabulation-resistance diagnostic. Cheap and high-information. Worth it for any high-stakes review. |
| Falsifier requirement | +$0 (prompt change only) | Improves calibration without adding calls. Worth it always. |
| Auto-stop on convergence | -$5-10 | Saves cost by halting early when positions stabilize. Requires VOYAGE_API_KEY. Worth it always. |
| 5th round | +$5-7 | Marginal — v2 R5 deltas were ~0%. Drop if budget-constrained. |

## When to drop configuration

- **Budget < $10**: max-rounds 3, no prereg, no Agent D. You're getting independent-then-synthesize with light cross-talk.
- **Budget $10-20**: max-rounds 4, no prereg, with Agent D, auto-stop. Most of the value at half the cost.
- **Budget $20-30**: max-rounds 5, prereg R3-R4 only, Agent D, auto-stop. The recommended default — captures the calibration signal without paying for R5 prereg.
- **Budget unlimited / audit-class review**: full v2 protocol. Maximum diagnostic.

## Hidden costs (not in token spend)

- **Agent D template generation**: requires the orchestrating model to write the fake R1 (5-10 min of context). Not in API cost but real time.
- **Reading META_SYNTHESIS.md**: ~10 min reading + ~5 min cross-checking single-source findings against actual source.
- **Acting on findings**: the protocol's value is realized only if you act on the recommendations. A roundtable that surfaces 6 actionable findings the user doesn't act on has zero ROI.

## ROI heuristic

Roundtable is worth it when:

- You'd otherwise spend >2 hours reviewing the target manually
- The decision affects production code, shipped methodology, or marketplace skills
- Multiple stakeholders disagree and you need triangulation
- The cost of being wrong (shipping a bad skill, missing a security issue) exceeds $200

Not worth it when:

- The decision is reversible at low cost
- The target has been reviewed by a domain expert recently
- You'd take the recommendations on faith without acting on them

## 2026-08-30 live requalification (historical evidence)

The first live requalification recorded in SKILL.md ran with `claude-fable-5`
as the Anthropic arm (`high` effort) alongside grok-4.6 and gpt-5.6-sol:
$5.45 total across 21 provider calls, of which the Anthropic arm was $3.69.
On 2026-09-04 `contracts/model-capabilities.json` moved Claude Fable 5 to
`superseded` and the adapter default followed the contract to
`claude-fable-5-1`, which the vendor prices identically per token; no live run
has been repeated on it yet, so treat the figures above as the predecessor's.
