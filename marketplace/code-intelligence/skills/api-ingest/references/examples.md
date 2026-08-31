# Examples

**OpenAPI spec URL (direct)**
```
/api-ingest https://api.example.com/openapi.json --name example
```
Phase 0 skipped (direct spec URL). Phase 2a downloads, parses, writes files. Phase 4 incremental index. ~10 seconds total.

**HTML doc site (unknown if spec exists)**
```
/api-ingest https://docs.vendor.com/api --name vendor
```
Phase 0b probes 5 paths. If `/openapi.json` returns 200 + valid JSON → Phase 2a. If not → Phase 2e scrapes 10 pages. ~30 seconds if spec found, ~3 minutes if scraping.

**Batch (5 APIs in parallel)**
Main session dispatches 5 `api-ingest-worker` agents (rate-limit permitting), each handling one API. Main session runs one incremental re-index after all return. Verify Phase 5 per API.
