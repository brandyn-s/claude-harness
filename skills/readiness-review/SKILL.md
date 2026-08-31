---
name: readiness-review
description: "Assess whether a vibe-coded internal tool is ready to put in a technical SME's hands — orchestrates a shape-adapted, capability-first readiness review and emits ONE go/no-go handoff verdict. Review-only; fixes are a separate confirmed pass."
when_to_use: "Use to take a capable-but-vibe-coded internal tool from proof-of-concept to production-ready for technical SMEs (naval architects, analysts, engineers). Emits a readiness report + prioritized worklist + go/no-go verdict; makes NO changes. Trigger phrases: 'readiness-review', 'is this ready for an SME', 'productionize this tool', 'PoC to production', 'ready to hand off', 'vibe-coded to production'. Do NOT use for: deployment/infra productionization (use the mcp-productionization pipeline / lab-deploy), generic code-correctness review (use differential-review), or a tool that should be rebuilt rather than hardened (Step 1 early-exits to /superplan)."
metadata:
  author: example-security-engineering
  version: "1.0"
argument-hint: "<repo-name-or-path to the internal tool>"
allowed-tools: Bash Read Grep Glob AskUserQuestion
effort: high
---

# /readiness-review

Take a **vibe-coded proof-of-concept internal tool** to **production-ready for a
technical SME** — and emit one honest **go/no-go handoff verdict**. This is the
orchestrator: it owns the shape-independent spine (reason-to-exist, capability
correctness, the SME-trust gate, the merged grade) and **delegates the
shape-specific sweep** to a specialist:

- **backend service / API / CLI shape** → `/service-review`
- **full-stack** → BOTH, merged into one verdict.

Distilled from the Proteus Polar maturation (FastAPI seakeeping tool → naval
architect handoff, 2026-06-19) and the Labs frontend triad. **Review-only: it
produces the worklist + verdict and makes NO code changes.** Fixing is a
separate, user-confirmed pass (see "After the review").

## The one bar this skill defends

**The SME-trust gate = `correct + durable + verified-live`.** A technical SME
trusts a tool's *output* to make a real decision (a go/no-go seakeeping number, a
risk score, a compliance verdict). So the bar is higher than "it runs":

1. **correct** — the tool's core output is validated against an *independent*
   oracle, because **a wrong go/no-go number is worse than a crash** (a crash is
   visible; a plausible wrong number is not).
2. **durable** — every bad input fails *closed* and informatively; nothing
   silently produces a wrong-but-plausible result.
3. **verified-live** — proven by *booting and driving the running tool*, not by
   reading the code. **Static review lies** (Proteus Polar: a focus-trap shipped
   axe-clean but caught 0/12 Tabs; a junk upload returned HTTP 200 on code-read
   and only failed two steps later). This is the step teams skip; this skill
   forces it.

## Step 1 — Resolve the reason-to-exist from SOURCE, decide harden-vs-rebuild

Read the *domain source* (not the README — narratives over-claim), and answer:
**where does this tool's value actually live in the code?** Then triage:

- **Thin wrapper over a commodity library** → rebuild is on the table.
  **EARLY-EXIT:** stop here and hand off to `/superplan` for a rebuild plan.
  `/readiness-review` hardens; it does not rebuild.
- **A niche no off-the-shelf package fills** (Proteus Polar: a multi-format
  seakeeping unifier + closed-form post-processor — *no vendor tool reads its
  competitors' formats*) → **HARDEN.** Proceed.

State the reason-to-exist in one paragraph, cited to `file:line`. If the README
claims capabilities the code doesn't have (PP claimed "async job processing"
that wasn't implemented; "ZIP export" with no zip path), note them — doc-drift
is a finding.

See `references/readiness-method.md` for the full procedure and the worked PP example.

## Step 2 — Classify shape, then dispatch the specialist sweep

Shape decides which specialist runs and which pillars carry weight. Read
`README.md` + the source tree, then:

| Shape | Signal | Specialist |
|---|---|---|
| **Backend service / API** | a server (FastAPI/Flask/Express), routes, auth, data processing | **`/service-review <repo>`** |
| **CLI / batch tool** | an entrypoint + args, no server | **`/service-review <repo>`** (its boot-and-drive generalizes to "invoke and drive") |
| **Full-stack** | both a UI AND an `api/`/server dir | **BOTH** — run each, merge worklists, never fold one into the other |

Dispatch the specialist(s) and collect their pillar findings + worklists. Do NOT
re-review what a specialist owns (no duplication; a separate skill (not included in this export) owns the
design-system/a11y pillars, `/service-review` owns durability/observability).

## Step 3 — Capability-first: validate the core output against an independent oracle

This is the spine, and it runs **regardless of shape** — it is what neither
specialist owns. Identify the tool's **core correctness claim**, then validate it
**three independent ways** (the bar from `build-measurement-harness`, generalized
beyond math):

| Tool's output is… | Independent oracle (≥2 of these, code-disjoint) |
|---|---|
| **Closed-form math** (PP: Rayleigh exceedance, operability%) | (a) hand-computed known-value vectors, (b) an independent library re-deriving the same formula (PP: `scipy.stats.rayleigh`, matched 1e-12), (c) real vendor/domain data run end-to-end |
| **A classification / score** | (a) hand-labeled gold set, (b) a second implementation or rules engine, (c) boundary cases at every threshold |
| **A transform / report** | (a) round-trip property (`decode(encode(x))==x`), (b) spec/standard test vectors, (c) a real production input |
| **CRUD / workflow (NO "math")** | (a) golden-record fixtures of expected state transitions, (b) spec-conformance of the API contract, (c) a real end-to-end task. *Step 3 degrades gracefully: the question is "what is the correctness claim, and what's the independent check on it?" — not "where's the math?"* |

**Internal consistency is necessary but not sufficient** — a self-consistent
transcription of a *wrong* formula passes its own unit tests. The independent
oracle is what catches that. If no independent oracle is achievable, say so and
grade capability **AMBIGUOUS**, not A.

## Step 4 — The SME-trust gate: boot it and drive it LIVE

`/service-review` and a separate skill (not included in this export) each run their live sweep; this step is the
*capability* live-drive the specialists don't own: **drive the real end-to-end
SME workflow against the running tool with real domain data.** (PP: login →
upload the real ShipMo3D file → evaluate operability → export — 11/11 live steps,
operability 37.5% on 338 real rows.)

**Honest escape hatch (per `engineering-assessment-plan-falsifier-discipline`):**
if live-verify is *environmentally blocked* (needs GCC-High SSO, a classified
feed, hardware-in-the-loop, or a vendor license the assessor lacks — PP could not
run the ShipMo3D vendor-differential), do NOT fake it and do NOT block "ready"
on the impossible. Record it as **live-blocked: <reason> + strongest available
substitute**, and grade that axis honestly (the absent vendor-differential was a
documented open gap, not a hidden failure). Name *which* readiness you certified:
methodology-ready vs verified-live.

## Step 5 — Pre-registered grade + go/no-go verdict

Grade against a **pre-registered bar** — do not invent it per run (that
re-introduces the implicit-rubric failure `grading-discipline.md` and
`red-team-rubric-discipline.md` exist to prevent). The fixed bar lives in
`references/readiness-rubric.md` (5-pillar, production-ready = all ≥ L3, safety
pillars ≥ L4). Emit, in this order (per `grading-discipline`):

1. **Axis table FIRST** — per axis: metric · evidence (the live command/output, not a vibe) · grade. One row per pillar (Capability, Usability, Reliability, Security, Operability), capability graded by Step 3's oracle result.
2. **Prioritized worklist** — Critical / High / Nice (per `scope-discipline`), each tied to a pillar and the evidence that surfaced it.
3. **The go/no-go verdict** — collapse on the SME-handoff axis with the collapse rule named. State honest scope limits (what was NOT verified and why). A Critical (wrong-number / silent-corruption / authz-hole) is a NO-GO; a High is "go for a supervised pilot, fix before unsupervised handoff."

## After the review (the fix pass — separate, confirmed)

This skill is **review-only**. If the user wants the worklist fixed:
1. Surface the fix plan via **AskUserQuestion** (which findings, rough scope) — never edit during a review.
2. Fix-forward in an **isolated worktree** (per `worktree-by-default`), one finding class at a time.
3. Every fix ships a **regression test proving the fix AND that valid input still passes** (the no-false-reject control — PP's junk-upload guard had to reject prose while still accepting the real ShipMo3D file).
4. **Re-verify live** and **re-grade** against the same pre-registered bar.

## Example

`/readiness-review proteus-polar` → Step 1: reads `seakeeping.py` → "post-processor
+ multi-format unifier, niche no vendor fills → HARDEN." Step 2: shape =
backend service → dispatch `/service-review`. Step 3: capability oracle = 12/12
hand-values + `scipy.stats.rayleigh` 1e-12 + real MRV0 file → Capability **A**.
Step 4: live drive 11/11; vendor-differential **live-blocked (no ShipMo3D
license)** — documented, not faked. Step 5: axis table → Capability A, Durability
A (0 crashes, fail-closed), … → **go/no-go: ready for supervised pilot; one High
(junk-upload-200) fix before unsupervised handoff.**

## Success Criteria

- Shape classified and the correct specialist(s) dispatched — no duplication of what a specialist owns
- Reason-to-exist resolved from SOURCE with a harden-vs-rebuild call (rebuild → early-exit to /superplan)
- Capability validated against an INDEPENDENT oracle (≥2 code-disjoint checks), or graded AMBIGUOUS with the reason
- The SME-trust gate enforced by a LIVE drive (or an honestly-documented live-blocked substitute)
- Grade uses the pre-registered rubric (references/readiness-rubric.md), axis table BEFORE the letter, honest scope limits
- Review-only: zero code changes; the fix pass is a separate confirmed step

## What this skill does NOT do

- Make code changes — it produces the worklist + verdict; the fix pass is separate and confirmed
- Rebuild a tool — Step 1's "rebuild" verdict early-exits to /superplan
- Deploy / productionize infrastructure — that is the mcp-productionization pipeline / lab-deploy
- Re-review what a specialist owns — a separate skill (not included in this export) owns frontend design/a11y; /service-review owns backend durability/observability
- Generic security code review — use /differential-review
