# Skill body-cap decisions

Written 2026-09-04 on `feat/skill-cap-decisions`. Scope: the ten skills still over both
body caps after the 2026-09-03 trim (`scripts/token-audit.py`: 6,000-token soft body cap,
5,000-token compaction re-attach proxy; chars/4). Question per skill: is the body loaded
routinely inside working sessions (**WORKFLOW** — the cap keeps applying and the skill
should be split or slimmed), or occasionally for a report or a sweep (**PERIODIC** — size
is irrelevant; exempt)?

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
| `superplan` | WORKFLOW | 8,564 | Planning entry point for any non-trivial task. `requires_skills` of supergoal, supergoal-pause, supergoal-resume and audit-skill; interview ("after /superplan produces a plan"), refine (escalates complex prompts to it), monitor and readiness-review hand off to it; retrospective lists brainstorm → /superplan → subagent-driven-development as a known chain; `hooks/worktree-enforcement.py` allow-lists its `plans/` writes; in the install "Planning toolkit" roster and the planning-toolkit bundle. | Split: move Steps 5a.1–5a.4 (SHA attestation, plan-template sections, plan-pattern write, parallel-dispatch routing) into the existing `references/save-plan.md` and the supergoal routing gate into supergoal's own references; the body keeps Phases −1 to 4 and Step 5b — target ≤ 5,000 tokens. |
| `capture` | WORKFLOW | 8,879 | Runs at every session wrap-up: `/retro` chains `/distill` then `/capture` (retro `requires_skills`); also required by mega-capture and gather-intel; distill, recall, garden and review-learnings point at it; `bin/kb-dedup.py` and `bin/kb-entry-budget.py` exist for it; in the knowledge-ops and research-intel bundles. | Split: move Step 4c (macOS Keychain identifiers — "most captures skip this step") and the Step 5 git/PR conflict playbook (fast-forward preflight, append-vs-append, DIRTY worktree) into `references/push-flow.md`; the body keeps the write path Steps 0–5 — target ≤ 6,000 tokens. |
| `mega-distill` | WORKFLOW | 8,568 | Conditional but routine: `/retro` runs it for any compacted session (retro `requires_skills`, description "using /mega-distill and /mega-capture for compacted sessions"); mega-capture requires it; it loads inside an already-huge session, exactly where the 5,000-token compaction re-attach budget bites; knowledge-ops bundle; `bin/backup-transcripts.sh` and `rules/transcript-over-summary.md` reference it. | Split: move the four blind-spot sections into `references/queued-turn-recovery.md` and wire the bundled but unreferenced `scripts/recover_queued_turns.py` as the sweep; move Corpus Mode into `references/corpus-mode.md`; the body keeps Steps 0–3 — target ≤ 5,000 tokens. |
| `gather-claude` | PERIODIC | 10,494 | An upstream-sync report: time window "since last run" (no prior run = 30 days), Watching table reconciled run over run, "Adopted last 90d" metric, 25–50 turns in the main thread; no hook chains into it; the only `requires_skills` edge is validate-changes, which names it as the skill to re-run when platform evidence is stale; install "Research intel" roster; knowledge-ops and research-intel bundles. | exempt (`body-cap: exempt` in frontmatter) |
| `deep-dive` | PERIODIC | 9,331 | Hidden from model routing since 2026-09-04 (`disable-model-invocation: true`; explicit `/deep-dive` only), `context: fork`, 15–30 turns, "each run is independent — does NOT maintain a cumulative report"; the only `requires_skills` edge is scout-frontier (another report skill); install "Research intel" roster; knowledge-ops and research-intel bundles. | exempt (`body-cap: exempt` in frontmatter) |
| `gather-claude-endpoints` | PERIODIC | 8,279 | A data-channel drift sweep against committed baselines: numbered runs, `baseline` refresh argument, Watching triggers; 6–15 turns; the only `requires_skills` edge is its vendor sibling gather-openai-endpoints; in no install roster or bundle ("All portable skills" only). | exempt (`body-cap: exempt` in frontmatter) |
| `audit-architecture` | PERIODIC | 9,304 | `disable-model-invocation: true`; a Phase 0–7 audit that writes dated findings snapshots and a "Changes since last audit" section, 15–30 turns; no `requires_skills` edge; healthcheck runs its `doc_accuracy_audit.py` script, not the skill; pr-fix and retrospective only mention it; knowledge-ops bundle; no install roster. | exempt (`body-cap: exempt` in frontmatter) |
| `audit-skill` | PERIODIC | 8,298 | "Before shipping a skill, after a multi-file change, or as a periodic hygiene pass"; corpus mode (`--all`) and campaign trackers; the routine part is `bin/audit-skill.py --strict` in pre-commit, a script, not this body; the only `requires_skills` edge is audit-fix, which consumes its worklist; in no install roster or bundle. | exempt (`body-cap: exempt` in frontmatter) |
| `scout-frontier` | PERIODIC | 8,202 | A 15–30 turn scouting run producing a tiered findings report; persona's manifest requires it but persona only names it as a fallback suggestion; scout-skills and gather-repos point at it as a hand-off; not in any install roster; knowledge-ops and research-intel bundles. | exempt (`body-cap: exempt` in frontmatter) |
| `gather-intel` | PERIODIC | 8,378 | Scheduled: `templates/launchd/com.example.claude.gather-intel.plist` runs `claude -p "/gather-intel"` every Monday 08:30; hidden from model routing since 2026-09-04; 20–50 turns; the only `requires_skills` edge is scout-frontier; install "Research intel" roster; knowledge-ops and research-intel bundles. | exempt (`body-cap: exempt` in frontmatter) |

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
the PERIODIC set in the table above and that every WORKFLOW row still has a proposal.

Descriptions and `when_to_use` were not changed; the routing eval run against them stands.

## After exemptions (measured 2026-09-04)

| Measure | Before | After |
|---|---|---|
| Skills over the 6,000-token soft cap, counted | 25 | 18 |
| Skills over the 5,000-token compaction proxy, counted | 30 | 23 |
| Exempt skills (all seven are over both caps) | 0 | 7 |

The 18 counted skills over the soft cap: capture 8,879, garden 8,692, mega-distill 8,568,
superplan 8,564, healthcheck 8,255, retrospective 8,041, distill 7,920,
build-measurement-harness 7,724, code-explore 7,664, supergoal 7,645, audit-rules 7,424,
pr-fix 7,313, api-ingest 6,822, roundtable 6,764, review-learnings 6,622, mega-capture
6,565, gather-research 6,295, absorb 6,034. The five between the two caps: retro 5,768,
ship 5,705, agentic-actions-auditor 5,704, evaluate-repos 5,622, gather-repos 5,506. Those
outside the ten were not classified here; several (garden, healthcheck, retrospective,
audit-rules, build-measurement-harness) read as PERIODIC by the same criteria and are
candidates for the next pass.

## WORKFLOW proposals in detail

- **superplan** (8,564 → ≤ 5,000). The body already delegates Phases 2–3 to references; the
  remaining weight is Step 5a (persistence, attestation, the five required plan-template
  sections, the Goodhart artifact probe, parallel-dispatch routing, ~1,900 tokens) and the
  supergoal routing gate (~500). Move 5a.1–5a.4 into `references/save-plan.md`, which the
  body already cites for the git flow, and the routing gate into
  `skills/supergoal/references/`, leaving one paragraph in Step 5b that names the gate.
- **capture** (8,879 → ≤ 6,000). Step 4c (Keychain identifier persistence, macOS-only,
  conditional, ~900 tokens) and the Step 5 item-4 playbook for fast-forward preflight,
  append-vs-append conflicts and DIRTY PR recovery (~1,600 tokens) are recovery procedures a
  routine capture never reaches. Move both to `references/push-flow.md` and keep a two-line
  pointer at each site.
- **mega-distill** (8,568 → ≤ 5,000). The four "blind spot" sections (~2,300 tokens) all
  serve one procedure: recover mid-turn user messages the condenser drops. Move them to
  `references/queued-turn-recovery.md`, replace the inline heredoc sweep with the bundled
  `scripts/recover_queued_turns.py` (tested in `hooks/test-hooks/test_recover_queued_turns.py`,
  currently unreferenced by the body), and move Corpus Mode (~1,400 tokens, a different
  entry point) to `references/corpus-mode.md`. Steps 0–3 stay in the body.
