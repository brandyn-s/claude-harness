# Channel map — what each channel is and why its extractors exist

Companion to `scripts/channel_specs.py`. The registry says *what* is extracted;
this says *why that fact-set is the right thing to watch*.
**Live-verified 2026-07-27.** Counts are the committed baselines.

| Channel key | Doc page | Extractors (baseline count) |
|---|---|---|
| `otel` | `code/monitoring-usage.md` | otel-metrics (8) · otel-events (28) · otel-env-vars (44) |
| `compliance-api` | `manage-claude/compliance-api.md` | compliance-ratelimits (600) |
| `compliance-activities` | `api/compliance/activities/list.md` | activity-types (412) · activity-actor-types (9) |
| `compliance-endpoints` | `api/compliance.md` | compliance-endpoint-paths (33) |
| `compliance-access` | `manage-claude/compliance-api-access.md` | compliance-scopes (4) · key-prefixes (3) |
| `admin-usage-cost` | `manage-claude/usage-cost-api.md` | admin-endpoint-paths (2) · admin-bucket-widths (3) |
| `admin-claude-code-analytics` | `api/admin/usage_report/retrieve_claude_code.md` | cc-analytics-fields (35) |
| `admin-rate-limits` | `api/admin/rate_limits/list.md` | ratelimit-endpoint (1) |
| `analytics-enterprise` | `api/admin/analytics.md` | analytics-endpoint-paths (11) |
| `analytics-guide` | `manage-claude/analytics-api.md` | analytics-ratelimits (60) · analytics-freshness-windows (2) |
| `webhooks-managed-agents` | `managed-agents/webhooks.md` | webhook-event-types (37) |
| `gateway` | `code/claude-apps-gateway-config.md` | gateway-telemetry-keys (7) · gateway-config-sections (10) |
| `zdr` | `code/zero-data-retention.md` | *(none — prose-only)* |
| `data-usage` | `code/data-usage.md` | telemetry-optout-vars (4) |
| `dashboards` | `code/analytics.md` | dashboard-urls (4) |

## Why these fact-sets

**Names and paths, because they are the contract.** An event name is what a
detector matches on; an endpoint path is what a poller calls; a scope is what a key
carries. When one of these changes, something we run changes behavior — that is the
definition of a fact worth watching. Prose describing the same thing can be reworded
freely with no operational effect.

**Integers, because they are thresholds.** Rate limits set poller pacing; freshness
and revision windows decide when a number is invoicing-grade. A silent change from
60 to 30 req/min turns a working poller into a throttled one.

**Two channels carry no extractors on purpose.** `zdr` is watched for its
*disabled-features table*, which is prose in a shape too unstable to extract
reliably; its marker assert still catches the page moving, and the Watching table
carries the trigger. Better an honest prose-watch than a fragile regex that reports
confident nonsense.

## The three channels most likely to move

1. **`analytics-enterprise`** — grew from ~4 to 11 endpoints between our first
   audit and 2026-07-27. Fastest-moving surface in the set.
2. **`compliance-activities`** — 412 types tracks the whole product's feature
   surface, so it moves whenever anything ships (`claude_code_workflows_enabled`,
   `ccr_agent_*` for Claude Tag, sandbox egress toggles).
3. **`otel`** — event list grows with each Claude Code capability (hooks, plugins,
   skills, compaction all have events now).

## Pages deliberately NOT watched

| Page | Why not |
|---|---|
| `api/compliance.md` full body (2.54 MB) | watched for paths only; full-body diff is unusable noise |
| `api/admin/analytics.md` full body (176 KB) | same — paths only |
| `manage-claude/api-and-data-retention.md` | prose matrices (HIPAA/residency/eligibility); no stable token set. Watching-table triggers instead |
| `code/hooks.md` (239 KB) | hook *events* are a Claude Code product surface → `/gather-claude` owns it |
| `code/code-review.md`, `code/claude-security.md` | product features; only their **push** surfaces matter here, tracked via Compliance activity types |
| per-endpoint reference pages | the index pages already carry the paths; per-page watching multiplies fetches for no added signal |

## Known benign noise

| Extractor | Noise | Do not "fix" |
|---|---|---|
| `gateway-telemetry-keys` | `OTEL_TOKEN` is a doc placeholder secret | narrowing the pattern would re-break the bare-token case that this widening fixed |
| `otel-env-vars` | includes non-telemetry `CLAUDE_CODE_*` vars mentioned in passing | a broader set is safer than a curated one that misses a new flag |

Recorded here so a future run recognizes them instead of re-diagnosing — and,
more importantly, does not "fix" them into a narrower pattern that reintroduces
the original blindness.
