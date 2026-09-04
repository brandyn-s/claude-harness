"""Channel registry: which Anthropic doc page carries which collectable fact-set.

This module is DATA, not logic. Each ChannelSpec names:
  - the doc URL (the authoritative source for that channel)
  - a liveness MARKER that must appear in the fetched body (a fetch that returns
    but misses its marker is a dead/rewritten channel, not a quiet vendor --
    gather-conventions.md §4)
  - the extractors that turn prose into a normalized, diffable fact-set

Extractors are deliberately narrow regexes over doc-page markdown rather than
prose summarization: a set-difference over names/paths/integers has a near-zero
false-positive rate, whereas a raw-page diff drowns in prose rewording. The
tradeoff is that an extractor can go BLIND when the vendor restructures a page
-- which is why every extractor has a `min_expected` floor. Falling below the
floor is reported as INSTRUMENT_BLIND (a detector bug), never as "the vendor
removed everything" (see verify-effectiveness.md: a 0-hit result on a plausible
phenomenon is a detection bug until proven otherwise).

Verified against the live doc surface 2026-07-27.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The spec dataclasses moved to the shared engine dir (2026-08-22) so every
# vendor registry consumes one contract definition. Re-exported here so
# `from channel_specs import ChannelSpec, Extractor, ProseTrigger` keeps working.
_SHARED = Path(__file__).resolve().parents[2] / "_shared" / "endpoint-drift"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
from spec_types import ChannelSpec, Extractor, ProseTrigger  # noqa: E402,F401




# --------------------------------------------------------------------------
# 1. OpenTelemetry (client-side, self-hosted collection)
# --------------------------------------------------------------------------
OTEL = ChannelSpec(
    key="otel",
    title="OpenTelemetry (Claude Code client-side export)",
    url="https://code.claude.com/docs/en/monitoring-usage.md",
    marker="CLAUDE_CODE_ENABLE_TELEMETRY",
    surface="self-hosted",
    extractors=(
        Extractor(
            key="otel-metrics",
            # STRUCTURAL: metrics are declared as the first cell of the metrics
            # table (`| `claude_code.x.y` | description | unit |`). The previous
            # pattern enumerated the 8 known metric FAMILIES
            # (session|lines_of_code|...) — a closed vocabulary, the same defect
            # class as the activity-types verb whitelist: a 9th family would be
            # invisible. Measured 2026-08-22: the table-cell anchor returns the
            # identical 8 values AND stays open to new families. A bare
            # two-segment widening was measured too and REJECTED — it captured
            # `claude_code.tool.execution`/`.blocked_on_user`, which are TRACE
            # SPAN names from the span-tree diagram, not metrics (the
            # cross-surface capture that bit webhook-event-types).
            pattern=r"^\|\s*`(claude_code\.[a-z_.]+)`\s*\|",
            min_expected=8,
            note="A NEW metric is a new collectable counter; a REMOVED one breaks dashboards.",
        ),
        Extractor(
            key="otel-events",
            # STRUCTURAL: the vendor declares every event as
            # `**Event Name**: `claude_code.x``. The previous pattern captured
            # ANY single-segment token, which filed the 4 single-segment TRACE
            # SPAN names (claude_code.{tool,hook,llm_request,interaction}) as
            # events — measured 2026-08-22: the events baseline said "30, all
            # documented" while the observed inventory held only 26, and the 4
            # "documented-but-unobserved" were exactly those spans (a span is a
            # trace signal; it never appears as an event name). The declaration
            # marker yields the observed 26 precisely.
            pattern=r"\*\*Event Name\*\*:\s*`(claude_code\.[a-z_]+)`",
            min_expected=20,
            note="Event types are the audit-grade surface. New event = new detection opportunity.",
        ),
        Extractor(
            key="otel-trace-spans",
            # The span vocabulary from the traces (beta) section, declared as
            # bold-backtick headings (`**`claude_code.tool.execution`**`).
            # Separate fact-set on purpose: 1,444,269 spans were live in a
            # deployment's trace sink (finding #4, retracted), and a span rename
            # is invisible to both the metrics and events sets. Measured
            # 2026-08-22: 6 values, pairwise disjoint with both other sets.
            pattern=r"^\*\*`(claude_code\.[a-z_.]+)`\*\*",
            min_expected=4,
            note=(
                "Span names are the trace-forensics surface (tool.output bodies "
                "under OTEL_LOG_TOOL_CONTENT). A rename breaks span-keyed "
                "queries; a new span is a new forensic join point."
            ),
        ),
        Extractor(
            key="otel-env-vars",
            # NOT backtick-anchored: several vars appear only inside `export FOO=1`
            # code blocks, never in inline code. Requiring backticks silently
            # dropped CLAUDE_CODE_ENABLE_TELEMETRY (caught by the fixture test).
            # ACCEPTED-CLOSED prefix families (OTEL_/CLAUDE_CODE_): these are the
            # vendor's own env namespaces, not a value vocabulary; widening to
            # any ALL_CAPS token over-captures table headers and HTTP constants.
            pattern=r"\b(OTEL_[A-Z0-9_]+|CLAUDE_CODE_[A-Z0-9_]+)\b",
            min_expected=25,
            note="New content-gating flag (OTEL_LOG_*) unlocks a new field; renamed var breaks config.",
        ),
    ),
    note=(
        "Content is off by default; each OTEL_LOG_* flag unlocks a field class. "
        "OTEL_* is NOT inherited by subprocesses (Bash tool, hooks, MCP servers)."
    ),
    prose_triggers=(
        ProseTrigger(
            key="otel-traces-beta",
            pattern=r"#traces-beta",
            expect="present",
            note=(
                "The traces section losing its (beta) anchor means GA — which "
                "changes the adoption calculus for the 1.4M unconsumed spans. "
                "Was a manual Watching row; automated 2026-08-22."
            ),
        ),
    ),
)

# --------------------------------------------------------------------------
# 2. Compliance API -- per-event audit + content (claude.ai)
# --------------------------------------------------------------------------
COMPLIANCE_ACTIVITIES = ChannelSpec(
    key="compliance-activities",
    title="Compliance API - Activity Feed (activity type taxonomy)",
    url="https://platform.claude.com/docs/en/api/compliance/activities/list.md",
    marker="/v1/compliance/activities",
    surface="claude.ai",
    extractors=(
        Extractor(
            key="activity-types",
            # Activity types are DECLARED as an enum bullet followed by a prose
            # description:  - `"seat_tiers_purchased"`\n\n    Seat tiers were...
            # The description requirement is load-bearing: bare `- `"x"`` bullets
            # also carry actor types, `reason`/`result`/`data_type` enum values,
            # and per-setting discriminators (`chat_enabled`), none of which are
            # activity types. The previous verb-suffix whitelist both MISSED real
            # types whose final verb was unlisted (`seat_tiers_purchased`,
            # `inference_hooks_request_denied`, `tunnel_token_minted`) and
            # CAPTURED ~80 field/enum phantoms (`is_enabled`, `repo_ids_added`,
            # `org_member_removed` — a device-trust `reason` value). Measured
            # 2026-08-22: 10/10 sampled phantoms confirmed non-types; 14/14
            # negative controls excluded by this form; every spot-checked real
            # type (incl. all observed-only promotions) captured.
            pattern=(
                r'-\s+`"([a-z][a-z0-9]*(?:_[a-z0-9]+)+)"`\n\n\s+(?![-`])[A-Z]'
            ),
            min_expected=350,
            note=(
                "The audit taxonomy. A NEW type is a newly-auditable action (often a "
                "new product feature landing); a REMOVED type silently breaks a SIEM rule."
            ),
        ),
        Extractor(
            key="activity-actor-types",
            # NOT backtick-anchored: on the API reference the actor union members
            # appear as bare schema tokens, never in inline code (the prose guide
            # backticks them, the reference does not). Requiring backticks
            # extracted ZERO here -- caught by the min_expected floor on the
            # first live run, which is the whole point of that floor.
            pattern=r"\b([a-z][a-z0-9_]*_actor)\b",
            min_expected=6,
            note=(
                "A new actor type means a new class of principal appears in the "
                "audit trail -- a SIEM rule keyed on the actor union silently "
                "misses it. The reference carries more than the prose guide."
            ),
        ),
    ),
)

COMPLIANCE_API = ChannelSpec(
    key="compliance-api",
    title="Compliance API - overview, key types, rate limit",
    url="https://platform.claude.com/docs/en/manage-claude/compliance-api.md",
    marker="/v1/compliance/",
    surface="claude.ai",
    extractors=(
        Extractor(
            key="compliance-ratelimits",
            pattern=r"(\d[\d,]*)\s*requests? per minute",
            min_expected=1,
            note="Rate-limit change forces a poller-pacing change. 600/min per parent org as of 2026-07-27.",
        ),
    ),
)

COMPLIANCE_ENDPOINTS = ChannelSpec(
    key="compliance-endpoints",
    title="Compliance API - endpoint inventory",
    url="https://platform.claude.com/docs/en/api/compliance.md",
    marker="/v1/compliance/",
    surface="claude.ai",
    extractors=(
        Extractor(
            key="compliance-endpoint-paths",
            # STRUCTURED extraction, not prose. The reference declares every real
            # operation as `**get** ` + a backticked path; free prose ALSO renders
            # paths mid-sentence ("Download via `GET .../apps/artifacts/{id}/content`"),
            # and a prose regex captures those plus their PREFIXES as if each were
            # an endpoint.
            #
            # Measured 2026-07-28 on the live page: prose regex -> 33 "endpoints";
            # the `**verb** path` markers -> 31 operations / 28 distinct paths, and
            # ZERO declared operations are missed. So the old pattern never
            # UNDER-captured; it OVER-captured by 5, all of them prefixes of real
            # paths: /apps/artifacts, /apps/chats/files,
            # /apps/chats/generated-files, /apps/projects/documents,
            # /apps/projects/documents/{claude_proj_doc_id}. Those 5 phantom rows
            # cost a wrong "we don't call 11 of 33 endpoints" grade — 4 of them
            # were probed as collection paths, 404'd, and reported as vendor
            # phantoms when the endpoints are real at their {id} form.
            #
            # Trailing punctuation is no longer a concern: a backticked path cannot
            # carry the sentence's period.
            #
            # 2026-08-30: the verb marker is CASE-INSENSITIVE via a scoped `(?i:)`
            # flag. The vendor re-rendered every declaration from `**get**` to
            # `**GET**` between run 6 and run 7, which took BOTH extractors here to
            # 0 and fired INSTRUMENT_BLIND -- the surface was byte-identical (31
            # GET + 5 DELETE = the same 36 operations). The flag is scoped to the
            # verb, not the whole pattern, so the PATH stays case-sensitive: a
            # global re.IGNORECASE would let `/V1/Compliance/...` in prose match.
            pattern=r"\*\*(?i:get|post|put|patch|delete)\*\*\s*`(/v1/compliance/[^`]+)`",
            min_expected=20,
            note="A NEW endpoint is a new collectable stream (e.g. /apps/code/artifacts, added 2026).",
        ),
        Extractor(
            key="compliance-endpoint-operations",
            # verb+path, so a GET->DELETE change or a new DELETE on an existing
            # path is DRIFT. The path-only fact-set above cannot see that: it
            # collapses 31 operations onto 28 paths, and the 5 DELETEs (the only
            # destructive surface in the API) are indistinguishable from the 26
            # GETs. A new DELETE endpoint is exactly the drift most worth alarming
            # on, and it was previously invisible.
            # Case-insensitive verb (see the sibling extractor above). The captured
            # verb is upper()'d by the engine's `pair` handling, so the fact-set is
            # stable across a vendor case flip and the baseline needs no rewrite.
            pattern=r"\*\*((?i:get|post|put|patch|delete))\*\*\s*`(/v1/compliance/[^`]+)`",
            kind="pair",
            min_expected=20,
            note="A new DELETE (or a verb change) on a compliance path is the highest-risk drift class.",
        ),
    ),
)

# Scopes live on the ACCESS page, not the endpoint reference (the reference never
# names them). Splitting this into its own channel keeps each extractor pointed
# at the page that actually carries its facts -- a single spec spanning both
# pages would report a permanent INSTRUMENT_BLIND for whichever half is absent.
COMPLIANCE_ACCESS = ChannelSpec(
    key="compliance-access",
    title="Compliance API - key types and scopes",
    url="https://platform.claude.com/docs/en/manage-claude/compliance-api-access.md",
    marker="Compliance Access Key",
    surface="claude.ai",
    extractors=(
        Extractor(
            key="compliance-scopes",
            # Verb half is OPEN ([a-z]+): the old (read|delete|write) whitelist
            # was a closed set — a new verb class (admin:, org:) would be
            # invisible. Measured 2026-08-22: identical 4 values today, zero
            # over-capture (the :compliance anchor does the discriminating).
            pattern=r"\b([a-z]+:compliance[a-z_]*)\b",
            min_expected=3,
            note=(
                "A new scope means a new permission gate to request on the "
                "Compliance Access Key -- and a new capability boundary."
            ),
        ),
        Extractor(
            key="key-prefixes",
            pattern=r"`(sk-ant-[a-z0-9]+)-",
            min_expected=2,
            note="Key-class prefixes. A new prefix = a new key type = a new access path.",
        ),
    ),
)

# Session-transcript capture guide (new page, surfaced by the coverage guard
# 2026-08-22). The endpoints themselves are extracted by compliance-endpoints;
# what THIS page uniquely declares is the product->surface coverage map, and the
# vendor promises expansion in place ("Products are added to this table as
# coverage expands" / "New values appear as coverage expands"). A new
# product_surface value = a new product's transcripts entering the feed.
COMPLIANCE_SESSIONS = ChannelSpec(
    key="compliance-sessions",
    title="Compliance API - session transcripts (Cowork + Claude Code)",
    url="https://platform.claude.com/docs/en/manage-claude/compliance-sessions.md",
    marker="product_surface",
    surface="claude.ai",
    extractors=(
        Extractor(
            key="session-product-surfaces",
            # The mapping table's middle column always reads "... session
            # endpoints ..." and the last cell is the backticked surface value.
            # Anchoring on the middle column excludes the retention table, the
            # `product_surface` header token, and id-prefix cells (`clls_`,
            # `cse_`) that a bare last-cell match captures (measured 2026-08-22).
            #
            # 2026-08-30: this pattern requires the value cell to be a SINGLE
            # backticked token ending the cell, so it cannot see the Claude for
            # Microsoft 365 row, whose cell holds FIVE slash-bearing values
            # ("`office_agents/excel`, `office_agents/powerpoint`, ... (`office_agents`
            # when the app is not identified)"). Slashes fall outside the char
            # class and the multi-value cell defeats the trailing `\|` anchor.
            # The M365 family therefore gets its own extractor below rather than a
            # looser pattern here -- loosening this one to span a multi-value cell
            # is how prose regexes start capturing prefixes (see
            # compliance-endpoint-paths).
            pattern=r"session endpoints[^|]*\|\s*`([a-z][a-z0-9_]+)`\s*\|",
            min_expected=3,
            note=(
                "A new product_surface value means a NEW PRODUCT's session "
                "transcripts entered the Compliance feed -- a collection "
                "opportunity and a coverage-matrix change (the vendor promises "
                "expansion in this exact table)."
            ),
        ),
        Extractor(
            key="session-product-surfaces-office",
            # The Claude for Microsoft 365 add-in surfaces, invisible to the
            # mapping-table extractor above (see its note). Anchored on the
            # distinctive `office_agents` prefix inside backticks, so it cannot
            # pick up prose: measured 2026-08-30, 11 match sites on the live page
            # all resolve to these 5 values and nothing else.
            #
            # Why this matters beyond completeness: these are the session
            # transcripts of the Excel/PowerPoint/Word/Outlook add-ins. The union
            # of both extractors is 9 values, which reconciles EXACTLY with the
            # vendor's own enumerating sentence (8 local values + `cowork_remote`
            # from the remote family). Before this extractor the fact-set was 4
            # of 9 -- and the 5 missing ones were the M365 surface.
            pattern=r"`(office_agents(?:/[a-z]+)?)`",
            min_expected=5,
            note=(
                "Claude for Microsoft 365 add-in session surfaces (Excel, "
                "PowerPoint, Word, Outlook, plus bare `office_agents` when the "
                "app is unidentified). A new per-app value = another add-in's "
                "transcripts in the Compliance feed."
            ),
        ),
    ),
)

# --------------------------------------------------------------------------
# 3. Admin API -- billing-grade usage/cost + org management (Console)
# --------------------------------------------------------------------------
ADMIN_USAGE_COST = ChannelSpec(
    key="admin-usage-cost",
    title="Admin API - Usage and Cost",
    url="https://platform.claude.com/docs/en/manage-claude/usage-cost-api.md",
    marker="usage_report/messages",
    surface="platform",
    extractors=(
        Extractor(
            key="admin-endpoint-paths",
            pattern=r"(/v1/organizations/[a-z_/]+)",
            min_expected=2,
            note="New usage/cost endpoint = new billing-grade feed.",
        ),
        Extractor(
            key="admin-bucket-widths",
            # `\d+`, not the literal `1`: a hardcoded width digit is a closed
            # set — a new `7d` or `15m` bucket would be invisible. Measured
            # 2026-08-22: identical {1m,1h,1d} today.
            pattern=r"`(\d+[mhd])`",
            min_expected=3,
            note="Bucket granularity options; a new one (e.g. 1w) changes aggregation strategy.",
        ),
    ),
    note="cost_report excludes Priority Tier; usage_report/messages excludes code execution.",
    prose_triggers=(
        ProseTrigger(
            key="aws-usage-cost-gap",
            pattern=r"not currently available",
            expect="present",
            note=(
                "Claude Platform on AWS usage/cost is API-invisible today; this "
                "sentence disappearing means programmatic usage/cost became "
                "reachable. Was a manual Watching row; automated 2026-08-22."
            ),
        ),
    ),
)

ADMIN_CLAUDE_CODE = ChannelSpec(
    key="admin-claude-code-analytics",
    title="Claude Code Analytics API (Admin key)",
    url="https://platform.claude.com/docs/en/api/admin/usage_report/retrieve_claude_code.md",
    marker="/v1/organizations/usage_report/claude_code",
    surface="platform",
    extractors=(
        Extractor(
            key="cc-analytics-fields",
            pattern=r"^\s*-\s+`([a-z_]+):",
            min_expected=15,
            note="Per-user daily metric fields. New field = new productivity signal.",
        ),
    ),
    note=(
        "DOCUMENTED EXCLUSION: tracks Claude Code on the Claude API only -- Bedrock, "
        "Microsoft Foundry, Google Cloud, Claude Platform on AWS are NOT included."
    ),
)

# --------------------------------------------------------------------------
# 4. Claude Enterprise Analytics API (claude.ai, Analytics key)
# --------------------------------------------------------------------------
ANALYTICS_ENTERPRISE = ChannelSpec(
    key="analytics-enterprise",
    title="Claude Enterprise Analytics API",
    url="https://platform.claude.com/docs/en/api/admin/analytics.md",
    marker="/v1/organizations/analytics/",
    surface="claude.ai",
    extractors=(
        Extractor(
            key="analytics-endpoint-paths",
            pattern=r"`?(/v1/organizations/analytics/[a-z_/]+)`?",
            min_expected=9,
            note=(
                "The endpoint inventory. 11 known as of 2026-07-27; 5 of them "
                "(skills, plugins, connectors, artifacts, apps/chat/projects) were "
                "added after our first audit -- exactly the drift this skill exists to catch."
            ),
        ),
    ),
)

ANALYTICS_GUIDE = ChannelSpec(
    key="analytics-guide",
    title="Analytics APIs - key types, freshness, limits, exclusions",
    url="https://platform.claude.com/docs/en/manage-claude/analytics-api.md",
    marker="read:analytics",
    surface="both",
    extractors=(
        Extractor(
            key="analytics-ratelimits",
            pattern=r"(\d[\d,]*)\s*requests per minute",
            min_expected=1,
            note="60/min per ORGANIZATION (not per key) as of 2026-07-27.",
        ),
        Extractor(
            key="analytics-freshness-windows",
            # Capture the UNIT with the number: the old pattern captured bare
            # digits, so "24 hours" and a hypothetical "24 days" were the SAME
            # fact and a unit change was invisible drift. Baseline values
            # migrate "24" -> "24 hours" (one-time refresh, 2026-08-22).
            pattern=r"(?:up to |within )(\d+\s*(?:hours|days))",
            min_expected=2,
            note=(
                "Freshness/revision windows drive when a number is invoicing-grade. "
                "30-day revision window + 4h/24h availability as of 2026-07-27."
            ),
        ),
    ),
    prose_triggers=(
        ProseTrigger(
            key="analytics-bedrock-limitation",
            pattern=r"does not return Claude Code activity",
            expect="present",
            note=(
                "The Known-limitations Bedrock exclusion. Its disappearance "
                "would close our biggest per-user attribution gap. Was a "
                "manual Watching row; automated 2026-08-22."
            ),
        ),
    ),
)

# Prose-trigger-only channel: the CC Analytics GUIDE page. Its endpoint facts
# are extracted from the API reference (admin-claude-code-analytics); what this
# page uniquely carries is the Bedrock exclusion sentence the Watching table
# tracked by hand — and run 3 false-zeroed that hand check by probing the WRONG
# page. Encoding the trigger against the page it names ends that failure class.
ANALYTICS_CC_GUIDE = ChannelSpec(
    key="analytics-cc-guide",
    title="Claude Code Analytics guide - exclusions prose",
    url="https://platform.claude.com/docs/en/manage-claude/claude-code-analytics-api.md",
    marker="Claude Code Analytics",
    surface="platform",
    extractors=(),
    prose_triggers=(
        ProseTrigger(
            key="cc-analytics-bedrock-exclusion",
            pattern=r"only tracks Claude Code usage on the Claude API",
            expect="present",
            note=(
                "The Bedrock/Vertex exclusion sentence, verbatim 2026-08-22. "
                "Firing on a reword is intended: the exclusion's wording IS "
                "the fact, and any change means re-reading the page."
            ),
        ),
    ),
)

# Prose-trigger-only channel: App Attest. Excluded from the registry as a
# non-data-surface in run 4 (0 endpoints, 0 scopes, console-only) with a manual
# Watching row for "an API appears". The trigger now runs in code; the page
# costs one fetch per run.
APP_ATTEST = ChannelSpec(
    key="app-attest",
    title="App Attest - device-attestation auth (API appearance watch)",
    url="https://platform.claude.com/docs/en/manage-claude/app-attest.md",
    marker="App Attest",
    surface="platform",
    extractors=(),
    prose_triggers=(
        ProseTrigger(
            key="app-attest-api",
            pattern=r"/v1/",
            expect="absent",
            note=(
                "Registration/revocation is Console-UI-only today. A /v1/ path "
                "appearing makes app integrations programmatically "
                "inventoriable, like api_keys. Was a manual Watching row."
            ),
        ),
    ),
)

# --------------------------------------------------------------------------
# 5. Push channels
# --------------------------------------------------------------------------
WEBHOOKS = ChannelSpec(
    key="webhooks-managed-agents",
    title="Managed Agents webhooks (push)",
    url="https://platform.claude.com/docs/en/managed-agents/webhooks.md",
    marker="webhook",
    surface="platform",
    extractors=(
        Extractor(
            key="webhook-event-types",
            # Anchored to the event TABLE ROW (`| `event` | description |`).
            # An unanchored backtick match also captures prose mentions of the
            # EVENT STREAM's different vocabulary — measured 2026-08-22:
            # "the stream's `session.status_idle` and `session.status_running`
            # correspond to the `session.status_idled` and
            # `session.status_run_started` webhook events" produced 2 phantom
            # NEW webhook types that are another surface's names.
            # Prefix half is OPEN: the previous
            # (agent|deployment|environment|session|memory_store|vault) family
            # list was a closed set — a new family (runner.*, workspace.*)
            # would be invisible. The TABLE-ROW anchor does the real
            # discriminating (prose mentions of other surfaces' vocabularies
            # stay excluded). Measured 2026-08-22: identical 38 values.
            pattern=r"\|\s*`([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)`\s*\|",
            min_expected=20,
            note="Push events. A new one is a new real-time signal we could subscribe to.",
        ),
    ),
)

# --------------------------------------------------------------------------
# 6. Self-hosted intercept
# --------------------------------------------------------------------------
GATEWAY = ChannelSpec(
    key="gateway",
    title="Claude apps gateway (self-hosted intercept: audit log + OTLP fan-out)",
    url="https://code.claude.com/docs/en/claude-apps-gateway-config.md",
    marker="telemetry",
    surface="self-hosted",
    extractors=(
        Extractor(
            key="gateway-telemetry-keys",
            # Bare, not backticked: the pushed-var list renders as a bullet list
            # of plain tokens. Floor is 4 (live: 7 as of 2026-07-27).
            pattern=r"\b(CLAUDE_CODE_[A-Z0-9_]+|OTEL_[A-Z0-9_]+)\b",
            min_expected=4,
            note=(
                "Env vars the gateway pushes to clients at the managed tier "
                "(overriding developer-set OTEL_*). A new one changes what the "
                "org collects without any client-side change."
            ),
        ),
        Extractor(
            key="gateway-config-sections",
            pattern=r"^###\s+`([a-z_]+)`\s*$",
            min_expected=6,
            note="A new gateway.yaml section can be a new enforcement or telemetry surface.",
        ),
    ),
    note=(
        "Gives per-request JSON audit log with IdP identity + server-side "
        "user.id/user.email/user.groups stamping -- the only channel that closes "
        "the Bedrock per-user attribution gap the Admin/Analytics feeds document."
    ),
)

# --------------------------------------------------------------------------
# 7. Constraints that gate collection
# --------------------------------------------------------------------------
ZDR = ChannelSpec(
    key="zdr",
    title="Zero Data Retention - features disabled, collection impact",
    url="https://code.claude.com/docs/en/zero-data-retention.md",
    marker="zero data retention",
    surface="both",
    extractors=(
        Extractor(
            key="zdr-table-rows",
            # First cell of every table row on the page — both the
            # what-ZDR-does-not-cover table and the features-disabled table.
            # A row added or removed in EITHER is the Watching-table trigger
            # ("channel availability for ZDR orgs"), previously checked by
            # hand-counting rows each run. Greedy name capture ending on a
            # non-space, optional markdown link unwrapped; measured 2026-08-22:
            # 10 clean feature names ('Cloud sessions' included — a lazy
            # quantifier missed it behind its post-link text).
            pattern=r"^\|\s*\[?([A-Za-z][^|\]\n]{1,59}[^\s|\]\n])",
            min_expected=8,
            note=(
                "A row appearing/disappearing in the ZDR coverage or "
                "disabled-features tables changes channel availability for "
                "ZDR orgs. ('Feature' header rows are part of the set; a "
                "header rename is page restructuring worth seeing.)"
            ),
        ),
    ),
    note="ZDR disables Web/cloud sessions/Artifacts/feedback/Remote Control and contribution metrics.",
)

DATA_USAGE = ChannelSpec(
    key="data-usage",
    title="Data usage - Anthropic-bound telemetry and opt-outs",
    url="https://code.claude.com/docs/en/data-usage.md",
    marker="Telemetry services",
    surface="both",
    extractors=(
        Extractor(
            key="telemetry-optout-vars",
            pattern=r"`(DISABLE_[A-Z_]+|CLAUDE_CODE_DISABLE_[A-Z_]+)`",
            min_expected=3,
            note="Opt-out surface for Anthropic-bound operational telemetry.",
        ),
    ),
)

DASHBOARDS = ChannelSpec(
    key="dashboards",
    title="Dashboards, CSV exports, GitHub contribution attribution",
    url="https://code.claude.com/docs/en/analytics.md",
    marker="analytics",
    surface="both",
    extractors=(
        Extractor(
            key="dashboard-urls",
            pattern=r"(https://(?:claude\.ai|platform\.claude\.com)/[a-z0-9/-]*analytics[a-z0-9/-]*)",
            min_expected=2,
            note="UI surfaces + their CSV exports.",
        ),
    ),
    note="GitHub attribution: 21d-before/2d-after window, >20% rewrite drops attribution, labels PRs claude-code-assisted.",
)

RATE_LIMITS = ChannelSpec(
    key="admin-rate-limits",
    title="Admin API - organization rate limits endpoint",
    url="https://platform.claude.com/docs/en/api/admin/rate_limits/list.md",
    marker="rate_limits",
    surface="platform",
    extractors=(
        Extractor(
            key="ratelimit-endpoint",
            pattern=r"(/v1/organizations/rate_limits)",
            min_expected=1,
            note="Org rate limits are themselves a collectable feed.",
        ),
    ),
)


# --------------------------------------------------------------------------
# Channels added 2026-07-28 after a COVERAGE AUDIT found the registry watched
# 15 doc pages while `manage-claude/` alone has 28 -- and only 4 of the 15 were
# in it. Root cause: the registry was seeded by KEYWORD-GREPPING llms.txt, then
# treated as if it were the surface. A page whose title lacks a monitoring
# keyword (access-transparency, cmek, workspaces) was structurally invisible,
# and probing cannot find what the registry never lists.
#
# See `enumerate_uncovered_pages()` below: the guard that makes this class of
# gap visible instead of silent.
# --------------------------------------------------------------------------

ADMIN_KEY_SCOPES = ChannelSpec(
    key="admin-api-keys",
    title="Admin API keys - the AUTHORITATIVE scope table",
    url="https://platform.claude.com/docs/en/manage-claude/admin-api-keys.md",
    marker="read:analytics",
    surface="platform",
    extractors=(
        Extractor(
            key="all-scopes",
            # Verb half is OPEN. Measured 2026-08-22: the old
            # (read|write|delete|api) whitelist MISSED `org:admin` — the OAuth
            # bearer scope the service-account/federation-issuer/federation-rule
            # endpoints require — i.e. a whole authentication class absent from
            # the fact-set. Widening captures 13 (12 + org:admin) with zero
            # noise: the backticks + verb:noun shape discriminate.
            pattern=r"`([a-z]+:[a-z_]+)`",
            min_expected=10,
            note=(
                "THE authoritative scope list (12 live). Not on compliance-api-access, "
                "which is why an earlier registry saw only the 4 compliance scopes and "
                "missed read:org_audit -- a single read-only scope covering every Admin "
                "user-management READ plus every Compliance READ, for audit integrations."
            ),
        ),
    ),
)

ACCESS_TRANSPARENCY = ChannelSpec(
    key="access-transparency",
    title="Access Transparency - Anthropic disclosing its OWN access to your data",
    url="https://platform.claude.com/docs/en/manage-claude/access-transparency.md",
    marker="Access Transparency",
    surface="both",
    extractors=(),
    note=(
        "A data channel in its own right and the single largest registry miss: it "
        "reports ANTHROPIC-side access to customer data. Prose-only (no stable token "
        "set), so it is marker-watched; a Watching trigger carries the semantics."
    ),
)

CMEK = ChannelSpec(
    key="cmek",
    title="Customer-managed encryption keys (CMEK) + external_keys endpoints",
    url="https://platform.claude.com/docs/en/manage-claude/cmek.md",
    marker="ustomer-managed",
    surface="platform",
    extractors=(),
    note=(
        "Per-provider pages (cmek-aws-kms / -azure-key-vault / -google-cloud-kms) "
        "document /v1/organizations/external_keys. Key-custody posture: a revoked "
        "CMEK key changes what is readable AT ALL, so it gates every content channel."
    ),
)

#: Canonicalize a CONCRETE EXAMPLE ID back to the vendor's own placeholder name.
#:
#: The Admin API pages under manage-claude/ declare no endpoint marker -- every
#: path appears only inside a `curl` example -- so whatever the example renders
#: IS the extracted fact. On 2026-08-30 Anthropic re-rendered those examples from
#: `{workspace_id}` to a literal `wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ`, which made
#: `workspaces` and `wif` report added/REMOVED pairs for an UNCHANGED endpoint
#: set. Two channels were worse off: `user-management` and `spend-limits` had
#: BOTH forms baselined (13 rows for 8 real endpoints) and so never drifted --
#: stably wrong, which is why no alarm had ever fired on them.
#:
#: This REWRITES rather than DROPS, so no endpoint can be lost -- the property
#: that separates it from tightening the path regex, which silently deleted the
#: real /archive and /members endpoints while turning the report green.
#: Truth table over all 4 ID-bearing channels, 2026-08-30: 0 raw values
#: unmapped, 0 residual literal IDs, `workspaces` reproduces its baseline
#: EXACTLY (4/4), and `wif` GAINS the two real /archive endpoints that the old
#: pattern had truncated into the phantoms `.../fdis_` and `.../fdrl_`.
#:
#: Add a prefix here only with a page citation; an unmapped prefix leaves a
#: literal ID in the fact-set and reintroduces the churn.
EXAMPLE_ID_NORM: tuple[tuple[str, str], ...] = (
    (r"/wrkspc_[A-Za-z0-9]+", "/{workspace_id}"),
    (r"/rbac_group_[A-Za-z0-9]+", "/{group_id}"),
    (r"/user_[A-Za-z0-9]+", "/{user_id}"),
    (r"/invite_[A-Za-z0-9]+", "/{invite_id}"),
    (r"/fdis_[A-Za-z0-9]+", "/{issuer_id}"),
    (r"/fdrl_[A-Za-z0-9]+", "/{rule_id}"),
    (r"/slir_[A-Za-z0-9]+", "/{id}"),
    (r"/spl_[A-Za-z0-9]+", "/{id}"),
)

WORKSPACES = ChannelSpec(
    key="workspaces",
    title="Workspaces - the cost/usage attribution dimension",
    url="https://platform.claude.com/docs/en/manage-claude/workspaces.md",
    marker="/v1/organizations/workspaces",
    surface="platform",
    extractors=(
        Extractor(
            key="workspace-endpoints",
            pattern=r"(/v1/organizations/workspaces[A-Za-z0-9_/{}-]*)",
            min_expected=3,
            normalize=EXAMPLE_ID_NORM,
            note="workspace_id is the group_by dimension cost_report reconciles on.",
        ),
    ),
)

USER_MANAGEMENT = ChannelSpec(
    key="user-management",
    title="User management / RBAC groups / invites",
    url="https://platform.claude.com/docs/en/manage-claude/user-management.md",
    marker="rbac_groups",
    surface="platform",
    extractors=(
        Extractor(
            key="user-mgmt-endpoints",
            pattern=r"(/v1/organizations/(?:users|invites|rbac_groups)[A-Za-z0-9_/{}-]*)",
            min_expected=4,
            normalize=EXAMPLE_ID_NORM,
            note=(
                "Group membership = access-review + offboarding data. Probed 2026-07-28: "
                "users/invites 200, rbac_groups 403 (needs read:rbac_groups|read:org_audit)."
            ),
        ),
    ),
)

SPEND_LIMITS = ChannelSpec(
    key="spend-limits",
    title="Spend Limits API - per-user cost caps + increase-request workflow",
    url="https://platform.claude.com/docs/en/manage-claude/spend-limits-api.md",
    marker="spend_limit",
    surface="platform",
    extractors=(
        Extractor(
            key="spend-limit-endpoints",
            pattern=r"(/v1/organizations/spend_limit[A-Za-z0-9_/{}-]*)",
            min_expected=3,
            normalize=EXAMPLE_ID_NORM,
            note=(
                "Probed 2026-07-28: /spend_limits 405 on GET (not collection-listable); "
                "/spend_limit_increase_requests 400 'not supported for this organization "
                "type' -- a REACHABILITY gate, not a scope gate. CORRECTED 2026-08-01: "
                "that 400 was the CONSOLE key (sk-ant-admin01-) hitting a claude.ai-"
                "Enterprise-ONLY endpoint, i.e. the WRONG ORG -- not a fact about our org. "
                "Re-probe with the claude.ai key (sk-ant-api01-): 403 'Organization level "
                "API key required', so the endpoint is LIVE and needs read:spend_limits. "
                "This channel must be probed with the ENTERPRISE key; a Console-key probe "
                "of it is meaningless."
            ),
        ),
    ),
)

WIF = ChannelSpec(
    key="wif",
    title="Workload Identity Federation - federation issuers + rules",
    url="https://platform.claude.com/docs/en/manage-claude/wif-admin-api.md",
    marker="federation",
    surface="platform",
    extractors=(
        Extractor(
            key="wif-endpoints",
            pattern=r"(/v1/organizations/federation_[a-z_]+[A-Za-z0-9_/{}-]*)",
            min_expected=2,
            normalize=EXAMPLE_ID_NORM,
            note=(
                "WIF is how a federated_identity_actor comes to exist -- the actor type "
                "finding #1 is about. Issuer/rule changes alter who can act on the org."
            ),
        ),
    ),
)

RATE_LIMITS_API = ChannelSpec(
    key="rate-limits-api",
    title="Rate Limits API - org AND per-workspace limits",
    url="https://platform.claude.com/docs/en/manage-claude/rate-limits-api.md",
    marker="rate_limits",
    surface="platform",
    extractors=(
        Extractor(
            key="rate-limit-endpoints",
            pattern=r"(/v1/organizations/(?:rate_limits|workspaces/\{workspace_id\}/rate_limits))",
            min_expected=2,
            note=(
                "PER-WORKSPACE rate limits exist, not just org-level -- the registry "
                "previously watched only the org endpoint."
            ),
        ),
    ),
)


# --------------------------------------------------------------------------
# 8. Inference hooks -- the ONLY inbound channel: Anthropic calls US
# --------------------------------------------------------------------------
# Direction is the reason these are separate channels rather than a note on
# compliance-api. Every other channel here is one we POLL; Inference hooks
# inverts that -- Anthropic POSTs the full conversation transcript to an HTTPS
# endpoint we operate, before inference runs, and waits for an allow/deny
# verdict. The vendor's own comparison table says so ("Direction | Anthropic
# calls your AI security server | You call Anthropic's API").
#
# That makes drift here higher-consequence than a normal fact-set: a change to
# the frame schema, the signature headers, or the verdict contract breaks a
# server WE run, in the inference path, where the failure mode is decided by our
# fail-open/fail-closed setting rather than by a poller retry.
INFERENCE_HOOKS = ChannelSpec(
    key="inference-hooks",
    title="Inference hooks - inline allow/deny gate (Anthropic calls us)",
    url="https://platform.claude.com/docs/en/manage-claude/inference-hooks.md",
    marker="AI security server",
    surface="claude.ai",
    extractors=(
        Extractor(
            key="hook-event-types",
            pattern=r"only hook event is `([a-z_]+)`",
            min_expected=1,
            note=(
                "`prompt` is the ONLY event today; the page states response-side "
                "enforcement is planned. A second event appearing here means the hook "
                "starts firing at a new point in the request lifecycle -- i.e. a new "
                "inbound data surface, not just a new name."
            ),
        ),
    ),
    prose_triggers=(
        ProseTrigger(
            key="ih-beta",
            pattern=r"in beta",
            expect="present",
            note=(
                "GA changes the adoption calculus for the inline gate. Was a "
                "manual Watching row; run 6's hand check false-zeroed on a "
                "literal-`(beta)` grep — the page says 'in beta'."
            ),
        ),
        ProseTrigger(
            key="ih-config-api",
            pattern=r"/v1/",
            expect="absent",
            note=(
                "Enablement is claude.ai-console-only today, so this channel's "
                "state is unverifiable from our side. A /v1/ path appearing "
                "means a config API exists — probeable, and drift measurable."
            ),
        ),
    ),
)

INFERENCE_HOOKS_CONFIG = ChannelSpec(
    key="inference-hooks-config",
    title="Inference hooks - enforcement, failure handling, rollout controls",
    url="https://platform.claude.com/docs/en/manage-claude/inference-hooks-configuration.md",
    marker="Enforce verdicts",
    surface="claude.ai",
    extractors=(
        Extractor(
            key="hook-failure-modes",
            pattern=r"\*\*(Block the request|Allow the request|Shadow mode)\*\*",
            min_expected=3,
            note=(
                "The fail-closed / fail-open / shadow triad. These are the settings that "
                "decide what happens to USER TRAFFIC when our endpoint is unreachable, so "
                "a change to this set changes our blast radius. Deliberately NOT extracting "
                "the timeout bounds (1-10,000ms) or the rollout percentage: both are prose "
                "numbers and the Watching table is the right instrument for them."
            ),
        ),
    ),
    prose_triggers=(
        ProseTrigger(
            key="ih-config-api-config-page",
            pattern=r"/v1/",
            expect="absent",
            note="Same trigger as ih-config-api, on the configuration page.",
        ),
    ),
)

INFERENCE_HOOKS_ENDPOINT = ChannelSpec(
    key="inference-hooks-endpoint",
    title="Inference hooks - request/verdict wire contract we must implement",
    url="https://platform.claude.com/docs/en/manage-claude/inference-hooks-endpoint.md",
    marker="anthropic-dlp/1",
    surface="claude.ai",
    extractors=(
        Extractor(
            key="hook-frame-fields",
            # The trailing `\|` is load-bearing: it requires the type cell to CLOSE
            # immediately after the type name. Without it the verdict table's rows leak
            # in, because their type cell also STARTS with "string or null" ("string or
            # null; at most 500 characters"). Measured on the live page: 11 with the
            # loose pattern, 9 with this one, and 9 is the frame table's real row count.
            pattern=r"^\|\s*`([a-z_]+)`\s*\|\s*(?:string|object|array|string or null)\s*\|",
            min_expected=7,
            note=(
                "The prompt-frame schema Anthropic sends us. `actor` carries id + "
                "email_address (both nullable), so identity resolution here has the same "
                "shape as finding #1's actor-union problem on the Activity Feed."
            ),
        ),
        Extractor(
            key="hook-content-block-types",
            # OPEN over block-type names: the old (text|tool_use|tool_result|
            # attachment) alternation was a closed set — a new block type (an
            # `image` block, say) would be invisible, on the one fact-set whose
            # additions change what our DLP endpoint must inspect. The anchor is
            # the content-block table's SHAPE: its second cell starts with a
            # backticked field name + colon (`` `text`: ``), which the frame
            # table (type words) and signature table (dashed header names) do
            # not. Measured 2026-08-22: exactly the 4 block types.
            pattern=r"^\|\s*`([a-z_]+)`\s*\|\s*`[a-z_]+`:",
            min_expected=4,
            note=(
                "What the transcript can contain. This is the DLP-relevant fact-set: "
                "tool_result carries tool output, attachment carries extracted document "
                "text. Raw file/image bytes are never sent, so image-only content is a "
                "documented inspection blind spot."
            ),
        ),
        # (prose trigger ih-config-api-endpoint-page added below, after the
        # remaining extractors)
        Extractor(
            key="hook-signature-headers",
            pattern=r"`(webhook-(?:id|timestamp|signature))`",
            min_expected=3,
            note=(
                "Standard Webhooks signing: HMAC-SHA256 over "
                "{webhook-id}.{webhook-timestamp}.{raw body}. A change to this set is an "
                "AUTHENTICATION break on an endpoint that gates inference -- the highest-"
                "consequence drift this channel can carry."
            ),
        ),
        Extractor(
            key="hook-verdict-fields",
            # ACCEPTED-CLOSED (audited 2026-08-22): the verdict and frame tables
            # share the same 3-column `| `field` | constraints | semantics |`
            # shape, so no structural anchor separates a hypothetical 4th
            # verdict field from a frame field. A REMOVED/renamed field still
            # alarms (the set shrinks below min_expected or drifts); a purely
            # additive 4th field would be missed here and is covered by the
            # wire-contract Watching row instead.
            pattern=r"^\|\s*`(action|deny_reason|reference_id)`\s*\|",
            min_expected=3,
            note=(
                "What our server must return. `reference_id` is the join key onto the "
                "`inference_hooks_request_denied` compliance activity, which is how a "
                "denial in our system reconciles with Anthropic's audit record."
            ),
        ),
    ),
    prose_triggers=(
        ProseTrigger(
            key="ih-config-api-endpoint-page",
            pattern=r"/v1/",
            expect="absent",
            note="Same trigger as ih-config-api, on the endpoint-contract page.",
        ),
    ),
)


ALL_CHANNELS: tuple[ChannelSpec, ...] = (
    OTEL,
    COMPLIANCE_API,
    COMPLIANCE_ACTIVITIES,
    COMPLIANCE_ENDPOINTS,
    COMPLIANCE_ACCESS,
    COMPLIANCE_SESSIONS,
    ADMIN_USAGE_COST,
    ADMIN_CLAUDE_CODE,
    RATE_LIMITS,
    ANALYTICS_ENTERPRISE,
    ANALYTICS_GUIDE,
    ANALYTICS_CC_GUIDE,
    APP_ATTEST,
    WEBHOOKS,
    GATEWAY,
    ZDR,
    DATA_USAGE,
    DASHBOARDS,
    # added 2026-07-28 by the coverage audit
    ADMIN_KEY_SCOPES,
    ACCESS_TRANSPARENCY,
    CMEK,
    WORKSPACES,
    USER_MANAGEMENT,
    SPEND_LIMITS,
    WIF,
    RATE_LIMITS_API,
    # added 2026-08-08 (run 4, finding #19) — the coverage guard reported these 3
    # pages UNCOVERED, which is exactly the trigger run 3 armed for it.
    INFERENCE_HOOKS,
    INFERENCE_HOOKS_CONFIG,
    INFERENCE_HOOKS_ENDPOINT,
)

BY_KEY = {c.key: c for c in ALL_CHANNELS}


def all_extractor_keys() -> list[str]:
    return [e.key for c in ALL_CHANNELS for e in c.extractors]


# --------------------------------------------------------------------------
# COVERAGE GUARD
# --------------------------------------------------------------------------
#: Doc-index neighbourhoods this registry claims to cover completely. A page in
#: one of these that no ChannelSpec names is a COVERAGE GAP -- reported, never
#: silently excluded.
# The `(?:[a-z0-9-]+/)?` segment is load-bearing: the original pattern was
# `[a-z0-9-]+\.md` with no `/`, so it could not match a page one directory DEEP.
# Measured 2026-08-01: `manage-claude/wif-providers/{aws,github-actions,gcp,
# kubernetes,azure,okta,spiffe}.md` -- 7 pages -- were structurally invisible, and
# the guard reported "28 accounted / 0 UNCOVERED" while a whole subdirectory sat
# outside both the channel set AND the exclusion registry.
#
# That is finding #9's own mechanism (filter-and-assume) recurring INSIDE the
# guard built to prevent it: a guard whose pattern cannot express a path shape
# answers "nothing uncovered" for a reason that has nothing to do with coverage.
COVERED_NEIGHBOURHOODS: tuple[tuple[str, str], ...] = (
    (
        "platform-manage-claude",
        r"https://platform\.claude\.com/docs/en/manage-claude/(?:[a-z0-9-]+/)?[a-z0-9-]+\.md",
    ),
)

#: Pages inside a covered neighbourhood that are DELIBERATELY not channels, each
#: with a reason. An empty reason is not allowed -- the point is that every
#: exclusion is a recorded decision rather than an accident of keyword filtering.
DELIBERATE_EXCLUSIONS: dict[str, str] = {
    "admin-api.md": "index page; its endpoints are covered by admin-usage-cost + user-management + workspaces",
    "authentication.md": "how-to for auth headers; no collectable surface",
    "compliance-activity-feed.md": "prose guide for a surface compliance-activities already watches (and it is the LESS complete of the two -- 6 actor types vs the reference's 9)",
    "compliance-content-data.md": "prose guide; endpoints covered by compliance-endpoints",
    "compliance-errors.md": "error-code reference; no collectable surface",
    "compliance-faq.md": "FAQ; no collectable surface",
    "compliance-integration-patterns.md": "design guidance; no collectable surface",
    "compliance-org-data.md": "prose guide; endpoints covered by compliance-endpoints",
    "cmek-aws-kms.md": "per-provider variant of cmek.md (same external_keys endpoints)",
    "cmek-azure-key-vault.md": "per-provider variant of cmek.md",
    "cmek-google-cloud-kms.md": "per-provider variant of cmek.md",
    "api-and-data-retention.md": "prose retention/HIPAA matrices with no stable token set; Watching-table triggers instead",
    "data-residency.md": "prose; residency also appears as a group_by dimension on admin-usage-cost",
    "wif-reference.md": "reference detail for the wif channel",
    "workload-identity-federation.md": "concept page for the wif channel",
    "analytics-api.md": "covered as the analytics-guide channel",
    "compliance-api.md": "covered as the compliance-api channel",
    "compliance-api-access.md": "covered as the compliance-access channel",
    "usage-cost-api.md": "covered as the admin-usage-cost channel",
    "admin-api-keys.md": "covered as the admin-api-keys channel",
    "access-transparency.md": "covered as the access-transparency channel",
    "cmek.md": "covered as the cmek channel",
    "rate-limits-api.md": "covered as the rate-limits-api channel",
    "spend-limits-api.md": "covered as the spend-limits channel",
    "user-management.md": "covered as the user-management channel",
    "wif-admin-api.md": "covered as the wif channel",
    "workspaces.md": "covered as the workspaces channel",
    # wif-providers/* — 7 per-provider WIF setup guides, one directory deep. Made
    # VISIBLE to the guard on 2026-08-01 (finding #13); the guard's regex had no
    # `/` so it could not match them at all. All 7 fetched 200 (13-61 KB) and the
    # union of `/v1/organizations/*` paths across them is ZERO — they are IdP
    # trust-configuration walkthroughs, not data surfaces. Excluded on measured
    # grounds, not on the title-keyword grounds that caused finding #9.
    "wif-providers/aws.md": "per-provider WIF setup guide; 0 endpoints (probed 2026-08-01)",
    "wif-providers/azure.md": "per-provider WIF setup guide; 0 endpoints (probed 2026-08-01)",
    "wif-providers/gcp.md": "per-provider WIF setup guide; 0 endpoints (probed 2026-08-01)",
    "wif-providers/github-actions.md": "per-provider WIF setup guide; 0 endpoints (probed 2026-08-01)",
    "wif-providers/kubernetes.md": "per-provider WIF setup guide; 0 endpoints (probed 2026-08-01)",
    "wif-providers/okta.md": "per-provider WIF setup guide; 0 endpoints (probed 2026-08-01)",
    "wif-providers/spiffe.md": "per-provider WIF setup guide; 0 endpoints (probed 2026-08-01)",
    # app-attest.md was EXCLUDED in run 4 (0 endpoints, 0 scopes, console-only)
    # with a manual Watching row; it became the prose-trigger-only APP_ATTEST
    # channel on 2026-08-22 so its "an API appears" trigger runs in code.
    # claude-code-analytics-api.md similarly became ANALYTICS_CC_GUIDE (the
    # Bedrock-exclusion sentence trigger — the one run 3 false-zeroed by
    # probing the wrong page).
    # The 3 inference-hooks pages are CHANNELS as of run 4, not exclusions — see
    # INFERENCE_HOOKS / _CONFIG / _ENDPOINT above.
}


def enumerate_uncovered_pages(index_text: str) -> list[tuple[str, str]]:
    """Return [(page, status)] for every page in a covered neighbourhood.

    WHY THIS EXISTS: the registry was originally seeded by keyword-grepping the
    doc index, which silently excluded every page whose title lacked a monitoring
    keyword -- `access-transparency.md` (an entire data channel), `cmek*`,
    `workspaces`, `rate-limits-api`, `user-management`, `spend-limits-api`,
    `admin-api-keys` (the authoritative scope table). Probing could not find them
    because probing only visits what the registry lists.

    The fix is to enumerate the neighbourhood and subtract, rather than filter and
    assume. A page that is neither a channel nor a DELIBERATE_EXCLUSION is
    reported as UNCOVERED -- a finding, not a silent omission.

    Keys are the path RELATIVE to the neighbourhood root (`wif-providers/aws.md`,
    not `aws.md`), so a subdirectory page cannot collapse onto a same-named
    top-level page.
    """
    import re

    covered_urls = {c.url for c in ALL_CHANNELS}
    out: list[tuple[str, str]] = []
    for _label, pattern in COVERED_NEIGHBOURHOODS:
        # Derive the root from the pattern's own literal prefix rather than
        # hardcoding it, so adding a second neighbourhood cannot silently key
        # every page in it off the FIRST one's root.
        root = pattern.split("(?:", 1)[0].replace("\\", "").rsplit("/", 1)[0] + "/"
        for url in sorted(set(re.findall(pattern, index_text))):
            leaf = url.split(root, 1)[-1] if root in url else url.rsplit("/", 1)[-1]
            if url in covered_urls:
                out.append((leaf, "CHANNEL"))
            elif leaf in DELIBERATE_EXCLUSIONS:
                out.append((leaf, f"EXCLUDED — {DELIBERATE_EXCLUSIONS[leaf]}"))
            else:
                out.append((leaf, "UNCOVERED — no channel and no recorded exclusion"))
    return out
