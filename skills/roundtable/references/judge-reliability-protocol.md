# /roundtable judge-reliability protocol (JRH-style)

> **STATUS: RUN 2026-06-14 (crisp-target instantiation).** All 3 jurors passed all 4 gates
> on a 6-item unambiguous-gold fixture ($1.43). Result is **ceiling-bound** — validates the
> harness + rules out gross bias on clear cases, does NOT yet validate subtle-target
> reliability. See `jrh-fixture/JUDGE_CARD.md`. Next step: discriminating near-tie fixture.

Validate the reliability of `/roundtable`'s adversarial-judge verdicts before trusting them,
per the Judge Reliability Harness (JRH, arXiv:2603.05399) and the LLM-judge-bias literature
(AgentProp-Bench: substring judging κ=0.049 chance-level, 3-LLM ensemble κ=0.432;
Bias-in-the-Loop arXiv:2604.16790: prompt bias can flip model rankings).

## Why `/roundtable` specifically
`/fp-check` is already an **Agent-as-a-Judge** (tool-grounded: data-flow + exploitability +
PoC-builder subagents) — the frontier (survey arXiv:2601.05111) rates that *more* reliable
than LLM-as-judge, so it needs less validation. `/roundtable` is an **LLM-jury** (Opus + Grok
+ GPT producing verdicts on a target) — exactly the single/multi-LLM-judge class JRH targets.

## The 4 reliability tests (run on a frozen fixture of 8–12 past roundtable targets)
1. **Position/order invariance** — swap the order claims/options are presented; measure
   verdict flip-rate. >10% flip = order bias.
2. **Paraphrase invariance** — re-word the target without changing meaning; measure verdict
   stability.
3. **Verbosity bias** — pad the target with semantically-empty length; measure score
   inflation (length-controlled win rate).
4. **Stochastic stability** — re-run the SAME target N=3 at temp 0; measure verdict
   consistency.

## Fixture + scoring
- Fixture: 8–12 targets from past `/roundtable` runs with an agreed "gold" verdict, stored
  under `skills/roundtable/references/jrh-fixture/`.
- Per test: pass-rate + CI; aggregate into a **Judge Card** (per JRH).
- Gate: if any test < 80% stability, the roundtable verdict on that dimension is unreliable —
  report verdicts with the measured bias band, or add anonymization / order-swap /
  length-control to the roundtable prompt (the documented JRH/D3 mitigations).

## Cost note (why this is scoped, not auto-run)
A full run invokes `/roundtable` (3 frontier LLMs × multi-round) per fixture item — real API
spend. This protocol is **ready-to-run**; execute it as a deliberate, budgeted experiment
(eval-shipping-discipline) rather than inline. Cheapest first probe: the position-invariance
test on ONE past target (a single re-run with swapped option order).
