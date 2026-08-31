# Report Output Template

Every deep-dive run saves a report to `$HOME/Documents/knowledge-base/research/YYYY-MM-DD-topic-slug.md`. Use this template exactly.

## Topic Slug Rules

Generate the slug from the topic:
- Lowercase, hyphens instead of spaces
- Max 50 characters
- Strip articles (a, an, the) and prepositions when over limit
- Examples: `airlock-vs-carbon-black-fedramp`, `zero-trust-nixos`, `opa-policy-testing-cicd`

## Template

The report MUST follow this structure. Do not skip sections — if a section has no content, write "None identified." instead of omitting it.

---

# Research: [Topic — full user query]
**Date:** YYYY-MM-DD
**Waves completed:** N
**Research questions:** N asked, N answered (High), N answered (Medium), N unanswered
**Provider status:** Tavily: N calls (errors: <raw error text or "none">) | Exa: N calls (errors: <raw>) | Firecrawl: N calls (errors: <raw>) | arxiv: N calls (errors: <raw>) | xai: N calls (errors: <raw>)
**Estimated credits consumed per provider:** Tavily ~N (basic: N1, advanced: N2, extract: N3, research: N4) | Exa ~N (web_search: N1, advanced: N2, code_context: N3, crawling: N4) | Firecrawl ~N (search: N1, scrape: N2, map: N3, crawl: N4, extract: N5)

## Prior Knowledge
[What the system already knew before external research. Include source (memory file, topic file, ARCHITECTURE.md). If nothing was known, write "No prior knowledge found in local system."]

## Research Questions
[Numbered list. Each question tagged with its resolution status.]

1. [Question] — **Answered (High)**
2. [Question] — **Answered (Medium)**
3. [Question] — **Partially answered**
4. [Question] — **Unanswered**

## Key Findings

### Finding 1: [Title]
- **Claim:** [What we found — specific, factual statement]
- **Confidence:** [High/Medium/Low]
- **Sources:** [Numbered references to Sources table, e.g., [1], [3], [7]]
- **Evidence:** [What supports this claim — quote key evidence, note methodology if available]
- **Caveats:** [Any limitations, conditions, or qualifications on this claim]
- **Counterfactual:** [State the inverted hypothesis. What evidence would refute this finding? If the inverse held, what would change? Mark `SURVIVES` (likely recombination, downgrade by one tier), `COLLAPSES` (potential extrapolation, maintain confidence), or `AMBIGUOUS` (tag DISPUTED).]
- **Jury:** [ONLY for claims that went through Step 11b (Cross-Model Jury). Format: `opus=SUPPORTED, sonnet=SUPPORTED, haiku=INSUFFICIENT → split → DISPUTED, downgraded to Medium`. Note any same-model-sample fallback as `[same-model jury — partial]`. OMIT this line entirely for findings that did not require a jury.]

### Finding 2: [Title]
[Same format]

[Continue for all findings. Order by confidence level: High first, then Medium, then Low.]

**The Counterfactual field is mandatory per finding** — it is the structurally weakest layer of the three-layer defense (skills/_shared/output-grounding.md) and the easiest to fake with boilerplate. A claim like "voyage-code-3 is the SOTA code embedding model" has the counterfactual: "If voyage-code-3 were not SOTA, would the recommendation still hold?" — survival-test forces you to articulate what falsifies the finding.

## Trade-offs and Disagreements
[Where sources disagree. Present both sides with their confidence levels. Assess which is more credible and why. If no disagreements found, write "No significant disagreements found between sources."]

- **[Claim]**: [Source A] says X ([High]) vs [Source B] says Y ([Medium]). [Assessment of which is more credible and why.]

## Comparison Matrix
[For comparison topics ONLY. Include a feature comparison matrix with the same dimensions evaluated for each subject. Ensure symmetric evidence: every claim about Subject A must have a corresponding investigation for Subject B on the same dimension. Omit this section for non-comparison topics.]

| Dimension | Subject A | Subject B | Notes |
|-----------|-----------|-----------|-------|
| [Feature/Criterion] | [Status/Details] | [Status/Details] | [Evidence source] |

## Changes from Prior Research
[If prior reports on the same or related topic exist in `~/Documents/knowledge-base/research/`, summarize what changed. Include: new findings, findings that were confirmed, findings that were contradicted or superseded. If no prior research exists, write "No prior research found on this topic."]

## Unanswered Questions
[What we couldn't determine. For each, explain why (no sources found, conflicting information with no resolution, topic too niche) and suggest where to look next.]

- [Question] — [Why unanswered] — [Suggested next step]

## Recommendation
[Clear recommendation grounded in the evidence above. Reference specific findings by number. Acknowledge uncertainty where it exists. If the evidence doesn't support a clear recommendation, say so rather than forcing one.]

## Sources
| # | URL | Provider | Type | Authority Tier | Confidence | Bias flags | Key contribution |
|---|-----|----------|------|---------------|-----------|------------|------------------|
| 1 | [URL] | [Tavily / Exa / Firecrawl / arxiv / xai / multi] | [Official docs / Blog / Paper / Forum / Vendor / Standards body] | [T1-T5] | [High/Medium/Low] | [vendor/sponsored/competitor/dated/no method or none] | [1-sentence: what this source contributed] |

For reports with fewer than 10 sources, the condensed format is acceptable: `| # | URL | Provider | Authority Tier | Bias flags | Key contribution |`

---

## In-Conversation Summary

After saving the report, present this summary in the conversation. **This block is the in-conversation surface only — it must NEVER appear in the saved file.** Step 12 readback verification (c) greps the saved report for the literal placeholder token `**Research complete: [Topic]**` (see PLACEHOLDER TOKEN below); if any of these placeholder tokens — `[Topic]`, `[N] findings`, `[2-3 sentence executive summary` — survive in the saved file, real content was not written and the readback fails.

PLACEHOLDER TOKEN (literal string the readback check searches for): `**Research complete: [Topic]**`

---

**Research complete: [Topic]**

[2-3 sentence executive summary of the main finding/recommendation]

**Key findings:** [N] findings ([X] High, [Y] Medium, [Z] Low confidence)
**Unanswered:** [N] questions remain open
**Report saved:** `$HOME/Documents/knowledge-base/research/YYYY-MM-DD-topic-slug.md`

[If there are critical trade-offs or disagreements, mention the top 1-2 here]

---
