# Audit context — ground truth for /audit-skill agents

Audit agents (Phase 2 of `/audit-skill`) reason from a skill's contents
in isolation. Without context about what's actually true at runtime,
they false-flag patterns that look suspicious but are fine. This file
is the small set of repo-wide facts every audit agent should treat as
authoritative.

Read this first. Then audit the target skill.

## Environment variables that ARE set by Claude Code

These don't need fallbacks; you can use them directly. Flag a finding
only if the skill uses them without checking for the case where they
might be empty (rare, but happens in non-project sessions).

- `$HOME` — POSIX environment, set on Linux/Mac/WSL/Git-Bash. On
  Windows PowerShell, `$env:USERPROFILE` is the equivalent. Skills
  that shell out via Bash always have `$HOME`.
- `$CLAUDE_PROJECT_ID` — exposed in most Claude Code surfaces when
  the session is bound to a project (CLI, Desktop, Cowork, VS Code
  extension). NOT exposed in headless `claude -p` invocations or
  in worktree-isolated sessions where the project root isn't fixed.
  Skills that use it should have a graceful fallback for the unset
  case, but flagging "always unset" is wrong.
- `$CLAUDE_CODE_SESSION_ID` — the canonical session UUID; set per-invocation
  in all surfaces (CLI, Desktop, hooks via stdin, MCP subprocesses since
  v2.1.154). Use this for per-session namespacing.
- `$CLAUDE_SESSION_ID` — a LEGACY name that current Claude Code does NOT set
  (verified 2026-06-13: unset while `$CLAUDE_CODE_SESSION_ID` was set). Code
  reading it must fall back to `$CLAUDE_CODE_SESSION_ID`. A skill that uses
  bare `$CLAUDE_SESSION_ID` for identity IS a finding, not a safe assumption.
- `$AWS_PROFILE`, `$AWS_REGION` — set by per-user shell config, not
  guaranteed. Skills should default rather than assume.

NOT set by default:
- `$TEMP` (Windows-only; Linux/Mac use `$TMPDIR` or `/tmp`)
- `$SCRIPTS`, `$WORKSPACE` (skill-specific; if the skill defines them
  earlier in the same bash block, they're fine — that's local-to-block)

## Path prefixes that DO resolve

Skills are deployed at `~/.claude/skills/<name>/`. The deployed-path
convention assumes the user ran the install setup or symlinked the
source repo. Flag a finding if a path is ONLY valid in a specific
clone (e.g., `/home/<my-username>/Documents/GitHub/...`), but
`~/.claude/skills/<this-skill>/scripts/X.py` is canonical and
expected to resolve.

Other deployed locations that exist:
- `~/.claude/rules/` — rule files
- `~/.claude/hooks/` — installed hooks
- `~/.claude/scripts/` — shared scripts (NOT every skill's scripts/)
- `~/.claude/agent-memory/topics/` — topic markdown files
- `~/.claude/manifests/` — manifest infrastructure (compile.py etc.)
- `~/Documents/knowledge-base/topics/` — captured strategic decisions
- `~/Documents/knowledge-base/research/` — research reports
- `~/Documents/knowledge-base/plans/` — supergoal plan files +
  terminal docs

DO NOT exist by default (skill must create or refuse gracefully):
- `~/Documents/api-docs/<service>/` — only after `/api-ingest` populates
- `~/Documents/knowledge-base/plan-patterns/` — design exists, write
  side not yet implemented (see supergoal/references/plan-pattern-library.md)

## Tool names that ARE real

**Authoritative registry: `rules/mcp-tool-names.md`** (regenerated
2026-06-12 from the live macOS tool surface; three tiers — LIVE /
GATEWAY / RETIRED). This section summarizes the tiers for audit
purposes; when they disagree, the rule file wins.

LIVE on this host (don't flag):

- `mcp__codebase-memory-mcp__*` — the unified code-intelligence server
  (code-search + code-graph merged): search_code, search_code_semantic,
  query_graph, search_graph, trace_call_path, get_architecture,
  get_code_snippet, code_localize, index_repository, index_status,
  index_health, list_projects, delete_project, query_security_surfaces,
  service_map, and more — see the rule file.
- `mcp__memory-search__*` — memory_search, memory_search_batch,
  memory_check_duplicate, memory_stats, memory_stale, memory_reindex,
  checkpoint_save/resume/list
- `mcp__tavily__*` — tavily_search, tavily_extract, tavily_research,
  tavily_map, tavily_crawl
- `mcp__exa__*` — web_search_exa, web_fetch_exa ONLY (the upstream Exa
  MCP consolidated to two tools)
- `mcp__firecrawl__*` — firecrawl_search, firecrawl_scrape, firecrawl_map,
  firecrawl_crawl, firecrawl_check_crawl_status, firecrawl_extract,
  firecrawl_parse, firecrawl_agent, firecrawl_agent_status, monitors,
  interact
- `mcp__linear-server__*` — Linear (named form; the macOS registration)
- `mcp__tailscale__*` — Tailscale API v2

GATEWAY — deployed at `*.mcp.example.internal`, not yet re-registered on
this host post-migration. Skill references are VALID (the servers
exist; treat wildcards as authorized), they just can't be invoked from
this host until re-registered:

- `mcp__remote-crowdstrike__*`, `mcp__remote-tenable__*`,
  `mcp__remote-airlock__*`, `mcp__remote-msgraph__*`,
  `mcp__remote-lever__*`, `mcp__remote-ashby__*`,
  `mcp__remote-confluence__*` / `mcp__confluence-fedramp__*`,
  `mcp__remote-tailscale__*`, Slack (`mcp__036e0c74-...__*` /
  `mcp__slack-user__*`), `mcp__ramp__*`

RETIRED / HOST-MIGRATED — these names no longer resolve here:

- `mcp__code-search__*`, `mcp__code-graph__*` — merged into
  `codebase-memory-mcp`
- `mcp__exa__web_search_advanced_exa`, `mcp__exa__get_code_context_exa`,
  `mcp__exa__crawling_exa` — consolidated upstream
- `mcp__arxiv-mcp-server__*`, `mcp__xai__*` — Windows-era local servers,
  not migrated
- `mcp__93acadff-cc17-4b6c-b323-1d575dcca6d3__*` — the Linear connector
  GUID (Windows install); the macOS form is `mcp__linear-server__*`

**Audit handling for RETIRED names**: a skill citing one of these IS
drift on this host, but it is a KNOWN, centrally-tracked migration
class (the MCP-consolidation arc owns the corpus-wide rename — see
rules/check-before-change.md "before renaming/consolidating an MCP
server's tools"). Do NOT file new per-skill findings whose only content
is the bare name-swap; note the reference in your category record and
move on. DO flag retired names in any skill section you are otherwise
editing, and DO flag claims that a retired tool's CAPABILITY exists
nowhere (e.g. "no semantic search available") — the successor tools
cover most of them.

Tools that LOOK plausible but DON'T exist (do flag these):
- `mcp__codebase-memory-mcp__get_index_status` — the unified server's
  real tool is `index_status` (the OLD code-search spelling was
  `get_index_status`; the polarity flipped in the merge — check the
  rule file when in doubt).

## Builtin Claude Code tools

Always available without declaration in `allowed-tools` (don't flag M2 for these):
- `Read`, `Write`, `Edit`, `Bash`, `Grep`, `Glob`, `Skill`, `ToolSearch`
- `AskUserQuestion`, `WebFetch`, `WebSearch`, `Agent`
- `Task`, `TaskCreate`, `TaskUpdate`, `ExitPlanMode`, `NotebookEdit`

But: explicitly listing them in `allowed-tools` is the convention, so
seeing them listed is fine. Flag missing ones if used.

## Document conventions

- Frontmatter `argument-hint: "[X]"` (square brackets) = optional
  argument by repo convention. Maps to `manifest.yaml: required: false`.
- Frontmatter `argument-hint: "<X>"` (angle brackets) = required.
  Maps to `manifest.yaml: required: true`.
- Mismatch between hint brackets and manifest required is M1 drift.

- Backtick-wrapped file references (`` `references/X.md` ``) are
  citations the agent will Read. They MUST exist or the agent silently
  fails.

- Cross-skill citations like `supergoal/references/plan-pattern-library.md`
  resolve against `skills/`. They MUST also exist.

## Severity calibration

- **drift** = changes user-visible runtime behavior; needs a behavior-fix
- **info** = hygiene, doc consistency, dead declarations; doc-fix is
  enough; no observable behavior change

When you flag a finding, label it explicitly:
  - `[behavior-fix]` if the runtime output changes once fixed
  - `[doc-fix]` if only the docs change (clearer prose, accurate
    severity, etc.)

A finding that's `[doc-fix]` should be `info` severity unless it
breaks an LLM-readable citation (H1) or contradicts a documented
invariant (A3).

## What to do when uncertain

If you find a pattern that looks suspicious but you can't confirm
from this file:

1. Mark the finding as **`[unverified]`** — describes what you saw,
   not what's wrong.
2. Suggest a check to verify: "run `gh api ...`", "grep all skills
   for X", "test the documented command against /tmp/fixture".
3. Don't claim a behavior bug without a constructed reproducer.

This prevents the false-positive class where audit agents reason
plausibly but arrive at the wrong conclusion.
