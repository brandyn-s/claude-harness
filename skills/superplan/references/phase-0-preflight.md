# Phase 0: Empirical Preflight — Detail

The high-level Phase 0 workflow (fires-when, skip-when, verification table,
stop-and-ask gate) is in SKILL.md. This reference holds the discipline
subsections.

---

## Mechanical verification (mandatory — do not skip on session-memory)

The verification table in SKILL.md describes WHAT to verify. This subsection
enforces that the verification is **mechanically executed**, not aspirationally assumed.

Before writing Phase 4, execute a literal grep/ls/find on every named entity in the request. Do not skip because "I was in the same session" or "I know this file exists." Session memory is not evidence — entities can be in a different repo, renamed, or never existed in the named location.

**Required pattern** (run as a single Bash block, surface results in Phase 0 report):

```bash
# Entity verification — one line per cited entity
test -f ~/path/to/file.py && echo "✓ file.py" || echo "✗ file.py NOT FOUND"
test -d ~/.claude/skills/foo && echo "✓ /foo skill" || echo "✗ /foo NOT FOUND"
grep -l "function_name" ~/repo/src/ 2>/dev/null | head -3   # function existence + dedup
```

When `✗` appears: STOP. Either re-scope (drop the entity from the plan) or correct the citation (find the right repo/path). Do NOT proceed to Phase 1 with the entity still cited but unverified.

**Common failure mode**: citing a tool that lives in a SIBLING repo. Example (2026-05-10 incident): `bench/research/locbench_prewarm.py` cited in code-search; actually lived in code-graph. Same directory shape; different repos. A literal `test -f ~/Documents/GitHub/code-search/bench/research/locbench_prewarm.py` would have surfaced ✗ in 5 seconds. The plan instead carried the wrong citation into Phase D, which was dropped at execution as misattributed.

**Discipline**: if you wrote the words "X exists at Y" anywhere in the plan body, run `ls Y` or `grep X Y` BEFORE the words ship. The verification is the discipline; the table above is just the checklist.

---

## Baseline freshness check (mandatory when plan cites metric values)

If the user request OR the planned scope cites a SPECIFIC METRIC value
(precision = 17.6%, recall = 27.3%, F1 = 0.85, MRR = 0.5, edge count = 17,
etc.) AND the citation source is older than **24 hours**, re-run the query
that produced the cited value before designing the plan around it.

Examples that fire:
- "PSM HTTP_CALLS precision is 17.6%" cited from a 2026-05-08 doc → re-run today's `mcp__code-graph__query_graph` to confirm.
- "Loc-Bench class accuracy is 46.5%" cited from 2026-05-04 baseline → re-run today's eval if planning a fix.
- "IMPLEMENTS recall is 27.3%" cited from a multi-day-old measurement → re-run.

Examples that skip:
- The inventory that cites the number was published today — measurement IS today.
- Request doesn't cite specific metric values — no re-baseline needed.

Required verification command per metric type:

| Metric type | Re-baseline command |
|---|---|
| code-graph edge count | `mcp__code-graph__query_graph "MATCH ()-[r]->() RETURN count(r)"` |
| code-graph F1 / precision / recall | `python3 bench/accuracy/compare.py <fixture>` |
| code-search MRR / Hit@K | the prior eval script (e.g. `eval_against_psm_full.py`) re-run today |
| Loc-Bench accuracy | `python3 bench/research/eval_locbench_compare.py` re-run today |

If today's measured value diverges from the cited value by **> 20% relative**, STOP and surface the divergence to the user before proceeding to Phase 1. Don't build a plan around a number that's no longer current.

INCIDENT 2026-05-10 (3rd recurrence of "stale-baseline-in-plan"): the accuracy gap inventory (PR #279) cited 2026-05-08 measurements for HTTP_CALLS (17.6% precision → today the misresolution failure mode is gone, ~85%+ precision) and IMPLEMENTS (27% recall → today 980 edges with 94% precision). 3 of 13 inventory gaps were obsolete on day-one because the inventory inherited stale numbers without re-running. Phase G and Phase I both shipped REDUNDANT verdicts as a result. The `verify-instrument-before-fix.md` rule (folded into `verify-effectiveness.md` 2026-09-03) "plan_baselines_decay_between_authoring_and_execution" was added 2026-05-09 (PR #867) but as prose; this Phase 0 freshness check is the structural enforcement.

---

## Invocability + instrument-soundness check (mandatory for eval / measurement / model-using plans)

Existence (`test -f`, `ls`, a capability LISTING) is NOT invocability or soundness. Phase 0's
existence check passes while the thing is still unusable for the plan. For any plan that will
INVOKE a model, RUN a query engine, or REUSE a function as a measurement instrument, add a
**smoke** step to Phase 0 — actually invoke it once, on a known input, before the plan commits.

This is the superplan-process gap behind the 2026-06-20 accuracy-measurement plan: a heavily
red-teamed plan STILL carried 3 wrong assumptions that only surfaced on real invocation. The
red-team caught the one DESIGN flaw (the oracle); it could not catch these — they are not
reasoning errors, they are reality not matching the listing. The fix is structural: smoke
BEFORE the expensive phase.

| Assumed-from-listing | Reality on invoke | Smoke that catches it |
|---|---|---|
| Model is ACTIVE in `aws bedrock list-inference-profiles` | invoke → `ResourceNotFoundException` "marked Legacy, not used in 30 days" | invoke each model once on a trivial prompt |
| A cross-model protocol param is universal ("replicate ×3 at temp 0") | Opus 4.8 → `ValidationException` "temperature is deprecated for this model" | invoke EACH model with the exact params the plan specifies |
| A model will perform the task | frontier model REFUSES attacker-TTP / security grading without authorized-review framing | smoke on a representative (not just benign) input |
| A production function is a clean measurement instrument | `detect_taint`'s best-effort `except: return []` swallowed a transient throttle → silent "0 findings" (true count 326; ~42% census undercount) | run it twice on the same input; if a transient error yields a DIFFERENT (lower) count, it swallows — wrap with hard-fail |

**Rule of thumb:** capability LISTING ≠ invocability (extends `verify-before-assuming.md`
reachability-vs-capability to model invocation); and a PRODUCTION code path reused as a
measurement instrument inherits its production-tuned failure modes (swallow-and-continue is
correct for a never-block-the-brief path, FATAL for a census) — wrap or re-prove it to
HARD-FAIL, never silent-zero (extends `verify-effectiveness.md` prove-the-instrument).

**Two-gate discipline this codifies:** red-teaming catches DESIGN / ASSUMPTION flaws
(pre-execution, by argument); P0/P1 empirical-smoke gates catch INSTRUMENTATION / REACHABILITY
flaws (only surface on real invocation). A rigorous plan needs BOTH, and the smoke gate MUST
run before any expensive/billable/long phase — its entire purpose is to fail cheap.

**Scale caveat — the smoke fails CHEAP, so it can miss SCALING cliffs.** Invoking once on a SMALL
input proves invocability, not scalability: an instrument that is fine at small N and pathological at
full N (a paginated result-fetch fine at 2K rows but untenable at ~1.5M; a per-unit full-table scan;
an O(N²) join) PASSES a small smoke. Pair the smoke with a full-N COST estimate (fetch / transport /
fan-out at the real population size), not only a small invoke — and prefer staging large data in-cloud
over paginating it to the local machine. (Extends the smoke from "does it run?" to "does it run at the
size the plan needs?")

**SIX-catcher model (2026-06-20: five catchers distilled from the accuracy-measurement run's 6
flaws + a 6th TEMPORAL catcher from a parallel live-telemetry census run — no single gate
catches more than one class):**

| Flaw class | Example | The ONLY gate that catches it |
|---|---|---|
| DESIGN / assumption | oracle panel ≠ independent (n_eff≈2) | research red-team (pre-execution, by argument) |
| REACHABILITY / instrument | model listed-but-disabled; API-contract drift | P0/P1 empirical smoke |
| CONSISTENCY / propagation | a scope amendment not propagated into the phases it invalidates | Phase 4b read-the-WHOLE-plan-at-resume |
| MEASUREMENT-TARGET / population | wrong denominator for the objective; degenerate/empty input population | build-time SOURCE-read of the decision function + a population census |
| INFRASTRUCTURE / transport | a mid-run network blip hard-dropping recoverable units | LIVE run-MONITORING that ALARMS on the pre-registered checkpoint |
| TEMPORAL / live-substrate | denominator/population GREW between the count and its use; an exact-match count-gate false-alarms on near-real-time data | authoring-time WATERMARK (pin as-of T) + SUBSET-detection gate (materialized ≥ last-known), never exact-match-vs-stale |

The last three are the 2026-06-20 additions. Their authoring-time gates:

- **MEASUREMENT-TARGET preflight (flaws 7+8):** before the plan trusts a number or a population,
  (a) read the decision function's CONTRACT from source — does the LLM/engine actually EMIT the
  field you're measuring? what is the field's denominator? (the plan measured a `severity` it
  assumed the judge emitted, and counted a census denominator from an ADJACENT objective —
  ~17-20% wrong). (b) Census the input POPULATION before judging it — degenerate/empty units
  exist (~14-17% of sessions were <500 chars; 2 of 3 panel models HALLUCINATED findings on
  empty input). State the inclusion threshold and report the excluded count; never feed an LLM
  panel a degenerate input and trust the verdict.
- **INFRASTRUCTURE resilience (flaw 9):** any plan with a long run against a REMOTE service must
  specify, at authoring, that the harness CLASSIFIES transient (network/throttle/timeout — retry
  + circuit-break) vs deterministic (parse/validation — fail fast) errors, captures dropped units
  for a retry pass, and computes the coverage checkpoint POST-retry. "Hard-fail on error" is
  correct ONLY for deterministic errors; applied to a transient transport blip it turns a
  recoverable 10-min outage into permanent coverage loss (34% of a day lost this way before the
  fix). And the run-monitor must ALARM when the live drop-rate crosses the pre-registered
  checkpoint — not merely report progress.
- **TEMPORAL preflight (live / streaming / append-only substrate):** if the source is
  near-real-time, the population is a MOVING TARGET — pin a WATERMARK (as-of cutoff T) BEFORE
  measuring. Every count, denominator, and gate is then relative to T; the run is "historical
  as-of T" and post-T data belongs to the streaming-detection path, not this census. Gate on
  SUBSET-detection (materialized count ≥ last-known), NEVER exact-match against a stale
  denominator — an exact-match gate is GUARANTEED to false-alarm on a growing population (it
  fired "DRIFT" on every surface of a live-telemetry run where the data had merely grown between
  two measurements). This is the F0 substrate-assumption pattern on the TEMPORAL axis: the
  substrate isn't only a fixed shape, it's growing.

**Single-instance generalization (the retraction, flaw 6):** when a system has N instances of a
role (here, 2 judges — per-tool-action AND session-level), ENUMERATE all N before generalizing
one instance's contract to "the X." A diagnosis built on the first instance found is
single-source (see `symmetric-evidentiary-burden.md`); the plan's O1 was briefly mis-diagnosed
as "the judge emits no severity" from reading only one of two judges.

---

## Why Phase 0 exists

Pre-existing skills assume things they should verify. The 2026-05-03 roundtable surfaced the pattern (its own protocol-failure-mode #1: "every agent endorsed cheap empirical tests, none ran them") and the same session caught a wrongly-flagged consolidation (`retrospective` → `retro`) that would have shipped without preflight. Phase 0 codifies the discipline so /superplan structurally requires what individual agents forget to do. The baseline-freshness check (added 2026-05-10) is the third recurrence of stale-baseline-in-plan — see PR #867 (rule) and PR #283 (3 obsolete inventory gaps).
