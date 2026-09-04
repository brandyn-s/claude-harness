@rule agent_delegation_routing
@version 2026-08-06
@scope tasks where independent work, isolation, or specialist context can materially improve the outcome

# Agent Delegation — Risk-Tiered Routing

Delegation is an execution option, not a universal quality requirement.
Choose it from task topology, authority, shared-state risk, context cost, and
whether parallel work has an independent deliverable.

## Decision contract

RISK LOW — direct execution is preferred:
- Trivial answers, a single read, or one bounded edit.
- Work whose dispatch and verification overhead exceeds the task.
- Protected/deployed-path inspection that a child cannot safely isolate.

RISK MEDIUM — use one focused worker when beneficial:
- Multi-step research or cross-tool correlation with a separable output.
- Broad code exploration where a read-only specialist can answer a precise
  question without mutating shared state.
- Include a bounded scope, required context/topic files, output contract,
  authority limits, and verification expectations.

RISK HIGH — isolate and bound every writer:
- Repository writes, infrastructure changes, security-sensitive operations,
  or multiple agents touching related state.
- Use an isolated worktree or other transaction boundary, assign non-overlap,
  cap fan-out, and verify returned artifacts from the parent.
- Never infer permission to push, merge, deploy, delete, message, or expand
  scope merely because the work was delegated.

Dispatch a team only when at least three independent subtasks can progress
without editing the same state. Dependent steps remain sequential. Host and
configured concurrency limits are ceilings, not targets.

Read-only is a TOOL-SET property, not a prompt property. A prose prohibition
("do not Write/Edit; propose changes in JSON") does not reliably bind a
general-purpose subagent: measured 2026-08-22, 3 of 49 proposal agents wrote
the shared worktree directly despite an explicit hard rule, one before it even
returned. For proposal/analysis dispatches, use an agent type without
Write/Edit in its tool set; when only general-purpose is available, treat
every returned proposal tree as dirty — snapshot and reset it before the
parent applies anything. The tell: a returned verbatim anchor that counts 0
in the tree usually means the agent already applied its own edit.

## Authentication boundary

Before dispatch, check whether the task depends on an authenticated remote MCP.
Subagents do not inherit the parent session's remote-MCP authentication and may
appear anonymous to those services.

- Keep authenticated remote MCP calls in the main thread, or query from the
  parent and pass already-grounded results to a worker.
- Do not dispatch remote-MCP-dependent work to a subagent. Dispatch only the
  separable analysis that can operate on supplied data without remote auth.

## Orchestration boundary

FORBIDDEN: background Skill forks as a third orchestration model.

A Skill is an on-demand procedure loaded into the active agent. It is not a
background job type. Do not launch a Skill invocation in the background or
use a background Skill fork alongside direct execution and native agents.
Choose exactly one execution owner for each subtask:

1. the main thread, or
2. a native bounded agent with an explicit output contract.

Long-running deterministic commands may use the platform's ordinary
background-process mechanism, but the owning agent remains responsible for
polling, evidence, cancellation, and cleanup.

## Context and topic routing

Load only topic context required by the delegated task. Common routes:

- Security, STIG, alerts, vulnerabilities: `security.md` and the named tool.
- AWS, Terraform, ECS, CI/CD: `infrastructure.md`.
- Identity, Entra, Microsoft Graph: `msgraph.md`.
- Skills, hooks, rules, Claude Code config: `architecture.md`.
- Slack, Linear, Box, Confluence, Tailscale: the matching topic file.

Do not load unrelated topic files “just in case.” A child receives only the
prompt and context explicitly supplied to it; claimed parent knowledge does
not transfer automatically.

## Required output contract

Every analysis/research child prompt specifies:

- exact question and target files/systems;
- read/write authority and prohibited actions;
- required evidence and citation format;
- expected artifact/schema;
- completion, partial-success, and failure states;
- time/context boundary and durable handoff requirements.

The parent verifies child claims against source, disk, tests, or live state.
A child completion message is not proof.

## Failure recovery

- Prompt too long: do not retry unchanged. Reduce supplied context, narrow the
  task, or execute directly.
- Missing or duplicate child: reconcile the expected/running count and
  reassign only the missing scope.
- Partial result: preserve the artifact and explicit remaining work; do not
  relabel it complete.
- Shared-state collision: stop writers, inspect repository/runtime state, and
  recover transactionally before continuing.

## User override policy

Respect user instructions about whether to use agents unless doing so would
violate a higher-priority safety, authorization, or isolation constraint.
Urgency is not authority. Explain a necessary safety boundary concretely;
do not claim that delegation is mandatory merely because a task is
non-trivial.

## UNDER-delegation is a measured failure too

This rule prevents over-delegation and works. The opposite miss is real: measured
0.6% delegation (12 of 2,045 calls) on a session whose costliest phase burned 1,130
turns and 35% of its errors working three competing hypotheses serially. RISK MEDIUM
already permits the worker; the gap is recognising the shape. Fan out when three or
more INDEPENDENT hypotheses could each explain the symptom, each is answerable by a
bounded READ against a different surface, and being wrong is cheap to discover but
expensive to assume — **if you can enumerate the competing explanations, that
enumeration IS the fan-out, regardless of the order they occurred to you.** Pair it
with an adversarial second pass on any verdict that will drive a write, spending that
budget only on findings whose being-wrong costs something (a wrong "live" gets acted
on; a wrong "not live" leaves the status quo).
Full: `incidents#2026-08-29-under-delegation`.

Detailed historical incidents and superseded host-specific calibrations live
in `rules/incidents/agent-delegation.md` and are loaded only for diagnosis.
