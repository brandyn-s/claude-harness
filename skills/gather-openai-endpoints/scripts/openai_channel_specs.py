"""Channel registry: which OpenAI doc page carries which collectable fact-set.

This module is DATA, not logic. It is loaded by the shared drift engine at
`skills/gather-claude-endpoints/scripts/diff_channels.py` via `--specs`; the
dataclasses (ChannelSpec, Extractor, ProseTrigger) are imported from that
sibling so there is exactly one definition of the contract.

OpenAI's public doc surface differs structurally from Anthropic's, and the
channel design follows from three measured constraints (probed 2026-08-22):

1. `platform.openai.com/docs/*` is UNFETCHABLE — HTTP 403 Cloudflare bot
   challenge on every request. The markdown-serving hosts are
   `developers.openai.com` (append `.md`, plus `llms.txt` indexes),
   `learn.chatgpt.com` (same), and `cookbook.openai.com` (same).
2. The developers.openai.com API reference is Stainless-generated STUBS —
   a method page is ~400 bytes with no schema and no enums. The extractable
   fact-set there is the PAGE INDEX itself: which admin resources and methods
   exist. That is exactly the drift we care about (a new/removed admin
   surface), so the index IS the channel.
3. The enterprise Compliance API contract lives behind login
   (chatgpt.com/admin/api-reference); learn.chatgpt.com says verbatim "This
   page doesn't duplicate that contract." The public carriers of contract
   facts are the cookbook quickstart (base URL, scope segment, event-type
   examples) and OUR OWN PROBES — the confirmed 7-value event_type enum is
   probe-discovered and belongs in `observed_values` provenance, not the
   docs-sourced baseline (see memory: openai-compliance-logs-platform).

Verified against the live doc surface 2026-08-22.
"""

from __future__ import annotations

import sys
from pathlib import Path

# One contract definition: the shared spec types next to the engine.
_SHARED = Path(__file__).resolve().parents[2] / "_shared" / "endpoint-drift"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
from spec_types import ChannelSpec, Extractor, ProseTrigger  # noqa: E402

# Read by diff_channels.py --specs: baselines live under
# ~/Documents/knowledge-base/reference/<KB_SUBDIR>/baselines/.
KB_SUBDIR = "openai-data-channels"
REPORT_TITLE = "OPENAI DATA-CHANNEL DRIFT REPORT"
# Rendered under OBSERVED_ONLY rows instead of the Anthropic sibling's pointer.
OBSERVED_HINT = ("not drift; re-verify these via reconcile_openai_observed.py "
                 "--probe (live keyed GETs)")

# --------------------------------------------------------------------------
# 1. Platform API admin reference index (audit logs, admin keys, users,
#    invites, projects, service accounts, certificates, groups, rate limits)
# --------------------------------------------------------------------------
PLATFORM_ADMIN_REFERENCE = ChannelSpec(
    key="platform-admin-reference",
    title="OpenAI Platform API — administration reference index",
    url="https://developers.openai.com/api/reference/llms.txt",
    marker="Administration",
    surface="platform",
    extractors=(
        Extractor(
            key="openai-admin-reference-pages",
            # STRUCTURAL: the index declares every admin page as a markdown link
            # to resources/organization/... .md. The slug is the fact; a new
            # slug is a new admin resource or method (e.g. a usage or
            # certificates subresource appearing), a removed slug is an admin
            # surface our pollers may already call. Method pages themselves are
            # Stainless stubs — the index is the only enumerable declaration.
            pattern=r"developers\.openai\.com/api/reference/(resources/organization[a-z_/]*)\.md",
            min_expected=40,  # measured 60 on 2026-08-22
            note="New slug = new admin API surface (audit logs, keys, users, "
                 "projects...). Removed slug = an endpoint a poller may call is gone.",
        ),
        Extractor(
            key="openai-api-resource-groups",
            # Top-level endpoint families across the whole Platform API
            # (responses, realtime, organization, ...). Coarser than the admin
            # slugs: detects a NEW FAMILY (e.g. a compliance or analytics group
            # appearing on the platform side) that the admin-scoped extractor
            # would miss.
            pattern=r"developers\.openai\.com/api/reference/resources/([a-z_]+)[/.]",
            min_expected=5,
            note="A new top-level resource family is a new API product area; "
                 "check whether it carries org/telemetry data we should collect.",
        ),
    ),
    note="The reference is Stainless-generated; method pages are stubs. The "
         "index is the declaration surface. platform.openai.com equivalents 403.",
)

# --------------------------------------------------------------------------
# 2. ChatGPT Enterprise Compliance Logs Platform (cookbook quickstart)
# --------------------------------------------------------------------------
COMPLIANCE_LOGS_COOKBOOK = ChannelSpec(
    key="compliance-logs-cookbook",
    title="ChatGPT Compliance Logs Platform (public cookbook quickstart)",
    url="https://cookbook.openai.com/examples/chatgpt/compliance_api/logs_platform.md",
    marker="api.chatgpt.com/v1/compliance",
    surface="chatgpt-enterprise",
    extractors=(
        Extractor(
            key="compliance-event-types",
            # The page's script examples name event types as ALLCAPS *_LOG
            # tokens. Only AUTH_LOG appears today (min_expected=1); the full
            # authorized enum (AUTH_LOG, AUDIT_LOG, APP_LOG, APP_AUTH_LOG,
            # CODEX_LOG, CODEX_SECURITY_LOG, CUSTOM_AGENTS_LOG) is
            # probe-discovered and held in observed_values provenance — the
            # docs never list it, and a 400 on a bad type does not enumerate
            # options. A NEW token appearing here means the vendor started
            # documenting the enum publicly: promote and re-probe.
            pattern=r"\b([A-Z][A-Z_]{2,}_LOG)\b",
            min_expected=1,
            note="A new documented event type = a new compliance feed to ingest "
                 "(30-day retention: start pulling IMMEDIATELY or the history is gone).",
        ),
        Extractor(
            key="compliance-scope-segments",
            # Both the bash and PowerShell examples assign the URL scope
            # segment, switching on principal type: `workspaces` for workspace
            # ids, `organizations` for org-… ids (cookbook lines ~69-71).
            # Measured 2026-08-22: 2 values. (An earlier probe memory said
            # "workspaces only" — refuted by this very extractor on its first
            # fixture run.) A third segment appearing = new routing contract.
            pattern=r"[Ss]cope[_ ]?[Ss]egment\s*=\s*['\"]([a-z]+)['\"]",
            min_expected=2,
            note="Scope segment is the URL routing contract; a change breaks "
                 "our compliance poller's request path.",
        ),
    ),
    # No prose trigger on the base URL: it IS the liveness marker, and
    # CHANNEL_DEAD short-circuits before triggers evaluate — a trigger on the
    # marker string is unreachable dead code (variant of the marker/trigger
    # coupling flaw caught on chatgpt-docs-index, 2026-08-22).
    note="The authoritative reference (chatgpt.com/admin/api-reference) is "
         "login-gated; this cookbook page is the public contract carrier. "
         "Retention is 30 days — removals here are collection outages.",
)

# --------------------------------------------------------------------------
# 3. ChatGPT / Codex docs index (enterprise admin, governance, analytics,
#    compliance guide, Codex security — one index covers all of them)
# --------------------------------------------------------------------------
CHATGPT_DOCS_INDEX = ChannelSpec(
    key="chatgpt-docs-index",
    title="ChatGPT Work + Codex documentation index (learn.chatgpt.com)",
    url="https://learn.chatgpt.com/llms.txt",
    # Marker must be INDEPENDENT of any single watched line: an earlier draft
    # used "Compliance API", so removing the one compliance-api.md index line
    # reported the whole channel CHANNEL_DEAD instead of firing its precise
    # trigger (caught by the trigger mutation test, 2026-08-22). The section
    # header is structural and survives per-page churn.
    marker="## Administration",
    surface="chatgpt-enterprise",
    extractors=(
        Extractor(
            key="chatgpt-doc-pages",
            # Every published doc page, as its slug. developers.openai.com/codex/
            # llms.txt 308-redirects INTO this index (measured 2026-08-22), so
            # one channel covers enterprise + Codex + security docs. A new
            # enterprise/* or security/* slug is the usual first public signal
            # of a new admin/data surface (this is where analytics-api.md and
            # compliance-api.md live).
            pattern=r"learn\.chatgpt\.com/(docs/[a-z0-9/_-]+)\.md",
            min_expected=100,  # measured 140 on 2026-08-22
            note="New enterprise/security doc page = earliest public signal of "
                 "a new collectable surface; removed page = surface possibly retired.",
        ),
    ),
    prose_triggers=(
        ProseTrigger(
            key="compliance-api-guide-listed",
            pattern=r"docs/enterprise/compliance-api\.md",
            expect="present",
            note="The Compliance API guide left the index — the enterprise "
                 "compliance surface moved or was renamed.",
        ),
        ProseTrigger(
            key="analytics-api-guide-listed",
            pattern=r"docs/enterprise/analytics-api\.md",
            expect="present",
            note="The Codex Analytics API guide left the index — the adoption/"
                 "usage reporting surface moved or was renamed.",
        ),
    ),
    note="Index-of-pages channel: coarse but removal-sensitive. Contract "
         "details for anything found here are verified in Step 4/4b, not "
         "extracted from the stub pages.",
)

# --------------------------------------------------------------------------
# 4. Logged-in Admin API reference (manual export — the authoritative contract)
# --------------------------------------------------------------------------
COMPLIANCE_ADMIN_REFERENCE_EXPORT = ChannelSpec(
    key="compliance-admin-reference-export",
    title="ChatGPT Admin API — captured openapi.json (manual logged-in export)",
    url="https://chatgpt.com/admin/api-reference",
    # The spec self-identifies; independent of any single route/enum line.
    marker="Programmatic Admin Platform",
    surface="chatgpt-enterprise",
    # KB-relative: the engine resolves it against --kb. Captured 2026-08-22
    # from the reference page's own openapi.json (browser network tab; the
    # direct URL is session-gated 401 and chatgpt.com paths are Cloudflare
    # 403 — a page save works too, but the spec is the machine contract).
    local_path="reference/openai-data-channels/exports/admin-api-reference.openapi.json",
    extractors=(
        Extractor(
            key="admin-reference-event-types",
            # Quoted ALLCAPS tokens across the spec: the event_type enums PLUS
            # the Codex client-surface enum and visibility/principal enums —
            # all stable spec facts (54 measured 2026-08-22). NOT anchored on a
            # _LOG suffix: the real enum carries suffix-less names
            # (CONVERSATION_MESSAGE, COSTS) that a *_LOG pattern silently
            # missed — the closed-vocabulary trap, caught on the first capture.
            # NOTE the spec's enums are DELIBERATELY non-exhaustive: they
            # carry a literal "etc..." placeholder (3 occurrences).
            pattern=r'"([A-Z][A-Z_0-9]{2,})"',
            min_expected=40,
            note="A new token = a new event type, Codex surface, or enum class "
                 "in the authoritative contract. New event type => start "
                 "ingestion immediately (30-day retention).",
        ),
        Extractor(
            key="admin-reference-routes",
            # Route paths as declared in paths{} keys and $ref strings.
            pattern=r'"(/(?:compliance|manage|analytics)[a-z0-9_/{}.-]*)"',
            min_expected=60,  # 89 measured 2026-08-22
            note="Route set of the authoritative admin contract (compliance + "
                 "manage + codex analytics); a removal is an outage for "
                 "whichever poller calls it.",
        ),
    ),
    note="Refresh: open chatgpt.com/admin/api-reference logged in, save the "
         "openapi.json the page loads (network tab) over the local_path file. "
         "Absent file reports LOCAL_SOURCE_MISSING and never fails the run.",
)

ALL_CHANNELS: tuple[ChannelSpec, ...] = (
    PLATFORM_ADMIN_REFERENCE,
    COMPLIANCE_LOGS_COOKBOOK,
    CHATGPT_DOCS_INDEX,
    COMPLIANCE_ADMIN_REFERENCE_EXPORT,
)

BY_KEY = {c.key: c for c in ALL_CHANNELS}
