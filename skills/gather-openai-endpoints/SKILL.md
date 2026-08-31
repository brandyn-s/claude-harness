---
name: gather-openai-endpoints
description: "Detect drift in OpenAI's data-collection surface — ChatGPT Compliance Logs Platform, Platform Admin/Audit-Log APIs, Codex Analytics, and enterprise doc surfaces — by diffing live vendor docs against committed baselines, then PROBING each finding against the live API and our own code before grading it."
when_to_use: Use when checking whether OpenAI changed what telemetry, audit, usage, cost, or content data can be collected from ChatGPT Enterprise or the OpenAI Platform — new or removed compliance event types, new or removed admin API resources, changed scope segments or retention, or new enterprise/Codex doc surfaces. Also use to probe or validate a claim about an OpenAI data endpoint (does it exist, what does it return, do we already collect it). Trigger phrases - "gather-openai-endpoints", "did the OpenAI APIs change", "new OpenAI endpoints", "ChatGPT Compliance API changes", "OpenAI audit log changes", "what can we collect from OpenAI", "OpenAI data channel drift", "probe the OpenAI endpoints". Do NOT use for OpenAI model releases or product changes (use gather-vendor openai), answering a usage or spend question from data we already hold (use openai-monitor), the Anthropic surface (use gather-claude-endpoints), or community patterns (use gather-intel).
argument-hint: "[optional: 'full', a channel key, 'baseline' to refresh baselines, or 'probe' to re-validate existing findings]"
effort: medium
metadata:
  author: example-security-engineering
  version: "1.0"
compatibility:
  requires:
    - cli: python3
    - skill: gather-claude-endpoints
allowed-tools: Bash Read Write Edit Glob Grep mcp__memory-search__memory_search AskUserQuestion
---

## gather-openai-endpoints

# Detect drift in OpenAI's data-collection surface

Vendor sibling of `/gather-claude-endpoints` — same engine, same verdict
semantics, an OpenAI channel registry. That skill's SKILL.md is the canonical
description of the differ's verdicts (Step 2), extractor-repair procedure
(Step 2b), probe discipline (Step 4b), and finding format (Step 5); **read it
alongside this file on first use.** This file carries only what is
OpenAI-specific.

The dedicated knowledge base is
`~/Documents/knowledge-base/reference/openai-data-channels/`.

Runs in the main thread. **Never auto-writes** anything except baseline files.

---

## Step 0: Scope guard + argument

| Request is about | Use instead |
|---|---|
| OpenAI model releases, API changelog, deprecations | `/gather-vendor openai` |
| Answering a usage/spend/finding question from data we hold | `/openai-monitor` |
| The Anthropic surface | `/gather-claude-endpoints` |
| Cross-provider comparison | `/enterprise-ai-monitor` |

Argument: none = all channels · a channel key = just that one (`--list`) ·
`baseline` = establish/refresh baselines after review.

---

## Step 1: Load baseline (MANDATORY)

Read in parallel; note any absent file in the Sources Log and continue:

1. `~/Documents/knowledge-base/reference/openai-data-channels/INTELLIGENCE.md`
   — Metadata sets the window; the Watching table sets this run's must-check
   triggers.
2. `CATALOG.md` + the `channels/*.md` pages relevant to the argument.
3. `memory_search` for our own probe results — start with
   `openai-compliance-logs-platform` (the probe-discovered event_type enum and
   the 30-day retention), `openai-keychain-items` (which key class works
   where), and `openai-entra-scim-topology`. Vendor docs describe the surface;
   those memories describe **what we measured** — and one of them was already
   refuted once by this skill's own extractor (scope segments), so treat both
   directions as hypotheses.

---

## Step 2: Run the differ (MANDATORY)

The engine is shared (`skills/_shared/endpoint-drift/`); the launcher binds the OpenAI registry:

```bash
python3 ~/.claude/skills/gather-openai-endpoints/scripts/diff_openai_channels.py \
  --kb ~/Documents/knowledge-base \
  --run-date <YYYY-MM-DD> \
  --json /tmp/claude/openai-drift-<date>.json
```

The launcher injects `--specs openai_channel_specs.py` into the shared engine
(`skills/_shared/endpoint-drift/diff_engine.py`); all engine flags pass
through. Both vendor skills' code-freshness gates and the KB baseline gate are
cached FRESH for 15 min (`/tmp/claude/endpoint-drift-freshness.json`) so
back-to-back vendor runs pay the `git fetch` once; STALE/UNKNOWN are never
cached.

Exit codes and verdicts (`CLEAN`/`DRIFT`/`OBSERVED_ONLY`/`NO_BASELINE`/
`INSTRUMENT_BLIND`/`CHANNEL_DEAD`/`FETCH_FAILED`/`TRIGGER_FIRED`) are the
sibling's — its Step 2 table governs. Non-negotiables carried over verbatim:
`INSTRUMENT_BLIND` and `CHANNEL_DEAD` invalidate that channel's diff for the
run; a first run ALWAYS establishes the baseline; never hand-edit a baseline;
refresh baselines only after drift has been graded.

### OpenAI-specific instrument constraints (measured 2026-08-22)

- **`platform.openai.com/docs/*` is unfetchable** — HTTP 403 Cloudflare
  challenge on every request. Channels point at `developers.openai.com`,
  `learn.chatgpt.com`, and `cookbook.openai.com`, which serve markdown by
  appending `.md` and publish `llms.txt` indexes. Never "fix" a fetch failure
  by pointing a channel at platform.openai.com.
- **Reference method pages are Stainless-generated stubs** (~400 B, no
  schemas, no enums). The enumerable fact-set is the reference **index**; the
  contract behind any index-level finding is verified in Step 4b by probe, not
  by reading the stub.
- **The enterprise Compliance API contract is login-gated**
  (`chatgpt.com/admin/api-reference`). The public carriers are the cookbook
  quickstart and our probes. The confirmed `event_type` enum is
  probe-discovered and lives in `observed_values` provenance — the docs never
  listed it, and it must never be graded REMOVED for that reason.
- **The logged-in reference is a manual-export channel.** The
  `compliance-admin-reference-export` channel reads
  `~/Documents/knowledge-base/reference/openai-data-channels/exports/admin-api-reference.md`
  — an operator-saved copy of `chatgpt.com/admin/api-reference`. When the file
  is absent the run reports `LOCAL_SOURCE_MISSING` and does NOT fail; refresh
  the export whenever the admin UI shows new compliance scopes, and before any
  "the enum has N values" claim.
- **A liveness marker must be independent of any watched line.** The first
  draft used a trigger's own target string as the channel marker; removing one
  index line reported the entire channel dead. Markers are structural section
  headers; triggers watch specific lines.

### Step 2b: Fix a blind extractor in the same run

Follow the sibling's Step 2b (fetch, confirm the new declaration form, patch
`openai_channel_specs.py`, re-run `tests/test_openai_channels.py`, record in
the Sources Log). Extract from declaration markers (index link lines,
assignment statements), never from surrounding prose.

### Step 2c: Reconcile against LIVE data (MANDATORY when keys are present)

```bash
# Probe leg: ~15 read-only GETs (limit=1) against both hosts
python3 scripts/reconcile_openai_observed.py --probe --json /tmp/claude/oai-probe.json

# Observed leg: inventory extracted from the OpenAI Monitor pipeline
python3 scripts/reconcile_openai_observed.py --observed observed.json --update-baseline
```

Probe-leg contract (all measured live 2026-08-22):
- Keys are the CURRENT Keychain names — `OPENAI_PLATFORM_ADMIN_API`
  (api.openai.com) and `OPENAI_CHATGPT_ADMIN_API` (api.chatgpt.com), plus
  `OPENAI_ORG_ID`/`OPENAI_WORKSPACE_ID` principals. The pre-2026-08-04 names
  (`OPENAI_API_ADMIN_KEY` etc.) are GONE; a missing item reports
  `SKIPPED_NO_KEY`, never "unreachable". GET only — `UnsafeProbe` refuses
  anything else.
- The compliance API validates FastAPI-style: a **422 missing-param is
  REACHABLE** evidence (endpoint exists, key accepted, event_type validated),
  and `after` (ISO8601 with tz) is REQUIRED on every logs call.
- **Event types are scope-bound.** All 7 known types are workspace-scoped; the
  `organizations/{org-…}/logs` path is LIVE but rejects them by name:
  `"AUTH_LOG is a workspace-scoped event type. Use /v1/compliance/workspaces/…"`.
  Org-scoped event-type names are unknown — the logged-in export channel is
  where they will surface.
- Observed-leg verdicts mirror the sibling: `UNDOCUMENTED` (detector blind —
  merge with provenance), `DOC_ONLY` (informational, NOT a gap), `RECONCILED`.
- The full key-by-endpoint matrix instrument is
  `~/Documents/projects/claude-spend-report/probe_openai_keys.py`; this script
  probes only the drift-relevant subset.

---

## Step 3: Grade each drift item

The sibling's Step 3 severity table applies (removals outrank additions; grade
by blast radius on OUR collection). One OpenAI-specific escalation:

**Compliance Logs Platform retention is 30 days.** A new event type is not a
someday opportunity — every day before ingestion starts is history permanently
lost. A new `*_LOG` type grades MEDIUM minimum, and the recommended edit names
the poller change that starts collection.

Then check the Watching table from Step 1 explicitly.

---

## Step 4 + 4b: Verify, then PROBE (MANDATORY)

The sibling's Step 4 (read the cited page; a count change is not a semantic
change; UNCHARTED over fabricated refutation) and Step 4b (probe the live API
read-only; grep OUR code wide before any gap/impact claim; downgrade severity
to what the probe supports) apply in full, including the finding-format
required fields `API probe` / `Code probe` / `Severity basis`.

OpenAI-specific probe routing:

| Surface | Base | Key | Notes |
|---|---|---|---|
| Compliance Logs Platform | `api.chatgpt.com/v1/compliance/{workspaces|organizations}/{id}/logs` | `OPENAI_CHATGPT_ADMIN_API` (Keychain) | GET only; `after` REQUIRED; 422 missing-param = REACHABLE. Event types are scope-bound (all 7 known = workspace). |
| Platform Admin API (audit logs, users, projects…) | `api.openai.com/v1/organization/...` | `OPENAI_PLATFORM_ADMIN_API` (Keychain) | GET only, `limit=1`. A 401 here can be key CLASS, not absence. 7/7 families probed 200 on 2026-08-22. |
| Enterprise docs surfaces | `learn.chatgpt.com/docs/...md` | none | Public markdown; guides disclaim the contract — do not cite them as it. |

Hard rules carried over: **GET only — never probe a mutating endpoint**; count
returned records, not bytes; read error bodies, not just status codes; a 400
"field required" is REACHABLE; if a probe is blocked, STOP and surface it —
tag `UNVERIFIED-BLOCKED`, never downgrade silently to doc-inference. Code
probes grep `~/Documents/GitHub` wide (field names first) — the OpenAI Monitor
ingest code is the usual consumer to check before claiming "we don't collect
this".

---

## Step 5: Verdict per finding

`ADOPT | QUALIFY | DEFER | REJECT` with the exact finding format from the
sibling's Step 5 (field spellings are parsed by later runs; canonical
authority `~/.claude/skills/_shared/gather-conventions.md`). DEFER requires a
machine-checkable trigger.

---

## Step 6: Present, then persist

Present findings via **AskUserQuestion**; never auto-apply. After approval of
ADOPT: read the target, edit, re-read, leave uncommitted for review. Baseline
carve-out (machine artifacts, committed with the report):

```bash
python3 ~/.claude/skills/gather-openai-endpoints/scripts/diff_openai_channels.py \
  --kb ~/Documents/knowledge-base --run-date <date> --update-baseline
```

Then update `INTELLIGENCE.md` (rotate Metadata, per-channel Sources Log dates,
Watching table) and any `channels/*.md` whose facts changed. After a refresh,
re-run without `--update-baseline` and expect exit 0 — a non-idempotent
refresh is a detector bug.

---

## Step 7: Handoffs

| Finding shape | Route to |
|---|---|
| ingest/routing change for an OpenAI data source | `/openai-monitor` |
| model/product surface change discovered incidentally | `/gather-vendor openai` |
| a change with a cross-provider mirror worth checking on Anthropic | `/gather-claude-endpoints` |
| a security advisory on a collection path | `/security-alerts` |

---

## Examples

**Example 1 — establishing run (2026-08-22, real output):**
`channels: 3  drift: 0  new-baseline: 3  problems: 0` — 60 admin reference
pages, 23 API resource groups, 140 ChatGPT doc pages, 1 documented event type
(+6 probe-only in observed_values), 2 scope segments captured. The
establishing run itself refuted a memory: the cookbook documents BOTH
`workspaces` and `organizations` scope segments, where a 2026-08-04 probe
memory said "workspaces only".

**Example 2 — what a real drift run looks like:**
```
-- DRIFT --
  compliance-logs-cookbook
    compliance-event-types: 1 docs-baseline -> 2 live (+6 held out)
      + CONNECTOR_LOG   [NEW]
```
Grade MEDIUM minimum (30-day retention: ingestion delay is permanent data
loss), probe the type with a `limit=1` GET before writing the finding, and the
recommended edit names the OpenAI Monitor poller change.

## Success Criteria

- Differ ran with `--specs` against a FRESH KB checkout; every channel's
  verdict read per the sibling's table (no INSTRUMENT_BLIND graded as removal).
- Every finding carries verified vendor claim AND probed impact (`API probe`,
  `Code probe`, `Severity basis` fields present), or an explicit
  `UNVERIFIED-BLOCKED`.
- Baselines refreshed only after grading; refresh proven idempotent (re-run
  exits 0); observed_values survived.
- Findings presented via AskUserQuestion; nothing auto-applied.

## Reference

- `references/channel-map.md` — the four channels, extractor rationale, and
  the measured doc-surface constraints
- `scripts/openai_channel_specs.py` — the OpenAI channel registry (data, not logic)
- `scripts/diff_openai_channels.py` — launcher binding the registry to the engine
- `scripts/reconcile_openai_observed.py` — live probe + observed-inventory reconcile
- `tests/test_openai_channels.py` — hermetic fixture tests proving the
  registry through the shared engine
- Engine: `skills/_shared/endpoint-drift/diff_engine.py` (+ `spec_types.py`);
  canonical step semantics: `skills/gather-claude-endpoints/` SKILL.md
- Fast test loop while iterating: `python3 -m pytest
  skills/gather-openai-endpoints skills/gather-claude-endpoints -q` (~1 s);
  the full `pytest skills/` tier (~11 min locally) is the pre-push gate
