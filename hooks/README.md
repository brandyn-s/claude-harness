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
| `promise-checker.py` | Stop | Catches performative compliance and banned session-closure phrases ("let's continue in a new session") | Prevents the #1 most frustrating agent behavior: stopping early and suggesting a new session. Registered on Stop (it reads `transcript_path`, a Stop field — moving it to StopFailure would silently break it). |

The former `session-stop.py` and InstructionsLoaded validator implementations
were removed after their replacement coverage landed; Git history is the
rollback source. Interactive lifecycle hooks stay bounded, and explicit
workflows own analysis and repair.

### Security Guards (PreToolUse — Blocking)

| Hook | Matcher | What it does | Why it exists |
|------|---------|-------------|---------------|
| `bash-security-guard.py` | `Bash` | Blocks credential exposure (`cat ~/.aws`), data exfiltration (`curl` with env vars), destructive commands (`rm -rf /`), direct pushes to protected repos, forbidden org writes | The single most important security hook. Prevents credential leaks and destructive commands regardless of agent intent. Audit trail in `bash-security-audit.py`. |
| `config-guard.py` | `Write\|Edit` | Blocks attempts to disable hooks via settings.json edits | Self-protection. Prevents an agent or subagent from disabling its own safety net. |
| `memory-write-guard.py` | `Write\|Edit` | Blocks prompt injection patterns and oversized entries in memory file writes | Defends against ASI06 (indirect prompt injection via memory persistence). |
| `search-path-guard.py` | `Glob\|Grep` | Blocks overly broad search paths (home dir, C:/, ~/.claude/plugins) | Prevents ripgrep from scanning gigabytes of irrelevant files. A single broad Grep can timeout for 2 minutes. |
| `block-partial-read.py` | `Read` | Blocks partial reads of critical config files (settings.json, rules/, skills/) | Partial reads cause "string not found" errors on subsequent edits because the agent only saw a fragment. |
| `tavily-search-cap.py` | `mcp__tavily__tavily_search` | Caps `max_results` at 5 | Empirically verified: top 5 results are almost always sufficient. Higher values waste ~2.4M tokens/month in context. |

### Context and Routing (PreToolUse — Non-blocking)

| Hook | Matcher | What it does | Why it exists |
|------|---------|-------------|---------------|
| `pre-agent-dispatch.py` | `Agent` | Warns when dispatching workers that reference authenticated remote MCPs | Sub-agents can't authenticate to MCP Gateway. Warning prevents wasted turns on auth failures. |
| `auto-topic-loader.py` | `mcp__remote-.*` etc. | Auto-loads topic context on first call to each MCP server | Workers get domain-specific gotchas without needing to remember to load them. |
| `pdf-to-text.py` | `Read` (with `if: "Read(*.pdf)"`) | Converts PDF reads to text, saving ~48K tokens per PDF | Claude can't read raw PDF binary. Without conversion, it sees garbage. The `if` filter prevents spawning on 99% of Read calls. |

### Quality Enforcement (PostToolUse)

| Hook | Matcher | What it does | Why it exists |
|------|---------|-------------|---------------|
| `post-write-edit.py` | `Write\|Edit` | Consolidated checker: encoding validation, py_compile syntax check, gitleaks secret scan, ruff format, markdown fix, terraform fmt | Catches encoding errors (cp1252 on Windows), syntax errors, and secret leaks immediately after writing — before they propagate to commits. |
| `post-merge-sync.py` | `Bash` | Auto-syncs local main after `gh pr merge` (checkout main, fetch, rebase) | Prevents local/remote divergence after merges. Without this, the next PR creation fails with "up to date" errors. |
| `result-injection-guard.py` | `mcp__.*` | Scans MCP tool results for embedded instruction patterns | Defends against ASI01 (indirect prompt injection via MCP results). Warns the agent to treat flagged results as data, not instructions. |
| `loop-detector.py` | `mcp__.*\|Bash\|Read\|Glob\|Grep` | Detects no-op loops (3+ identical calls) and retry storms (4+ consecutive failures) | Prevents the agent from burning turns on repeated identical calls that will never succeed. |
| `query-routing-log.py` | `mcp__codebase-memory-mcp__search_code\|mcp__codebase-memory-mcp__search_code_semantic\|mcp__codebase-memory-mcp__query_graph\|mcp__codebase-memory-mcp__search_graph\|mcp__memory-search__memory_search` | Logs queries to JSONL for routing analysis | Provides data for evaluating search quality and routing decisions across sessions. |
| `tavily-research-poll.py` | `mcp__tavily__tavily_research` | Polls async Tavily research tasks for completion | Tavily research is async — without polling, the agent doesn't get results. |
| `bash-security-audit.py` | `Bash` | Logs **security-relevant** Bash decisions (blocks, auto-fixes, advisories) to a JSONL audit trail. Skips `passthrough` events by design, and returns early when `CLAUDE_EFFORT=low` — so it is NOT a complete record of every Bash decision (corrected 2026-07-26). The blocking guard runs regardless. | Security audit trail. Blocked commands are recorded for post-session analysis. |

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

## Design Principles

1. **Exit 0 = allow, exit 2 = block.** No ambiguity in hook behavior.
2. **Hooks don't ask the agent to remember — they fire mechanically.** The `encoding='utf-8'` check runs on every Python write whether the agent thinks about encoding or not.
3. **Guard hooks block silently dangerous operations. Visible errors don't need guards.** A `SyntaxError` is self-correcting (agent reads the traceback). But cp1252 encoding silently mangles Unicode with no error — that needs a guard.
4. **Every hook was tested retroactively against session transcripts before shipping.** The python-script-guard incident (85.6% block rate on historical commands) proved that unit tests alone don't catch aggressive hooks. Retroactive testing against 1-2 weeks of real tool calls is required.
5. **`if` conditions prevent unnecessary process spawning.** `pdf-to-text.py` uses `if: "Read(*.pdf)"` — spawns only for PDF reads, not the 99% of Read calls that are source files.

## Creating New Hooks

1. Write a Python script in `hooks/`
2. Register it in `settings.json` under the appropriate event type
3. Run unit tests against known good and bad inputs
4. **Run retroactive testing** against 1-2 weeks of session transcripts before shipping
5. If block rate exceeds 10%, the hook is too aggressive — tune before shipping

See the `ship-hook` skill for the full installation workflow.
