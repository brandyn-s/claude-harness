# OpenAI channel map — what each channel is, and why the extractors look this way

## Critical Gotchas

- **Do not point a channel at `platform.openai.com`** — every `/docs/*` path
  returns HTTP 403 (Cloudflare bot challenge, measured 2026-08-22). The
  markdown surface is `developers.openai.com`, `learn.chatgpt.com`, and
  `cookbook.openai.com` (append `.md`; each publishes `llms.txt`).
- **Do not extract facts from reference method pages** — they are
  Stainless-generated stubs (~400 B, no schema, no enum). A method page going
  from stub to stub tells you nothing; the reference INDEX is the declaration
  surface.
- **Do not make a liveness marker share text with a watched line.**
  CHANNEL_DEAD short-circuits before triggers evaluate, so a marker that
  co-varies with a trigger's target converts a precise one-line drift into
  whole-channel blindness (caught by mutation test, 2026-08-22). Markers are
  structural section headers.
- **Do not grade a probe-discovered value REMOVED because docs omit it.** The
  compliance `event_type` enum (AUTH_LOG, AUDIT_LOG, APP_LOG, APP_AUTH_LOG,
  CODEX_LOG, CODEX_SECURITY_LOG, CUSTOM_AGENTS_LOG) is held in
  `observed_values` provenance; only AUTH_LOG appears in public docs.
- **Do not trust `developers.openai.com/llms.txt`'s own link list as current** —
  its `codex/llms.txt` entry 308-redirects into `learn.chatgpt.com/docs/llms.txt`
  (byte-identical to the ChatGPT index). The index advertises a page its own
  redirect map has retired.

## Channels

### 1. `platform-admin-reference` — developers.openai.com/api/reference/llms.txt

The OpenAI Platform API's endpoint reference index. Two extractors:

- `openai-admin-reference-pages` (measured 60): every
  `resources/organization/...` page slug — audit logs, admin API keys, users,
  invites, projects, project API keys/service accounts/rate limits/groups,
  certificates. A new slug is a new admin surface (the class of change this
  skill exists to catch); a removed slug is a potential outage for a poller.
- `openai-api-resource-groups` (measured 23): top-level resource families
  across the whole API. Coarse; catches a NEW FAMILY (e.g. a compliance or
  analytics group appearing platform-side) the admin-scoped pattern would miss.

Why the index and not the pages: Stainless stubs (gotcha #2). Contract details
behind any index finding are established by Step 4b probes against
`api.openai.com/v1/organization/...` with a platform admin key, GET only.

### 2. `compliance-logs-cookbook` — cookbook.openai.com/.../logs_platform.md

The only public page carrying the ChatGPT Compliance Logs Platform contract
(the real reference at `chatgpt.com/admin/api-reference` is login-gated).
Extractors:

- `compliance-event-types` (docs: 1; +6 observed_values): ALLCAPS `*_LOG`
  tokens. A NEW token here means the vendor started documenting the enum —
  promote, probe, and start ingestion immediately (30-day retention makes
  delay permanent loss).
- `compliance-scope-segments` (measured 2): `workspaces` and `organizations`,
  switched on principal type in both the bash and PowerShell examples. This
  extractor refuted the 2026-08-04 "workspaces only" probe memory on its first
  fixture run. A third segment = routing contract change.

Marker: `api.chatgpt.com/v1/compliance` (the base URL — if it moves, every
extraction from this page is untrustworthy, which is exactly CHANNEL_DEAD's
meaning; no trigger duplicates it, per gotcha #3).

### 3. `chatgpt-docs-index` — learn.chatgpt.com/llms.txt

The ChatGPT Work + Codex documentation index (Codex docs consolidated here per
gotcha #5). Extractor `chatgpt-doc-pages` (measured 140): every `docs/...`
slug. This is where `enterprise/compliance-api.md`, `enterprise/analytics-api.md`,
`enterprise/governance.md`, and the Codex Security pages live — a new
enterprise/security slug is the earliest public signal of a new collectable
surface.

Prose triggers: `compliance-api-guide-listed` and `analytics-api-guide-listed`
(expect=present) — those two pages leaving the index means the enterprise
data-surface documentation moved or was renamed.

Marker: `## Administration` (structural section header, independent of any
watched line).

### 4. `compliance-admin-reference-export` — manual export of chatgpt.com/admin/api-reference

The authoritative Admin API reference is login-gated, so this channel reads an
operator-saved export at
`~/Documents/knowledge-base/reference/openai-data-channels/exports/admin-api-reference.md`
(`local_path` channel; absence reports `LOCAL_SOURCE_MISSING`, run not
failed). Extractors: `admin-reference-event-types` (the FULL enum, incl.
private names the cookbook never lists) and `admin-reference-routes`
(`/v1/...` paths). Refresh the export whenever the admin UI shows new
compliance scopes.

## Live-probe contract ([OUR PROBE] 2026-08-22)

- `after` (ISO8601 with tz) is REQUIRED on every compliance logs call; the
  surface validates FastAPI-style — **422 missing-param = REACHABLE** (endpoint
  exists, key accepted, event_type validated). api.openai.com uses 400 for the
  same class.
- **Event types are scope-bound.** All 7 known types are workspace-scoped;
  `organizations/{org-…}/logs` is LIVE and answers
  `400 "AUTH_LOG is a workspace-scoped event type. Use /v1/compliance/workspaces/…"`.
  Org-scoped type names are unknown — expected to surface via the export
  channel. This supersedes both prior memory states ("workspaces only" and
  "both segments interchangeable").
- Platform Admin families probed 200 (7/7): audit_logs, users, projects,
  invites, admin_api_keys, costs, usage/completions — key
  `OPENAI_PLATFORM_ADMIN_API`; compliance key `OPENAI_CHATGPT_ADMIN_API`.
  Pre-2026-08-04 key names are retired; never guess Keychain names.

## Provenance summary

| Fact-set | Docs-sourced | Observed-only (probe/telemetry) |
|---|---|---|
| Admin reference slugs | all 60 | — |
| API resource groups | all 23 | — |
| Compliance event types | AUTH_LOG | 6 more, all probed 200 on 2026-08-22 |
| Scope segments | both | org path live; event types scope-bound (workspace) |
| ChatGPT doc slugs | all 140 | — |
| Admin-reference enum/routes | (export channel; operator-refreshed) | — |

## Reconcile

`scripts/reconcile_openai_observed.py` (built 2026-08-22, closing the v1
deferral): `--probe` runs the bounded read-only GET set above; `--observed
FILE --update-baseline` merges the OpenAI Monitor's ingest inventory with
`observed_values` provenance (UNDOCUMENTED / DOC_ONLY / RECONCILED verdicts,
mirroring the Anthropic sibling).
