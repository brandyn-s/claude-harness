# Supergoal routing gate

Relocated verbatim from `skills/superplan/SKILL.md` Step 5b on 2026-09-04 (docs/skill-cap-decisions.md).
superplan's Step 5b runs this gate before recommending an execution path; supergoal is the path it
gates.

### Supergoal routing gate (recommend it for the right jobs only)

Recommend **`/supergoal`** ONLY when ALL four hold:

1. **Unattended intent** — the user wants to walk away (headless `claude -p`, overnight, "keep
   going until"), or explicitly asked for an autonomous loop.
2. **Metric-climbing shape** — progress IS a machine-checkable number that must move over many
   iterations (a failing-test count, a benchmark score, a coverage ratio). Supergoal's whole
   value is tool-backed between-turn verification of that number.
3. **Zero in-plan human gates** — no AskUserQuestion decision, no operator-run apply/login, no
   classifier-gated destructive op. A headless loop STALLS FOREVER at the first one; its
   evaluator cannot answer a question or run the operator's SSO login.
4. **One coherent optimization target** — not a program of N heterogeneous close-outs. A
   close-out program's "metric" is a checklist, not a gradient; the loop adds ceremony, not
   verification.

Otherwise recommend **direct execution** (main thread, or parallel dispatch per Step 5a.4) and
KEEP supergoal's disciplines inline: run the plan's `### Metric Commands` as the completion gate
and honor the falsifiers. Mention supergoal only as the resumption vehicle if an unattended
residue emerges later.

Measured basis (a direct close-out program vs a genuine loop-shaped build, same session):
`references/run-history.md`.
