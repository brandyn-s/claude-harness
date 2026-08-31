---
name: service-review
description: "Review a backend service / API / CLI tool for production readiness — boots and drives the running tool live, adversarial-hammers every input path for fail-closed behavior, and checks durability / observability / security / config-at-boot. Produces a prioritized worklist; read-only, makes no changes."
when_to_use: "Use to assess a backend service (FastAPI/Flask/Express), API, or CLI tool's production readiness — the backend analog of /lab-review (which is frontend-only and defers backend). Emits a findings report + worklist; makes NO changes. Trigger phrases: 'service-review', 'review the backend', 'is this API durable', 'boot and drive it', 'adversarial input test', 'does it fail closed'. Usually dispatched by /readiness-review for backend/CLI shapes, but runs standalone too. Do NOT use for: frontend/SPA UI (use /lab-review), deployment/infra (use lab-deploy / mcp pipeline), or generic security code review (use /differential-review)."
metadata:
  author: example-security-engineering
  version: "1.0"
argument-hint: "<repo-name-or-path to the backend service or CLI>"
allowed-tools: Bash Read Grep Glob AskUserQuestion
effort: high
---

# /service-review

The **backend / API / CLI analog of `/lab-review`** — for the shape `/lab-review`
explicitly defers ("backend reliability is its own track"). Produces a
**prioritized readiness worklist**; makes **NO code changes** (the fix pass is
separate). Distilled from the Proteus Polar FastAPI maturation (2026-06-19).

Its governing principle, learned the hard way: **static review lies.** A
focus-trap shipped axe-clean but caught 0/12 Tabs; a junk upload returned HTTP
200 on a code-read and only failed two steps later. So this skill's spine is
**boot the running service and DRIVE it** — findings come from observed runtime
behavior, cited to the actual request/response, not from reading the source.

## Step 1 — Boot the service (or document why you can't)

Get a running instance. Read `README`/`run.*`/`main.*` for the entrypoint and
env; boot it locally (a dev/test mode is fine — note any prod-only code that's
inert, e.g. PP's Windows cert path when `EXAMPLE_CERT_THUMBPRINT` is unset).

- Confirm it's actually serving (probe the port / health endpoint — the port is
  the oracle, not the launch log).
- Capture the **startup signal**: does it log a resolved-config line? bootstrap
  credentials? structured logs? (PP logged `config resolved env=… file_store_max=…`
  — that's config-at-boot working, a real Operability signal.)
- **Boot-blocked escape hatch** (per `engineering-assessment-plan-falsifier-discipline`):
  if it genuinely can't boot here (needs GCC-High SSO, a classified feed,
  hardware-in-the-loop), DOCUMENT the blocker + the strongest available
  substitute (unit/integration suite, a recorded trace) and grade live-dependent
  axes **AMBIGUOUS** — never fake a live pass.

Per `diagnose-before-fix`: when boot fails, read the actual error/log before
guessing; orphaned prior instances holding the port is common (kill the specific
PID, not a class).

## Step 2 — Drive the happy path live, with real domain data

Drive the real end-to-end workflow against the running service using a **real
input file / real request shape**, not synthetic stubs. Verify request shapes
from the live contract (`/openapi.json`, `--help`, the route source) BEFORE
driving — a wrong-shape request that 422s is YOUR bug, not the service's, and
mis-grades it.

Assert at each step: correct status, correct content-type, real output bytes.
(PP: login → upload real ShipMo3D → operability evaluate → export PNG/SVG/CSV →
health probes = 11/11, operability 37.5% on 338 real rows.) A happy-path step
that needs interactive setup the API can't supply (PP's column-mapping UI feeding
`/plot/extract`) is noted as a frontend-owned step, not a backend failure.

## Step 3 — Adversarial-hammer every input path (the durability core)

This is where readiness is won or lost. For every input boundary (upload, each
mutating endpoint, each CLI arg), send deliberately bad input and grade the
response. Cover at least:

| Bad input | Must do |
|---|---|
| **Junk / wrong-domain file** (prose as a data file) | **fail CLOSED at ingest** with an actionable message — NOT accept-as-empty/200 (PP's junk-upload-200 bug: prose parsed as a 1×N table, passed the row guard, failed cryptically 2 steps later) |
| **Empty / 0-row / truncated** input | reject with a message naming the cause |
| **Malformed body** (non-JSON, wrong types) | 4xx, never 5xx; name the offending field where possible |
| **Nonexistent IDs / missing required fields** | 404/422 actionable |
| **Binary garbage / oversized** | reject (size cap, content check), never crash |
| **Unauthenticated request** to every protected route | 401/403 — authz holds |

Grade each: **CRASH (5xx)** = durability failure; **accepted-bad-input (200)** =
fail-OPEN bug (the worst — silent wrong data); **actionable reject** = good;
**generic reject** = usability debt. The bar: **0 crashes, 0 accepted-bad-input,
authz holds.** Where a wrongly-accepted input is caught downstream (fails closed
at the next step), that BOUNDS the severity (High, not Critical) — but it's still
a finding.

## Step 4 — Pillar sweep (what the live drive doesn't directly surface)

Check the backend pillars `/lab-review` doesn't own, citing source + runtime:

- **Reliability:** fail-closed on bad/NaN data (never silently passes as zero/OK); shared-state/concurrency model honored (`workers=1` documented vs unbounded in-memory growth); a regression test exists for each prior fix (real calls, not mocks).
- **Observability:** structured + configured logging (not bare `logger.x()` with no handler); request/correlation IDs at trust boundaries; a real `/health` (+ readiness) probe, not a stub.
- **Security:** new routes default-deny (auth + ownership); no secrets in repo; input sanitization at trust boundaries (path traversal, formula injection, null bytes); rate limiting on expensive/abusable endpoints.
- **Config-at-boot:** validated config at startup (fails loud on bad config), secure-by-default (absent env → the SAFE mode, not the permissive one — PP: absent `EXAMPLE_ENV` → production).
- **Tests/CI:** suite runs green; lint/typecheck blocking for new code.

## Step 5 — Report (review-only)

Emit in chat (write a file only if asked):
- **Boot status** — live / live-blocked(+reason).
- **Findings table** — pillar | finding | evidence (the live request/response or the source `file:line`, not impression).
- **Prioritized worklist** — Critical / High / Nice (`scope-discipline`). Critical = crash / silent-wrong-data / authz-hole; High = fail-open caught downstream, or a real durability/UX defect; Nice = polish.
- **Owned / separate** — frontend (→ `/lab-review`), deploy (→ `lab-deploy` / mcp pipeline), core-output correctness (→ owned by `/readiness-review` Step 3 when dispatched by it).

Verify findings by reading the cited source / re-running the cited request — a count or a grep is a signal, the runtime behavior is the evidence (per `verify-effectiveness`).

## After the review (the fix pass — separate, confirmed)

Read-only by design. To fix: surface the plan via AskUserQuestion, fix-forward
in an isolated worktree (`worktree-by-default`), each fix with a regression test
proving **the fix AND that valid input still passes** (the no-false-reject
control), then re-drive live and re-grade.

## Example

`/service-review proteus-polar` → Step 1: boots `python run.py` on :8080,
captures `config resolved` + bootstrap pw. Step 2: real MRV0 upload →
operability evaluate → exports = 11/11 live. Step 3: 13 adversarial inputs → 0
crashes, authz holds, but **junk.txt → HTTP 200 (fail-OPEN bug)**; downstream
evaluate fails closed (422) → bounded to **High**. Step 4: structured JSON logs ✓,
`/health`+`/health/ready` real ✓, config-at-boot secure-by-default ✓. Step 5:
worklist — High: reject junk at ingest; verdict feeds `/readiness-review`.

## Success Criteria

- A running instance was driven live (or the boot-blocker is documented + live axes graded AMBIGUOUS)
- Happy path driven with REAL domain data and verified request shapes (not synthetic stubs)
- Every input boundary adversarial-hammered; graded for crash / accepted-bad-input / actionable-reject; bar = 0 crashes, 0 accepted-bad-input, authz holds
- Backend pillars (reliability/observability/security/config-at-boot) checked with source + runtime evidence
- Worklist prioritized (Critical/High/Nice), each finding citing the live request/response or file:line
- Review-only: zero code changes; the fix pass is separate

## What this skill does NOT do

- Make code changes — produces the worklist; the fix pass is separate and confirmed
- Review frontend/UI — that is `/lab-review` (this is its backend analog)
- Review deployment/infra — `lab-deploy` / the mcp-productionization pipeline
- Validate core-output correctness against an oracle — that spine is `/readiness-review` Step 3 (this skill assumes it, or runs standalone for pure durability review)
- Generic security code review — use `/differential-review`
