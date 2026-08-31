# API Contract Lookup

INVARIANT contract_before_implementation_or_instrumentation

Before an unfamiliar call/client, negative capability claim, or live instrumentation:

1. Search memory by endpoint/operation/parameter; read agent-memory/topics/<vendor>.md.
2. Inspect ~/Documents/api-docs/<vendor>/ now; remembered inventory/counts decay.
3. Read raw vendor/OpenAPI/Postman evidence for auth, permissions, real parameter names/ranges, pagination, response shape, and deployment/tier limits. Dereference parameter refs.
4. If absent, run /api-ingest <docs-url> --name <api-name>; use /api-preflight for prerequisite chains.

Locally emitted llms-full.txt concatenates this repository's reference.md + constraints.md; it is not independent vendor evidence. Verify against the preserved raw corpus.

NEGATIVE_CLAIMS:
- Empty 200/bare 4xx is a parameter claim until the contract is read.
- ToolSearch covers the MCP wrapper, not the vendor API. Check the vendor corpus and retry with the endpoint noun before claiming absence.
- Vendor docs describe a superset, not this deployment/build/tier. For a documented 404, vary actual spec-derived encodings/params and compare responses before choosing bad call versus unavailable endpoint.
- Never invent plausible numeric limits/ranges.

FORBIDDEN: report regression/retirement/absence from an empty result, wrapper-only search, guessed parameters, stale inventory, or an experiment whose success oracle came from your own assumption rather than the vendor contract.

INSTRUMENTATION: read the schema first. If undocumented, instrument a copy you own; never mutate a shared/deployed launcher, hook, settings file, statusline, or binary to answer a read-only question.

SCHEMA_VS_DATA: before blaming vendor data after a complete read, fetch the
current object/type/schema and inspect raw key presence, not a tolerant mapped
value. A field empty on every row is a schema-drift signal: absent from the
schema means our contract is stale; declared-but-null supports a data finding.
Compare missing and newly added fields for a rename before any user, ticket, or
vendor verdict.

Incidents: rules/incidents/api-doc-lookup.md. Host details: agent-memory/topics/api-ingest.md.
