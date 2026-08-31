# Triage protocol — Article VI

Source: `~/Documents/knowledge-base/research/2026-04-30-framework-dispatch-template-v2.md`
Article VI. Lock criteria copied here so the skill is self-contained.

## Five trigger criteria

Dispatch is justified when **at least 2 of the following hold**:

1. **Aggregate metric plateau** — F1, accuracy, coverage, or
   equivalent stuck for ≥2 consecutive sessions of standard
   engineering work (read code, fix bugs, optimize). The Go-precision
   plateau at 0.515 (2026-04-29) is the canonical example.

2. **Per-subset variance signal** — the modal-split or per-project
   F1 spread is ≥2× the aggregate. Code-graph Go pre-PR-#121:
   aggregate 0.586, internal/store 0.303, internal/cbm 0.973 —
   3.2× spread, dispatch-justified.

3. **Both precision AND recall stuck** — a single stuck axis is
   usually a bug in one direction. Both stuck simultaneously
   suggests framing issue (the system's view of the problem is
   incomplete).

4. **Engineer cannot articulate "what to measure next"** — the
   inversion case. Discovery mode + `--inversion` flag swaps the
   persona prompt to "what would your framework MEASURE that the
   current metrics don't capture?" See M1 measurement-design
   inversion methodology.

5. **>30 minutes of conventional investigation already returned
   diminishing results** — read code, ran greps, sampled FPs/FNs,
   no pattern emerged. The framework lens may surface the angle
   conventional path missed.

## Denied override petitions

GUARD pattern="let me run dispatch on a fresh problem just because":
  REFUSE. Criteria are AND-gated; ≥2 must hold. Fresh problems score
  0/5 by construction — engineering hasn't produced enough friction
  signal yet. NO EXCEPTIONS.

GUARD pattern="the aggregate is fine but I want broad creativity":
  REDIRECT to `/scout-frontier` for novel-paradigm exploration on
  systems that aren't friction-anchored. Framework dispatch is for
  friction-anchored problems; scout-frontier is for paradigm shifts.

GUARD pattern="this is an audit-class assessment, dispatch for thoroughness":
  REDIRECT to `/fp-check`, `/triage`, or `/interview`. Framework
  dispatch surfaces fixes/measurements; audits gather verdicts.

GUARD pattern="the user asked for it":
  EVALUATE: is the user providing friction signal or exploring? If
  exploring, propose `/scout-frontier` or measurement-design
  inversion. If friction-anchored but vague, ask for the specific
  metric and current state before dispatching.

## Worked examples

| Problem | Trigger checks | Verdict |
|---|---|---|
| Go precision = 0.515 (2026-04-29) | (1) plateau ≥2 sessions, (2) per-subset spread 3.2×, (3) both P+R stuck, (5) >2hrs conventional | **DISPATCH** (4/5) |
| F1 = 0.890 post-PR-#125 (the original 2026-04-30 superplan trigger) | (1) plateau, (4) can't articulate next | **DISPATCH** (2/5) — likely inversion mode |
| Latest commit broke 1 test | None | DON'T (just fix the bug) |
| Fresh codebase, just want to understand it | None | DON'T (use `/code-explore`) |
| User wants to "apply frameworks to code-graph generally" | None (no metric, no friction) | DON'T (use `/scout-frontier`) |

## Skill behavior

Step 0 of `/persona` checks the criteria. If <2 trigger, the skill
exits with a message identifying which criteria failed and suggests
the alternative skill (e.g., `/code-explore`, `/scout-frontier`).
The skill does NOT dispatch when the gate fails — this is the load-
bearing protection against cargo-cult dispatch.

If exactly 2 trigger, the skill warns ("dispatch is borderline-
justified; consider whether conventional engineering would resolve
faster") and asks for confirmation. If ≥3 trigger, dispatches without
prompt.

## Source

Article VI in `2026-04-30-framework-dispatch-template-v2.md`.
Modifications to the gate criteria should update both the template
AND this reference simultaneously.
