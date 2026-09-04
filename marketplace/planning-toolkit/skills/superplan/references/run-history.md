# superplan — run history

Dated incidents behind the rules in SKILL.md. The rule lives in SKILL.md; the
evidence lives here.

## Refresh-then-decide framing (INCIDENT 2026-05-10, Phase G assetman override)

The parent plan framed Lever 1 as "ship `{"assetman/":20}` based on 2026-05-09
CI." Refresh was Phase A1, BUT the framing implied "Phase G ships, Phase A is the
verification side-check." On execution, refreshed CI showed assetman CI now
includes zero — the original ship intent was dead. The falsifier-driven design
correctly handled this (Phase G dropped), but the FRAMING burned conversational
confidence on a measurement that hadn't been re-validated yet. Correct framing
would have been "Phase A refreshes CI; Phase G fires IF CI still excludes zero.
Default expectation: undetermined."

## Falsifier format and readiness self-check

- 2026-08-24: a `## Falsifiers` table parsed as zero falsifiers and
  `parse_plan.py` exited 20; the pre-commit dry-run is what catches it.
- 2026-06-21: a mega-capture plan deviated from the template (prose
  `## Verification`, bolded `**Demo:**`) and failed only at supergoal parse-time;
  the parser was made tolerant in #1416 and the readiness dry-run was added.

## Metric blocks must `git fetch` (2026-08-24)

`librechat_confluence_config_sites` still printed **0** after its PR merged —
local `origin/main` was `fa87c87b`, actual was `a0a9bbc8`; adding
`git fetch origin main -q` to the top of the block made the same command print
**2** with no other change.

## Supergoal routing gate (2026-08-23)

A 7-phase close-out program executed directly hit FOUR moments a headless loop
could not have crossed (a user policy decision, two classifier denials requiring
operator handoff, an SSO expiry) — while the inline metric gate still verified
completion. The same session's zero-ceremony build, by contrast, was a genuine
supergoal shape (one demo metric, no human gates) and ran under the loop's hook.
Both routings were right; offering the loop for both would not have been.

## Pattern provenance

Several Step 5a conventions were adapted from external playbooks: the SHA-256
attestation from `OthmanAdi/planning-with-files` (`/plan-attest`), Metric/Guard
Commands from `autoresearch` (v2's lesson: conflating them lets the model succeed
by regressing tests), the Artifact Probe from an mpt.solutions Goodhart's-Law
post (`/goal` shipped a 960×540 space shooter with 3 starfield pixels because
conversation-eval passed), Forbidden Actions from Devin playbooks, the
parallelization check from `evanflow/skills/evanflow-writing-plans` and
`obra/superpowers/skills/dispatching-parallel-agents`, scoped sub-task context
from the Roo Code Boomerang convention, and Phase 4c from tobihagemann/turbo's
`/capture-context`.
