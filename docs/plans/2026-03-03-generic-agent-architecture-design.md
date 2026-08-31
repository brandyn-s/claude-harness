# Generic Agent Architecture Design

**Date**: 2026-03-03
**Status**: Approved
**Scope**: Agent layer, memory system, skills, delegation rules, hooks, CI fixes

## Problem Statement

The current Claude Code architecture uses 5 domain-specific agents (security-ops, finance-ops, recruiting-ops, project-ops, runbook-dev) with rigid routing rules. Session transcript analysis of 150+ sessions over 2 weeks reveals this model does not match actual usage:

- 52% of agent dispatches use `general-purpose`, not domain agents
- 43% of sessions use no agents at all
- 0% Ramp/Lever sessions in 2 weeks; finance-ops and recruiting-ops are idle
- 70% of skill usage is meta-skills (superplan, deep-dive, distill, capture)
- 25% of sessions are architecture/meta work, 24% infrastructure - the two most common task types have no agent
- 8 of 23 skills saw zero usage in the summary week
- Cross-domain tasks (6-8% of sessions) require manual multi-agent dispatch with no handoff protocol

The domain boundaries are artificial friction. Work is task-based and cross-domain, not domain-siloed.

## Design

### 1. Agent Layer

**5 domain agents -> 1 generic worker**

Replace `security-ops.md`, `finance-ops.md`, `recruiting-ops.md`, `project-ops.md`, `runbook-dev.md` with a single `worker.md`.

```
~/.claude/agents/
  worker.md        # single generic agent
  TEMPLATE.md      # keep for reference
  README.md        # update conventions
```

`worker.md` characteristics:
- No `disallowedTools` - full tool access (matches existing `general-purpose` usage)
- Superpowers: systematic-debugging, verification-before-completion, dispatching-parallel-agents
- System prompt: generic task execution + transparency requirements + "load topic files listed in your task description before starting work"
- No domain knowledge in system prompt - domain context comes from topic files loaded at dispatch time

Dispatch prompt format:
```
Load topics: security.md, crowdstrike.md, linear.md
Task: Triage these CrowdStrike detections and create Linear tickets for confirmed findings...
```

### 2. Topic-Indexed Memory

**5 agent memory directories -> 15 topic files**

```
~/.claude/agent-memory/topics/
  security.md          # cross-cutting: triage workflow, severity scoring, tool routing
  crowdstrike.md       # GovCloud, Alerts v2/v3, FQL, cs_hygiene.py, read-only MCP
  tenable.md           # FedCloud, severity filters, export patterns, scan ops
  airlock.md           # type=[2], checkpoint calc, group IDs, response size guard
  msgraph.md           # GCC High, OBO delegated, Gateway app, audit log fields
  ramp.md              # SQLite 100-row limit, load order, two-phase aggregate, glossary
  lever.md             # opportunity model, search strategy, stage discovery
  linear.md            # team UUID, pagination, ticket conventions, priority heuristics
  confluence.md        # FedRAMP instance, search/write patterns
  tailscale.md         # API v2, no pagination, example.com tailnet
  slack.md             # per-user OAuth, OPA-gated writes, consent app
  infrastructure.md    # NEW - Terraform, ECS, Docker, CI/CD, branch protection
  architecture.md      # NEW - Claude Code config, skills, hooks, memory management
  runbook.md           # PowerShell 7+, Azure Automation, Graph API scripting
  transparency.md      # learning protocol: [observed] -> [confirmed], announcement rules
```

Migration: content extracted from existing agent MEMORY.md files, split by tool/topic. Two new files (`infrastructure.md`, `architecture.md`) fill gaps for the two most common task types (24% and 25% of sessions respectively).

Loading protocol: dispatch prompt lists topic filenames. Worker reads them via Read tool as first action.

### 3. Skill Refactoring

**23 skills -> 18 skills**

#### Genericize (3 skills)

**`security-triage` -> `triage`**
- Same phased workflow (connectivity check, severity scoring, correlation, recommend)
- Remove hardcoded security-remix routing; replace with "use tools relevant to loaded topics"
- Severity scoring matrix becomes a generic template applicable to any domain findings
- Skill says "load relevant topic files" instead of "dispatch to security-ops"

**`security-investigation` -> `investigate`**
- Same phased workflow (playbook selection, queries, enrichment, timeline, correlation, report)
- Playbooks become generic: "Compromised Endpoint" stays, framework supports "Vendor Spend Anomaly" etc.
- Remove hardcoded security-remix instruction; replace with topic-based tool routing
- Keep pivot gate (max +3 entities) and optional MITRE mapping when security topics loaded

**`bulk-api-script`** (keep name, strip domain rules)
- Remove domain-specific API rules from skill body
- API quirks move to topic files (FQL dates -> `crowdstrike.md`, SQLite limit -> `ramp.md`)
- Skill becomes: "write a Python script. Load topic files for the APIs you are hitting."

#### Retire (3 skills)

| Skill | Reason | Knowledge destination |
|---|---|---|
| `ramp-reports` | 0 usage in summary week. Two-phase pattern preserved in `ramp.md`. | `ramp.md` topic file |
| `linear-ops` | 0 usage in summary week. Conventions preserved in `linear.md`. | `linear.md` topic file |
| `checkpoint` | 0 usage. Auto-learn and distill cover persistence. | Archive (re-create if needed) |

#### Keep as-is (14 skills)

superplan, deep-dive, distill, capture, recall, garden, gather-intel, mcp-forge-build, mcp-forge-audit, mcp-create, sync-repo, stig-assess, obsidian, simplify

Minor updates to superplan (route to topics, not agents) and distill (route learnings to topic files).

### 4. Fixes from Gap Analysis

#### Fix 1: Pre-dispatch auth check (P0)
New PreToolUse hook on the Agent tool. Before spawning a worker, check if the task references authenticated remote MCPs (CrowdStrike, Tenable, Airlock, Graph, Lever). If yes, warn about sub-agent credential limitation. Non-blocking - surfaces the known issue before wasting a dispatch.

#### Fix 2: No-op CI gate job (P0)
Add a `gate` job to mcp-servers and example-compliance-repo CI workflows that always runs regardless of paths-ignore. Make `gate` the sole required status check. Eliminates the enforce_admins toggle workaround permanently.

#### Fix 3: CKLB parsing guard in stig-assess (P0)
Add to stig-assess skill: "CKLB files are single-line JSON, 200-300+ rules. NEVER use Read tool directly. Always use Python json.load()."

#### Fix 4: Promote PROMOTE-CANDIDATE entries (P1)
- GitHub strict-mode Catch-22 -> `infrastructure.md` topic file (and resolved by Fix 2)
- Remote MCP sub-agent auth rejection -> `transparency.md` topic file (and surfaced by Fix 1)

#### Fix 5: memory-search timeout mitigation (P1)
Update `recall` skill: primary path is Glob + Read on knowledge-base topic files. memory-search MCP becomes fallback only. Update `superplan` Phase 2c to use same file-first approach.

#### Fix 6: Airlock response guard (P1)
Add to `airlock.md` topic file: "ALWAYS filter by hostname or group_id. Unfiltered listings return ~114KB (96.8% waste)."

#### Fix 7: Auto-learn routing update (P1)
Update `session-stop.py`: route learnings to topic files instead of agent memory. CrowdStrike gotcha -> `crowdstrike.md`, Ramp gotcha -> `ramp.md`. Add tool/API keyword detection to map learnings to topic filenames.

#### Fix 8: Stale topic file alert (P2)
Update `session-start.py`: check `last_modified` of each topic file. Alert if any file >14 days stale.

#### Fix 9: Remove broken security-guidance plugin (P0 - DONE)
The `security-guidance@claude-plugins-official` plugin had a broken PreToolUse hook on `Edit|Write|MultiEdit` due to MSYS path corruption of `${CLAUDE_PLUGIN_ROOT}`. Removed entire `claude-plugins-official` marketplace (all plugins had equivalents in other marketplaces). Root cause: `shutil.rmtree()` fails on Windows git pack files - fix requires `onexc` handler with `os.chmod(stat.S_IWRITE)`.

#### Fix 10: Add force_remove_readonly pattern to platform-constraints (P1)
Add to `platform-constraints.md`: "shutil.rmtree() fails on Windows directories containing git repos (.idx/.pack files are read-only). Always use `onexc=force_remove_readonly` handler that calls `os.chmod(path, stat.S_IWRITE)` before retry."

### 5. Delegation Rules

Replace keyword-to-agent routing in `agent-delegation.md` with keyword-to-topic mapping:

| Keywords | Topic files |
|---|---|
| detection, vulnerability, alert, IOC, triage, contain, hash, block | `security.md` + tool-specific topic |
| sign-in, MFA, user, group, identity, audit log, Entra | `msgraph.md` |
| spend, transaction, expense, budget, vendor, card | `ramp.md` |
| candidate, pipeline, hiring, requisition, posting, offer | `lever.md` |
| issue, project, milestone, cycle, sprint, backlog | `linear.md` |
| runbook, Azure Automation, PowerShell, Graph API script | `runbook.md` |
| deploy, Terraform, ECS, Docker, CI/CD, GitHub Actions | `infrastructure.md` |
| skill, hook, agent, memory, Claude Code config | `architecture.md` |
| wiki, documentation, page, space | `confluence.md` |
| device, DNS, ACL, tailnet, key | `tailscale.md` |
| channel, message, thread, Slack | `slack.md` |
| STIG, SRG, compliance, CKLB, RMF | `security.md` + `infrastructure.md` |

Dispatch protocol:
1. Detect tools needed from user request
2. Map to topic files
3. Decide execution mode: main thread (simple) / 1 worker (multi-step) / 2-4 workers (parallel subtasks)
4. Compose dispatch prompt: task + topic files + optional skill workflow
5. Pre-dispatch auth check (Fix 1)

### 6. Hook Changes

| Hook | Event | Change |
|---|---|---|
| `pre-agent-dispatch.py` | PreToolUse (Agent) | NEW - Fix 1, warn on authenticated MCP dispatch |
| `session-start.py` | SessionStart | UPDATE - Fix 8, stale topic file alert |
| `session-stop.py` | Stop | UPDATE - Fix 7, route learnings to topic files |
| `skill-routing-hint.py` | UserPromptSubmit | UPDATE - suggest generic skill names (triage, investigate) |

## Migration Plan

### Phase 1: Topic files (zero risk, additive)
1. Create `~/.claude/agent-memory/topics/`
2. Extract content from existing agent MEMORY.md into per-topic files
3. Create `infrastructure.md` and `architecture.md` (new)
4. Create `transparency.md` from TEMPLATE.md shared requirements
5. Old agent memory directories untouched

### Phase 2: Worker agent (low risk, additive)
1. Create `worker.md`
2. Test by dispatching worker with topic files on real tasks
3. Old domain agents still present

### Phase 3: Skill refactoring (medium risk, reversible)
1. Copy security-triage -> triage, genericize
2. Copy security-investigation -> investigate, genericize
3. Strip domain rules from bulk-api-script (confirm in topic files first)
4. Old skills still present under old names

### Phase 4: Delegation rules and hooks (medium risk, reversible)
1. Update agent-delegation.md
2. Update superplan Phase 1/2/5
3. Update skill-routing-hint.py
4. Update session-stop.py auto-learn routing
5. Add pre-agent-dispatch.py hook
6. Update session-start.py stale alert

### Phase 5: CI fixes (independent, parallel with 1-4)
1. Add gate job to mcp-servers CI
2. Add gate job to example-compliance-repo CI
3. Add CKLB guard to stig-assess
4. Update recall to file-first
5. Add Airlock guard to airlock.md topic file

### Phase 6: Cleanup (after 1-2 weeks validation)
1. Delete old domain agent files
2. Delete retired skill directories (ramp-reports, linear-ops, checkpoint, security-triage, security-investigation)
3. Delete old agent memory directories
4. Update MEMORY.md index
5. Run sync-repo

### Rollback
Every phase is independently reversible. Phase 1-3 are purely additive (old and new coexist). Phase 4 changes are single-commit revertible. Phase 6 cleanup is recoverable from git history.

### Validation criteria before Phase 6
- [ ] 10+ sessions using worker agent successfully
- [ ] triage skill tested against CrowdStrike, Tenable, and one non-security domain
- [ ] investigate skill tested against a real cross-tool scenario
- [ ] Auto-learn routes to topic files correctly (3+ verified outputs)
- [ ] No session requires fallback to old domain agent names
- [ ] Pre-dispatch auth check warns correctly on authenticated MCP tasks

## Deferred

| Item | Reason |
|---|---|
| Circuit breaker hook | Low ROI at 19% friction rate. Revisit after migration stabilizes. |
| Context budget warning hook | Autocompact at 70% already handles this. |
| Post-skill validation hook | Skills getting simpler. Not justified yet. |
| Ramp load_users retry | Retiring ramp-reports. Pattern documented in ramp.md. |
