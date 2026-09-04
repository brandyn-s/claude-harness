# audit-skill — run history

Dated measurements behind the rules in SKILL.md. The rule lives in SKILL.md; the
evidence lives here.

## Origin (2026-05-24)

The test-battery was captured during the 2026-05-24 supergoal/superplan
debugging session; supergoal's `verification-hook.md` had material drift against
its code in that session, which is where D4 (references describe current code)
comes from.

## Phase 3 exists because Phase 2 findings went stale (May 2026 retro)

"Fix-batch agents 'fixed' 3 bugs that didn't exist because no one re-verified
the findings before acting." Oracle re-gating before any finding is actioned
closes that gap.

## Phase 1 — M4 and the repo-wide pass

- M4 (allowed-tools vs `requires_tools`) caught the ~12-skill `AskUserQuestion`
  consistency class surfaced by the 2026-05-28 corpus audit, plus ~125 more sites
  across the corpus.
- The repo-wide C5/C6/C7/C9/C10 pass closed the scope gap that let PR #977's 5
  sites in `bin/audit-skill.py` ship — the per-skill audit only scans the skill's
  own `scripts/` + `references/`.

## E1 — external-artifact claims (added 2026-07-03)

A rule claimed `/pr-fix` cleaned up worktree directories it never touched, a KB
topic's frontmatter claimed `/garden` owned a backlog file `/harness-prune` had
taken over three weeks earlier, and a KB entry claimed a skill (`/system-health`)
was shipped when it never existed in git history — all three survived because
nothing checked a skill against claims made about it OUTSIDE the skill's own
directory.

## I1 — live execution (added 2026-07-03)

Running `healthcheck` live surfaced a test-hermeticity bug and a stale Check-8
target path; `audit-rules`, `audit-architecture`, `pull-repos`, `pr-fix`, and
`ship-hook` each surfaced comparable live-only findings the same way, across 13
PRs merged 2026-07-03.

## Phase 2.5 — backfill (May 2026 campaign)

100% of Phase 2 findings shipped with `type: manual` paired with
`doc-fix`/`behavior-fix` labels — a contract violation that made Layer A's gate
decorative.

## Phase 3.5 — pre-action gate (May 2026 campaign)

When 8 fix-batches were dispatched against the raw
`AUDIT-TRACKERS/05-phase2-findings.md` tracker without a pre-action gate, **13 of
34 attempted fixes (38%) were against findings that had already been resolved by
parallel work**. Fix-agents redid work, consuming budget and confusing the change
record. Running `act-on` immediately before each batch drops that rate close to
zero. Full diagnosis: `_shared/oracle/ROOT-CAUSE-ANALYSIS.md`.

## Phase 4 — report subcommand (2026-05-27 self-assessment)

The hand-rolled prose-assembly that `oracle report` replaces was the source of
the "report drifted from worklist" pattern.
