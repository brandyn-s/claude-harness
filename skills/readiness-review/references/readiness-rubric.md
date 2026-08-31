# Readiness Rubric — the pre-registered SME-handoff bar

## Critical Gotchas (read first)

- **Do NOT invent the bar per run.** This file IS the pre-registered rubric. Re-deriving thresholds each session re-introduces the implicit-rubric failure that `grading-discipline.md` and `red-team-rubric-discipline.md` exist to prevent (the grader defaults to the most flattering or most pessimistic anchor). Cite this file; do not regenerate it.
- **Do NOT collapse to a single letter before the axis table.** Per `grading-discipline`, emit the per-axis table FIRST, then collapse on the named axis. A lone letter is unauditable.
- **Capability is graded by the independent-oracle result, not by "it ran."** A self-consistent transcription of a wrong formula passes its own unit tests. No independent oracle → grade Capability AMBIGUOUS, never A.
- **A live-blocked axis is graded AMBIGUOUS with a documented reason — never silently passed.** Faking a live pass is the failure this bar exists to prevent.

## The five pillars and their level bar

Production-ready for SME handoff = **every pillar ≥ L3, and the safety-relevant
pillars (Capability, Reliability, Security) ≥ L4.** Levels (knowledgelib
product-maturity 1–5):

| Level | Meaning |
|---|---|
| L1 | exists / runs in the happy case |
| L2 | handles common variation; some error handling |
| L3 | **production floor** — correct on real data, fails closed on bad input, observable, documented |
| L4 | **safety bar** — verified correct against an independent oracle; adversarial-hardened; no silent-wrong-output path |
| L5 | battle-tested at scale with monitoring + regression coverage |

| Pillar | What L3 requires | What L4 (safety) requires |
|---|---|---|
| **Capability** | core output correct on real domain data | validated against an INDEPENDENT oracle (≥2 code-disjoint checks); a wrong go/no-go number is the worst outcome |
| **Usability** | an SME can drive it; errors name the cause | errors are actionable (name the field/row + the fix), not generic |
| **Reliability** | fails closed on bad/missing data; no crash | adversarial-hammered: 0 crashes, 0 accepted-bad-input, every boundary fails closed |
| **Security** | auth on every route; default-deny; no secrets in repo | input sanitized at trust boundaries; authz verified live; rate-limited where abusable |
| **Operability** | boots; structured logging; a real health probe | config validated at boot (secure-by-default); request IDs; tested backup/restore |

## Per-axis grade thresholds (pre-registered)

State these in the grade output, then apply:

- **A** — meets the pillar's L4 bar with live evidence.
- **B** — meets L3, not yet L4 (e.g. correct + fails-closed but no independent oracle yet; or live-verified but one High finding open).
- **C** — partial L3 (a real gap that bounds SME trust but isn't a wrong-answer/crash/authz path).
- **D / NO-GO** — a Critical: a wrong-output path, a crash on realistic input, a silent-accept of bad data, or an authz hole.
- **AMBIGUOUS** — could not be verified (live-blocked, no oracle achievable). Documented, not a pass.

## The go/no-go collapse rule

Collapse the axis table on the **SME-handoff axis**:

- **Any Critical (D) on a safety pillar → NO-GO.** A wrong number / crash / silent-bad-data / authz hole is disqualifying regardless of the other pillars.
- **All safety pillars ≥ L4, others ≥ L3, zero Criticals → GO.**
- **A High finding open (real defect, bounded blast radius — e.g. caught downstream) → GO for a SUPERVISED pilot; fix before unsupervised handoff.**
- Always state honest scope limits: what was NOT verified and why (especially live-blocked axes).

## Worked instance (Proteus Polar, 2026-06-19)

Capability **A** (12/12 hand-values + scipy 1e-12 + real MRV0 file; vendor-differential live-blocked → documented, not faked) · Reliability **A** (0 crashes / fail-closed across 13 adversarial inputs) · Usability **B+** · Security **A** · Operability **A**. One High (junk-upload-200, caught downstream → bounded). Collapse → **GO for supervised pilot; fix the High before unsupervised handoff.**
