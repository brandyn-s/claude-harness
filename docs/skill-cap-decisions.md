# Skill body-cap decisions

Written 2026-09-04 on `feat/skill-cap-decisions`. Scope: the ten skills still over both
body caps after the 2026-09-03 trim (`scripts/token-audit.py`: 6,000-token soft body cap,
5,000-token compaction re-attach proxy; chars/4). Question per skill: is the body loaded
routinely inside working sessions (**WORKFLOW** — the cap keeps applying and the skill
should be split or slimmed), or occasionally for a report or a sweep (**PERIODIC** — size
is irrelevant; exempt)?

Second pass 2026-09-04 on `chore/skill-cap-splits`: the three WORKFLOW proposals below were
executed as verbatim relocations, and the fifteen remaining counted-over-cap skills were
classified by the same criteria (section "Next pass"). Every number in this document is a
`scripts/token-audit.py` `body_tokens_proxy` (whole SKILL.md, chars/4).

## Evidence used

- The skill's own frontmatter and body: how it says it runs, `disable-model-invocation`,
  `context`, `manifest.yaml` `estimated_turns`.
- Chaining: `requires_skills` in `skills/*/manifest.yaml` (the authoritative orchestration
  edges, per `skills/retrospective/SKILL.md`) plus every `/name` mention in `hooks/`,
  `agents/`, `rules/`, and other `SKILL.md` files, each read to tell a chain from a routing
  pointer.
- Rosters: the `install.sh` component menus (planning / security / knowledge / code-intel /
  research); `profiles/brandyn-operator/REBUILD-CHECKLIST.md` (installs the
  security-scanner, knowledge-ops and code-intelligence bundles and copies seven companion
  skills, none of them these ten); `marketplace/*/skills/` bundle membership;
  `templates/launchd/` schedules.
- Usage telemetry: none in the repo. `~/.claude/skill-usage.jsonl` was written by the
  retired keyword-routing hook (`skills/_shared/activation-eval/run_activation_eval.py`
  docstring); `skills/roundtable/skill-usage-audit.py` counts invocations from session
  transcripts that live outside the repo; the test HOME's copy holds 80 fixture records from
  the 2026-09-03 test run (refine, superplan, gather-vendor) and is not evidence. The
  decisions rest on the three sources above.

## Decisions

| Skill | Decision | Body tokens (2026-09-04) | Evidence | Action |
|---|---|---|---|---|
| `superplan` | WORKFLOW | 8,564 → 7,132 | Planning entry point for any non-trivial task. `requires_skills` of supergoal, supergoal-pause, supergoal-resume and audit-skill; interview ("after /superplan produces a plan"), refine (escalates complex prompts to it), monitor and readiness-review hand off to it; retrospective lists brainstorm → /superplan → subagent-driven-development as a known chain; `hooks/worktree-enforcement.py` allow-lists its `plans/` writes; in the install "Planning toolkit" roster and the planning-toolkit bundle. | Split done 2026-09-04 (`chore/skill-cap-splits`): Steps 5a.1–5a.4 → `references/save-plan.md`, the supergoal routing gate → `skills/supergoal/references/routing-gate.md`, Step 5b keeps one paragraph naming the gate. Still over the cap: the named sections measure 1,602 tokens, not the ~2,400 estimated, and even 8,564 − 2,400 never reached the ≤ 5,000 target. Follow-up proposal below (≈ 5,950 reachable inside the "Phases −1 to 4 stay" boundary; 5,000 is not). |
| `capture` | WORKFLOW | 8,879 → 7,614 | Runs at every session wrap-up: `/retro` chains `/distill` then `/capture` (retro `requires_skills`); also required by mega-capture and gather-intel; distill, recall, garden and review-learnings point at it; `bin/kb-dedup.py` and `bin/kb-entry-budget.py` exist for it; in the knowledge-ops and research-intel bundles. | Split done 2026-09-04: Step 4c and the Step 5 item-4 playbook → `references/push-flow.md`, two-line pointers at both sites. Still over the cap: the sections measure 1,397 tokens, not the ~2,500 estimated. Follow-up proposal below (≈ 5,800 reachable by relocating the remaining conditional gates). |
| `mega-distill` | WORKFLOW | 8,568 → 5,504 | Conditional but routine: `/retro` runs it for any compacted session (retro `requires_skills`, description "using /mega-distill and /mega-capture for compacted sessions"); mega-capture requires it; it loads inside an already-huge session, exactly where the 5,000-token compaction re-attach budget bites; knowledge-ops bundle; `bin/backup-transcripts.sh` and `rules/transcript-over-summary.md` reference it. | Split done 2026-09-04: the four blind-spot sections → `references/queued-turn-recovery.md` with the inline heredoc replaced by the bundled `scripts/recover_queued_turns.py` (now invoked from Step 1 as the required post-condense sweep); Corpus Mode → `references/corpus-mode.md`; Steps 0–3 stay. Under the soft cap; 504 tokens over the 5,000 proxy (three pointers + the sweep block). |
| `gather-claude` | PERIODIC | 10,494 | An upstream-sync report: time window "since last run" (no prior run = 30 days), Watching table reconciled run over run, "Adopted last 90d" metric, 25–50 turns in the main thread; no hook chains into it; the only `requires_skills` edge is validate-changes, which names it as the skill to re-run when platform evidence is stale; install "Research intel" roster; knowledge-ops and research-intel bundles. | exempt (`body-cap: exempt` in frontmatter) |
| `deep-dive` | PERIODIC | 9,331 | Hidden from model routing since 2026-09-04 (`disable-model-invocation: true`; explicit `/deep-dive` only), `context: fork`, 15–30 turns, "each run is independent — does NOT maintain a cumulative report"; the only `requires_skills` edge is scout-frontier (another report skill); install "Research intel" roster; knowledge-ops and research-intel bundles. | exempt (`body-cap: exempt` in frontmatter) |
| `gather-claude-endpoints` | PERIODIC | 8,279 | A data-channel drift sweep against committed baselines: numbered runs, `baseline` refresh argument, Watching triggers; 6–15 turns; the only `requires_skills` edge is its vendor sibling gather-openai-endpoints; in no install roster or bundle ("All portable skills" only). | exempt (`body-cap: exempt` in frontmatter) |
| `audit-architecture` | PERIODIC | 9,304 | `disable-model-invocation: true`; a Phase 0–7 audit that writes dated findings snapshots and a "Changes since last audit" section, 15–30 turns; no `requires_skills` edge; healthcheck runs its `doc_accuracy_audit.py` script, not the skill; pr-fix and retrospective only mention it; knowledge-ops bundle; no install roster. | exempt (`body-cap: exempt` in frontmatter) |
| `audit-skill` | PERIODIC | 8,298 | "Before shipping a skill, after a multi-file change, or as a periodic hygiene pass"; corpus mode (`--all`) and campaign trackers; the routine part is `bin/audit-skill.py --strict` in pre-commit, a script, not this body; the only `requires_skills` edge is audit-fix, which consumes its worklist; in no install roster or bundle. | exempt (`body-cap: exempt` in frontmatter) |
| `scout-frontier` | PERIODIC | 8,202 | A 15–30 turn scouting run producing a tiered findings report; persona's manifest requires it but persona only names it as a fallback suggestion; scout-skills and gather-repos point at it as a hand-off; not in any install roster; knowledge-ops and research-intel bundles. | exempt (`body-cap: exempt` in frontmatter) |
| `gather-intel` | PERIODIC | 8,378 | Scheduled: `templates/launchd/com.example.claude.gather-intel.plist` runs `claude -p "/gather-intel"` every Monday 08:30; hidden from model routing since 2026-09-04; 20–50 turns; the only `requires_skills` edge is scout-frontier; install "Research intel" roster; knowledge-ops and research-intel bundles. | exempt (`body-cap: exempt` in frontmatter) |

## Next pass (2026-09-04, `chore/skill-cap-splits`)

The fifteen skills that were counted over the soft cap after the first pass, classified by
the same criteria. Body tokens are measured before the exemption lines or the split; the
arrow gives the post-split figure where a split was executed. Executed splits are verbatim
relocations into `references/` with a pointer at each cut site; a proposal is executed only
when it is such a relocation and the skill's own tests stay green.

| Skill | Decision | Body tokens (2026-09-04) | Evidence | Action |
|---|---|---|---|---|
| `garden` | PERIODIC | 8,692 | Scheduled: `templates/launchd/com.example.claude.garden.plist` runs `claude -p "/garden"`; a KB curation sweep with an `audit` dry-run mode, 15–30 turns; no `requires_skills` edge into it; capture and distill only name it as the later curation pass. | exempt (`body-cap: exempt` in frontmatter) |
| `healthcheck` | PERIODIC | 8,255 | An on-demand hygiene report: Check 0–13 → `## Report`, 5–15 turns, `side_effects: none`; no `requires_skills` edge into it; the only mention (`hooks/skill-ref-validator.py`) is an incident note, not a chain. | exempt (`body-cap: exempt` in frontmatter) |
| `retrospective` | PERIODIC | 8,041 | A multi-session review report over a time window (`[48h] [focus-domain]`, trigger "weekly review"); Pass 5 reads the previous retrospective; 30–60 turns; no `requires_skills` edge into it. | exempt (`body-cap: exempt` in frontmatter) |
| `audit-rules` | PERIODIC | 7,424 | `disable-model-invocation: true`; its "When to Run" section says "Monthly or quarterly as a health check" and after adding rules or hooks; 8–15 turns; its only edge is outbound (validate-changes); `hooks/bash-security-guard.py` cites its past findings, not the skill. | exempt (`body-cap: exempt` in frontmatter) |
| `build-measurement-harness` | PERIODIC | 7,724 | "Use at the start of any new measurement project" — a once-per-project ten-phase bootstrap, 20–50 turns; no `requires_skills` edge into it; in no install roster, bundle, or schedule. | exempt (`body-cap: exempt` in frontmatter) |
| `roundtable` | PERIODIC | 6,764 | An occasional multi-model adversarial review run (`--max-rounds`, `--budget USD`; Step 4 outputs a consolidated report), 15–40 turns; no `requires_skills` edge into it; the only mention is an incident write-up. | exempt (`body-cap: exempt` in frontmatter) |
| `review-learnings` | PERIODIC | 6,622 | `disable-model-invocation: true`; a memory audit-and-prune sweep, 15–40 turns; `hooks/session_start_modules/consistency.py` prints "Memory review overdue: /review-learnings last run …" — a periodic reminder, not a chain; no `requires_skills` edge into it. | exempt (`body-cap: exempt` in frontmatter) |
| `gather-research` | PERIODIC | 6,295 | `disable-model-invocation: true`; Step 0 "Review Previous Run Actions" reconciles run over run, 30–60 turns; the only `requires_skills` edge is scout-frontier (a report skill); install "Research intel" roster — the same shape as the exempted gather-claude. | exempt (`body-cap: exempt` in frontmatter) |
| `absorb` | PERIODIC | 6,034 | `/absorb [github-username]`: a 30–60-turn study of one builder's repos and PRs ending in a KB artifact and PR; no `requires_skills` edge into it; in no install roster, bundle, or schedule; the mentions are an incident note and a rubric manifest. | exempt (`body-cap: exempt` in frontmatter) |
| `distill` | WORKFLOW | 7,920 | Session wrap-up step: `/retro` chains `/distill` then `/capture` (retro `requires_skills`); required by mega-distill and roundtable; install "Knowledge ops" roster; 10–20 turns inside working sessions. | Proposal, not executed: move Step 1b Collect Session Metrics (the definitions table plus the two over-count incidents, 1,036 tokens) to `references/session-metrics.md` and Step 5's writer-invocation detail (596) to `references/coordination-marker.md` → ≈ 6,400 with pointers; reaching ≤ 6,000 also needs the 681-token Success Criteria list condensed, which is a rewrite, not a relocation — next pass. |
| `code-explore` | WORKFLOW | 7,664 → 5,374 | An everyday code-search step (`effort: low`, 3–10 turns): required by verify-search-result, routed to by `rules/search-efficiency.md`, install "Code intel" roster. | Split done 2026-09-04: Step 1.6 (Identification recipe) → `references/service-module-identification.md`; Graph Query Quick Reference + Deep Architecture Review → `references/graph-query-quick-reference.md`; Step 1.5 (broad/audit queries) stays. |
| `supergoal` | WORKFLOW | 7,645 | The execution path superplan's routing gate hands to: inbound `requires_skills` from supergoal-pause, supergoal-resume, superplan-loop and superplan-status; 10–100+ turn loops, where the compaction re-attach budget bites. 1,729 of its tokens are the frontmatter `type:agent` Stop-hook prompt, which is not body text and cannot move. | Proposal, not executed: Key design choices (732) → `references/design-rationale.md`; Completion checklist (307) → `references/completion-checklist.md`; the two Step 1 incident warnings (same-surface probe, non-executable metric_commands, ≈ 630) → the existing `references/plan-parsing.md` → ≈ 6,100 with pointers. ≤ 6,000 additionally needs Composition with superplan + Substrate detection (304) moved, or the audit to stop counting frontmatter toward the body — a reviewer decision, so next pass. |
| `pr-fix` | WORKFLOW | 7,313 | Session-start modules (`repo_sync.py`, `stale_config_checkout.py`) and `rules/git-hygiene.md` / `rules/worktree-by-default.md` route to it; "fix CI", "stuck PRs" are working-session asks; 10–30 turns. | Proposal, not executed: the two Phase 3-ready sub-sections (deploy-trigger check 740 + UNSIGNED and merge-policy diagnosis 1,051) → `references/merge-gates.md` ≈ 5,620 with a pointer. Blocked for this pass because `tests/test_skill_contract.py` pins the merge-policy `AskUserQuestion` / `one-off` text to SKILL.md and the deploy-trigger check is a safety gate: the relocation needs a deliberate test change and sign-off. |
| `api-ingest` | WORKFLOW | 6,822 → 5,731 | `rules/api-doc-lookup.md` step 4 routes to `/api-ingest` inside coding sessions when an API's docs are not indexed; 8–15 turns; `agents/README.md` and the api-doc-lookup incidents point at it. | Split done 2026-09-04: Phase 0c concept-page probe → `references/concept-page-probe.md`; recipes 2a–2e → `references/source-conversion.md`; the 0c and 2a–2e labels that Phase 1's table and Phase 3 cite are kept in the pointers. |
| `mega-capture` | WORKFLOW | 6,565 → 5,993 | `/retro` requires it for compacted sessions (retro `requires_skills`); it requires capture, mega-distill and ship; 8–20 turns inside an already-huge session. | Split done 2026-09-04: the core-principle rationale and the non-goals list → `references/coverage-principle.md`, with a pointer paragraph stating the invariant. Marginal: 7 tokens under the soft cap; the next growth pushes it back over. |

## How the exemption works

A PERIODIC skill carries, in its `SKILL.md` frontmatter:

```yaml
metadata:
  body-cap: exempt
  body-cap-reason: "PERIODIC: <one line saying how it runs>"
```

`scripts/token-audit.py` still measures and lists the skill (`body_tokens_proxy`,
`over_soft_body_cap`, `over_compaction_reattach_proxy` are unchanged per row) and adds
`body_cap` (`applies` / `exempt` / `exempt-missing-reason`) and `body_cap_reason`. The
corpus totals `skills_over_soft_body_cap` and `skills_over_compaction_reattach_proxy`
exclude exempt rows; `skills_body_cap_exempt`, `skills_over_soft_body_cap_exempt` and
`skills_over_compaction_reattach_proxy_exempt` count them separately, and the text report
names them. An exemption without a reason is reported as `exempt-missing-reason` and keeps
counting against the caps. `scripts/test_token_audit.py` pins that the exempt set equals
the PERIODIC set across both tables above, that every WORKFLOW row still over the cap
carries a proposal, and that every WORKFLOW row under the cap records its executed split
("Split done").

`scripts/validate-skills.py` does not read the exemption: its C1_length (≤ 510 lines) and
C1b_token_budget (≤ 4,000 body tokens after frontmatter, since the compaction-continuity
banner escape was retired 2026-09-03) keep applying to every skill.

Descriptions and `when_to_use` were not changed in either pass; the routing eval run against
them stands.

## Measurements (2026-09-04)

| Measure | Before | After first pass (exemptions) | After second pass (splits + exemptions) |
|---|---|---|---|
| Skills over the 6,000-token soft cap, counted | 25 | 18 | 5 |
| Skills over the 5,000-token compaction proxy, counted | 30 | 23 | 14 |
| Exempt skills (all of them are over both caps) | 0 | 7 | 16 |
| `validate-skills.py` C1_length failures | 9 | 9 | 7 |
| `validate-skills.py` C1b_token_budget failures | 36 | 36 | 36 |

First pass, for the record — the 18 counted skills over the soft cap before the splits:
capture 8,879, garden 8,692, mega-distill 8,568, superplan 8,564, healthcheck 8,255,
retrospective 8,041, distill 7,920, build-measurement-harness 7,724, code-explore 7,664,
supergoal 7,645, audit-rules 7,424, pr-fix 7,313, api-ingest 6,822, roundtable 6,764,
review-learnings 6,622, mega-capture 6,565, gather-research 6,295, absorb 6,034.

Second pass — the 5 counted skills over the soft cap: distill 7,920, supergoal 7,645,
capture 7,614, pr-fix 7,313, superplan 7,132. The nine between the two caps: mega-capture
5,993, retro 5,768, api-ingest 5,731, ship 5,705, agentic-actions-auditor 5,704,
evaluate-repos 5,622, gather-repos 5,506, mega-distill 5,504, code-explore 5,374. retro,
ship, agentic-actions-auditor, evaluate-repos and gather-repos are under the soft cap and
were not classified. The exemption lines add about 45 tokens to each exempt skill (garden
8,692 → 8,739, and so on); the audit still lists every exempt row.

C1b did not move in either pass: its threshold is 4,000 body tokens, and no relocation
proposed here targets that (the doc caps are 6,000 / 5,000). Skills whose split took them
under 510 lines cleared C1_length (mega-distill 529 → 321, api-ingest 534 → 453).

## WORKFLOW proposals in detail

Executed 2026-09-04 (`chore/skill-cap-splits`), each as one commit, measured with
`scripts/token-audit.py` before and after:

- **superplan** (8,564 → 7,132; target ≤ 5,000 not reached). Steps 5a.1–5a.4 (persistence
  attestation, the five required plan-template sections, the Goodhart artifact probe,
  parallel-dispatch routing) moved verbatim into `references/save-plan.md`, which the body
  already cited for the git flow; the supergoal routing gate moved verbatim into
  `skills/supergoal/references/routing-gate.md`, and Step 5b keeps one paragraph naming the
  gate and its four conditions. The sections measured 1,249 + 353 = 1,602 tokens, not the
  ~1,900 + ~500 estimated, and the estimate itself (8,564 − 2,400 = 6,164) never reached
  5,000 — the target was inconsistent with the proposal. **Follow-up (next pass):** relocate
  Phase 0's "What to verify" table + report format (374) into the existing
  `references/phase-0-preflight.md`, Phase 4's "Refresh-then-decide framing" (510) into
  `references/phase-4-construction.md`, and Phase 6 Re-Plan (178) + Step 5c's quick-reference
  bullets (236) into `references/execution-discipline.md` → ≈ 5,950. Getting to 5,000 means
  moving part of Phase 4's mandatory "Plan structure" block (1,081) — a content decision the
  first pass said to keep.
- **capture** (8,879 → 7,614; target ≤ 6,000 not reached). Step 4c (Keychain identifier
  persistence, 656 tokens) and the Step 5 item-4 playbook (fast-forward preflight,
  append-vs-append conflicts, DIRTY PR recovery, 741 tokens) moved verbatim to
  `references/push-flow.md` (the playbook's list indentation removed), with a two-line
  pointer at each site; the worktree `--delete-branch` note stayed because the proposal did
  not name it. The sections measured 1,397 tokens, not the ~2,500 estimated. **Follow-up
  (next pass):** relocate the remaining conditional gates — Step 0 item 4's stale-work
  worktree procedure (≈ 475) and the `--delete-branch` note (127) into `push-flow.md`, the
  `kb-dedup.py` fallback (≈ 310) into `references/tuning-notes.md`, the broken-frontmatter
  recovery (≈ 125) into `references/topic-format.md`, and Steps 4a.1 + 4a.2 (resolution sweep
  389, Current-understanding regeneration 502, both conditional on fix sessions or evergreen
  pages) into a new `references/write-gates.md` → ≈ 5,800.
- **mega-distill** (8,568 → 5,504; target ≤ 5,000 missed by 504). The four "blind spot"
  sections (1,918 tokens) moved verbatim to `references/queued-turn-recovery.md`, with the
  inline heredoc sweep replaced by the bundled `scripts/recover_queued_turns.py` (tested in
  `hooks/test-hooks/test_recover_queued_turns.py`), which Step 1 now invokes as the required
  post-condense sweep; Corpus Mode (1,653 tokens) moved verbatim to
  `references/corpus-mode.md`. Steps 0–3 stay. The residue over 5,000 is the three pointers
  and the sweep block; the next candidate is the corpus-mode bullet in Success Criteria.
- **code-explore** (7,664 → 5,374). Step 1.6 Service/Module Identification (1,329) →
  `references/service-module-identification.md`; Graph Query Quick Reference + Deep
  Architecture Review (1,169) → `references/graph-query-quick-reference.md`.
- **api-ingest** (6,822 → 5,731). Phase 0c concept-page probe (770) →
  `references/concept-page-probe.md`; recipes 2a–2e (523) → `references/source-conversion.md`.
- **mega-capture** (6,565 → 5,993, marginal). Core-principle rationale (467) + non-goals
  (216) → `references/coverage-principle.md`.

Proposed for the next pass (see the table for the blocking reason on each):

- **distill** (7,920 → ≈ 6,400 by relocation; ≤ 6,000 needs a Success Criteria rewrite).
- **supergoal** (7,645 → ≈ 6,100 by relocation; the 1,729-token frontmatter hook prompt is
  the structural residue).
- **pr-fix** (7,313 → ≈ 5,620 by relocating the two Phase 3-ready gates; needs a deliberate
  `test_skill_contract.py` change and sign-off first).
