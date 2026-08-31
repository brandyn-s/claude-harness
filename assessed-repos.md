# Community Repo Assessments

Ledger for `/gather-repos`. Re-check entries >90 days old with new commits.

## Assessed

### [inventoried] kriegcloud/beep-effect (2026-04-05)
- 46* | 4 hooks (shell→TS via Bun), skills (Effect-TS), policies | Effect-TS monorepo config
- Found by: Q1 (permissionDecision), score 5/6
- Per-bucket:
  - Hooks(4): agent-init (SessionStart: Effect agent init via Bun), skill-suggester (UserPromptSubmit: suggest skills), pattern-detector (Pre/PostToolUse: architectural pattern detection), subagent-init (PreToolUse:Task: specialized subagent prompts).
  - Rules(0): No rules/ directory.
  - Skills(3 read): effect-concurrency-testing (fiber coordination, PubSub/Deferred/Latch), mcp-playwright (headless browser automation with smoke test gate), mcp-jetbrains (IDE integration via MCP).
  - Agents(0 .md): Policies instead — core.json (immutable reliability, max 3 skills/6 facts/2200 chars), adaptive.json (per-category routing for web/CLI/package).
  - Config: SessionStart→agent-init, UserPromptSubmit→skill-suggester, Pre/PostToolUse→pattern-detector. Plugins: serena, claude-supermemory.
  - Memory(0): No memory directory.

### [inventoried] hatch3r/hatch3r (2026-04-05)
- 19* | 0 real hooks (placeholder echo commands), 1 skill | Documentation automation harness
- Found by: Q1 (permissionDecision) + background screen, score 5/6
- Per-bucket:
  - Hooks(0 real): settings.json has echo placeholders for SubagentStart, PreToolUse:Bash, PostToolUse:Write, SessionStart. No hook scripts.
  - Rules(0): No rules/ directory.
  - Skills(1): docusaurus-generator (5-step doc site generation with i18n support).
  - Agents(0): No agents/ directory.
  - Config: Permissions allow Read/Edit/Write/Grep/Glob/LS/TodoRead/TodoWrite. Teammate mode: tool-using.
  - Memory(0): No memory directory.

### [inventoried] philoserf/claude-code-setup (2026-04-05)
- 11* | 9 hooks, 10 rules, 3+ skills, 2 agents, memory | Comprehensive personal CC template
- Found by: Exa code search + background screen, score 5/6
- Per-bucket:
  - Hooks(9): auto-format.sh (PostToolUse: gofmt+prettier), prompt-injection-guard.py (PreToolUse: injection pattern scan, advisory), config-protection.sh (blocks sensitive file edits), context-monitor.sh (session context size warnings), load-session-context.sh (SessionStart: prior decisions), validate-bash-commands.py (PreToolUse: shell syntax validation), stale-branch-guard.sh, statusline-command.sh, log-event.sh.
  - Rules(10): bash.md (shellcheck/shfmt, set -euo pipefail), git.md (feature branches, atomic commits, conventional format), go.md, python.md, markdown.md, test-failures.md, long-running-tasks.md, images.md, pdf.md, research-first.md.
  - Skills(3): cc-review (6-dimension quality scoring: Effectiveness 28%, Clarity 22%, Best Practices 17%, Documentation 15%, Verification 10%, Trigger Coverage 8%, tier classification Production/Good/Needs Work/Poor/Unusable, P1-P5 recommendations), fix-issue (plan→PRD→approval gate→branch→implement→test→ship), md-improve (conversation pattern analysis → CLAUDE.md improvement proposals).
  - Agents(2): code-reviewer (severity tiers CRITICAL/HIGH/MEDIUM/LOW, language-specific checks Go+TS, model:sonnet maxTurns:15), loop-operator (scheduled/one-time/ad-hoc recurring commands).
  - Config: Hook registrations for all 9 hooks. Taskfile.yml for orchestration.
  - Memory: state/cc-release-review-version.txt (version continuity).

### [inventoried] robomello/claude-code-setup (2026-04-05)
- 0* | 12 hooks, 5 rules, 14 skills, 30 agents | Heavy orchestration with human-in-loop
- Found by: Exa + background screen, score 5/6
- Per-bucket:
  - Hooks(12): archive_plan.sh (archives PLAN.md with timestamps), telegram_confirm.py (Telegram notification for human confirmation, 310s timeout), docker-compose-enforcer.sh (validates compose before Bash), doc-file-blocker.sh (blocks .doc/.docx writes), pre-edit.sh (path/permission validation), review_plan.sh (multi-agent plan review), review_on_exit_plan.sh (consensus review on plan exit), review_code.sh (auto code review trigger), printwalk-session.sh (full session execution logging), geo-check.sh (geographic restriction check), post_tool_router.sh (routes to monitoring), comfyui-logger.sh (ComfyUI usage logging).
  - Rules(5): planning.md (MANDATORY 5-phase: Plan→Review→Final Check→Present→Execute, Dependencies First for Docker, <20 lines skip), quality-gates.md (security checklist, code-reviewer enforcement for multi-file changes), agent-behavior.md (autonomy norms, error recovery), context.md (context window management, memory loading order), skill-vs-agent.md (decision framework: agents for autonomous, skills for guided).
  - Skills(14): cost-estimate, systematic-debugging, skill-creator, remember, pdf, disk-cleanup, frontend-design, interface-design, local-image-gen, youtube-analyzer, copywriting, content-idea-generator, etsy-browser, nest-control.
  - Agents(30): boris-style specialists (code-reviewer, security-reviewer, plan-agent, deploy-agent) + domain agents (telegram-agent, slack-agent, youtube-analytics-agent, youtube-seo-agent, youtube-uploader-agent, etsy-agent, elevenlabs-agent, suno_agent, etc).
  - Config: bypassPermissions, OTEL telemetry (127.0.0.1:4318), agent teams enabled. PreToolUse: docker-compose-enforcer + telegram_confirm (310s). PostToolUse: geo-check + comfyui-logger + post_tool_router.
  - Memory(0): No dedicated memory bucket; context via rule files.

### [inventoried] laurigates/claude-plugins (2026-04-05)
- 23* | 0 dedicated hooks, 18 rules, 300+ plugin skills, agents in plugins | Plugin architecture with comprehensive CC reference docs
- Found by: Q1 (permissionDecision) + background screen, score 5/6
- Per-bucket:
  - Hooks(0): No dedicated hooks directory. Hooks defined inline in settings or per-plugin.
  - Rules(18): agent-development.md (agent .md spec: frontmatter, tools, isolation, memory scopes user/project/local, agent teams), hooks-reference.md (comprehensive event reference: SessionStart through SubagentStop, timeouts), skill-quality.md (<500 lines, REFERENCE.md for detail, positive guidance style), prompt-agent-hooks.md (type: "prompt"/"agent"/"http" hooks), agentic-permissions.md (granular tool permissions), handling-blocked-hooks.md (hook failure debugging), plugin-structure.md (dir layout), conventional-commits.md, release-please.md, sandbox-guidance.md, shell-scripting.md, skill-development.md, skill-execution-structure.md, skill-fork-context.md, skill-naming.md, regression-testing.md, agentic-optimization.md, auto-mode.md.
  - Skills(300+): Plugin-packaged skills across domains (accessibility, agent-patterns, api, code-quality, communication, etc).
  - Agents: Embedded per-plugin, following agent-development.md spec.
  - Config: WebFetch domain allowlist (agentic-patterns.com), MCP tool allowlist (chrome-devtools, context7, github, playwright, sequential-thinking), enableAllProjectMcpServers: true, agent teams enabled.
  - Memory(0): Implicit via rules; no explicit memory buckets.

### [inventoried] llcoolblaze/claude-boris (2026-04-05)
- 26* | 3 hooks (inline), 0 rules dir, 1 skill, 15 agents, 6 memory files | Boris Cherny workflow with master orchestrator
- Found by: Q3 (never+incident+rules), score 4/6
- Per-bucket:
  - Hooks(3 inline): PostToolUse:Edit/Write (prettier --write auto-format), PreToolUse:Bash (audit command logging to .claude/audit/commands.log), PreToolUse:Edit/Write (audit file logging to .claude/audit/files.log).
  - Rules(0): No rules/ directory. Rules embedded in agent descriptions.
  - Skills(1): boris-workflow (UNDERSTAND→PLAN→EXECUTE→VERIFY→SHIP methodology, verification checklist: tests/TypeScript/lint/build/simplification/docs/CLAUDE.md, agent selection guide).
  - Agents(15): boris.md (master orchestrator: 5-phase workflow, delegates to 7 specialists via Task tool, plan approval gate), test-writer.md (AAA pattern, behavior-not-implementation, mock externals, unit+integration), pr-reviewer.md (security blockers/correctness/quality/style severity tiers), code-architect.md, code-simplifier.md, verify-app.md, audit-logger.md, ci-integrator.md, doc-generator.md, git-guardian.md, issue-tracker.md, memory-bank.md, mode-controller.md, oncall-guide.md, security-auditor.md.
  - Config: Granular Bash allowlist (git/gh/npm/node/bun/pnpm/yarn/deno/standard utils/docker/cargo/go/python/ruby), deny list (rm -rf /, chmod 777 recursive, piped curl to shell, force-push main, secret file reads .env/.pem/.key/.aws/.ssh). Env: BORIS_MEMORY_BANK=true, BORIS_AUDIT_LOG=true.
  - Memory(6): activeContext.md (current session focus), conventions.md (project patterns), decisionLog.md (decisions + rationale), progress.md (work status), projectContext.md (architecture overview), sessionHistory.md (cross-session learnings).

## Skill Ideas Backlog (from scout-skills)

Future skills to build, sourced from community pattern mining:

- **linear-issue-analysis** — Systematically fetch ALL context (issue + comments + images + linked PRs + related issues + effort estimate) before starting work on a Linear ticket. Source: n8n-io/n8n `linear-issue` skill. (2026-04-06)
- **ticket-craft** — INVEST+C ticket writing: treat tickets as prompts for AI execution. Combine with jwilger ticket-triage (readiness gate). Source: alinaqi/claude-bootstrap `ticket-craft` + jwilger/eventcore `ticket-triage`. (2026-04-06)
- **mutation-testing** — Verify test quality by systematically mutating production code. Option B (reference file) or Option C (standalone skill). Primary reference: alexanderop/workoutTracker `mutation-testing` (trust=9.4, bench=90) — has priority-ordered operators (5 tiers), execution workflow, WEAK/STRONG examples, summary template. Secondary: citypaul/dotfiles `mutation-testing`. (2026-04-06, updated 2026-04-08)
- **context-budget-audit** — Audit Claude Code context window token consumption across agents, skills, MCP servers, and rules. Estimates overhead (words x 1.3, ~500 tokens/MCP tool), classifies components as always/sometimes/rarely needed, produces prioritized savings report. Source: affaan-m/everything-claude-code `context-budget`. (2026-04-06)
- ~~**postmortem**~~ — DONE: Quick Postmortem integrated into `/retro` Step 3b (conditional on 3+ distill lessons or 10+ turn incident). Standard + 5 Whys templates in `retro/references/postmortem-templates.md`. Source: wshobson/agents `postmortem-writing` (trust=9.5, bench=98). (2026-04-08)
- **issue-triage** — 3-phase GitHub issue triage: audit (categorize, Jaccard duplicate detection, staleness), deep analysis (parallel agents), validated actions (with user approval). Jaccard algorithm is self-contained (no library). Source: florianbruniaux/claude-code-ultimate-guide `issue-triage` (trust=9.8). (2026-04-08)
- **skill-staleness-check** — Proactive detection of skill drift when upstream sources change. Two-pass diff classification (no impact / version bump / content update / breaking change). Surgical update of affected sections only. Cross-skill cascade check (bounded one level). Could integrate with `/garden` as a new check type. Source: tanstack/intent `skill-staleness-check` (trust=9.3, bench=95). Key concept: `sources:` frontmatter linking skills to their dependencies. (2026-04-08)
- **gha-security-review** — Exploitation-focused GHA workflow audit: pwn requests, expression injection, credential theft, supply chain attacks. Requires concrete exploitation scenario per finding (entry→payload→execution→impact→fix). Confidence gating: HIGH/MEDIUM only. Complements agentic-actions-auditor (AI-specific) with general workflow exploitation. Source: getsentry/skills `gha-security-review` (trust=9.7). ~100 lines. (2026-04-16)
- **flaky-test-fix** — Investigate→reproduce→fix→verify cycle for flaky tests. Key: `run-test-repeatedly` script for fast local reproduction, two-branch strategy (investigation + clean fix). Source: microsoft/aspire `fix-flaky-test` (trust=10). .NET-specific reference — needs adaptation. (2026-04-16)

## Assessment Queue

Score 5+ repos for next inventory run:
- Musonius-dev/praxis (0*, 5/6) — "Layered Claude Code harness — workflow discipline, AI-Kits, persistent vault"
- ibahgat/oh-my-iflow (0*, 5/6) — "Intelligent command-line workflows with multi-agent automation"
- easingthemes/dx-aem-flow (3*, 5/6) — "AI-powered dev plugins for Claude Code & Copilot CLI"
- alexanderop/workoutTracker (10*, 6/6) — project with full CC config
- IgorGanapolsky/trading (27*, 5/6) — trading platform with full CC config

Score 4 of interest:
- bitflight-devops/hallucination-detector (6*, 4/6) — "Zero-dep plugin catches speculation"
- harshanandak/forge (3*, 4/6) — "7-stage TDD-first workflow"
- dimakis/mitzo (0*, 4/6) — "Mobile-first AI command center"
- kochetkov-ma/claude-brewcode (16*, 4/6) — "Full-featured dev platform"

## Auto-SKIP (type classifier)

- TheBushidoCollective/han (130*) — marketplace/aggregator
- shep-ai/shep (104*) — multi-CLI product
- jackneil/claude-jacked (0*) — semantic search product
- civitai/civitai (7069*) — AI model platform
- dyad-sh/dyad (20060*) — app builder product
- modu-ai/moai-adk (905*) — agentic dev kit
- activepieces/activepieces (21584*) — workflow automation platform
- rtk-ai/rtk (18155*) — CLI proxy product
- jsboige/CoursIA (4*) — French AI course/tutorial
- thebiglaskowski/claude-sentient (1*) — plugin with marketplace.json

## Run Log

### Cumulative Metrics

| Metric | Value |
|--------|-------|
| Total repos screened | 287 |
| Deep assessments | 0 |
| Adoptions | 0 |
| Hit rate (deep assess) | N/A |
| Calibration target | N/A |

Discovery mode: **Dynamic query generation (v6)**

### Run 2026-04-05 (1st — fresh ledger, 3 dynamic queries + full screen)
- **Dynamic queries**:
  1. `"permissionDecision" path:.claude` → 1340 total, 30 repos
  2. `"mcpServers" "env" filename:settings.json path:.claude` → 536 total, 29 repos
  3. `"never" "incident" path:rules path:.claude` → 4056 total, 30 repos
- **Random sample**: topic:claude-code, updated desc, page 5 → 100 repos
- **Secondary**: recently pushed 7 days → 100 repos; Exa code search + community threads
- **Combined**: 293 repos → 287 after dedup
- **Phase 1**: 287 screened → 206 score 1+ → 42 score 4+
- **Type classification**: 10 auto-SKIP (products, platforms, aggregators, tutorials)
- **Qualification (historical)**: xrisk-pause-game promoted to [adopted] after regression review; elapsed days are no longer used as a promotion gate (rules/claude-md-quality.md active)
- **Inventoried**: 6 repos via parallel agents (3 + 3)
- **Note**: blast-radius-info.py hook was missing, blocking Write/Edit. Created stub to unblock.

## Handoff to /evaluate-repos

Run date: (none yet — bootstrap section; next gather-repos run overwrites this)
Run cursor: N/A

Inventoried this run: (none)

Assessment queue (deferred): (none)
