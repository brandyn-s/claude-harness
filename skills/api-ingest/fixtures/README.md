# Fixtures Reference

Critical Gotchas:
- Do not run fixtures against the canonical `api-docs` project — they emit `fixture-*` namespaces that pollute search results. Use `--name fixture-{variant}` and delete `~/Documents/api-docs/fixture-*` after verifying.
- Do not check in real PDF binaries — Phase 2c requires the user to supply one out-of-band (binary noise + repo hygiene).
- Do not assume the HTML stub exercises Firecrawl — `2e-html-scrape-stub.html` only verifies markdown extraction logic if used as a mock body; the actual Firecrawl path requires a live URL.

The `fixtures/` directory holds one minimal stub per Phase 2 variant for
manual dispatch verification (audit F3). Each fixture is the smallest
input that exercises the variant's parser path end-to-end.

## Variants

| File | Phase | What it exercises |
|---|---|---|
| `fixtures/2a-openapi-minimal.json` | 2a | OpenAPI 3.x JSON spec parsing (paths, securitySchemes, components) |
| `fixtures/2b-llms-full.txt` | 2b | llms-full.txt section splitting into reference.md + constraints.md |
| `fixtures/2c-pdf-stub.txt` | 2c | Placeholder for PDF (binary not committed — supply any real .pdf) |
| `fixtures/2d-postman-collection.json` | 2d | Postman v2.1 collection item-tree recursion |
| `fixtures/2e-html-scrape-stub.html` | 2e | HTML doc-site shape for Firecrawl fallback (mock body only) |

## Phase 4.5b classification coverage

The four Phase 4.5b outcome classifications (0 nodes / 1 node / >=1op+>=1scope /
only gotchas+auth) emerge from different `constraints.md` shapes — they are
produced by Phase 3, not external. The fixtures above implicitly cover the
">=1op+>=1scope" case (2a and 2d have operations and scoped auth) and the
"only gotchas+auth" case (2b and 2e have auth + rate limits but no scoped
permission tables).

The "1 node" case (API stub only) emerges when `constraints.md` has no
`### ` headings, no permission tables, and no `## Common Gotchas`
section — `constraint_graph.py` will emit only the API stub node.

## Manual verification

For each variant, dispatch the literal command (per the
verify-the-external-contract rule):

    /api-ingest ~/.claude/skills/api-ingest/fixtures/2a-openapi-minimal.json --name fixture-2a
    /api-ingest ~/.claude/skills/api-ingest/fixtures/2b-llms-full.txt        --name fixture-2b
    /api-ingest ~/.claude/skills/api-ingest/fixtures/2d-postman-collection.json --name fixture-2d

Confirm each routes to the correct Phase 2 path and produces
`~/Documents/api-docs/fixture-{2a,2b,2d,...}/{reference,constraints}.md`.

`2c` and `2e` need real-world inputs (a real PDF; a live HTML doc-site)
to exercise the binary parsing and Firecrawl scraping code paths.
