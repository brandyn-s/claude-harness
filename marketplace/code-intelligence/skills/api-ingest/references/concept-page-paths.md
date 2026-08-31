# Concept Page Paths

Standard URL paths to probe for cross-cutting concept docs that aren't in OpenAPI.
Used by Phase 0c of `api-ingest` to detect prose-docs concepts even when a spec was already found.

## Why this list exists

OpenAPI carries endpoint shapes; it doesn't carry the cross-cutting concepts that tell consumers HOW to use those endpoints. Examples that bit us:

- **Ashby (2026-04-26)**: OpenAPI defined `expand: array<string>` with no `enum`. Valid values were enumerated only at `developers.ashbyhq.com/docs/expansions` per endpoint. mcp-forge generated tools claiming `expand=['candidate'|'job']` worked when neither was valid; the model trusted the description, hit `invalid_input`, and concluded the API didn't expose form responses. The actual valid value was `applicationFormSubmissions`, which the prose page listed plainly. One probe of `/docs/expansions` would have prevented the whole rabbit hole.

## Paths to probe (run all in parallel via `curl -sI`)

### Authentication
- `/docs/authentication`
- `/docs/auth`
- `/docs/api-keys`
- `/docs/getting-started`

### Expansions (the "include related objects" feature, naming varies)
- `/docs/expansions`
- `/docs/expansion`
- `/docs/expanding-results`
- `/docs/include-parameter` (Stripe-style)
- `/docs/embedded-resources` (HAL-style)

### Pagination
- `/docs/pagination`
- `/docs/pagination-and-incremental-sync`
- `/docs/cursor-pagination`
- `/docs/incremental-sync`

### Endpoint conventions
- `/docs/endpoint-naming`
- `/docs/api-conventions`
- `/docs/conventions`

### Errors and responses
- `/docs/responses-and-errors`
- `/docs/errors`
- `/docs/error-codes`
- `/docs/api-errors`
- `/docs/error-handling`

### Rate limiting
- `/docs/rate-limit`
- `/docs/rate-limits`
- `/docs/rate-limiting`
- `/docs/throttling`
- `/docs/quotas`

### Idempotency
- `/docs/idempotency`
- `/docs/idempotent-requests`
- `/docs/idempotency-keys`

### Webhooks
- `/docs/webhooks`
- `/docs/setting-up-webhooks`
- `/docs/authenticating-webhooks`
- `/docs/webhook-events`
- `/docs/webhook-signatures`

### Query syntax
- `/docs/filtering`
- `/docs/sorting`
- `/docs/searching`
- `/docs/querying`
- `/docs/search-syntax`

### Versioning
- `/docs/versioning`
- `/docs/api-versioning`
- `/docs/changelog` (last because change logs are noisy, but useful for date-bounded behavior changes)

## Validation rule

A `200` HTTP status is necessary but not sufficient — many sites return a 200 HTML shell for any path. After the parallel probe, follow with one GET on each candidate URL and verify:

1. The response is HTML (`Content-Type: text/html`)
2. The page contains an `<h1>` or `<h2>` whose text matches the concept (`Authentication`, `Expansions`, `Pagination`, `Errors`, etc.) — case-insensitive substring match
3. Body length > 1 KB (rules out empty navigation shells)

If any of those fail, drop the page from the concept-page set.

## Output

Found concept pages flow into Phase 3 of api-ingest. Each becomes a section in `constraints.md`. See SKILL.md Phase 3 for the section-mapping table.

## Extending this list

When ingesting an API whose docs site uses a path convention not listed here, add the new path under the matching category. Trace ALL of these cross-cutting concepts:

- Authentication (token format, header name, refresh)
- Authorization (scopes, permissions, roles)
- Pagination (cursor vs offset, max page size, syncToken semantics)
- Filtering / searching / sorting (query DSL or query parameters)
- Expansions (include / expand / fields parameter)
- Idempotency (header, scope, retention)
- Rate limits (per-plan, per-endpoint, headers)
- Errors (response shape, codes, retry guidance)
- Webhooks (signing, retries, payload structure)
- Versioning (header, URL prefix, deprecation policy)

Most APIs cover most of these somewhere. The path conventions vary; the concepts don't.
