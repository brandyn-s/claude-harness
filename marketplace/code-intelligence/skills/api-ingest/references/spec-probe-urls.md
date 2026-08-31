# Spec Probe URLs

Before scraping docs page-by-page, probe these paths at the doc site's origin. A single GET replacing 20 scrapes is the biggest performance win in the ingestion pipeline.

## Priority Order

**Tier 1 — canonical sources (prefer these):**

| Path | Source of convention | Coverage |
|------|---------------------|----------|
| `/llms-full.txt` | Mintlify, Anthropic, Vercel, llmstxt.org | Entire docs as one markdown file |
| `/openapi.json` | OpenAPI 3.x convention | Full API spec |
| `/openapi.yaml` | OpenAPI 3.x (YAML variant) | Full API spec |
| `/swagger.json` | Swagger 2.0 / legacy | Full API spec |
| `/api/openapi.json` | Common docs-path variant | Full API spec |
| `/api-docs/swagger.json` | Springdoc / Java convention | Full API spec |

**Tier 2 — summary indexes:**

| Path | Coverage |
|------|---------|
| `/llms.txt` | Index of doc sections (not full content) |
| `/sitemap.xml` | URL list (useful for filtering, not content) |

**Tier 3 — vendor-specific known patterns:**

| Vendor / Pattern | URL |
|------------------|-----|
| Tailscale | `https://api.tailscale.com/api/v2?outputOpenapiSchema=true` |
| Cloudflare | `https://github.com/cloudflare/api-schemas/blob/main/openapi.json` (GitHub raw) |
| Stripe | `https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json` |
| GitHub | `https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json` |
| Anthropic | `https://docs.anthropic.com/llms.txt` and `/llms-full.txt` |
| ReadMe.io-hosted docs | `{origin}/api/v1/` often serves Swagger; check Network tab |
| Redocly-hosted | Look for `<redoc spec-url="...">` in HTML source |
| Scalar-hosted | Look for `<script id="api-reference" data-url="...">` in HTML source |

## Probe Implementation (parallel Bash)

```bash
ORIGIN="https://docs.example.com"
PROBE_PATHS=(
  "/llms-full.txt"
  "/llms.txt"
  "/openapi.json"
  "/openapi.yaml"
  "/openapi.yml"
  "/swagger.json"
  "/api-spec.json"
  "/spec.json"
  "/api/openapi.json"
  "/api/swagger.json"
  "/api-docs/swagger.json"
  "/v1/openapi.json"
  "/v2/openapi.json"
  "/docs/openapi.json"
)

for path in "${PROBE_PATHS[@]}"; do
  url="${ORIGIN}${path}"
  code=$(curl -sIL -o /dev/null -w "%{http_code}" -m 5 "$url")
  type=$(curl -sIL -m 5 "$url" | grep -i '^content-type:' | tail -1 | tr -d '\r')
  [ "$code" = "200" ] && echo "✓ $url  ($type)"
done
```

Run all probes in parallel with `&` and `wait`, or use `xargs -P 8`.

## Validation

A 200 response alone isn't enough — some doc sites return HTML 200 for any path. Verify content:

- `llms-full.txt` → should be plain text, > 10 KB
- `openapi.json` / `swagger.json` → should parse as JSON with `openapi` or `swagger` key
- `openapi.yaml` → should parse as YAML with `openapi` or `swagger` key

```bash
# Download to a file first — curl piped straight into an interpreter is
# blocked by the bash-security-guard hook, and this host is python3-only.
spec=$(mktemp)
curl -sL "$url" -o "$spec"

# JSON validation
python3 -c "import json,sys; d=json.load(open(sys.argv[1], encoding='utf-8')); assert 'openapi' in d or 'swagger' in d" "$spec"

# YAML validation
python3 -c "import yaml,sys; d=yaml.safe_load(open(sys.argv[1], encoding='utf-8')); assert 'openapi' in d or 'swagger' in d" "$spec"
```

## When Probes Fail

If no spec or llms-full.txt is found, fall back to Firecrawl scraping (Phase 2 of the skill). Note in `reference.md`: "Source: scraped HTML pages — no OpenAPI spec available at probed paths."

## Where Not to Waste Time

Do not probe these — they return 200 HTML regardless of actual presence:
- `/api` (usually a landing page, not a spec)
- `/docs` (usually a landing page)
- `/reference` (usually an HTML reference page)

Only use paths that return a structured format (JSON, YAML, or llms.txt).
