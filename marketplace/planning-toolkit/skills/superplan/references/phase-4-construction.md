# Phase 4: Plan Construction — Detailed Discipline

The core Phase 4 workflow (self-contained constraint, refresh-then-decide
framing, Demo statement basics) is in SKILL.md. This reference holds the
implementation-detail subsections.

---

## Default phase ordering for observable-system plans

When the plan touches an observable system (extractors, parsers, resolvers,
indexers, ranking algorithms, anything that pattern-matches against real
codebases), default the phase ordering to:

1. **Instrument** — ship the slog/counter/diagnostic so downstream phases have
   data. Skip if the system already emits the needed signal.
2. **Investigate** — run instrumentation against the real target, classify
   findings, produce a documented artifact (file:lines, sample shapes, counts).
3. **Implement** — write the fix against the specific shapes Investigation
   surfaced. Cite the artifact's findings in the implementation phase body.
4. **Verify** — re-measure the Phase 1 instrumentation; assert the predicted
   delta materialized. If observed << predicted (< 0.3× ratio per
   `verify-effectiveness.md`), the next phase MUST start with re-diagnosis,
   not with its own implementation.

This ordering prevents the "ship fix → see what happens" anti-pattern. INCIDENT
2026-05-07/08: PR #247 shipped a resolver fix without instrumentation; PR #248
later added instrumentation that revealed PR #247 was a misdiagnosis on PSM (the
labeled-trait path it expanded was never exercised). Instrument-first ordering
catches this before the wrong fix ships.

---

## Cross-component coordination check for instrumentation additions

When a plan step ADDS a new signal — a log prefix, metric name, env-var, response field, JSON key, event type — grep for the DOWNSTREAM CONSUMER in the same edit batch before assuming the new signal will be visible. The consumer is the code that filters, parses, persists, or routes the signal; if it doesn't accept the new shape, the signal goes nowhere and the instrumentation phase produces zero records.

**Required pattern** (one grep per new signal):

```bash
# Adding [NEW_LOG_PREFIX] in module X?
grep -rn "_ACCEPTED_PREFIXES\|ACCEPTED_PREFIXES\|allowed_prefixes" <repo>/  # find log filters
# Adding new env-var X?
grep -rn "os.environ\|os.getenv" <repo>/ | grep -i "X"  # find readers
# Adding new response-JSON field X?
grep -rn '"X"\|\.get(.X.)\|json\[.X.\]' <consumers>/  # find parsers
# Adding new metric label X?
grep -rn "metric_name\|MetricCollector" <repo>/  # find aggregators
```

Verify the downstream consumer **either already accepts the new shape OR is patched in the SAME edit batch**. If neither, the signal will be silently dropped and the instrumentation phase fails invisibly.

INCIDENT 2026-05-10 ([PATH_OVERRIDE_TRIGGER] log filter gap): plan added `LOG.info(f"[PATH_OVERRIDE_TRIGGER] ...")` emission in `_effective_threshold`. The existing `_SearchDiagFilter` in `search/indexer.py:75` had a hardcoded prefix-list (`_ACCEPTED_PREFIXES = ("[CHUNK_ID_DIAG]", "[REINDEX_PROGRESS]", "[ANTHROPIC_DIAG]")`) that DIDN'T include the new prefix. First override eval ran with the new logging code but produced **zero** trigger records — the filter silently dropped them. Discovered when `grep -c PATH_OVERRIDE_TRIGGER ~/.claude/logs/code-search-mcp.log` returned 0 mid-eval. Fix was 5 lines to extend the prefix list. Cost: one wasted eval (~$1.50 API, ~20 min wall) before the gap was caught.

The grep takes < 30 seconds at plan time and prevents the entire instrumentation-silently-dropped failure mode. Apply to EVERY new signal the plan introduces, even if the signal "looks like" existing signals (the filter may discriminate on exact prefix).

---

## Demo constraints for size-of-effect phases (mandatory)

1. **Cite the Phase 3.5 baseline.** Any Demo claiming a measurable lift must
   include "currently N → expected M" using the baseline number. Example:
   `Demo: "PSM HTTP_CALLS at /api/v2/power/status resolves to handle_power_status
   (currently resolves to run_http_server; baseline shows 14 such misresolutions)."`
   FORBIDDEN: `Demo: "PSM HTTP_CALLS ≥ 30"` without a "currently 17" baseline.
   FORBIDDEN: `Demo: "synthetic fixture passes"` as the ONLY demo for a phase
   that claims real-target impact. Synthetic passes are regression-gate
   evidence, supplementary to the target-state assertion.

2. **Target-system specificity.** Demos for size-of-effect phases must reference
   a specific entity in the target (file:line, edge target, metric name) — not
   the synthetic fixture or test name. The fixture is the validation; the demo
   is the claim about reality.

3. **Forbidden phrases.** Any of these in a Demo line block plan finalization:
   - "≥ N" / ">= N%" / "lift to N" without a "currently M" baseline citation
   - "improves <metric>" without specifying the size of the improvement
   - "fixture passes" as the standalone demo for a size-of-effect phase

4. **Production-stack verification.** When a phase ships a default-flip
   affecting a production deployment mode (default reranker config, default
   resolver flag, default embedding provider, default model), the Demo must
   cite BOTH (a) local-mode evidence AND (b) production-mode evidence — OR
   document a production-mode block with a named close-condition. See
   `rules/eval-shipping-discipline.md` for the underlying ship gate
   (`both_off_mode_and_production_mode_must_validate` invariant).
   Shipping local-mode-only evidence requires an explicit `## Pending:
   production-stack verification` section in the findings doc.

   INCIDENT 2026-05-10 (D1 example-gateway prop-interface decoration): code
   shipped (PR #156) with bootstrap CI on `RERANKER=off` showing +0.036
   golden MRR (CI excludes zero). Sonnet rerank validation (the production
   stack) was deferred without an explicit pending-section. User had to
   surface the gap by asking. The cross-reference to eval-shipping-
   discipline at Demo-construction time would have caught this.

---

## Deploy-seam check (mandatory for BUILD phases whose artifact is DEPLOYED)

Fires for any BUILD phase whose artifact is a **deployed component** — a Lambda
module, ECS service, hook, scheduled job, anything that runs somewhere other than
the test host. "File exists on main + repo tests pass" is NOT a completion criterion
for such an artifact; it is the documented multi-seam trap
(`verify-effectiveness.md` `a_multi_seam_feature_is_not_done_until_one_real_run_crosses_every_seam_to_the_real_sink`). The Demo line AND the `### Metric Commands` MUST assert
the artifact reaches its **real sink**, not its mere presence:

1. **In the deploy boundary.** A new module/file is actually packaged into what
   ships — COPYd in the Dockerfile, bundled in the layer/zip, on the image's import
   path. The metric `grep`s the Dockerfile / package manifest / image file list, NOT
   just `[ -f <file> ]` on the repo checkout. The Dockerfile COPY list IS the
   what-runs-in-prod manifest; a file outside it that a deployed module imports is a
   silent break.

2. **Wired into the entrypoint that actually runs.** The deployed call chain
   (scheduler / Lambda handler / daily-job entry) reaches the new code — grep the
   *production* call path, not the test that imports it. A function wired into a CLI
   `main()` the scheduler never calls is a no-op (see also
   `verify-effectiveness.md` "wired into <entrypoint> but production calls a DIFFERENT entry").

3. **One real invocation crosses every seam.** Deploy → run on real input under the
   real identity → assert on a far-end artifact only the real path could produce. A
   synthetic in-repo test that imports the module proves the code, not the deployment.

**Placement rule:** put a new module at its DEPLOY BOUNDARY (the directory the image
COPYs from), NOT by conceptual grouping. A module imported by a deployed entrypoint but
placed in a not-COPYd sibling dir is the specific trap.

### Deploy-seam incident (2026-06-26 detector-expansion)

INCIDENT 2026-06-26 (detector-expansion supergoal arc): Phase B shipped
`judge_hardening.py` to `detector/` and wired `from judge_hardening import
blind_transcript` into the daily detector's entrypoint module. The Lambda Dockerfile
COPYs only `scripts/` — so the deployed image was missing the module and the fail-loud
import would crash the daily judge at startup. The
supergoal metric read `phases_complete=7` GREEN (it checked `[ -f detector/judge_hardening.py ]`
+ repo-tests-pass); CI was green (tests run where `detector/` exists). The break was
invisible until the Lambda ran — caught only when the user asked "is it fully deployed?".
Fix: `git mv` to `scripts/` (the deploy boundary) + add to the Dockerfile COPY + a
flat-image-layout seam test (mcp-servers #686). Had the Demo/metric asserted "in the
image COPY + one real invocation," it would have failed at authoring time on the
`detector/`-path metric.

---

## Falsifiers section (mandatory for M/L/XL plans)

Every plan estimated at M or larger must include a `## Falsifiers` section
listing:

- For each phase: "If after Phase X we observe Y, the diagnosis is wrong."
- Specific observations that would invalidate the plan's working theory.
- The action to take when a falsifier triggers (re-diagnose, drop scope,
  change approach).

This forces the planner to articulate failure modes in advance. A plan with no
documented falsifier means the planner can't tell when the plan is failing —
which is how 2026-05-08's plan got 4 PRs deep before C3 surfaced "PSM didn't
move." Stating up front "if PSM HTTP_CALLS doesn't rise above 17 post-C1, the
diagnosis was wrong" makes that surfacing the trigger for re-diagnosis instead
of a write-up-after-the-fact finding.

---

## Phase grouping (for plans with >8 steps)

If the plan has more than 8 steps, **group steps into named phases** (e.g.,
"Phase A: Data Collection", "Phase B: Analysis", "Phase C: Output").
Each phase should have 3-6 steps with deep per-step detail. This prevents
the plan from becoming a shallow checklist — depth per step matters more
than total step count.

---

## Dependency and parallelism notation

Every step must include a `Depends on` field. Steps with `Depends on: none`
or that share the same dependency can be marked as parallelizable. Include
a **Dependency Summary** using arrow notation:
`1 → 2 → [3 | 4] → 5` (brackets = parallel, arrows = sequential)

Validate against the **Plan Quality Checks** in `references/planning-framework.md` before presenting.

For complex plans (4+ steps), before presenting, **decompose the plan into its load-bearing
assumptions and adversarially review each** — run `/interview` to stress-test internal
consistency, AND for any assumption about external-system or model behavior, research it against
current (≤6-month) sources before relying on it (`gather-research/references/citation-domain-freshness.md`).
A plan's most expensive flaws are design assumptions that felt obvious; the adversarial pass is
where they surface. (For MEASUREMENT / oracle plans this is MANDATORY and formalized as the
research-red-team step — see `references/measurement-run-plantype.md` §3a.)

---

## Engineering review sections (for M/L/XL plans)

For plans estimated at M or larger, include these additional sections to
force hidden assumptions into the open:

**Error map** — For each step that calls an external service or API, name
what can go wrong and what happens when it does. No catch-all error handling.
Every error path must be named:

| Error | Trigger | Handler | User sees |
|-------|---------|---------|-----------|
| `API timeout` | upstream >5s | retry 3x | "retrying..." then fail |
| `Auth expired` | SSO token stale | re-auth prompt | "re-authenticate" |

**Dependency failure analysis** — For each external dependency (MCP server,
API, CLI tool, database), answer: what happens if it's down? Timeout?
Returns garbage? This prevents plans that assume all dependencies are always
available.

```
Dependency: CrowdStrike MCP
  If down: skip detection fetch, report "CrowdStrike unavailable"
  If timeout: retry 2x with 10s backoff
  If bad data: validate response shape before processing
```

**Skip for XS/S plans** — these add overhead that's not justified for simple tasks.
(Pattern source: denchhq/denchclaw plan-eng-review — Context7 registry 2026-04-06)

---

## Phase-type + execution-mode (mandatory per-phase tags)

Every phase carries a phase-type tag and an execution-mode tag. SKILL.md Phase 4 states the rule; this is the procedure + the worked example. (Distilled 2026-06-22 from the credential-detector v4.1 arc, where these four decisions — typing, headless/durable, sequencing, sizing — were the difference between a plan that respected the user's "no laptop-tethered long run" constraint and one that didn't.)

### 1. Phase type — BUILD / MEASURE / WRITE
Tag each phase by what it PRODUCES, because the type determines execution mode and sequencing:
- **BUILD** — writes code/config that changes what the system DOES. Ships user-facing capability. The "measurement" attached to a BUILD (a falsifier) is its acceptance test, not its deliverable.
- **MEASURE** — runs an existing instrument to produce a number / verdict / CI. The number IS the deliverable; no new capability.
- **WRITE** — a document (design-of-record, evidence pack). No API, no code.

### 2. Execution mode — HEADLESS > DURABLE > LOCAL-FAST (the "no laptop-tethered long run" rule)
Default to **HEADLESS**; fall back to **DURABLE** only where headless is impossible; reserve **LOCAL-FAST** for genuinely-minutes work.
- **HEADLESS** — bulk API/model work submitted as an async batch (Bedrock `create_model_invocation_job` is the in-boundary primitive; verify the batch job uses the SAME model/contract as the on-demand path, transport-only difference). Submit → disconnect → collect output later. The run survives the laptop being off/closed.
- **DURABLE** — for work that CANNOT be headless: irreducible operator/human per-item JUDGMENT (the agent reading blobs one-at-a-time), not an API batch. Make it detached + checkpoint-resume (write each result the moment it's produced) + `.done`/`.fail` markers on a durable repo path, resumable across sessions. A disconnect/kill loses zero progress; it never needs one long tethered sitting. (The durability triad: `rules/worktree-by-default.md` `long_run_tied_to_shell_lifetime` + `expensive_run_output_written_to_tmp`.)
- **LOCAL-FAST** — bounded-minutes runs + builds; laptop-on is fine because it's minutes.
- **FORBIDDEN**: a laptop-tethered run expected to exceed ~30 min that is neither HEADLESS nor DURABLE. If a phase would be that, convert it (batch it, or checkpoint+shrink it) before presenting the plan.

### 3. Sequencing — capability before the long measurement
When a plan mixes BUILD and a long MEASURE: if the BUILD phases do NOT depend on the MEASURE phase's output, ORDER THE BUILDS FIRST (a "WAVE-1") so shipped user-facing capability is never blocked on operator-labeling / measurement labor. Long measurements (and the trust claims that rest on them) come after — they gate the *numbers*, not the *capability*.

### 4. "Is it actually long?" — size a MEASURE phase before calling it long
Before tagging a MEASURE phase as multi-hour, separate:
- **API-call time** — minutes at worker-parallelism. (Worked number: 516 single-Sonnet judge calls completed in ~90s at 16 workers. Hundreds-to-low-thousands of model calls is minutes, not hours.)
- **Irreducible operator/human labor** — the agent reading N items one-at-a-time, or a human hand-labeling. ONLY this is truly long.
Do NOT headless-engineer a 90-second run. The execution-mode machinery is for the operator-labor long-pole, not for a fast batch. If the long-pole IS operator labor, consider a HEADLESS judge PRE-PASS that shrinks the operator's scope to just the uncertain band.

### 5. Two-mode declaration (multi-mode systems only)
If the system has incompatible optimization targets (worked example: a detector's measure-mode wants recall SENSITIVITY while its rotation-mode wants PRECISION), each phase declares which mode it serves, and MUST NOT optimize one while silently damaging the other. A phase that improves precision must state its recall cost (and vice-versa); "improves the system" without naming the mode is the trap.

### Worked example (v4.1 credential-detector remaining-engineering plan, doc 42)
```
WAVE 1 [BUILD · LOCAL-FAST]   Phase C (value/rotation lane) -> Phase D (standing live-verify)   <- capability ships first, no dependency on measurement
WAVE 2 [MEASURE · HEADLESS]   Phase B-precision || Phase A (embedding scout) || Phase E (gates)  <- Bedrock batch: submit, laptop off, collect
WAVE 3 [MEASURE · DURABLE]    Phase B-realprose: headless judge pre-pass -> operator labels ONLY the uncertain band, checkpoint-resume  <- the one un-headless long-pole, shrunk + durable
WAVE 4 [WRITE · LOCAL-FAST]   Phase H (architecture-of-record)
```
Each phase tagged BUILD/MEASURE/WRITE + HEADLESS/DURABLE/LOCAL-FAST; capability (WAVE 1) sequenced before the long measurement (WAVE 3); B-realprose sized as the only true long-pole (operator labor, not API) and made durable rather than tethered.
