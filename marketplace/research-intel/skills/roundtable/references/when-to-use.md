# When to use /roundtable

Decision guidance for choosing /roundtable vs other review skills.

## Use /roundtable when

- **The target is methodologically subtle.** Examples: a skill with multiple optimization targets, a methodology that built on a self-validating fixture, a design proposal with hidden tradeoffs.
- **Individual blind spots are likely.** Single-reviewer assessment risks missing what one model can't see. Multi-agent diversity catches it.
- **You need confidence calibration, not just verdicts.** Pre-registration and falsifier requirements force agents to commit to positions before cross-talk and name what would flip them. The output tells you not just "what's wrong" but "how confident."
- **Cost ($15-30) is acceptable for the question.** Roundtable is overkill for $1 questions; appropriate for "should we ship this skill" or "is this design pattern worth adopting."

## Use a different skill when

| Situation | Use instead |
|---|---|
| Bug-shaped problem with obvious cause | /systematic-debugging |
| Single-tool lookup | the tool directly |
| Brainstorming, no friction signal | /brainstorm |
| Verifying a security finding | /fp-check |
| Triaging multiple findings by severity | /triage |
| Stress-testing a single proposal | /interview |
| Adversarial repo evaluation | /evaluate-repos (advocate/skeptic pair) |
| PR review for security issues | /differential-review |

## When the cost-benefit collapses

- The user has already read the target and has high prior confidence
- The disagreement is about preference (style, naming, organization)
- The decision is reversible at low cost (just try it)
- One specialized model would clearly outperform the others (e.g., security-specific reviews)

## Empirical evidence

The persona-skill review experiments (v1 + v2) showed:

**v1 (5-round adversarial, no pre-reg)**: $13, 12 min, surfaced 6 net-new findings beyond independent assessments. Each model caught issues the others missed.

**v2 (added pre-reg, falsifiers, null control)**: $32, 25 min. Cost 2.4x v1 but produced:
- Confirmation that v1 convergence was real correctness (not conformity)
- 3 new substantive findings
- Diagnostic of agent susceptibility (Grok was uniquely vulnerable to fabricated citations; the null-control caught this)

When v1 is enough: ranked recommendations on a moderately subtle target.
When v2 is worth 2.4x: when you need to be confident the convergence is real (audit, multi-stakeholder review, decision under uncertainty).
When neither is right: bug-shaped or trivial.
