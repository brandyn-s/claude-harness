# Step 1.6 — Service/Module Identification Pattern

Relocated verbatim from `skills/code-explore/SKILL.md` on 2026-09-04 (docs/skill-cap-decisions.md).
Step 1 of the skill routes **Identification** queries here.

### Step 1.6: Service/Module Identification Pattern

When Step 1 classifies a query as **Identification** ("what is X", "what
does X do", "tell me about X"), run this fixed recipe before falling back
to free-form exploration. The pattern is biased toward COMPLETENESS — it
eliminates the "I forgot to look at the consumer" class of misses.

**Step A — Discover the surface (graph search, paginated):**

```
search_graph(name_pattern=".*[Xx].*", project=<proj>, limit=55)
# If response has has_more=true OR total > limit:
search_graph(name_pattern=".*[Xx].*", project=<proj>, limit=100, offset=55)
# Continue paginating until has_more=false. Don't accept "I saw the top 15".
```

`search_graph` returns nodes degree-ranked by default — the highest-degree
file is usually the canonical entry point (main.rs / api.rs / config.rs).
**This is the workhorse step.** Pagination + degree ranking tends to
surface every important file (publisher, subscriber, lifecycle controller,
config) by itself for any well-named service.

**Step B — Architecture docs (high-signal, descriptive):**

```
ls docs/src/architecture/**/*.md          # if present, read service-relevant ones
grep -rn "X\b" docs/src/architecture/     # named references to the concept
```

Architecture docs describe the system's CURRENT state. RFCs (typically
under `docs/src/rfcs/`) describe PLANS — they may or may not be
implemented. Always prefer architecture docs for "what is X." Treat RFC
titles as design hints, never as implementation evidence (see Step D).

For ExampleApp, `docs/src/architecture/services/example-service/architecture.md`
revealed the `torchyd2 → V4L loopback → exampleapp` pipeline that no other
source surfaced.

**Step C — Cross-service edges (when present, high-value; not always present):**

```
# HTTP and async cross-service calls touching X
query_graph(query="MATCH (a)-[r:HTTP_CALLS]->(b) WHERE a.qualified_name =~ '(?i).*X.*' OR b.qualified_name =~ '(?i).*X.*' RETURN a.name, b.name, r.url_path, r.method, r.confidence LIMIT 30")

# USAGE references (variable assignments, callbacks, references in other modules)
query_graph(query="MATCH (a)-[r:USAGE]->(b) WHERE b.name = 'X_FOO' OR b.name = 'X_BAR' RETURN a.name, a.file_path, b.name LIMIT 30")
```

When these edges exist, they surface consumers (web clients, sidecars,
adjacent services) automatically. **But empty results don't mean no
consumers.** Edge density is uneven across languages and module types:
Rust services with config-struct USAGE patterns and CLI subprocess
glue (gandropd → systemctl) often show zero USAGE/CALLS edges to the
service. ExampleApp is one such case (0 rows for both queries despite real
consumers existing). When edge queries are empty, fall back to:
  - architecture docs (Step B)
  - `grep` for the service name across the repo
  - the rationale/TODO nodes from search_graph (often surface integration
    points: see `MoqPlayer.tsx:110` TODO that revealed the local relay
    plan)

Note: code-graph's Cypher supports `IN [list]` for the multi-name
case (`WHERE b.name IN ['Foo', 'Bar', 'Baz']`) — added in B1
(2026-05-07). Regex on `qualified_name` works but returns nothing if
the edge doesn't exist; explicit name-equality queries (`= 'X' OR =
'Y'` or the `IN` form) on identifiers found in Step A are more
reliable than wide regex.

**Step D — Read the canonical source files:**

Read in this order: `Cargo.toml` / `package.json` / `flake.nix` (declares
deps and ports), then `main.rs` / `index.ts` (entry point), then
`api.rs` / `routes.ts` (public surface), then `config.rs` (data model),
then any consumer files surfaced in Steps A-C.

**Step E — Verify before claiming:**

For any claim derived from doc filenames or doc text, grep for an
implementation reference. If an RFC is `rfc-2025-03-los-blos-video-
switching.md`, grep for "switching" / "los" / "blos" in source. If an
architecture doc claims "torchyd2 → V4L loopback → exampleapp", check that
the configured `video_dev` paths match the loopback device numbers
declared in `nix/`. Don't carry doc claims into the answer unless code
references them — flag claims you couldn't fully verify with `⚠️`.

**Anti-patterns:**
- Stopping after the first 15 graph results when `has_more=true`. The
  next 40 routinely include the consumer/sidecar/proxy that closes the
  loop.
- Treating RFC titles as implementation evidence. RFCs describe planned
  or design-stage behavior that may or may not exist in code.
- Treating empty edge-query results as "no consumers exist." Many
  service relationships in this repo go through CLI subprocesses,
  V4L loopback, systemd, or NixOS module composition — none of which
  produce USAGE/CALLS/HTTP_CALLS edges.
- Trusting `HTTP_CALLS` edge counts on older code-graph versions.
  Measured 2026-05-07 against PSM: 3 HTTP_CALLS edges total in an
  80K-node graph, with 2 of 3 being false positives (filesystem path
  treated as URL, JS file self-loop). Real cross-service HTTP edges
  (exampleapp → token-server, all VendorRouter client calls, all example-gateway
  fetch routes) are missing from the graph despite existing in source.
  Until the extractor is fixed, assume HTTP_CALLS is sparse and fall
  back to architecture docs + grep for cross-service relationships.
  Re-baseline this pattern after each code-graph version bump.

