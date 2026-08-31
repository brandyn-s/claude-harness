# Architecture Decision Log

> Chronological record of what was built, what was tried, what evidence drove each decision, and what changed. For current-state documentation, see ARCHITECTURE.md.
>
> Last updated: 2026-03-03.

---

## Timeline

| Date | Decision | Evidence |
|------|----------|---------|
| Feb 22 | Initial commit: 5 domain agents, 7 MCP servers, hooks | Organizational intuition |
| Feb 23 | Git hygiene rules, auto-learn system | Early session pain |
| Feb 23 | mcp-forge skill for building MCP servers from API specs | Research: tool explosion at >19 tools degrades LLM performance ~44% |
| Feb 24 | MCP Gateway landscape evaluation (20+ platforms) | gather-intel, deep-dive |
| Feb 24 | Source-code verification: agentgateway OBO claims fabricated | Cloned repos, read the code |
| Feb 25 | LiteLLM deployed as LLM proxy, Archestra for MCP gateway | deep-dive: different missions, deploy both |
| Feb 25 | Red team of all 19 skills: 290 findings | Adversarial review with parallel Opus agents |
| Feb 26-27 | Hook consolidation (7 scripts to 2), PR security checks | Windows console flash pain |
| Feb 28 | Archestra sunset, mcp-create pipeline, distill skill | Overlap with custom stack, zero usage data |
| Mar 1 | Slack per-user OAuth deployment (10 PRs to stabilize) | Only integration with per-user tokens + Entra SSO + OPA |
| Mar 1 | Tavily deployment, replaced built-in WebSearch/WebFetch | 5:1 ROI over built-in tools |
| Mar 2 | CI hardening: SHA-pinned actions, permissions blocks | Clinejection supply chain attack on Cline |
| Mar 3 | 5 domain agents consolidated to 1 generic worker | 150+ session analysis, AgentArch benchmark, DCT research |
| Mar 3 | ARCHITECTURE.md rewrite, PostToolUseFailure fix | Post-redesign reconciliation |

---

## February 22: Initial Setup

Started from a fresh Claude Code installation on Windows 11 with Git Bash. One engineer.

The initial commit (`9969bcc`) created 5 domain-specific agents (security-ops, finance-ops, recruiting-ops, project-ops, runbook-dev), each with tool restrictions via `disallowedTools` and its own `MEMORY.md`. MCP servers connected to CrowdStrike, Tenable, Airlock, Microsoft Graph, Linear, Ramp, and Lever.

**Rationale for domain agents**: Mirrored organizational structure. A security agent knows CrowdStrike FQL syntax; a finance agent knows Ramp SQL quirks. The denylist approach (allow everything except explicitly excluded tools) was chosen over an allowlist so new MCP servers would be available by default.

**What we got wrong**: The domain model assumed work would be domain-siloed. It isn't. Cross-domain tasks ("triage CrowdStrike detections and create Linear tickets") required multi-agent orchestration. The two most common task types (architecture work at 25% of sessions, infrastructure at 24%) had no dedicated agent at all. This took two weeks of usage data to become clear.

---

## February 22-25: Guardrails, Learning, and First Skills

**Git hygiene** (PRs #1-4): Protected branches with `enforce_admins=true`, mandatory pre-merge rebase, preference for `gh` CLI over MCP GitHub tools (MCP returned 404 on private repos - rediscovered multiple times before becoming `[confirmed]` in memory). Written as `rules/git-hygiene.md`. First lesson: rules work most of the time but not all of the time. Anything critical eventually needs to be a hook.

**Auto-learn system** (PR #5): `auto-learn.py` saved session transcripts and launched Opus analysis to extract patterns. The system correctly identified API quirks and promoted `[observed]` entries to `[confirmed]` on repeat sightings. Problems: imperfect deduplication, 50-line memory limit caused pruning, high context cost. Iterated three times (V1 Feb 16, V2 Feb 17, V3 Mar 3). Core insight held: sessions generate knowledge that should persist.

**First skills**: By Feb 25 we had 15+ skills. Early skills were tightly coupled to specific tools - `security-triage` hardcoded `security-remix` references, `linear-ops` had team UUIDs baked in, `ramp-reports` embedded SQL column names. This coupling made them work well in narrow domains but broke when anything changed underneath.

---

## February 22-27: MCP Gateway Security

Parallel to the agent/skill layer, a separate track made MCP servers production-ready.

### OBO Authentication

When Claude calls a CrowdStrike API, whose identity should be used? Three options considered:

1. **Service account**: Simple, no per-user audit trail. Rejected for GCC High compliance.
2. **Per-user API keys**: Secure, doesn't scale. Rejected.
3. **OBO token exchange**: Claude authenticates to Azure AD, gateway exchanges token for downstream API tokens carrying user identity. Chosen.

GCC High requires every action to be attributable to an individual user. Research (`2026-02-24-mcp-gateway-registry-enterprise-evaluation.md`) confirmed no commercial MCP gateway supported OBO + OPA + GCC High.

Implementation used MSAL `acquire_token_on_behalf_of` with `.us` endpoints. Side effect: sub-agents can't authenticate to remote MCP servers (they appear as "anonymous"). Research from March 3 confirmed agent credential delegation is an industry-wide unsolved problem (OWASP Agentic Top 10, 2026). We added a pre-dispatch warning hook rather than trying to solve what the industry hasn't.

### OPA Authorization

Every MCP tool call passes through an OPA sidecar evaluating Rego policies. Signed RS256 bundles pushed to S3 (with a JSON sort fix for OPA issue #4009). Added after the security audit scored A- on Feb 20, then passed 34/34 red team the next day.

### API Gateway: Five Failed Approaches

The API Gateway went through five iterations documented in `api-gateway-architecture.md`:

1. HTTP API v2 (worked but lacked WAF)
2. REST API v1 + NLB (NLB overwrote Host header)
3. Fixed Host header (TLS certificate mismatch)
4. Fixed TLS (missing `tls_config` on deploy)
5. Fixed all three (persistent 500s, reverted)
6. HTTP API v2 + CloudFront for WAF and Shield (final)

Added `disable_execute_api_endpoint = true` after discovering the default endpoint bypassed WAF entirely. Added Conftest policy (45 tests across 5 policies) to prevent recurrence.

---

## February 24-28: Research That Shaped Decisions

Three research campaigns influenced major choices. The research artifacts live in `~/Documents/research/`.

### MCP Gateway Landscape (Feb 24)

Evaluated 20+ platforms. Marketing-based assessment suggested competitors had caught up: agentgateway claimed OBO, Obot claimed "30+ safety guards," Horizon reached GA.

Source code verification (`2026-02-24-mcp-gateway-source-code-verified.md`) corrected the picture:

- **agentgateway** (Solo.io): Claimed OBO, Cedar policies, Entra ID SSO. Source had zero lines of any of these.
- **Obot**: Claimed "30+ safety guards." Source showed ~5 mechanisms, server-level only.
- **Archestra**: We had dismissed it as "catalog-only." Source revealed full OAuth 2.1 with PKCE, DCR, 5 auth methods. We were wrong.
- **Context Forge**: Only platform where all claims verified correct.

After this, we defaulted to source code analysis before considering adoption of any platform.

### Archestra vs LiteLLM (Feb 25)

`deep-dive` research (`2026-02-25-archestra-vs-litellm-llm-proxy.md`) found they serve different missions. Archestra: MCP gateway (tool routing, policy, multi-tenant). LiteLLM: LLM proxy (multi-provider routing, cost tracking, budgets).

Decision: deploy both. LiteLLM at `service.mcp.example.internal` for LLM routing, Archestra for MCP experimentation. Archestra was later sunset Feb 28 (overlapped with custom OBO+OPA stack). LiteLLM remains in production.

### BYOM Landscape (Feb 28)

Surveyed AI coding tools (`2026-02-28-byom-ai-coding-cli-popularity.md`): OpenCode (RCE vulnerability), Cline (Clinejection supply chain attack), Aider (cleanest record). None had security certifications. Enterprise compliance documentation identified as "the single biggest procurement blocker."

Decision: double down on Claude Code's enterprise security story (OPA, per-user identity, OTel audit trails, signed bundles) as the differentiator. Clinejection directly informed our SHA-pinned GitHub Actions.

---

## February 25-28: Skill Red-Team and Design Patterns

By Feb 25 we had 23 skills. PRs #8-12 systematically red-teamed all 19 custom skills using parallel Opus agents. 290 findings total.

**Notable failures discovered**:
- `security-investigation`: Dispatched sub-agents to query CrowdStrike/Tenable, but sub-agents can't authenticate. This was already `[confirmed]` in agent memory - the system knew but hadn't acted on it.
- `ramp-reports`: SQL referenced nonexistent columns (`full_name`, `spend_time`). Every query would have failed.
- `gather-internal-intel`: Required `search:read` Slack scope the MCP server didn't have.

286 of 290 findings were domain-specific (wrong columns, missing scopes, broken auth). Only 4 were generic. Red-teaming can't be templated - it requires bespoke reasoning per skill. All 290 fixed across 7 PRs. PostToolUse hook added for continuous shallow checks; deep review stays manual on a quarterly cycle.

**Skill design lessons** (from `skill-design-patterns.md`):
- High-autonomy beats interactive Q&A. `capture` went from 5 questions per invocation to reading conversation context directly.
- Split monolith skills at ~500 lines with <15% shared logic. `mcp-forge` (907 lines) split into `mcp-forge-build` and `mcp-forge-audit`.
- "Human Review Needed" when the agent has sufficient context is friction disguised as safety.

---

## February 27 - March 1: Productionization

### mcp-create Pipeline (Feb 28)

PR #31 introduced a 6-phase deployment pipeline: code adaptation, Dockerfile, Terraform config, OPA policy, Docker build, deploy, health check. Tested against Tailscale, Slack, and Tavily deployments. Accumulated 32 fixes across PRs #32, #36, #52.

Recurring production gotchas:
- Redis `ssl=True` must be hardcoded - ElastiCache TLS hangs silently without it (discovered independently on LiteLLM and Slack)
- For new services, merge order is inverted: mcp-infra first (creates ECR + ECS), then mcp-servers (builds image)
- ASGI middleware breaks FastMCP ContextVars - inject identity via custom headers instead

### Slack Per-User OAuth (Mar 1)

Most complex deployment: 3 coordinated services (MCP server, OAuth consent app, Redis token store) with per-user identity propagation. Required 10 PRs to stabilize.

`slack-user` at `service.mcp.example.internal` posts as the real user, not a bot. Research (`2026-03-01-claude-slack-integrations-comparison.md`) confirmed it's the only integration combining per-user Slack tokens, Entra SSO, and OPA RBAC. Gotcha: Slack manifests silently drop unrecognized OAuth scopes with no error.

### Tavily (Mar 1)

Replaced built-in WebSearch/WebFetch. Added a PostToolUse polling hook for async research tasks instead of blocking for 120 seconds.

---

## February 23 - March 1: Knowledge System

### Three-Tier Memory

Evolved organically into three tiers:

1. **Topic files** (operational) - 16 files, 20-50 lines each. API quirks and gotchas. Always loaded. "Tenable returns severity as int 0-4 but expects text in filters."
2. **Pattern files** (reference) - 23 files, some >10KB. Full API documentation. Loaded on demand.
3. **Knowledge base** (strategic) - Digital garden of decisions, alternatives, and lessons. 40+ topic pages.

### Digital Garden Pivot

Started as file-per-capture ADRs. OBO knowledge ended up scattered across 3 files (`decisions/0003-obo-msal.md`, `sessions/2026-02-17-obo-debug.md`, `insights/obo-only-auth.md`) that should have been one.

Pivoted to one-file-per-topic model where entries accumulate as dated sections. Validated empirically: `distill` analyzed 6 pain points from a session and all 6 were already captured at existing tiers (6/6 skip rate). The system was working - it needed better organization, not more capture mechanisms.

### Self-Improvement Pipeline

Three iterations:
- **V1** (Feb 16): `auto-learn.py` after sessions >50KB. Writes to agent memory files.
- **V2** (Feb 17): Raised threshold, added dedup, `[observed]` to `[confirmed]` promotion. 9 SessionStart consistency checks.
- **V3** (Mar 3): Consolidated into `session-stop.py`. Threshold 1MB. Routes to topic files by keyword. 10 consistency checks. Stale topic alert at 14 days.

---

## March 3: Agent Consolidation

The largest single-day architectural change. Driven by three independent lines of evidence.

### Evidence

**Usage data** (150+ sessions):
- 52% of agent dispatches used `general-purpose`, not domain agents
- 43% of sessions used no agents at all
- 0% used finance-ops or recruiting-ops in two weeks
- The two most common task types (architecture 25%, infrastructure 24%) had no dedicated agent

**Academic research** (`2026-03-03-agent-architecture-research.md`):
- AgentArch benchmark (Google/DeepMind/MIT): single agents outperform multi-agent on tool-heavy tasks when single-agent accuracy >45%. Independent agents showed 17x error amplification.
- Dynamic Context Tuning (DCT): domain adaptation should be on-demand, not baked into identity.
- Anthropic's multi-agent research system uses orchestrator-worker, matching our convergence toward `general-purpose`.

**Red team results** (Feb 25): Domain-specific skills were the most broken part of the system. The skills that worked well (`superplan`, `deep-dive`, `distill`) were domain-agnostic.

### Changes

Design document: `docs/plans/2026-03-03-generic-agent-architecture-design.md`

- **Agents**: 5 domain agents replaced by 1 generic `worker.md`. No tool restrictions. Domain context loaded from topic files at dispatch time.
- **Memory**: 5 agent memory directories replaced by 16 topic files. Two new files (`infrastructure.md`, `architecture.md`) filled the gap for the most common task types. `recent-sessions.md` added episodic memory (gap identified by MIRIX research).
- **Skills**: 23 reduced to 20. `security-triage` genericized to `triage`, `security-investigation` to `investigate`. Three retired for zero usage.
- **Hooks**: SubagentStart hook auto-injects topic content. PreToolUse on Agent warns about auth limitation. PreToolUse on remote MCPs auto-loads topic context on first call. Hooks became the primary context engineering mechanism.
- **Delegation**: Keyword-to-agent routing replaced by keyword-to-topic mapping.

Implementation: six reversible phases in PRs #78-88. Old artifacts deleted only after end-to-end validation.

---

## March 3: Post-Consolidation Fixes

**PostToolUseFailure hook** (PRs #90-91): Original was a `prompt` type hook that blocked continuation on every tool failure, including expected non-zero exit codes. The "learn from failures" intent never worked - blocking prevented Claude from reaching the fix/persist steps. Replaced with a `command` type hook that emits a non-blocking diagnostic hint with pattern file references.

**Documentation rewrite** (PRs #88-89): ARCHITECTURE.md rewritten from scratch. sync-repo audit confirmed all counts match disk: 20 skills, 1 agent, 10 rules, 21 hooks, 16 topic files, 23 pattern files, 28 MCP servers.

---

## Recurring Patterns

- When a design choice "makes sense" but usage data contradicts it, trust the data. Domain agents, domain-specific skills, and interactive Q&A capture all failed this test.
- If it must always happen, make it a hook. If it should usually happen, make it a rule. Every major safety improvement came from converting a rule to a hook.
- Ship, measure, correct. The API Gateway went through 5 failed approaches. The agent model lasted two weeks. The mcp-create pipeline accumulated 32 fixes. Reversible phased migrations are the right default.
- Spend time on research before building. Source-code verification of the gateway landscape saved us from adopting a platform with fabricated OBO claims.
- Operational knowledge and strategic knowledge need different storage. Topic files for "Airlock's type field must be a list." Knowledge base for "we chose OBO because of GCC High audit requirements."

---

## Open Questions

- **Agent credential delegation**: Industry-wide unsolved problem (OWASP Agentic Top 10, ARIA framework). Pre-dispatch warning hook is a mitigation, not a solution.
- **Code Mode**: Cloudflare's pattern challenges per-tool OPA authorization. Would require moving auth to HTTP method+path layer.
- **Episodic memory**: `recent-sessions.md` is lightweight. MIRIX research suggests situation-specific retrieval could improve multi-session continuity.
- **Team scaling**: Current architecture is for one engineer. Per-user OBO + OPA scales, but shared `settings.json` and topic files will need isolation.

---

*Maintained at `~/.claude/docs/EVOLUTION.md`. Update on major architectural shifts - not every PR, but decisions a new hire or exec should understand.*
