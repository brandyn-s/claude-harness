---
paths:
  - "**/rules/verify-instrument-before-fix.md"
  - "**/rules/incidents/verify-instrument-before-fix.md"
---

# verify-instrument-before-fix: Incident Narratives

Extracted from `rules/verify-instrument-before-fix.md` to keep the ambient body small
while preserving the failure-mode history. The parent rule keeps the
trigger line; the full narrative lives here.


<!-- extracted 2026-08-01: ambient-context reduction -->

## in-three-documented-incidents-the-cell-surfaced-by-per

```
WHY: in three documented incidents the cell surfaced by per-cell
     precision/recall analysis turned out to be an instrument bug
     (oracle drop, CBM definition-time QN format, stale per-subset DB
     indexes), not a real system failure. Designing a fix targeting
     the cell when the cell is a measurement artifact wastes the
     fix budget AND re-introduces the upstream problem when the
     instrument is later corrected. The 2026-05-02 THEME D revert
     (PR #144 → PR #145) was the third instance: +3.3pp F1 vs stale
     per-subset DBs, -2.9pp F1 vs fresh ones after Janusian penalty
     shipped between measurements.
```

## one-or-two-samples-can-be-cherry-picked-or

```
WHY: one or two samples can be cherry-picked or accidentally
     representative of a sub-mode. Three to five edges drawn from
     the dominant cell give enough variance to surface the difference
     between "real failure mode" and "artifact of how the instrument
     sees it."
```

## not-the-harness-s-report-not-the-llm-judge

```
WHY: not the harness's report, not the LLM-judge's verdict, not the
     grep snippet. Open the file at the line, read the surrounding
     function, trace the call into the resolver. The instrument bugs
     that have appeared all looked normal in summary form and only
     diverged from reality on direct source reading.
```

## 2026-07-28-mcp-infra-719-otel-canary-missed

```
WHY: 2026-07-28 mcp-infra #719 — `otel-canary-missed` reported 0 of 4
attack fixtures caught, two days running, incl. credential-exfil and a
reverse shell. The obvious reading was that detection had gone blind. The
evidence file existed, all 4 canary sessions were present, and the
detector had flagged every one at `crit` — 8 of 8 across both days. The
verifier ran at a fixed 10:00 UTC while the judge finished at 08:33 /
09:38 / 11:43 / 11:50, so it read a pre-canary version of the file. Had I
"fixed the detector," I would have modified a healthy system on the
strength of a broken instrument.
```

## 2026-05-02-theme-d-pr-144-pr-145

```
INCIDENT 2026-05-02 THEME D (PR #144 → PR #145): F1 0.890 plateau,
cell looked like "cross-package-heuristic threshold too loose,"
shipped tighter threshold. Measured against stale per-subset DBs.
Fresh DBs after Janusian penalty (commit 3980e24) showed -2.9pp
regression. Reverted in PR #145.
```

## 2026-05-10-production-readiness-gaps-plan-phase-a

```
INCIDENT 2026-05-10 production-readiness gaps plan: Phase A baseline
cited "100% null r.strategy" from a prior /retro audit; on
day-of-execution the actual rate was 6%, dominated by self.method()
path missing resolution_strategy. The audit query had used wrong
column name (`r.strategy` vs `r.resolution_strategy`); plan inherited
the error. Phase B baseline cited "4 manual recovery modes" against a
taxonomy doc that had been updated 5 days earlier (B3.5 promoted Mode
5 from silent re-create to structured error). Both errors propagated
through Phase 3.5 baselines, plan documentation, falsifier tables,
and PR descriptions until day-of-execution measurement caught them.
The fixes shipped were correct; the predicted lifts were wrong (Phase
A delivered ~5pp vs ~95pp predicted). This is the same instrument-
decay pattern as the four-in-a-row incidents above, but at the
plan-authoring layer rather than the per-cell-analysis layer.
```

## 2026-07-31-a-gold-etl-lambda-was-actively

```
WHY: 2026-07-31 — a gold ETL Lambda was actively in CloudWatch ALARM (a non-atomic,
unguarded delete-then-insert can leave a partition permanently empty). Source (bronze)
had been measured exhaustively; the destination (gold) was trusted on a 6-week-old KB
entry saying "Delta=0" and never re-checked live.
```
