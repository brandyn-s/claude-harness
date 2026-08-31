# Evidence Quality Framework

Tag every claim in the synthesis with one of three confidence levels. When multiple sources address the same claim, use the highest applicable level.

## Confidence Levels

| Level | Label | Criteria | Source examples |
|---|---|---|---|
| **High** | Primary sources, independent verification, or multiple corroborating sources | Official documentation, standards body publications (NIST, ISO, RFC), lab-tested results with methodology, analyst reports with disclosed methodology, 3+ independent sources agreeing | Vendor's own FedRAMP package, NIST SP 800-53, MITRE evaluation, Gartner MQ with visible criteria |
| **Medium** | Credible secondary sources or single expert account with evidence | Reputable technical blog with demonstrated expertise, conference talk with demos or benchmarks, practitioner post with reproduction steps, independent review with some methodology | Well-known security blog, SANS whitepaper, conference presentation, detailed GitHub README |
| **Low** | Anecdotal, marketing material, or single unverified claim | Vendor whitepaper without independent validation, forum post without evidence, opinion piece, sponsored content, single N=1 observation | Product landing page, Reddit comment without specifics, "Top 10" listicle |

## Tagging Rules

1. **Per-claim tagging**: Every factual claim in the Key Findings section gets tagged. Don't tag the entire finding — tag individual claims within it.
2. **Upgrade on corroboration**: A Low-confidence claim upgrades to Medium if a second independent source confirms it. Medium upgrades to High with 3+ independent sources.
3. **Vendor content discount**: Claims sourced only from the vendor's own materials are capped at Medium, regardless of specificity. Vendor claims corroborated by independent sources can reach High.
4. **Recency matters**: For rapidly evolving topics (software versions, compliance status, pricing), flag claims older than 6 months as potentially stale regardless of confidence level.
5. **Methodology visibility**: Sources that describe their testing methodology score one level higher than equivalent sources that don't. "We tested X by doing Y and measured Z" > "X is better than Y."

## Disagreement Handling

When sources disagree on a claim:

1. Present both positions with their confidence levels
2. Note which position has stronger evidence (higher confidence, more sources, better methodology)
3. If evidence is roughly equal, say so — don't pick a winner artificially
4. Note potential reasons for disagreement (different versions tested, different use cases, vendor bias)

## Source Authority Tiers

Tag each source with its authority tier in the Sources table.

| Tier | Label | Description | Examples |
|------|-------|-------------|----------|
| **T1** | Authoritative | Standards bodies, official documentation, peer-reviewed research | NIST SP 800-series, ISO standards, RFCs, peer-reviewed journal articles, CMVP certificates, official product documentation |
| **T2** | Expert analysis | Independent expert analysis with methodology shown | SANS whitepapers with test methodology, analyst reports with disclosed criteria, conference papers with benchmarks |
| **T3** | Corroborated | Multiple independent corroborating sources | 3+ independent blog posts reaching the same conclusion from different evidence, community consensus on forums with evidence |
| **T4** | Single credible | Single credible source (reputable publication, known expert) | Well-known security blog (Krebs, Schneier), reputable tech publication (Ars Technica), recognized practitioner post with evidence |
| **T5** | Unverified | Vendor marketing, unverified claims, anonymous sources | Product landing pages, vendor whitepapers without independent validation, anonymous forum posts, sponsored content, "Top 10" listicles |

## Triangulation Rules

Sources are independent only if they derive from different primary sources. Multiple blog posts citing the same vendor announcement count as 1 source. When counting corroborating sources, trace each back to its primary source and deduplicate.

## tavily_research Confidence Cap

Claims sourced solely from `tavily_research` synthesis without traceable URLs are capped at Medium confidence. To reach High confidence, the underlying primary source URL must be identified and verified.

## Source Bias Indicators

Flag these bias risks in the Sources table:

| Bias type | Indicator | How to flag |
|---|---|---|
| **Vendor bias** | Source is produced by the vendor being evaluated | Tag: `[vendor]` |
| **Sponsored** | Content is sponsored or paid | Tag: `[sponsored]` |
| **Competitive** | Source is produced by a competitor | Tag: `[competitor]` |
| **Outdated** | Source is >6 months old for a fast-moving topic | Tag: `[dated: YYYY-MM]` |
| **No methodology** | Source makes claims without describing how they were tested | Tag: `[no method]` |

## Scope Note

This skill's evidence framework is intentionally general-purpose. For domain-specific research, consider using `/gather-intel` (community patterns) or `/gather-research` (academic frontier) which have richer evaluation frameworks optimized for their domains.


## Tavily Score vs Source Quality

The `score` field returned by `tavily_search` reflects **search relevance** (how well the result matches the query), NOT source authority or evidence quality. A 0.9-score vendor marketing page is still T5. A 0.3-score NIST publication is still T1. Always evaluate source quality independently of Tavily relevance scores.
