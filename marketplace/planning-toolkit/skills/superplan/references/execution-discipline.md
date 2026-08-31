# Phase 4b + Phase 5c: Plan Execution Discipline

Two paired phases that govern how plans loaded from prior sessions are
executed (Phase 4b) and how plans that under-deliver are documented as
terminal artifacts for the next plan author (Phase 5c).

---

## Real-time plan-flaw log (MANDATORY during execution — do not defer to /distill)

When executing ANY plan, the moment a step or checkpoint reveals that **the plan
itself was wrong** — a refuted assumption, a reachability/invocability miss, a bad
instrument, a flawed approach, a wrong number, a missing prerequisite — **append a
dated entry to a `<plan-slug>-flaws.md` sibling of the plan file, IN THE SAME TURN
you discover it.** Do not wait for /distill or /retro: by end-of-session the specific
trigger, the exact error string, and the corrected value have faded, and a flaw found
in an early phase is forgotten by a late one.

This is a SEPARATE artifact from the plan's own execution log (which records what
happened); the flaw log records **where the PLAN/RED-TEAM was WRONG and why**, so the
next plan author (and the superplan/red-team process) improves. Distinct from Phase 5c's
terminal-doc (which fires only on undershoot/falsifier and summarizes at the end).

**Entry format (append immediately):**
```
## <phase> — <one-line flaw> (YYYY-MM-DD, this-session)
- WHAT THE PLAN ASSUMED: <the assumption / instrument / number the plan relied on>
- WHAT EXECUTION FOUND: <the reality + the exact error / measured value>
- ROOT CAUSE CLASS: assumption | reachability | instrumentation | approach | number-stale
- WHY RED-TEAM/PLAN MISSED IT: <e.g. "only surfaces on real invoke; not a reasoning flaw">
- FIX APPLIED THIS SESSION: <the in-session correction> | DEFERRED: <why>
- DURABLE LESSON → <rule/skill file the lesson should land in at /distill>
```

**Discipline:** every stop-and-ask gate below that resolves to "the plan was wrong"
(not "the world changed") MUST produce a flaw-log entry before the fix proceeds. At
session end, /distill reads `<plan-slug>-flaws.md` as its pre-collected pain-point list
for the plan-authoring lessons — real-time capture feeds end-of-session routing, it does
not replace it. (Established 2026-06-20: the accuracy-measurement run surfaced 4 plan
flaws across P0/P1/P2; logging them as they occurred — rather than reconstructing at
distill — is what kept the root-cause classes and exact error strings intact.)

---

## Phase 4b: Critical Review Gate (for plans from prior sessions)

**This phase fires only when executing a plan loaded from a file or carried
over from a previous session.** Skip for plans just constructed in Phase 4.

Before executing a pre-existing plan:

1. **Read the plan file** completely — don't skim
2. **Check for stale assumptions**:
   - Were tools available when this plan was written that aren't now?
   - Has the codebase changed since the plan was written? (`git log --oneline --since="<plan date>"`)
   - Are there new constraints from recently-added rules or topic files?
3. **Check for open questions**: Does the plan's `## Session Context` have
   unresolved items?
4. **Raise concerns BEFORE starting**: If you find stale assumptions or
   missing prerequisites, present them to the user. Do not start executing
   a plan you have concerns about.
5. **If no concerns**: Proceed to execution. Create tasks with TaskCreate
   for each plan step, mark as in_progress/completed as you go.

**Stop-and-ask gates during execution:**
- Hit a blocker (missing dependency, test fails, instruction unclear): STOP
- Plan step produces unexpected output: STOP, re-evaluate
- Verification fails on 2+ consecutive steps: STOP, question the plan
- Don't force through blockers — ask for clarification
- **Predicted-vs-measured re-diagnosis gate**: when a phase ships and verification
  measures the actual delta, compare against the phase's predicted delta from the
  Demo line. If observed < 0.3× predicted (per `verify-effectiveness.md` "3× is
  better than expected" failure), the next phase MUST start with re-diagnosis —
  read the actual outcome, identify why the prediction was wrong — BEFORE
  proceeding to its own implementation. Continuing to ship the next phase against
  a falsified diagnosis is how 2026-05-08's plan reached 4 PRs deep without
  catching that PSM wasn't moving.
- **Falsifier trigger**: if the plan has a `## Falsifiers` section and a listed
  observation occurs (e.g., "PSM HTTP_CALLS unchanged after C1"), STOP and apply
  the documented re-diagnosis action — do not silently continue to the next phase.
- **Per-phase baseline-freshness re-check** (mandatory when the plan has been in-flight for >24h and the next phase predicts a metric value): BEFORE starting a new phase in a multi-phase plan that has been in-flight for >24h since the previous phase shipped, re-run the measurement command for each metric the next phase predicts (from the plan's Phase 3.5 Baselines section). If today's value diverges from the cited value by **>20% relative**, STOP and surface the divergence to the user — the phase's predictions may be obsolete. Report format: "Phase N baseline re-check: metric X measured M today vs P cited (Δ ±Q%). [PROCEED if within ±20% / STOP if outside]". The verdict for each phase is then carried into Step 5c's terminal doc as a per-phase freshness line so the audit trail survives. INCIDENT 2026-05-10 (plan-mid-execution drift): 4 inventory phases of the 13-gap remediation were obsoleted between authoring (2026-05-08) and execution (2026-05-10) because the metric the inventory cited had been moved by PRs that landed between authoring and execution. Phase 0's authoring-time check did not fire because the plan was authored against fresh baselines on 2026-05-08; by 2026-05-10 the baselines had drifted but no gate re-fired. This per-phase variant closes the residual.

- **Per-bucket falsifier measurement**: when a phase falsifier is scoped to a
  specific bucket (e.g. "delta from express+express-module within 30-60 range"),
  measure THAT bucket post-ship, not the total or aggregate. INCIDENT 2026-05-08
  (Phase B Express FP cleanup): post-merge index showed total Route count delta
  of -112 (424→312). Initial reading framed this as falsifier-triggered (-112
  outside the 30-60 range). Per-bucket re-measurement showed express+express-module
  went 50→4 (-46), exactly within range; the additional -66 came from unrelated
  index-refresh effects on rust-actix-builder / rust-axum-builder when `force=true`
  cleared stale entries. **Refinement:** when the falsifier names a per-extractor /
  per-bucket / per-language metric, the measurement query must SCOPE to that
  bucket (e.g. `r.extractor IN [...]`), not return the total.

- **Scope-amendment propagation** (mandatory when a mid-flight plan's scope changed
  since authoring): if the plan carries a SCOPE AMENDMENT — a top-of-doc banner, an
  inserted note, a "user changed X" edit added AFTER the original phases — re-read
  EVERY phase/section the new scope touches and confirm each was rewritten or marked
  N/A IN THE BODY. A banner records intent; it does NOT reconcile the phases below it.
  If a phase still describes the pre-amendment machinery (the amendment said "no human
  labels" but a later phase still says "human adjudication"), STOP and reconcile before
  executing — executing the stale phase rebuilds exactly what the amendment removed.
  INCIDENT 2026-06-20 (detection-pipeline measurement): a "ZERO human labels" amendment
  was prepended as a banner, but §4 oracle-design + §5 P3/P5 still specified human
  calibration, λ-tuning, and validity P/R/F1. The Phase 4b whole-plan re-read caught it
  at resume; the fix was a SCOPE RECONCILIATION table mapping each plan element to its
  post-amendment fate. The reconciliation artifact (not the stale body) becomes
  authoritative. Sibling of the per-phase freshness re-check: that one catches stale
  NUMBERS, this catches stale SCOPE.

(Pattern source: obra/superpowers executing-plans — Context7 registry 2026-04-06)

---

## Phase 5c: Terminal-doc-on-undershoot contract (mandatory after plan execution)

**Fires when** plan execution completes AND any phase falsifier triggered OR observed lift was < 0.3× the predicted lift OR the combined falsifier triggered.

When this fires, the terminal doc that ships with the plan's PR cycle MUST contain four named sections — PLUS a per-phase baseline-freshness verdict line for any phase that triggered the Phase 4b per-phase re-check (>24h-in-flight gate).

0. **Per-phase baseline-freshness verdict** (only when the Phase 4b per-phase re-check fired): one line per phase that was in-flight >24h since the prior phase shipped. Format: "Phase N baselines re-checked YYYY-MM-DD: [✓ within ±20% / ✗ drifted +Q% — re-predicted M→P]". When a re-check found drift, document what the plan author updated (predictions revised? phase dropped as REDUNDANT?) so the audit trail survives. Skip this section if no phase was in-flight >24h.

1. **Re-diagnosis** — citing measured evidence (not author belief). What does the post-execution data say about the actual mechanism? Example: "Phase A predicted ≥600 IMPLEMENTS rescues, got 16. Re-diagnosis: of 889 trait-failure cases, 873 are external std/external-crate traits not in the indexed graph (verified by sampling 50 traitQN-empty records). The substrate the plan attacked was 16 internal-trait cases, not 889."

2. **Retired hypothesis** — explicit statement of what the plan thought was the gap and why that was wrong. Example: "Retired: 'internal traits are reachable via project-wide name+label match' — wrong because the trait-failure denominator is dominated by external-crate references that have no Interface node to match."

3. **Named next-plan target** — bucket + measurement command + Phase 3.5 / 3.6 fields the next plan author can populate. Example: "Next plan target: external-crate trait awareness. Substrate count command: `mcp__code-graph__query_graph 'MATCH (n:CALL) WHERE n.target_name IN [\"From\",\"Display\",\"Debug\"] RETURN count(n)'`. Layer: IMPORTS resolver. Recoverable ceiling: bounded by Cargo.lock-resolved dep count (~50 trait-defining crates)."

4. **Versioned anchor file** — sibling file at `~/Documents/knowledge-base/plans/YYYY-MM-DD-<slug>-terminal.md` that the next plan's Phase 2d MUST read. The next plan cites this file's measurements as its starting baseline.

The terminal doc itself is a /superplan deliverable, not a discretionary artifact. Phase 5c writes it via the same git+PR flow as Step 5a.

**Execution-count audit**: the terminal doc names the SHA range it covers AND the /superplan invocation it ships under. Two terminal docs against two SHA ranges = two executions. One terminal doc covering one SHA range with a better artifact ≠ two executions. (This audit prevents the "Execution 3" framing slip surfaced by the 2026-05-08 roundtable, where a single plan's better terminal doc was framed as a separate execution.)

**Drop-on-zero-substrate ≠ defer (terminology contract)**: when Phase 3.6 field 1 substrate measurement returns zero on the named target, the correct framing is **DROP** (the plan's substrate estimate was wrong on this codebase), not **DEFER** (revisit later). These are different outcomes and confusing them produces the wrong terminal doc framing.

| Framing | Meaning | When to use |
|---|---|---|
| DEFER | Work is valuable but not session-feasible; revisit later | Time/dependency constraints, not substrate |
| DROP-ON-ZERO-SUBSTRATE | Plan's substrate estimate was wrong; this work has no measurable target on the named codebase | Phase 3.6 field 1 returns 0 on substrate verification |
| REDUNDANT | Plan-scoped target is already implemented; the work has no recoverable surface | Phase 0 / Phase A1 surfaces existing implementation |

INCIDENT 2026-05-08 (HTTP_CALLS link-rate followups, Phase D): substrate measurement returned 0 genuine HTTP wrappers on PSM (the plan's 16-count was geographic-path / GeoJSON / canvas functions, not HTTP wrappers). Initial framing in tasks called this "deferred"; user pushback ("Stop deferring, execute the plan") forced a re-framing as drop-on-zero-substrate. The framing matters: defer implies revisit, which sets up a future plan to re-attack the same substrate; drop-on-zero-substrate implies the substrate doesn't exist, which prevents that.

**Refinement:** when Phase 3.6 field 1 returns 0, the terminal doc's section 2 (Retired hypothesis) explicitly states "substrate measured 0; plan's estimate was wrong; this is drop-on-zero-substrate, not defer."

**Ceiling-claim verification (mandatory before Step 5c "structural ceiling" framing)**: before writing a terminal doc that concludes "this metric is at structural ceiling" or "no room to improve", ENUMERATE orthogonal mechanisms. The check has 3 questions:

1. Have I exhausted only mechanisms within the SAME architectural surface (e.g. more route extractors), or have I considered DIFFERENT surfaces (e.g. caller-side resolution, matching algorithm, downstream filters)?
2. For each not-yet-attempted mechanism: what's its substrate count? (Even rough back-of-envelope is sufficient.)
3. If ≥2 orthogonal mechanisms have non-zero substrate that wasn't measured: the ceiling claim is premature. Re-frame as "current-architecture ceiling" or "current-mechanism ceiling" with the orthogonal candidates listed.

INCIDENT 2026-05-08 (HTTP_CALLS link-rate diagnostic terminal doc): I wrote "26% link rate is structural" after exhausting B-fetch, B-python, B-filter paths. User pushed back: "So we are at a ceiling? There is no room to improve?" Re-enumeration surfaced 4 paths I had missed (Rust URL tracing, API-wrapper, mount-prefix, FP cleanup). 2 of those turned out to already be shipped or have zero substrate, but 1 (Express FP cleanup) was a real shippable improvement.

**Refinement:** the terminal doc's section 1 (Re-diagnosis) must include the 3-question enumeration when concluding ceiling. Use phrasing "current-mechanism ceiling, with the following orthogonal mechanisms NOT yet attacked: [list]" — not "structural ceiling" — unless the orthogonal-mechanism enumeration confirms zero remaining substrate.

**Why this contract exists:** the 2026-05-08 D-Implement plan's Phase A under-delivered (16/600 = 2.7% of target). The honest re-diagnosis ("external-crate awareness is the next gap") was written into the terminal doc voluntarily and structured the next plan's input, but /superplan did not require it. Without the contract, plans that under-deliver can ship "Phase A failed, oh well" as the terminal artifact and the next plan rediscovers context from scratch. The 2026-05-08 multi-week arc burned 4 PRs in this pattern. The contract closes the loop: undershoot → measured re-diagnosis → next plan's Phase 2d input.
