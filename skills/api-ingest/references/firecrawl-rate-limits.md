# Firecrawl Rate Limits (verified 2026-04-12)

Firecrawl rate limits are per-plan, per-team, measured in requests/minute. The `/crawl` endpoint has the tightest limit — sequence crawls, don't parallelize.

| Endpoint | Free | Hobby | Standard | Growth | Scale |
|----------|------|-------|----------|--------|-------|
| `/scrape` | 10 | 100 | 500 | 5,000 | 7,500 |
| `/map` | 10 | 100 | 500 | 5,000 | 7,500 |
| `/crawl` | **1** | **15** | 50 | 250 | 750 |
| `/search` | 5 | 50 | 250 | 2,500 | 7,500 |
| `/agent` | 10 | 100 | 500 | 1,000 | 1,000 |

**Key constraints:**
- `/crawl` is the bottleneck — Free plan allows only 1 crawl/min
- Scrape is 10x more generous than crawl — prefer `map` + batch `scrape` over `crawl` for small sites
- Rate limit 429 responses include `Retry-After` header
- All limits are per-team (shared across API keys)
- Source: https://docs.firecrawl.dev/rate-limits

**Recommended approach for `/api-ingest` Phase 2 (scraping fallback):**
1. Use `/map` first (10 req/min on Free) to discover all URLs
2. For <20 pages: sequential `/scrape` calls (10 req/min on Free)
3. For 20-100 pages: sequential `/crawl` calls with 60s spacing between batches
4. For >100 pages: ask user to narrow scope or use `/map` search to filter

## When parallel agents hit the shared rate limit

Parallel `api-ingest-worker` agents share the same Firecrawl team rate limit. Math:

| Plan | /scrape/min | Safe parallel workers | Per-worker headroom |
|------|-------------|----------------------|---------------------|
| Free | 10 | 2 | ~5 scrapes/min each |
| Hobby | 100 | 5 | 20 scrapes/min each |
| **Standard (current)** | **500** | **10 by rate; operational cap 5 pending runtime measurement** | **50+ scrapes/min each** |
| Growth | 5,000 | 10+ | 500+ each |
| Scale | 7,500 | 10+ | 750+ each |

On Standard, Firecrawl rate is not the bottleneck at the five-worker operational cap. Keep that conservative cap until a target-host probe records child process count and resident memory; do not infer process fan-out from the number of configured MCP servers.

Phase 1 spec probes (curl, no Firecrawl cost) remain the cheapest path regardless of plan.
