# Agents

Agents are Claude subprocesses spawned via the Agent tool, each with its own context window. They execute tasks autonomously and return results to the main session.

## Why a Single Worker Agent

An earlier version of this system had five specialized domain agents: security-ops, finance-ops, recruiting-ops, project-ops, and runbook-dev. Each had hardcoded tool access and domain knowledge. Analysis of 150+ sessions revealed the problems:

- **52% of dispatches used a generic agent anyway** — most tasks don't fit neatly into one domain
- **43% of sessions used no agents at all** — the main thread handled everything
- **Cross-domain tasks required awkward multi-agent handoffs** — a security investigation that needs Ramp spend data had to bounce between security-ops and finance-ops

The current design uses a **single generic worker** that loads whatever domain context it needs from topic files at runtime. A worker handling CrowdStrike triage loads `security.md` and `crowdstrike.md`. The same worker type handling a Ramp analysis loads `ramp.md`. No routing ambiguity, no idle specialized agents, no cross-domain handoff problems.

## Agent Inventory

| Agent | Source | Purpose | When used |
|-------|--------|---------|-----------|
| `worker` | Example | Generic task executor — loads topic files on demand, handles any domain | Primary dispatch target for multi-tool tasks |
| `api-ingest-worker` | Example | API documentation ingestion with local tools plus five Firecrawl tools | Spawned by `/api-ingest` for parallel multi-API ingestion |
| `data-flow-analyzer` | Trail of Bits (fp-check) | Trust boundary mapping and data flow analysis | Spawned by `/fp-check` during Phase 1 verification |
| `exploitability-verifier` | Trail of Bits (fp-check) | Attacker control analysis and mathematical bounds proofs | Spawned by `/fp-check` during Phase 2 verification |
| `poc-builder` | Trail of Bits (fp-check) | Proof-of-concept creation for vulnerability verification | Spawned by `/fp-check` during Phase 4 |
| `semgrep-scanner` | Trail of Bits (static-analysis) | Parallel Semgrep scan execution — one agent per detected language | Spawned by `/semgrep` skill |

The `worker` is the primary generic dispatch target. The other five are specialized subagents spawned by specific skills — you normally do not dispatch them manually.

## How the Worker Loads Context

When the main thread dispatches a worker, the prompt specifies topic files to load:

```
Load topics: security.md, crowdstrike.md
Task: Check the latest CrowdStrike detections for severity >= High...
```

The worker reads those files from `~/.claude/agent-memory/topics/` as its first action, gaining:
- **Critical gotchas**: API quirks, auth limitations, response format issues
- **Key patterns**: Correct tool names, parameter formats, workflow steps
- **References**: Pointers to deeper pattern files for complex operations

Additionally, the `SubagentStart` hook (`subagent-start-context.py`) auto-injects topic file content as `additionalContext`, so workers get domain knowledge even before their first tool call.

## Dispatch Protocol

The main thread decides when to dispatch using a simple decision tree:

| Scenario | Approach |
|----------|----------|
| Simple query, 1-2 tools | **Main thread** — no agent needed |
| Multi-step, 1-2 tools | **Main thread** — unless auth-gated MCP or >10KB output |
| Multi-step, 3+ tools | **Single worker** with relevant topics |
| Independent parallel subtasks | **2-4 workers** in parallel |

The keyword-to-topic mapping is defined in `rules/agent-delegation.md`. Keywords in the user's request trigger topic file loading — "CrowdStrike detection" loads `security.md` + `crowdstrike.md`, "Terraform deploy" loads `infrastructure.md`, etc.

## Worker Capabilities

- **Intentional inherited tool access**: No positive `tools:` allowlist, so the worker inherits the parent-visible tool surface across its heterogeneous domain routes; `disallowedTools: Agent` prevents sub-dispatch but does not bound MCP access
- **Worktree isolation**: File-writing workers operate in temporary git worktrees by default
- **Transparency protocol**: Announces learnings inline, classifies as `[observed]` (first occurrence) or `[confirmed]` (seen 2+ times)
- **Model selection**: Inherits the parent session's model by default. Per-agent models now work (see below) — set `model:` in an agent's frontmatter or `CLAUDE_CODE_SUBAGENT_MODEL` to override (e.g. a cheaper model for `semgrep-scanner`)
- **Preloaded skills**: systematic-debugging and verification-before-completion

## Known Limitations

> Several entries below are version-pinned to ~2026-04 platform bugs. Tagged
> `[re-verify]` where current docs neither confirm nor refute the bug — test
> empirically on the live version before relying on the workaround (B6 review).

- **No remote MCP auth** `[re-verify]`: Workers historically appeared as anonymous and got rejected by remote servers (CrowdStrike, Graph, Lever, etc.); authenticated queries had to run in the main thread. Current docs don't describe subagent MCP-auth propagation either way — re-test.
- **200K context ceiling** `[re-verify]`: subagents historically got 200K even with 1M on the parent (#40929). Current docs don't state a hard per-subagent cap — re-test before assuming.
- **Model routing — FIXED (was #43869)**: per-agent model selection now works. **Resolution order CHANGED in v2.1.251** — `CLAUDE_CODE_SUBAGENT_MODEL` is now the *default*, not an override: per-invocation `model` param → frontmatter `model:` → `CLAUDE_CODE_SUBAGENT_MODEL` → parent's model. Before v2.1.251 the env var came FIRST and overrode both of the others (env var added v2.1.141). The old "silently ignored" behavior no longer holds. **Note the upstream `sub-agents` doc still publishes the pre-2.1.251 order**; the live Agent tool schema is authoritative ("Takes precedence over the agent definition's model frontmatter and the configured default subagent model"). This inversion matters for cost control — see `agent-memory/topics/claude-monitoring.md` "Model-config levers for fan-out cost".
- **bypassPermissions skips hooks** `[re-verify]` (#43772): workers in bypass mode historically skipped all PreToolUse hooks — which would also skip the always-on worktree-isolation block below, leaving worktree isolation as the only defense. Current docs are ambiguous; re-test, because the worktree block's effectiveness depends on it.

## Tool Access Convention

**Narrow specialists**: Declare a non-empty positive `tools:` allowlist. Omitted built-ins and MCP tools do not enter that agent's tool surface. MCP entries can be exact tool names or MCP server patterns such as `mcp__server` and `mcp__server__*`.

**Inherited agents**: Omitting `tools` grants every tool available to subagents except entries removed by `disallowedTools`. Use this only as a reviewed exception. `disallowedTools: mcp__*` is the direct way to inherit built-ins while excluding all MCP tools. The generic `worker` intentionally inherits MCP access because its current route contract spans many domains; it remains the sole exception here.

## Agent Definition Format

Agent definitions use markdown with YAML frontmatter:

```yaml
---
name: worker
description: Generic task worker that loads topic-indexed memory on demand.
model: inherit
memory: user
isolation: worktree
maxTurns: 200
disallowedTools:
  - Agent
skills:
  - systematic-debugging
  - verification-before-completion
---

[Agent instructions in markdown body]
```

See `TEMPLATE.md` for the full authoring reference.

### Supported frontmatter fields (verified 2026-07-26)

Only fields documented in Anthropic's
[subagents reference](https://code.claude.com/docs/en/sub-agents) have any effect.
Verified supported: `name`, `description`, `tools`, `disallowedTools`, `model`,
`permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory`,
`background`, `effort`, `isolation`, `color`.

**`allowedAgentTypes` is NOT a supported field** and was removed from `worker.md`,
this README, and `TEMPLATE.md` on 2026-07-26. It silently did nothing, while
reading as if it restricted delegation. Use the real levers instead:

| Goal | Correct field |
|---|---|
| Restrict which tools an agent may use | `tools:` (positive allowlist) |
| Deny specific tools from the inherited set | `disallowedTools:` |
| Prevent an agent from dispatching subagents | `disallowedTools: Agent` |
| Grant/connect additional MCP servers | `mcpServers:` — **additive**, it grants; it does not restrict |

### Choosing `tools:` vs `disallowedTools:`

Every narrow specialist must use a non-empty positive allowlist. CI locks the
exact specialist policies and reports any agent that omits one via
`scripts/validate-agent-frontmatter.py --warn-unbounded`; `worker` is reported
as the one intentional inherited-tool exception rather than mislabeled bounded.

Prefer a **positive `tools:` allowlist** for a narrow specialist (the five
specialists here do this: `data-flow-analyzer` gets Read/Grep/Glob and nothing
else). It is the stronger form: anything new is denied by default.

Use **`disallowedTools:`** for exclusions from an intentionally inherited set.
Server patterns mean an allowlist does not need to enumerate every MCP tool, but
the generic `worker` still spans a heterogeneous, changing route contract. A
static union of its current server patterns would remain broad and could silently
drift from routing. Phase 1 therefore preserves inherited access and denies
`Agent`; narrow it only after splitting routes by domain or proving a supported
per-invocation tool policy.

`disallowedTools: [Agent]` is the primary nesting control. Source also requires
`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` as defense in depth, but #84974 shows
that Claude Code 2.1.225/226 applies the value off by one and can permit one
child layer if `Agent` is available. The explicit tool fence is the primary
current control for the generic worker and the documented fork exception.

Two contracts worth knowing, quoted from the same reference:

* `tools` — *"Inherits every tool available to subagents if omitted."* So omitting
  `tools` is a grant of everything, not a neutral default.
* Nesting — first-party documentation describes the intended depth behavior,
  but local 2.1.225/226 qualification must account for #84974. Do not infer
  zero nesting from the configured depth alone; require the `Agent` tool fence.
