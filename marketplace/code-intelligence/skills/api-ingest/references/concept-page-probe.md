# Phase 0c — Concept-page probe

Relocated verbatim from `skills/api-ingest/SKILL.md` on 2026-09-04 (docs/skill-cap-decisions.md).
Runs alongside 0b when the source is a docs site; its findings flow into Phase 3.

### 0c. Concept-page probe

Even when 0b finds a spec, the prose-docs site usually carries cross-cutting concepts that aren't in OpenAPI: per-endpoint expansion values, pagination semantics, endpoint-naming conventions, error code shapes, webhook auth, idempotency keys, search/filter syntaxes. **Skipping the prose docs because OpenAPI was found gives a doc-set that looks complete but isn't.** This bit the Ashby ingestion (2026-04-26): the OpenAPI spec defined `expand: array<string>` with no per-endpoint enum, but the prose docs at `developers.ashbyhq.com/docs/expansions` listed the actual valid values per endpoint. mcp-forge built tool descriptions claiming `expand=['candidate'|'job']` worked when neither was valid; the model trusted the description, hit `invalid_input`, and incorrectly concluded the API didn't expose form responses.

When the source URL points to a docs site (not a direct spec URL), probe these standard concept paths in parallel **alongside 0b** — they flow into Phase 3, not Phase 2:

```bash
# Step 1 of 2 (HEAD): cheap status check — narrows the candidate set
# Step 2 of 2 (GET): inline body+heading validation — accepts only real
# concept pages and drops HTML 200 shells. Both run inline below.
for path in /docs/authentication /docs/auth \
            /docs/expansions /docs/expansion /docs/expanding-results \
            /docs/pagination /docs/pagination-and-incremental-sync \
            /docs/endpoint-naming \
            /docs/responses-and-errors /docs/errors /docs/error-codes \
            /docs/rate-limit /docs/rate-limits /docs/rate-limiting \
            /docs/idempotency /docs/idempotent-requests \
            /docs/webhooks /docs/setting-up-webhooks /docs/authenticating-webhooks \
            /docs/filtering /docs/sorting /docs/searching; do
  (url="${ORIGIN}${path}"; \
   # Step 1: HEAD status check
   code=$(curl -sIL -o /dev/null -w "%{http_code}" -m 5 "$url"); \
   [ "$code" != "200" ] && exit 0; \
   # Step 2: GET body + Content-Type + <h1>/<h2> heading match (>1KB body)
   tmp=$(mktemp); \
   ct=$(curl -sL -m 8 -D - -o "$tmp" "$url" | grep -i '^Content-Type:' | head -1); \
   echo "$ct" | grep -qi 'text/html' || { rm -f "$tmp"; exit 0; }; \
   [ "$(wc -c < "$tmp")" -lt 1024 ] && { rm -f "$tmp"; exit 0; }; \
   # Heading text must match the concept (case-insensitive substring)
   concept=$(echo "$path" | sed 's|/docs/||; s|-| |g'); \
   grep -iE "<h[12][^>]*>[^<]*${concept}" "$tmp" >/dev/null && \
     echo "FOUND: $url"; \
   rm -f "$tmp") &
done
wait
```

Per `references/concept-page-paths.md` (extend that list as new vendors surface different conventions). HEAD 200 is not sufficient — many sites return a 200 HTML shell for any path. The GET validation above is inline (no separate step required): each candidate must be `Content-Type: text/html`, body > 1 KB, AND contain an `<h1>`/`<h2>` whose text matches the concept name.

Concept pages found here are mandatory inputs to Phase 3 when the source is a docs site, even if a spec was also found. The two are complementary, not redundant.

---

