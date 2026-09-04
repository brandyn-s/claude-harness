# Hooks

Hooks are Python scripts that fire automatically before, during, or after tool calls and session events. They are the enforcement layer of the architecture — they don't rely on the AI agent remembering rules because they execute mechanically, every time, regardless of what the agent is thinking about.

## Why Hooks Exist

Rules (markdown files in `rules/`) tell the agent what to do. But rules are guidance — they can be forgotten under cognitive load, especially in long sessions after compaction summarizes the context. A rule that says "never push to main" works until the agent is 50 turns deep in a debugging session and forgets.

Hooks make rules mechanical. `bash-security-guard.py` doesn't care what the agent is thinking — it blocks `git push origin main` every time. `post-write-edit.py` doesn't need the agent to remember encoding rules — it checks every Python file for `encoding='utf-8'` automatically.

The design principle: **if something must happen every time, it's a hook, not a rule.** Rules explain *why*. Hooks ensure *it happens*.

## How Hooks Work

Hooks are registered in `settings.json` under event types. Each hook has:
- **Event type**: When it fires (SessionStart, PreToolUse, PostToolUse, etc.)
- **Matcher**: Which tool calls trigger it (e.g., `Bash`, `Write|Edit`, `mcp__remote-.*`)
- **Type**: `command` (Python script), `prompt` (LLM injection), `http` (endpoint), or `agent` (subagent)
- **`if` condition** (optional): Pre-filter using permission rule syntax — prevents the hook process from spawning at all for non-matching calls

When a tool call fires, matching hooks execute. PreToolUse hooks can:
- **Allow** (exit 0): Tool call proceeds
- **Block** (exit 2 + JSON): Tool call is prevented, agent sees the block reason
- **Warn** (exit 0 + `systemMessage`): Tool call proceeds but agent sees a warning

PostToolUse hooks can modify outputs via `updatedMCPToolOutput`.

## Hook Inventory

### Session Lifecycle

| Hook | Event | What it does | Why it exists |
|------|-------|-------------|---------------|
| `session-start.py` | SessionStart | Persists `CLAUDE_ENV_FILE` and injects the active OS's compact `session-start.md` digest (legacy fallback: top-level OS rules) | Keeps first-response latency predictable and output below the 10,000-character inline cap; full incident catalogs, health, sync, pruning, and repair stay on demand. |
| `session-end.py` | SessionEnd | Atomically records a bounded receipt plus the official SessionStart model seed when available | Keeps exit fast; the local scheduled `bin/enrich-session-end-receipts.py` job recovers model/fallback/refusal metadata without retaining prompt content, and leaves unsupported facts explicitly `runtime-unknown`. |
| `stop-failure-handler.py` | StopFailure | Logs API failures, injects recovery guidance for rate limits, auth errors, billing, server errors | API failures at session end are invisible without this. Provides immediate fix instructions. |
| `precompact-priorities.py` | PreCompact | Prints a static checklist (unanswered questions, root causes vs ruled-out hypotheses, exact ids and numbers, subagent reports, A-vs-B decisions); Claude Code 2.1.260 appends PreCompact stdout to the summarizer's prompt as `Additional Instructions` | The default compaction template never asks for these, and they are what a resumed session pays most to rediscover. Under 3 KB, ASCII, never blocks. A/B measurement lives in `skills/_shared/compaction-eval/`. |

The former `session-stop.py` and InstructionsLoaded validator implementations
were removed after their replacement coverage landed; Git history is the
rollback source. Interactive lifecycle hooks stay bounded, and explicit
workflows own analysis and repair.

### Security Guards (PreToolUse — Blocking)

| Hook | Matcher | What it does | Why it exists |
|------|---------|-------------|---------------|
| `bash-pretooluse-dispatcher.py` | `Bash\|PowerShell` | Runs the six unconditional Bash hooks in one Python process, in order: `bash-security-guard.py`, `destructive-ops-guard.py`, `git-destructive-checkout-guard.py`, `bash-tail-buffering-guard.py`, `zsh-dialect-guard.py`, `poll-loop-nudge.py`. The first exit 2 wins and stops the chain; an `updatedInput` rewrite is what the hooks after it see; `additionalContext`, `permissionDecision` (strictest wins) and `systemMessage` are merged into one JSON object. Writes a fire row per hook so `bin/hook-fire-report.py` still sees each one. PowerShell payloads reach only `destructive-ops-guard.py`, the one hook that was ever matched on it. | Six `run-hook` + `python3` spawns per Bash call measured 210 ms median (`ls -la`, 2026-09-03); one interpreter does the same work in ~50 ms. Nothing is refactored — each hook runs its own `__main__` under `runpy`, so every one of them still works standalone and its own crash policy still applies. |
| `bash-security-guard.py` | `Bash` | Always blocks credential exposure, exfiltration, reverse shells, security-control disablement, and broad destruction; optionally applies delivery, portability, and workflow policy from `bash_policy_tables.py` | One process and one JSON parse. Fresh-laptop loads the catastrophic core; the author profile sets `CLAUDE_BASH_POLICY_PACKS=all`. Writes its own per-decision audit trail to `~/.claude/audit/bash-security-*.jsonl`. |
| `config-guard.py` | `Write\|Edit` | Blocks attempts to disable hooks via settings.json edits | Self-protection. Prevents an agent or subagent from disabling its own safety net. |
| `memory-write-guard.py` | `Write\|Edit` | Blocks prompt injection patterns and oversized entries in memory file writes | Defends against ASI06 (indirect prompt injection via memory persistence). |
| `search-path-guard.py` | `Glob\|Grep` | Blocks overly broad search paths (home dir, C:/, ~/.claude/plugins) | Prevents ripgrep from scanning gigabytes of irrelevant files. A single broad Grep can timeout for 2 minutes. |
| `block-partial-read.py` | `Read` | Blocks partial reads of critical config files (settings.json, rules/, skills/) | Partial reads cause "string not found" errors on subsequent edits because the agent only saw a fragment. |
| `tavily-search-cap.py` | `mcp__tavily__tavily_search` | Caps `max_results` at 5 | Empirically verified: top 5 results are almost always sufficient. Higher values waste ~2.4M tokens/month in context. |

### Context and Routing (PreToolUse — Non-blocking)

| Hook | Matcher | What it does | Why it exists |
|------|---------|-------------|---------------|
| `pre-agent-dispatch.py` | `Agent` | Warns when dispatching workers that reference authenticated remote MCPs | Sub-agents can't authenticate to MCP Gateway. Warning prevents wasted turns on auth failures. |
| `auto-topic-loader.py` | `mcp__.*\|WebSearch\|WebFetch` | Injects the routed topic on the first call to each MCP server. A topic over 8,000 chars is split on headings and only the summary plus the sections matching the tool name and input are injected, ending with a pointer to the file; sections are never repeated within a session | Workers get domain-specific gotchas without loading them by hand. Measured 2026-09-04, one call per routed server (13): whole-file injection emitted 64,866 chars and delivered NOTHING for msgraph.md (24,170 chars) and linear.md (10,256) beyond a NOT DELIVERED pointer; retrieval emits 78,262 chars and every route delivers (msgraph 8,030, linear 6,929, firecrawl 6,902; the 10 topics under 8,000 arrive whole). The hook's own work is about 1 ms; the ~18 ms end-to-end is interpreter startup. |

### Quality Enforcement (PostToolUse)

| Hook | Matcher | What it does | Why it exists |
|------|---------|-------------|---------------|
| `post-write-edit.py` | `Write\|Edit` | Consolidated checker: encoding validation, py_compile syntax check, gitleaks secret scan, ruff format, markdown fix, terraform fmt | Catches encoding errors (cp1252 on Windows), syntax errors, and secret leaks immediately after writing — before they propagate to commits. |
| `post-merge-sync.py` | `Bash` | Auto-syncs local main after `gh pr merge` (checkout main, fetch, rebase) | Prevents local/remote divergence after merges. Without this, the next PR creation fails with "up to date" errors. |
| `result-injection-guard.py` | `mcp__.*` | Scans MCP tool results for embedded instruction patterns | Defends against ASI01 (indirect prompt injection via MCP results). Warns the agent to treat flagged results as data, not instructions. |
| `loop-detector.py` | `mcp__.*\|Bash\|Read\|Glob\|Grep` | Detects no-op loops (3+ identical calls) and retry storms (4+ consecutive failures) | Prevents the agent from burning turns on repeated identical calls that will never succeed. |
| `tavily-research-poll.py` | `mcp__tavily__tavily_research` | Polls async Tavily research tasks for completion | Tavily research is async — without polling, the agent doesn't get results. |

Oversized MCP results use Claude Code's native 25,000-token persistence limit
and tool-specific `anthropic/maxResultSizeChars` metadata. The former custom
trimmer was retired because its generic fallback irreversibly replaced the
model-visible result with a hard-truncated fragment; transcript replay showed a
caller immediately repeating a truncated request.

### Failure Recovery (PostToolUseFailure)

| Hook | Matcher | What it does | Why it exists |
|------|---------|-------------|---------------|
| `post-failure-guide.py` | `mcp__.*\|Bash\|Read\|Edit\|Write` | Diagnoses failure cause, suggests fix from pattern files | Turns cryptic errors into actionable fix instructions. Reduces wasted turns on common failures. |
| `bash-error-classifier.py` | `Bash` | Classifies bash errors with specific fix suggestions | Different error types need different fixes. "File not found" vs "Permission denied" vs "Command not found" each have specific resolution paths. |

### User Prompt Processing (UserPromptSubmit)

| Hook | What it does | Why it exists |
|------|-------------|---------------|
| `prompt-secret-scan.py` | Scans user prompts for embedded secrets (API keys, tokens, passwords) | Prevents accidental secret exposure in conversation context. |

Native skill descriptions own skill discovery. Knowledge recall and judgment
workflows are explicitly invoked instead of being keyword-injected into every
prompt.

### Agent Lifecycle (SubagentStart/Stop)

| Hook | Event | What it does | Why it exists |
|------|-------|-------------|---------------|
| `subagent-start-context.py` | SubagentStart | Injects topic file content into workers via `additionalContext` | Workers get domain knowledge before their first tool call. Without this, they waste turns loading topics manually. |
| `subagent-stop.py` | SubagentStop | Captures worker learnings and routes to appropriate topic files | Knowledge from worker sessions persists to topic files. Without this, learnings die with the worker's context. |

### Team Coordination

| Hook | Event | What it does | Why it exists |
|------|-------|-------------|---------------|
| `teammate-idle.py` | TeammateIdle | Quality gate — checks teammate produced sufficient activity and file changes | Prevents teammates from going idle without actually completing work. |
| `task-completed.py` | TaskCompleted | Rejects explicit failures and verifies non-empty paths declared by a `Completion-Contract` in `task_description` | Research/no-diff tasks remain valid; workflows that require artifacts cannot close on missing, empty, partial, truncated, or prompt-too-long outcomes. |

### Other wired hooks

Every remaining hook that settings.json wires, so `bin/architecture-drift-check.py` can hold the inventory complete.

| Hook | Event | What it does | Why it exists |
|---|---|---|---|
| `cklb-to-md.py` | PreToolUse(Read) | PreToolUse hook for Read: Auto-convert .cklb (STIG checklist JSON) to Markdown | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `compaction-continuity.py` | PostCompact, UserPromptSubmit | Carry a re-invoke reminder across a compaction boundary | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `config-change-validate.py` | ConfigChange(user_settings\|project_settings\|local_settings) | Validate settings after a Claude Code ConfigChange event.""" | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `git-empty-push-guard.py` | PreToolUse(Bash) | PreToolUse:Bash — BLOCK `git push` of a branch with 0 commits ahead | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `kql-schema-hint.py` | PreToolUse(mcp__remote-msgraph__call_tool\|mcp__msgraph__call_tool) | KQL schema-hint hook for Defender Advanced Hunting queries (RC1) | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `mcp-truncation-signal-guard.py` | PostToolUse(mcp__.*) | Advisory PostToolUse guard: surface MCP truncation signals on the main thread | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `nessus-to-md.py` | PreToolUse(Read) | PreToolUse hook for Read: Auto-convert .nessus (Tenable XML) to Markdown | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `pr-duplicate-preflight.py` | PreToolUse(Bash) | PreToolUse:Bash — BLOCK `gh pr create` when one of YOUR open PRs already | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `security-write-confirm.py` | PreToolUse(mcp__.*) | PreToolUse hook: require user confirmation before security write operations | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `skill-ref-validator.py` | PostToolUse(Write\|Edit) | PostToolUse hook for Edit|Write: warn on dead hook/script refs in SKILL.md | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `staged-additions-guard.py` | PreToolUse(Bash) | PreToolUse:Bash — BLOCK `git commit` when staged ADDITIONS coexist with | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `stale-checkout-before-analysis.py` | PreToolUse(Read\|Grep\|Glob) | PreToolUse:Read|Grep|Glob — advise when analysis reads a BEHIND checkout | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `worktree-remove-snapshot.py` | WorktreeRemove | WorktreeRemove: snapshot uncommitted work before a worktree disappears | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `write-edit-dispatcher.py` | PreToolUse(Write\|Edit) | Consolidated PreToolUse:Write|Edit dispatcher | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |
| `xlsx-to-md.py` | PreToolUse(Read) | PreToolUse hook for Read: Auto-convert .xlsx workbooks to Markdown | Documented 2026-09-04 when the drift check's hooks-section parser was fixed; see the source docstring for the full rationale. |

## Design Principles

1. **Exit 0 = allow, exit 2 = block.** No ambiguity in hook behavior.
2. **Hooks don't ask the agent to remember — they fire mechanically.** The `encoding='utf-8'` check runs on every Python write whether the agent thinks about encoding or not.
3. **Guard hooks block silently dangerous operations. Visible errors don't need guards.** A `SyntaxError` is self-correcting (agent reads the traceback). But cp1252 encoding silently mangles Unicode with no error — that needs a guard.
4. **Every hook was tested retroactively against session transcripts before shipping.** The python-script-guard incident (85.6% block rate on historical commands) proved that unit tests alone don't catch aggressive hooks. Retroactive testing against 1-2 weeks of real tool calls is required.
5. **`if` conditions prevent unnecessary process spawning.** The Read converters (`nessus-to-md.py`, `cklb-to-md.py`, `xlsx-to-md.py`) use `if: "Read(*.nessus)"` and friends — they spawn only for those file types, not the 99% of Read calls that are source files. (Claude Code reads PDFs natively, so no PDF converter is needed.)

## Creating New Hooks

1. Write a Python script in `hooks/`
2. Register it in `settings.json` under the appropriate event type
3. Run unit tests against known good and bad inputs
4. **Run retroactive testing** against 1-2 weeks of session transcripts before shipping
5. If block rate exceeds 10%, the hook is too aggressive — tune before shipping

See the `ship-hook` skill for the full installation workflow.
