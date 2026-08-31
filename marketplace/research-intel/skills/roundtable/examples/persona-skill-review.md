# Worked example: /persona + /plateau-diagnose review

> **Historical evidence — frozen experiment narrative.** Model names and
> behavior observations below identify the models that actually produced these
> runs; they do not describe or qualify the current production panel.

The protocol was developed by running this exact target. Two iterations of the
roundtable shipped final docs into the knowledge base:

- **v1**: 5 rounds adversarial, no pre-reg, no null control (Grok 4.3). ~$13 spent.
- **v2**: 5 rounds + pre-reg R3-5 + Agent D injection (Grok 4.20-reasoning). ~$32 spent.

Persistent docs in `~/Documents/knowledge-base/research/` (claude-knowledge-base
PR #377):
- `2026-05-02-roundtable-v1-synthesis.md` — v1 META_SYNTHESIS
- `2026-05-02-roundtable-v2-synthesis.md` — v2 META_SYNTHESIS with pre-reg delta
  analysis and Agent D detection table
- `2026-05-02-persona-recommendations.md` — final P0/P1/P2/P3 recommendations
  derived from both runs (10 shipped in claude-config PR #813; 4 deferred per
  `skills/persona/references/_runbook-deferred.md`)

## What the runs surfaced

**Convergent (3-of-3, all 5 rounds, both versions)**:
- DISPATCH_PROMPT_TEMPLATE doc-vs-code drift (calibration tags missing from runtime)
- Validate mode missing from CLI argparser
- Methodology overfit to single telegraphing fixture (M4/M5/F6 all on same source)
- Recursion: auto-promotion of red-team-rubric-discipline.md from N=1 recurrence

**Divergent (survived all rounds)**:
- /plateau-diagnose disposition: Opus + Grok say demote to rule; GPT says keep-if-narrowly-scoped. Resolution: AGREE TO DISAGREE — depends on Claude Code invocation patterns.
- Closed-context dispatch materiality: GPT says material limitation; Opus + Grok say intentional design. Resolution: EXPERIMENT proposed (problem-only vs context-bundle vs tool-using A/B).

**New from cross-talk (v1)**:
- Bucket-coverage tautology: even a perfect fixture wouldn't fix N=11 saturation, because saturation is mechanically guaranteed against the curator's own ontology
- Context-bundle middle path: orchestrator-generated archived bundle into closed-context personas, hybrid between SDK-direct and tool-using

**New from cross-talk (v2)**:
- Honesty surface pattern: triage gate + pre-reg check + curator bias all rely on same author obeying conventions; one structural fix addresses what looks like four findings
- Confabulation-resistance: confident citations bypass scrutiny when they look like rigor
- Convergence-under-cross-fire is a stronger signal than initial confidence

## Agent D detection results (v2)

Agent D R1 contained:
- "Levenshtein distance 0.85 at score_keyword.py:39-50" (FALSE — code uses substring match)
- "Yates correction by default in cohens_kappa" (FALSE — uses Feinstein-Cicchetti)
- Contrarian framing: "single-fixture critique is overstated"

Detection by round:
| Agent | R2 | R3 | R5 |
|---|---|---|---|
| Opus | flagged both fabrications | reinforced | "low effort or possibly adversarial test" |
| GPT | flagged Yates as conceptually wrong | reinforced | "useful as dissent but several findings did not hold up" |
| Grok | initially accepted Levenshtein | retracted after seeing peers | "weakest of four, did not hold up" |

**Lesson**: the protocol caught the manipulation. Grok's R2 acceptance shows that fabricated citations CAN bypass single-reviewer scrutiny — the multi-agent structure is what surfaced it.

## What worked, what didn't

**Worked**:
- Independent Round 1 preserved blind-spot diversity
- Forced critique in R2 surfaced weak claims fast
- Defend/concede in R3 + falsifier requirement improved calibration
- R4 disagreement-resolution path forced experimental thinking
- Pre-registration (v2) confirmed convergence was correctness not conformity
- Null-control (v2) caught a confabulation-resistance weakness specific to Grok

**Didn't work or under-performed**:
- R5 pre-reg → main delta was zero for all agents. Drop R5 prereg in future runs.
- Grok-4.3 hit a bandwidth cap at 600-900 tokens by R3. Switching to 4.20-reasoning fixed it but at higher per-token cost.
- Agent D was a one-shot R1-only injection. A more rigorous null-control would have D respond in later rounds with continued fabrications.
- The orchestrator (Claude Opus 4.7 in this conversation) is also a participant via fresh API calls. Some risk of subtle alignment between orchestrator and participant. Mitigated by using fresh API calls but not eliminated.

## How to use this example

If you're running /roundtable on a different target:
1. Read v1's META_SYNTHESIS.md to see the structure of synthesis output
2. Read v2's META_SYNTHESIS_V2.md to see the pre-reg delta analysis and Agent D commentary
3. Read PERSONA_RECOMMENDATIONS.md to see how synthesis converts to actionable P0/P1/P2/P3 work
4. Cross-reference the patterns. If your target is similar (methodology review of an LLM-using skill), expect similar findings shapes.
