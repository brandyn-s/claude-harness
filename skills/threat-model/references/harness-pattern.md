# Eight-component harness map — threat-model

Fifth reference implementation of the harness pattern. Domain:
grounding a structured threat model in actual code rather than prose.

## Entry test

The verification asymmetry:

- **Generation** = scope detection, recon over README/SECURITY.md/
  architecture docs, security-relevant code discovery (12 categories),
  4-section model authoring, attacker-story crafting. Thousands of LLM
  tokens. Adapts to library/CLI/web service/MCP server/embedded.
- **Verification** = Tier-1 structural checks (4 sections present,
  file refs resolve, surfaces have mitigations + stories) + Tier-2
  code-graph CALLS-edge probes (each "X crosses Y trust boundary"
  claim becomes a Cypher query that either returns rows or doesn't).

The Tier-2 oracle (code-graph) is the key lift over prose-only
threat-modeling: claims like "tool arguments cross the MCP client-
server boundary into the policy decision point" become Cypher queries
on `CALLS|HTTP_CALLS|USAGE` edges. If the graph has no edge from a
Handler to an execute function, the claim is unverified — flagged
rather than carried forward as fact.

## Per-component map

### 1. Proposer

Claude follows the five-step `SKILL.md` procedure: scope check, recon,
security-relevant code discovery, four-section model write, review.
The proposer emits the threat-model.md and (optionally) a claims.json
listing cross-boundary edges to verify.

### 2. Oracle / verifier (stratified)

`scripts/verify_claims.py` runs the verification suite:

- **structure_check** (Tier 1, mechanical) — the four required
  sections (Overview / Trust Boundaries / Attack Surface / Criticality)
  are all present as `##` headings. Catches drafts that skipped
  Section 4 calibration.
- **file_refs_resolve** (Tier 1, mechanical) — every backtick-quoted
  path with a known source extension AND every parenthetical path
  resolves on the local filesystem. Catches stale references after
  refactors / renamed modules.
- **surface_attribution** (Tier 1, mechanical) — each `###` heading
  inside Section 3 is followed by both a **Mitigations** block and an
  **Attacker stories** block. Catches partial surfaces.
- **calls_edge_probe** (Tier 2, deterministic source grounding) — when
  claims.json is provided, the script runs a deterministic grounding:
  each claimed cross-boundary edge's endpoint symbols are searched in
  the source tree under `root`. Each claim emits one `calls_edge_grounding`
  record with verdict GROUNDED (endpoint symbols present — a necessary
  condition for the edge), UNSUBSTANTIATED (an endpoint symbol is absent,
  claim fails), or MANUAL (pattern too ambiguous to search, human review
  required). A `calls_edge_intent` record with a Cypher query is also
  emitted per claim so an optional orchestrator with code-graph indexed
  can run the stronger graph query for proof of the specific A→B edge.

The split-execution model (intent in the script, query in the agent
runtime) keeps the script offline-safe and replayable. The model_history
diff still sees the verdicts because they're in the same NDJSON file.

What's *not* in the oracle: severity calibration (Section 4 is
descriptive), attacker-story prose quality, and fix recommendations
(out of scope per `SKILL.md`).

### 3. Context engineering

Two reference / context sources feed the proposer:

- Existing `SKILL.md` Step 1 recon (README, CLAUDE.md, SECURITY.md,
  prior threat models). The reconnaissance pass IS the context.
- `mcp__codebase-memory-mcp__get_architecture` + `search_graph` for indexed
  repos. The graph provides entry-point and module-dependency
  structure as input to the security-relevant-code discovery step.

The claims.json shape (consumed by `verify_claims.py`) is the
proposer/oracle contract: per claim — kind (`calls_across` /
`usage`), from_pattern (regex on qualified_name), to_pattern,
boundary label.

### 4. Tool surface (minimal)

The skill declares: `Glob`, `Grep`, `Read`, `Write`, `Bash`,
`mcp__codebase-memory-mcp__get_architecture`, `mcp__codebase-memory-mcp__search_graph`.
No specialized linters — POSIX + the graph tools carry the verification.

### 5. Orchestration / parallelism

Section 3 surfaces are independent: each can be discovered and
authored in parallel by sub-proposers. The orchestrator merges the
surfaces back into a single Section 3 with consistent severity
language.

Tier-2 code-graph probes are independent per claim — the
`calls_edge_intent` records can be dispatched as parallel Cypher
queries by the skill, then the `calls_edge_verdict` records re-merge
on completion. The Cypher `IN [...]` form (B1+) supports batching
multiple from_patterns in one query when claims share a boundary.

### 6. Memory / skill library

`model-history.jsonl` accumulates one row per threat-model run.
`scripts/model_history.py {append,diff,summary}` surfaces patterns:

- **`append`** — one summary row per run (surfaces count, refs
  resolved, claims verified vs unverified, git_sha).
- **`diff`** — same repo, two runs: did the new model add surfaces?
  Did file-ref breakage creep in? Did previously-verified claims
  become unverified (signal: code-graph schema changed, or the
  claimed edge disappeared)?
- **`summary`** — which check has the highest failure rate across
  models. Repeat-offender claims (intent emitted but never verified)
  indicate either a stale graph index or an over-confident proposer.

This makes threat-model state-aware: the second pass on the same repo
can short-circuit on surfaces whose mitigations haven't changed.

### 7. Failure-detection middleware

- **`file_refs_resolve` as a CI gate** — every reference in a merged
  threat-model.md must resolve at HEAD. Wire into CI; a rename without
  a model update fails the build.
- **`surface_attribution`** — catches the most common SKILL.md
  rubric violation: a surface authored without a mitigations block or
  attacker stories. Earlier failure than the human review pass.
- **`calls_edge_probe` unverified rate** — when more than ~30% of
  claims are unverified, either the graph isn't indexed for this repo
  (Tier-2 unavailable) or the proposer is leaning on prose
  speculation. Flag rather than promote to fact.

### 8. Observability / audit trail

`verify_claims.py --ndjson PATH` emits one record per check:

```json
{"run_id": "2026-05-30T...", "check": "structure_check", "passed": true, "missing_sections": []}
{"run_id": "2026-05-30T...", "check": "file_refs_resolve", "n_refs": 23, "n_missing": 0, "passed": true}
{"run_id": "2026-05-30T...", "check": "surface_attribution", "n_surfaces": 6, "n_issues": 0, "passed": true}
{"run_id": "2026-05-30T...", "check": "calls_edge_intent", "claim_id": "tool-args-cross-mcp-boundary", "cypher": "MATCH ..."}
```

The orchestrator (skill) runs each Cypher and writes back
`{"check": "calls_edge_verdict", "claim_id": "...", "passed": true/false, "n_rows": N}`.
`model_history.py append` sees both intent and verdict records and
summarizes verified-vs-unverified counts into the JSONL.
