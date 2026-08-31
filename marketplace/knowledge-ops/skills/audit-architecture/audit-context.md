# Audit context — ground truth for /audit-architecture

Architecture audit phases (0–6) reason about a complex multi-component
system. Without context about what's actually true at runtime, they
false-flag patterns that are known-OK. This file is the set of repo-wide
facts every audit phase should treat as authoritative.

Read this before starting Phases 0–6. Then audit.

## Authoritative config file locations

- `~/.mcp.json` — top-level MCP server definitions (user-scoped)
- `~/.claude.json` — full Claude config including per-project MCP overrides.
  **Always** read with `python json.load()`, never Bash `cat`. Claude Code
  actively writes to this file; the Edit tool and shell cat may encounter
  partial writes.
- `~/.claude/settings.json` — hooks, permissions, disabled MCP servers
- `~/.claude/settings.local.json` — local overrides; may not exist
- `~/.claude/hooks/skill-rules.json` — routing rules

## Known-OK deviations (do NOT flag these)

- **Windows-only performance probes**: Phase 0 CPU/memory/process-dedup
  probes use Windows-specific APIs. On non-Windows hosts they correctly
  report `SKIP — non-Windows host`. That SKIP is not a gap.

- **Project-scoped MCP servers**: Some MCP servers live under
  `projects[<encoded-path>]["mcpServers"]` in `~/.claude.json`, not at
  the top level. They have a narrower owning-agent scope than user-scoped
  servers. Do not flag C2 (no routing rule) for a project-scoped server
  that only appears in project sessions — the routing scope is intentional.

- **Disabled servers with no routing rules**: A server listed in
  `disabledMcpServers` intentionally has no routing rule. Only flag C2
  for a disabled server if the server is simultaneously accessible to an
  agent (i.e., the disabled-server bypass check in Phase 2 fires).

- **Plugin hooks require direct inventory**: `enabledPlugins`, `settings.json`
  hooks, and `/hooks` are not authoritative inventories. Read
  `~/.claude/plugins/installed_plugins.json`, resolve every `installPath`, and
  inspect `hooks/hooks.json` unless a manifest string/array/object `hooks` field
  replaces that default. Resolve state using local > project > user
  `enabledPlugins`, then marketplace/manifest `defaultEnabled`; keep unknown
  distinct from disabled. A disabled plugin with hook definitions is actionable
  evidence (#85893), not a known-OK visibility gap. Unreadable relevant metadata
  blocks a clean verdict.

- **MCP/skill identifiers share a failure boundary**: Compare exact
  case-sensitive runtime names for standalone MCP servers versus personal or
  project skills and legacy commands in overlapping scopes. Skill identity is
  its directory, command identity its file stem; their frontmatter `name` does
  not replace it. A collision can silently remove the MCP server from the tool
  inventory (#85827). Do not Unicode-normalize, case-fold, collapse punctuation,
  compare unrelated projects, or hard-fail plugin components: plugin skills and
  MCPs have scoped names and installed plugins may be disabled. Preserve both
  standalone source paths as finding evidence.

- **Missing `agent-memory/sentinel/` on first run**: The sentinel
  directory and `audit-architecture-findings.yaml` are created during
  Phase 7A on the first run. `file_missing` on these paths before Phase 7A
  completes is expected. Only flag if they're absent AFTER Phase 7A runs.

## Platform-specific behavior

- `settings.local.json` may not exist. Normal. Only flag if a hook in
  `settings.json` references it.
- `Get-CimInstance` and `kernel32` APIs are Windows-only. On Linux/macOS,
  use `psutil` or skip the performance subsection.
- On Linux containers (CI, Claude Code on the web), `psutil` may not be
  installed. Skip performance probes gracefully; don't fail the whole audit.

## Severity calibration for architecture findings

- **drift** (behavior-impacting): broken MCP connectivity, missing
  denylist entry that lets an agent access a server it shouldn't, routing
  collision that routes to the wrong agent/skill, stale file paths that
  break scripts or hooks. These cause user-visible failures.
- **info** (hygiene): wrong count in ARCHITECTURE.md, missing delegation
  row in CLAUDE.md, stub pattern file, agent memory underutilization,
  MEMORY.md entry missing while the agent works correctly. Documentation
  gaps, not failures.

When in doubt: if the issue would cause a failed user request, it's
`drift`. If it only surfaces in audit output, it's `info`.

## Finding labels

- `[behavior-fix]` — fixing changes runtime behavior (routing, tool
  access, connectivity). Must include a machine-checkable reproducer.
- `[doc-fix]` — fixing only updates documentation or counts. These are
  `info` severity and have lower fix priority.
- `[unverified]` — no machine-checkable reproducer can be written; must
  remain unverified until a human provides one. Cannot be acted on
  autonomously.

The two-way pairing contract: `type: manual` reproducers ⟺ `label: unverified`.
A `[behavior-fix]` or `[doc-fix]` finding with `type: manual` violates the
contract and must be backfilled or demoted before oracle gating.

## Host profile — macOS, single-worker architecture (verified 2026-08-22)

This host does NOT use the per-domain owning-agent design that Phase 2's
8-dimension matrix was written for. Interpret the matrix accordingly:

- **C1 (owning agent): N/A.** One generic `worker` agent (allowlist: all
  tools except Agent) serves every MCP domain; the other agents
  (api-ingest-worker, semgrep-scanner, the fp-check trio) are task-scoped.
  Do not flag a server for lacking a dedicated owning agent.
- **C5 (agent memory entries): N/A for `worker`.** Accumulation happens in
  the topics tier (`agent-memory/topics/*.md`, ~90 files, actively
  updated), not in `agent-memory/worker/`. An empty `worker/` directory is
  by design, not an unused agent. Task-scoped subagents are deliberately
  stateless (no `memory:` field) — do not flag L2 for them either.
- **C4 (topic file)** and **C2 (routing rule)** remain meaningful, but per
  compare-by-need they are inventory unless a concrete friction incident
  exists: routing rules are advisory hints (description-routing still
  works), and tavily/exa/firecrawl routing is owned by the
  `web-search-preference` rule, not skill-rules.json.
- **Router dispatch is priority-sorted**, not first-match — see Phase 4.

## What to do when uncertain

1. Mark the finding `[unverified]` — describe what you saw, not a
   conclusion about what's wrong.
2. Suggest a verification command: `"run python -c 'import json; ...'"`
   or `"grep the agent .md for X"`.
3. Don't assert a behavior bug without a constructed reproducer.

This prevents the false-positive class where audit phases reason
plausibly but arrive at the wrong conclusion about the live system.
