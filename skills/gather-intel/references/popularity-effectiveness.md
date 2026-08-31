# Popularity vs Effectiveness Assessment

Upvotes measure resonance, not correctness. A 749-point post about "no-bs lessons" is popular because it's well-written, not because every lesson has been verified. This framework separates the two.

## Verdict Definitions

| Verdict | Definition | Criteria |
|---------|-----------|----------|
| **VALIDATED** | Popular AND effective for this setup | We implemented it + measurable improvement (fewer errors, faster workflows, agent memory confirms) |
| **UNVALIDATED** | Popular AND implemented, but no evidence it helps | We have the rule but never measured. Needs a test — run with and without, compare outcomes. |
| **HYPE** | Popular but NOT implemented, AND no evidence for this setup type | Community loves it, but it's for different contexts (web dev, CI/CD, Mac) or untested at scale. Deprioritize until evidence emerges. |
| **HIDDEN GEM** | Low popularity BUT strong evidence + direct applicability | Few upvotes, but includes code, reproduction steps, and addresses MCP-heavy/Windows/GovCloud. Investigate. |
| **OVERHEAD** | Implemented but evidence suggests it's net negative | Rule causes latency, token burn, or false positives that outweigh the protection it provides. Suggest relaxing. |

## Key Principles

- If a finding scores T2+ authority and Verified evidence but has <50 upvotes, it may be a HIDDEN GEM.
- If it scores T4-T5 authority but has >300 upvotes, it may be HYPE.
- Popularity and quality are independent dimensions — evaluate both.

## Confirmed Learnings

**[confirmed] Phase A yields higher ROI than Phase B**: The backward-looking audit (existing intel health) consistently produces more immediately actionable items than the forward-looking web search. Phase A findings come with specific file + line references and clear actions (REMOVE, TEST, RELAX). Phase B findings typically need further investigation before acting. Never skip Phase A to rush to Phase B.

**[confirmed] Popularity does not correlate with applicability**: Multiple high-upvote recommendations (345pts "40% context cliff", 425pts agent teams) were classified UNVALIDATED or HYPE for this architecture, while low-visibility patterns (35pts config-driven routing hook) became the most impactful mechanism implemented. The composite scoring (authority x evidence x applicability) correctly prevents popularity from dominating. Trust the framework over gut reactions to upvote counts.
