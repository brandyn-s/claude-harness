# Implementation status — docs/plans/ catalog

> Snapshot 2026-06-10 (B11 documentation review). One row per plan so a dead
> plan is discoverable as dead. Verdicts: **SHIPPED** (implementation exists —
> evidence named), **PARTIAL** (some tasks landed, named gaps remain),
> **DEAD** (no trace of implementation), **BLOCKED** (waiting on an external
> dependency or owner decision). Add a row when you add a plan; flip a verdict
> in place when reality changes.

| Plan | Topic | Verdict | Evidence |
|------|-------|---------|----------|
| 2026-02-25-recall-and-superplan-kb.md | /recall skill + KB Phase 2c | SHIPPED | `skills/recall/` exists; memory-search MCP integration live |
| 2026-03-03-architecture-improvements.md | 8 arch improvements | PARTIAL | Hooks, agents, drift gates shipped; B1/B2/B5 open DECIDE items remain |
| 2026-03-03-generic-agent-architecture-design.md | Agent layer design | SHIPPED | Single-worker + topic-loading in `agents/worker.md` |
| 2026-03-03-retrospective-impl-plan.md | /retrospective skill | SHIPPED | `skills/retrospective/` exists |
| 2026-03-03-retrospective-skill-design.md | Retrospective design spec | SHIPPED | Design implemented in `/retrospective` SKILL.md |
| 2026-03-04-architecture-streamlining.md | Hook overhead reduction | PARTIAL | Dispatcher consolidation done; guard-consolidation PR pending (B1/F2) |
| 2026-03-04-claude-code-red-team-design.md | Red team assessment | SHIPPED | Assessment completed; findings catalogued in AUDIT-FINDINGS.md |
| 2026-03-04-red-team-remediation-plan.md | Red team fixes | PARTIAL | HIGH items closed; long-tail tracked through B7/B9 |
| 2026-03-04-research-intelligence-update.md | Research findings implementation | SHIPPED | Changes integrated and validated per plan |
| 2026-03-04-retrospective-fixes.md | First /retrospective issues | SHIPPED | Hook noise, retry metric, session dedup fixes landed |
| 2026-03-08-retro-deficiency-fixes.md | 48h retrospective fixes | SHIPPED | WebSearch enforcement, ToolSearch, auto-learn fixes |
| 2026-03-08-skill-auto-dispatch.md | Agent dispatch + worktrees | SHIPPED | `rules/agent-delegation.md`; worktree-default isolation in place |
| 2026-03-09-weekly-update-skill-design.md | a separate skill (not included in this export) skill design | SHIPPED | a separate skill (not included in this export) exists per design spec |
| 2026-03-10-changelog-alignment.md | v2.1.51–2.1.63 doc fixes | SHIPPED | ARCHITECTURE aligned; drift gate prevents recurrence |
| 2026-03-12-adversarial-validation-template.md | Validation template | SHIPPED | Adversarial-validation reference used by security skills |
| 2026-03-12-harden-skill-and-distill-t0.md | /harden skill + distill T0 tier | PARTIAL | /distill has T0 tier; **/harden skill DEAD** (`skills/harden/` does not exist) |
| 2026-03-12-retire-component-hardening.md | Retire skill, extract primitives | SHIPPED | Skill retired; STIG pipeline absorbed primitives |
| 2026-03-14-claude-monitoring-routing.md | a separate skill (not included in this export) routing | SHIPPED | a separate skill (not included in this export) + topic routing implemented |
| 2026-03-18-cklb-evidence-verification.md | STIG evidence verification | SHIPPED | a separate skill (not included in this export) implements 3-layer verification |
| 2026-03-18-retro-p0-p1-fixes.md | P0/P1 closing (Mar 16–18) | SHIPPED | Auto-stash, auto-merge, error classifier expanded |
| 2026-03-18-sca-review-impl-plan.md | a separate skill (not included in this export) skill | RETIRED | Non-runnable prototype removed; historical design archived under `docs/archive/sca-review/` |
| 2026-03-18-sca-review-skill-design.md | SCA review methodology | ARCHIVED | Historical design only; no active skill or product claim |
| 2026-03-18-stig-assess-restructure.md | a separate skill (not included in this export) restructure | SHIPPED | Paths fixed, reference data consolidated, evidence verification added |
| 2026-03-20-v2180-leverage-and-retest.md | v2.1.80 upstream retest + features | SHIPPED | Subagent bugs retested; `effort` frontmatter adopted; StopFailure hook added |
| 2026-03-21-friction-reduction-p0-p1.md | 6 highest-impact friction sources | PARTIAL | WebSearch enforcement + ToolSearch done; MEMORY.md churn open (B7) |
| 2026-03-21-github-friction-reduction.md | GitHub interaction friction | PARTIAL | Hook consolidation done; multi-PR parallel dispatch blocked on upstream #43772 |
| 2026-03-21-retro-gap-fixes.md | Retrospective P2/P3 gaps | PARTIAL | Most closed; remaining skill gaps catalogued in B8 reports |
| 2026-03-22-skill-optimization.md | Skill quality improvements | PARTIAL | Manifest coverage improved; eval coverage still partial (B8 eval backlogs) |
| 2026-03-23-code-graph-property-extraction.md | code-graph Q10 property fix | DEAD | No commit in code-graph references the plan's per-language Q10 fixes (checked 2026-06-10); the extraction infrastructure it cites predates the plan |
| 2026-03-23-code-search-code-graph-optimization.md | Code search optimization | PARTIAL | Hybrid search works; code-graph accuracy harness tracked in B8d |
| 2026-03-24-skill-tool-integration-followup.md | Tool integration follow-ups | PARTIAL | MCP integration ongoing; B12 add-a-server checklist now covers the gap |
| 2026-03-26-community-repo-adoption.md | Community pattern adoption | SHIPPED | /gather-repos, /evaluate-repos, assessed-repos.md maintained |
| 2026-03-27-retro-opportunities.md | Retrospective opportunities | PARTIAL | Absorb-sessions + cross-repo patterns shipped; others open |
| 2026-03-28-anti-pattern-remediation-v2.md | Anti-pattern fixes v2 | PARTIAL | Prompt-injection defenses added; rule-compliance measurement open (B5) |
| 2026-03-28-anti-pattern-remediation.md | Anti-pattern fixes v1 | SHIPPED | Initial anti-patterns remediated; v2 carried the rest |
| 2026-04-29-research-findings-implementation.md | Research frontier integration | SHIPPED | `skills/scout-frontier/`, /deep-dive, research skills implemented |
| 2026-05-23-goal-vs-orchestration-eval-design.md | Goal vs orchestration eval | BLOCKED | Design ready; execution blocked on parallel-subagent instability (#64774) |
| 2026-05-31-guard-obsolescence-evaluation.md | Guard consolidation evaluation | BLOCKED | Evaluation done (B1/F2); implementation waits on the B2/F4 fail-posture owner decision |
