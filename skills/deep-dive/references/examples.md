# deep-dive — worked examples

Example 1 (vendor comparison for compliance) stays in SKILL.md. These two show
the same phases on a standards question and a best-practices question.

### Example 2: Standards deep dive

User says: `/deep-dive FIPS 140-3 validation timeline for Tailscale`
Actions:
1. Phase 1: 3 research questions. Memory search finds tailscale-patterns.md.
2. Phase 2: 9 parallel searches — 3 questions × 3 providers + 1 tavily_research(pro).
3. Phase 3: Wave 1 mostly answers questions. Wave 2 extracts CMVP database page (firecrawl_scrape) and Tailscale's security docs (tavily_extract cross-check). Convergence in 2 waves.
4. Phase 4: Report with 4 findings (1 High, 2 Medium, 1 Low). 1 unanswered. Report saved.
Result: Clear assessment with the High-confidence answer that Tailscale is not FIPS-validated, Medium-confidence timeline estimate, and alternatives list.

### Example 3: Technology best practices

User says: `/deep-dive best practices for OPA policy testing in CI/CD`
Actions:
1. Phase 1: 4 research questions. Memory search finds OPA source repo reference.
2. Phase 2: 12+ parallel searches — 4 questions × 3 providers + 1 tavily_research(pro) + firecrawl_map on OPA docs site.
3. Phase 3: Wave 1 answers 3/4 questions. Wave 2 crawls OPA docs (firecrawl_crawl) for testing section. Wave 3 extracts 3 high-signal blog posts. Convergence in 3 waves.
4. Phase 4: Report with 6 findings (2 High, 3 Medium, 1 Low). No major disagreements. Report saved.
Result: Comprehensive practices guide grounded in official docs (firecrawl) and practitioner experience (tavily + exa).
