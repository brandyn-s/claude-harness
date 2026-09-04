---

name: audit-architecture
description: "Audit the Claude Code architecture for drift and coverage gaps across MCP servers, agents, hooks, skills, and rules."
when_to_use: "Use when asked to audit the Claude Code architecture, validate system health after changes, or find drift and coverage gaps across MCP servers, agents, hooks, skills, and routing rules. Runs live runtime probes, coverage analysis, consistency checks, and offers ranked batch fixes. Do NOT use for simple status checks (/healthcheck), single-component debugging (/systematic-debugging), or querying a specific MCP tool."
disable-model-invocation: true
argument-hint: "[optional focus, e.g. 'hooks', 'topics', 'routing', 'skills', 'MCP servers']"
effort: high
metadata:
  author: example-security-engineering
  version: "2.0"
  body-cap: exempt
  body-cap-reason: "PERIODIC: an architecture audit producing dated findings snapshots, hidden from model routing"
allowed-tools: Agent AskUserQuestion Bash Edit Glob Grep Read Write
---

# Architecture Audit

Comprehensive meta-analysis of the Claude Code architecture. Dynamically discover all components, run live runtime probes, evaluate across 8 dimensions, rank findings by impact, and offer batch fixes.

> **Before starting Phases 0–6**: Read `audit-context.md` in this skill's directory. It documents repo-wide ground truth (which config files are authoritative, known-OK deviations, severity calibration) so you don't false-flag patterns that are fine in this environment.

> **Suppression**: If `audit-suppress.yaml` exists in this skill's directory, skip any finding whose code + target matches a suppression entry. Note the suppression in the report with its documented reason.

> **Focus area**: If the user provided an argument (e.g., `/audit-architecture hooks`), narrow the audit to that component. Always run Phase 0 (runtime health) and Phase 7 (oracle gating + rank). Skip phases and per-phase steps that don't touch the focus:
> | Focus argument | Phases to run | Phases to skip |
> |---|---|---|
> | `hooks` | 0, 1, 3 (steps 7-8, 10), 5 (denylist + memory), 6, 7 | 2, 2b-d, 4, 3 (skill/MCP rows) |
> | `topics` | 0, 1, 3 (step 5-6), 5 (pattern files), 7 | 2, 2b-d, 4, 6 |
> | `routing` | 0, 1, 4, 7 | 2, 2b-d, 3, 5, 6 |
> | `skills` | 0, 1, 2b, 2c, 2d, 7 | 2 (MCP rows), 3 (MCP), 4, 5, 6 |
> | `MCP servers` | 0, 1, 2, 3 (MCP rows), 4 (MCP domains only), 7 | 2b-d, 5, 6 |
> When skipping a phase, still list it in the report header as `SKIP (focus=<arg>)` so the reader knows what's missing.

## Phase 0: Runtime Health Probes

Run live checks FIRST — these find problems that static analysis cannot.

**Platform gate**: Check `platform.system()` before running performance probes. The CPU/memory/process-dedup probes below use Windows-only APIs (`CreateToolhelp32Snapshot`, `kernel32.GetProcessTimes`, `psapi.GetProcessMemoryInfo`, `Get-CimInstance`). On non-Windows hosts, either substitute `psutil` (`cpu_percent`, `memory_info`, `cmdline`) for the same measurements, or skip the performance subsection and report `SKIP — non-Windows host`. **macOS fallback (no psutil):** rather than a total no-op, run the two cheap native probes — process **dedup/orphan** via `pgrep -f <substring>` counts (PIDs only), and **memory** via `ps -o rss=,comm=` summed across matched PIDs. **Derive the substring per server from its EXEC'D form, not its config**: launcher scripts (`*-mcp-launch`) exec their child, so `pgrep -f` on the launcher path returns 0 — match the script basename (`jamf_mcp_server.py`) or the npm form (`npm exec tavily-mcp`) instead. Never use a generic `mcp` pattern — it sweeps in unrelated processes and inflates the footprint to a meaningless number (`references/run-history.md`). NEVER use `ps -o args=`/`command=` or `pgrep -a`/`pgrep -lf` (they dump argv, which leaks launcher-inlined secrets — see platform-constraints.md). Idle-CPU sampling has no cheap safe native equivalent — SKIP it. Reliability probes (connectivity, hook exec, stale paths, config syntax, credential scan) run on all platforms.

**Probe error handling**: If any probe crashes (ctypes permission denied, CimInstance unavailable, MCP tool timeout, psutil import error), report that probe as `SKIP — {error}` and continue with remaining probes. Never let a single probe failure stall the entire audit.

### Performance Probes (Windows-only without psutil)

**MCP idle CPU:** Write and run a Python script that:
1. Enumerates all Python processes via `CreateToolhelp32Snapshot` (Windows) or `psutil.process_iter(['name', 'cmdline'])` (cross-platform)
2. Snapshots CPU via `kernel32.GetProcessTimes` or `psutil.Process.cpu_times()`
3. Waits 15 seconds
4. Snapshots again, computes delta
5. Get command line via `Get-CimInstance Win32_Process` (batch) or `psutil.Process.cmdline()`
6. Flag any process >5% idle CPU with server name extracted from command line

**Memory footprint:** Sum `WorkingSet64` via `psapi.GetProcessMemoryInfo` (Windows) or `psutil.Process.memory_info().rss` (cross-platform) across all MCP Python processes. Flag if total exceeds 2GB.

**Process deduplication:** First, count active Claude Code sessions by finding distinct `claude` parent processes. Then group MCP processes by normalized command line. For each unique MCP server, count instances. Expected count per server = number of active sessions. Flag any server with more instances than active sessions. Report: active sessions, expected instances per server, actual count, and excess.

**FastMCP version check:** Verify all stdio Python MCP servers use FastMCP >= 3.0. For each stdio Python server in `~/.mcp.json` AND `~/.claude.json`, read the script file and check for `from fastmcp` imports, then verify the fastmcp version **through each server's own launch interpreter** (resolve the `command`/launcher to its venv python and run `<venv-python> -m pip show fastmcp`). System `pip show fastmcp` is the wrong instrument — on venv-launched fleets it reports NOT INSTALLED while every server runs fine; that result is UNKNOWN, not a finding.

### Reliability Probes

**MCP connectivity:** Probe only the **connectible** class — locally-registered stdio servers and known-authenticated HTTP servers — by calling one lightweight tool each (ping map in `references/probe-targets.md`); flag failures with the specific error message. Do NOT probe **gateway / OAuth-pending** servers (the `*.mcp.example.internal` class whose only exposed tools are `authenticate`/bootstrap): probing them starts an OAuth flow or bills an expensive call. Classify each such server `AUTH-PENDING` (registered, not probed) — this is NOT a connectivity gap. Report R1 as `probed OK / probed FAIL / AUTH-PENDING (not probed)`, never implying full 1-per-server coverage when the gateway class was skipped.

**Hook execution:** Prefer LIVE EVIDENCE over re-execution: the current session's own startup already ran every SessionStart hook, and its injected context (platform digest, banner output) proves execution without side effects. Re-running SessionStart commands can mutate state (`repo_sync`, notifications) — only re-run a hook when no live evidence exists for it (e.g. a hook added since session start), and check its exit code. Flag non-zero.

**Stale file paths:** Read `~/.mcp.json` and `~/.claude/settings.json`. For `args` arrays, check each `.py` and `.ps1` path exists. For hook commands, extract the script path and verify. Flag missing files.

**Config syntax:** JSON-parse `~/.mcp.json` (if present — absent on macOS hosts, where MCP config lives only in `~/.claude.json`), `~/.claude/settings.json`, `settings.local.json`, and project `settings.json`. Flag parse errors.

**Executable collision and plugin-hook guards:** Run both canonical healthcheck
helpers before declaring discovery complete:

```bash
python3 ~/.claude/skills/healthcheck/references/_check_config.py
python3 ~/.claude/skills/healthcheck/references/_check_hooks_aux.py
```

`_check_config.py` hard-fails an **exact case-sensitive standalone MCP versus
skill/command runtime-name collision** (#85827), with both evidence sources; it
does not Unicode-normalize or case-fold unproven aliases, and plugin components
remain informational because Claude namespaces them. Do not substitute a
top-level-only name comparison. `_check_hooks_aux.py` inventories hook
definitions directly from every installed plugin path regardless of enabled
state, resolves user/project/local precedence plus `defaultEnabled`, and exits 2
when relevant metadata is unreadable or malformed. Preserve both outputs as
Phase 0 evidence.

**Knowledge capture health:** On hosts with `~/.claude/session-transcripts/`, check for recent files and /distill + /capture usage in recent retrospectives. On macOS hosts that directory does not exist — use `memory-search`'s `memory_stats` instead (chunk count, last reindex, staleness distribution); a same-day reindex with zero very-stale chunks is a pass.

**Credential exposure check:** Scan `~/.mcp.json` and `~/.claude.json` for patterns matching API keys or tokens in URLs, headers, or env values (e.g., `tskey-`, `Bearer `, `sk-`, API key patterns in query strings). Flag any inline credential that should be in an environment variable.

**Checkout currency (stale-base guard):** The audit reads `~/.claude`, which may be on a feature branch or behind `origin/main` in a contended checkout. Run `git -C ~/.claude fetch origin main` then `git -C ~/.claude rev-list --count HEAD..origin/main`. If the count is > 0, emit a banner in the report header: `findings derived from a checkout N commits behind origin/main — doc/count findings (D3/D4) may already be fixed on main; re-verify against origin/main before acting`. This is not a finding; it calibrates trust in every doc/count finding, and Phase 7 fixes MUST be re-verified against `origin/main` (a worktree cut from it), not the stale working tree. **When the count is > 0, do more than banner it — REDIRECT THE AUDIT BASE:** cut a read-only worktree from `origin/main` (`git -C ~/.claude worktree add --quiet ~/worktrees/cc-audit-base origin/main` — `--quiet` suppresses ~3,500 lines of checkout progress; reuse the path if it already exists and is at the right commit) and run Phase 1 discovery AND both scanners against it by exporting `CLAUDE_CONFIG_DIR=<worktree>` (both `doc_accuracy_audit.py` and `skill_quality_audit.py` honor it). Auditing the stale tree yields an INCOMPLETE finding SET, not just uncertain counts. The banner still describes the DEPLOYED-state delta; the finding set comes from the `origin/main` base. **The redirect covers the skill's own definition too**: the SKILL.md you were invoked with is the DEPLOYED (stale) copy — diff it against the worktree's copy (`git -C ~/.claude diff HEAD origin/main -- skills/audit-architecture/`) and follow the worktree version where phases/steps were added. Measured instances of all three failure shapes: `references/run-history.md`.

## Phase 1: Discovery

**Run the discovery script FIRST** — it covers the deterministic parts of Phases 1, 2, and 6 in one pass and eliminates the ad-hoc-matcher false positives (`references/run-history.md`):

```bash
python3 ~/.claude/skills/audit-architecture/references/discovery.py > discovery.json
# honors CLAUDE_CONFIG_DIR for repo content; runtime state always reads from HOME
```

Use `discovery.json` as the inventory (servers, agents, skills, topics, hooks/matchers), the Phase 2 coverage matrix (`coverage`), and the Phase 6 loop checks (`loops`). The numbered steps below define WHAT the script collects — read them to know what each field means, spot-check any surprising row against the source file, and fall back to manual collection only for steps the script does not cover (plugin hooks, ARCHITECTURE.md content, project settings).

Do NOT hardcode file paths, agent names, or MCP names — discover them from the file system.

> **Project directory resolution**: Resolve `$PROJECT_DIR` once at the start of Phase 1: list `~/.claude/projects/`, filter to directories containing a `CLAUDE.md`, and pick the most-recently-modified one.

1. **MCP servers**: Read `~/.mcp.json` (if present — absent on macOS hosts, where MCP config lives only in `~/.claude.json`) AND `~/.claude.json` to get all defined MCP servers (name, type, enabled/disabled). Enumerate BOTH the top-level `mcpServers` key AND all `projects[*].mcpServers` entries. Tag each server with its scope (`user` vs `project:<path>`). Use Python `json.load()` for atomic read of `~/.claude.json`.
2. **Agents**: Glob `~/.claude/agents/*.md` (excluding `TEMPLATE.md`, `README.md`) — extract name, `disallowedTools`, `memory`, `skills` from frontmatter and body
3. **Skills and legacy commands**: Inventory `~/.claude/skills/*/SKILL.md` and `~/.claude/commands/*.md`; for the active project, inspect `.claude/skills/` and `.claude/commands/` in the starting directory and every parent through the repository root, plus nested `.claude/skills/` directories that can load on file access. Also inventory plugin default/custom/root skill shapes for visibility. Personal/project skill runtime identity is the directory name and command identity is the file stem; frontmatter `name` is display-only there. Use the executable guard for exact case-sensitive standalone MCP collisions only; do not hard-fail a bare standalone name against a plugin component.
4. **Hooks**: Read `~/.claude/settings.json` — extract all hook entries by event type with their matchers and types. For each agent `.md` file, also check for `hooks:` in YAML frontmatter. Include agent-scoped hooks tagged as 'agent-scoped'.
5. **Plugin hooks**: Read `~/.claude/plugins/installed_plugins.json`, then inspect every recorded `installPath` for `.claude-plugin/plugin.json` and `hooks/hooks.json`. A manifest `hooks` string/array/object field replaces the default hook file; never treat `.claude-plugin/hooks.json` or root `hooks.json` as implicit defaults. Require custom paths to start with `./` and remain contained after resolution. Inventory definitions independently of enablement and `/hooks`; tag plugin id, tri-state enabled/disabled/unknown state, state source, event, matcher, and exact source path. Resolve `enabledPlugins` with local > project > user precedence, then marketplace/manifest `defaultEnabled`. Treat malformed/unreadable relevant metadata as incomplete discovery, not zero hooks. Surface disabled definitions because upstream #85893 shows they can remain active after disablement, and report unresolved state separately.
6. **CLAUDE.md**: Read `$PROJECT_DIR/CLAUDE.md` — extract delegation tables
7. **MEMORY.md**: Read `$PROJECT_DIR/memory/MEMORY.md` — note total line count
8. **Topic files**: Glob `~/.claude/agent-memory/topics/*.md` — for each, read first 5 lines to determine stub vs populated. (The former `memory/*-patterns.md` tier was retired 2026-06-10 with the T3 collapse — B7/F3.)
9. **Agent memory**: Glob `~/.claude/agent-memory/*/` — list directories, count entries, check last-modified date
10. **ARCHITECTURE.md**: Read `~/.claude/ARCHITECTURE.md` — the documented architecture for drift comparison
11. **Project settings**: Read `$PROJECT_DIR/settings.json` — check for `disabledMcpServers`

## Phase 2: Coverage Analysis

Start from `discovery.json`'s `coverage` map (topic file, PreToolUse, CLAUDE.md mention — with the maintained alias map, so `palantir-mcp` → `palantir-foundry.md` resolves and no loose prefix matching occurs). Apply the host profile in `audit-context.md` before flagging: C1/C5 may be N/A by design. For each MCP server discovered in Phase 1, the dimensions are:

| Dimension | How to check |
|---|---|
| **Has owning agent?** | For allowlist agents (those with a `tools:` field), check if the server matches any allowlisted pattern. For denylist agents (those with `disallowedTools:`), check if the server is NOT denied. A server has an owning agent if it matches at least one agent's allowlist OR is not denied by at least one denylist agent. |
| **Has PreToolUse validation?** | A PreToolUse matcher covers `mcp__{server}__*` tools |
| **Has populated topic file?** | An `agent-memory/topics/{server}.md` exists and is NOT a stub (T3 pattern-file tier retired 2026-06-10) |
| **Has agent memory accumulation?** | The agent that owns this server has a memory directory with >0 entries |
| **Has delegation row in CLAUDE.md?** | The server or its keywords appear in the CLAUDE.md delegation table |
| **Connectivity OK?** | Phase 0 ping succeeded |
| **Idle CPU OK?** | Phase 0 CPU check passed (<5%) |

**Disabled server bypass**: For each disabled MCP server (from `disabledMcpServers` in project settings), verify it is also in the `disallowedTools` of all agents. Flag if a disabled server is accessible to any agent.

Build a coverage matrix table. Flag any MCP server with gaps.

## Phase 2b: Skill Quality Evaluation

Run the automated skill quality scanner:

```bash
python3 ~/.claude/skills/audit-architecture/references/skill_quality_audit.py >quality.json 2>quality_report.txt
# Windows/Git Bash: use the explicit C:/Users/<you>/.claude/... path here AND for every
# scanner/oracle invocation in this skill (Phase 3 doc_accuracy_audit.py, Phase 7
# audit-skill-oracle.py). `~/` expands to /c/Users/... which native python.exe reads as a
# literal C:\c\Users\... → "can't open file" (platform-constraints.md → msys_path_to_native_windows_binary).
```

The scanner evaluates all skills against S1-S7 (structure), C1-C7 (content quality), X1-X3 (composability) from `references/skill-quality-checklist.md`, plus:
- `effort:` field presence
- Reference path validation (orphaned files in `references/` and broken references in SKILL.md)
- Body size against the Anthropic 500-line cap

Note: the scanner does NOT check whether trigger phrases appear in the first 250 chars of the description for `/skills` menu visibility. The 250-char menu truncation is still worth manual review, just not via this scanner.

Flag any skill scoring below 12/16 for remediation. Include specific FAIL items in the findings. For skills that only fail on X1 (false positive from precedence language), note as acceptable if they are manual-invoke-only.

## Phase 2c: Self-Audit

Verify the audit skill's own references are accurate:

1. **Probe target accuracy**: Run `python3 ~/.claude/skills/audit-architecture/references/gen_probe_targets.py --check` — the current-host block of `probe-targets.md` is GENERATED from live config between markers; exit 1 means drift (fix with `--write`, which is idempotent — never hand-edit inside the markers). The Windows-era/prior-host sections below the markers remain prose; only flag those if a listed server contradicts a live one.
2. **File path validity**: Verify all file paths referenced in SKILL.md and `references/*.md` actually exist on disk. Flag broken paths.
3. **Fix-safety classifications**: Verify the fix types listed in `references/scoring-and-output.md` correspond to actions still emitted by Phases 0-6 — flag any classification whose category no longer appears in current findings.
4. **Coverage matrix fallback**: For servers not in `probe-targets.md`, use ToolSearch to attempt loading any tool as a connectivity check.

## Phase 2d: Skill Portfolio Health Check

Audit ALL skills discovered in Phase 1 (Step 3) for frontmatter compliance, structural integrity, and operational readiness.

### Frontmatter Field Compliance

For each skill, verify these fields exist in YAML frontmatter:

| Field | Required | Check |
|---|---|---|
| `name` | Yes | Must match folder name exactly |
| `description` | Yes | Must be under 1024 chars total. First 250 chars must contain primary trigger phrases (v2.1.86 truncation). |
| `effort` | Recommended | Must be one of: `low`, `medium`, `high`, `max`. Flag skills missing effort. |
| `disable-model-invocation` | Conditional | Required for expensive maintenance skills. Flag if present on lightweight utility skills. |
| `maxTurns` | Informational | If present, verify upstream bug #41143 annotation exists in body. Flag unannotated maxTurns as misleading. |
| `context` | Conditional | If set to `fork`, verify the skill body does NOT dispatch Agent tool workers. |
| `model` | Conditional | If set to `sonnet`, verify the skill does not require complex reasoning or multi-step conditional logic. |

### Required Sections Audit

Per `rules/skill-standards.md`, every skill MUST have:

1. **Examples section** — at least 2 concrete usage examples. Grep for `## Examples` or `## Example`. Flag skills with 0-1 examples.
2. **Success Criteria section** — measurable outcomes. Grep for `## Success Criteria`. Flag skills missing this section entirely.

Build a compliance matrix:

```
| Skill | effort | examples | success_criteria | desc_250 | maxTurns_ok | fork_safe | Rating |
|---|---|---|---|---|---|---|---|
| superplan | high | 3 | yes | yes | n/a | n/a | PASS |
```

### Reference Path Validation

1. Glob each skill's `references/` directory (if it exists)
2. Grep the SKILL.md body for all `references/` and `_shared/` path mentions
3. Verify every referenced path actually exists on disk
4. Flag broken references (file mentioned but doesn't exist)
5. Flag orphaned references (file exists in `references/` but never mentioned in SKILL.md)

### Effort Distribution Analysis

1. Count skills at each level: `low`, `medium`, `high`, `max`, and `missing`
2. Cross-reference `model: sonnet` skills — these should typically have `effort: low` or `effort: medium`
3. Cross-reference `context: fork` skills — fork context has 200K limit, so `effort: max` may be wasteful
4. Flag mismatches

### Portfolio Summary

Produce a one-paragraph summary: total skills, compliance rate, top 3 issues by frequency, and recommended batch fix actions.

## Phase 3: Consistency Analysis

Run the automated documentation accuracy scanner first:

```bash
python3 ~/.claude/skills/audit-architecture/references/doc_accuracy_audit.py >doc_accuracy.json 2>doc_report.txt
```

The scanner checks ARCHITECTURE.md, CLAUDE.md, and MEMORY.md against actual disk state. JSON to `doc_accuracy.json`, human-readable to `doc_report.txt`.

> **CLAUDE_CONFIG_DIR caveat**: when the stale-base guard redirects the scanners to an origin/main worktree, the worktree's `projects/<encoded>/` dir exists (CLAUDE.md is versioned) but its `memory/` subdir does not — memory is gitignored runtime state. The scanner falls back to the deployed tree's memory for the same project (stderr `note:` line). If the report instead prints `MEMORY.md: SKIP — check did not run` (or, on a pre-fallback scanner version, `0 issues (0/200 lines, 0 links)`), the check DID NOT RUN — re-run once with `CLAUDE_CONFIG_DIR` unset and take only the MEMORY.md section from that deployed-base run (discard its ARCHITECTURE/CLAUDE results; the stale tree invalidates those).

After the automated scan, cross-reference sources for contradictions:

0. **Identifier and hidden-hook guards**: Reconcile the full Phase 1 inventories with `_check_config.py` and `_check_hooks_aux.py`. Any exact case-sensitive standalone MCP/skill-or-command runtime-name collision is behavior-impacting drift; case/Unicode variants and plugin namespaces are negative controls, not findings. Any disabled or unknown-state plugin hook definition must remain visible with its evidence even if `/hooks` omits it; an incomplete plugin inventory blocks a clean verdict.
1. **Agent denylists**: Compare `disallowedTools` in each agent `.md` file vs what ARCHITECTURE.md documents. Flag mismatches.
2. **ARCHITECTURE.md counts**: Compare documented MCP server count vs actual. Compare documented agent count vs actual. Compare documented hook count vs actual.
3. **ARCHITECTURE.md MCP bidirectional diff**: Extract every MCP server name from ARCHITECTURE.md (all three tables: remote, local stdio, hosted/remote utility). Compare against the Phase 1 discovery inventory in BOTH directions: (a) servers documented but not in config → flag as "documented phantom", (b) servers in config but not documented → flag as "undocumented server".
4. **Agent transparency**: Read TEMPLATE.md and compare the transparency/memory section against each agent. Flag agents that have drifted from the template.
5. **MEMORY.md registry**: Compare the agent list in MEMORY.md vs actual `~/.claude/agents/` directory. Flag missing or extra entries.
6. **Skills registry**: Compare MEMORY.md skills list vs actual `~/.claude/skills/` directories. Flag missing or extra entries.
7. **Shell conventions**: Verify hook commands use the cross-platform `run-hook` launcher (resolves to `python3` on macOS, `pythonw.exe` on Windows), not a hardcoded interpreter. (Prior Windows-host check: `pwsh` not `powershell`.)
8. **Adding-a-New-Agent checklist**: Check if ARCHITECTURE.md documents all necessary steps — and whether the SubagentStop matcher is wildcarded (`.*`) or hardcoded.
9. **Security-confirmation validation**: Verify `security-confirmations.md`: For each destructive action category, verify at least one confirmation mechanism exists.

## Phase 4: Routing Health — retired

Retired 2026-09-03. Skills route natively from their SKILL.md frontmatter
descriptions; the static `hooks/skill-rules.json` table and the
`skill-routing-hint` hook were removed, so there are no skip patterns, keyword
collisions, or rule orderings left to audit. The phase number is kept so Phases
5-7 keep their stable IDs.

## Phase 5: Scaling Projections

Evaluate growth health:

1. **MEMORY.md capacity**: Estimate token count (lines x avg ~15 tokens per line). Compare against ~5K token context budget. Project what adding 5 more MCPs and 3 more agents would cost.
2. **Denylist complexity**: Count total denylist entries across all agents. Calculate O(agents x MCPs) overhead. Project at N+3 agents.
3. **Topic files**: Count stubs vs populated. Flag stubs that have existed since the last audit.
4. **Agent memory size**: For each agent, count total entries in memory files. Flag agents with 0 entries (never used?) or >25 entries (needs consolidation).

## Phase 6: Self-Improvement Loop Validation

Start from `discovery.json`'s `loops` section (PostToolUseFailure universality, SubagentStop wildcard, per-agent `memory:` fields, gather-skill presence). Check that all feedback loops from ARCHITECTURE.md are functional:

| Loop | What to check |
|---|---|
| **Error Learning** | PostToolUseFailure matcher covers `mcp__.*\|Bash`? Should be universal. |
| **Cross-Session Memory** | Every agent has `memory: user` in frontmatter? Memory directory exists? |
| **Pre-flight Prevention** | Which MCPs are covered by PreToolUse matchers? Which are NOT? |
| **Transparency + Human Audit** | SubagentStop matcher is `.*` (wildcard)? Or hardcoded to specific agents? |
| **Pattern Promotion** | Any agent memory entries with 3+ `[confirmed]` tags? (candidates for promotion to agent .md) |
| **Intelligence Gathering** | `/gather-intel` and `/gather-internal-intel` skills exist? |

## Phase 7: Emit Findings, Oracle Gating & Fix

### Phase 7A: Self-Challenge + Emit YAML

For each finding from Phases 0–6, complete this checklist before emitting it to the findings file:

1. **Alternative explanation**: State one plausible alternative that would make this finding a false positive. If you cannot disprove the alternative with evidence already collected, downgrade to `[unverified]`.
2. **Data dependency**: Which Phase 1 discovery data does this finding depend on? If a finding sharing the same data source was already disproven, flag this finding SUSPECT.
3. **Code verification**: Have you read the relevant source code? If recommending "add pruning," verify pruning doesn't already exist.
4. **Compare-by-need gate**: Does the finding describe concrete user friction or is it purely rubric-derived? If purely rubric-derived AND the target component is working correctly, tag `[RUBRIC-ONLY]` and place below all real-friction findings.
5. **Measurement gate**: Does the fix involve a numeric threshold? Is there empirical evidence? If not, tag `[UNMEASURED]`.

Drop any finding that fails all five checks. Downgrade findings that fail one check.

**Suppression**: Before emitting, check `audit-suppress.yaml`. Skip any finding whose code + target matches a suppression entry with a valid reason. Log suppressed findings in the report.

**Rubric-bias warning**: The `skill_quality_audit.py` scanner has a history of producing findings that violate compare-by-need. Before surfacing any finding sourced only from the scanner's rubric, apply gate 4 above and verify the skill is actually broken from a user's perspective.

**Concrete FP pattern — broken-reference detection on meta-references:** the scanner's "broken refs" check greps SKILL.md for `references/<name>.md` mentions and flags any whose file doesn't exist, without distinguishing META-references (a placeholder like `references/X.md` in prose, a path inside a YAML schema example, a path inside a `reason:` example — `references/run-history.md`) from LITERAL citations. Before auto-fixing a "broken ref" finding, READ the cited line and surrounding context; if the path appears inside a code block, backtick-wrapped placeholder string, YAML example, or "the scanner flags X" prose, the finding is an FP — the file is meta-cited, not literally cited.

**Emit findings to YAML**: Write all surviving findings to `~/.claude/agent-memory/sentinel/audit-architecture-findings.yaml` (the canonical file the oracle reads) AND copy the same content to a dated snapshot `audit-architecture-findings-<YYYY-MM-DD>.yaml` in that dir. The dated snapshot survives concurrent-session churn — a parallel session can delete the canonical file mid-run, which silently destroys delta history; the dated snapshots are the durable per-run record the delta step reads. For each finding, write a machine-checkable reproducer using the patterns in `references/finding-codes.md`. Findings that cannot be expressed as grep/bash/python/file_exists/file_missing must use `type: manual` and `label: unverified`.

**Run the two-way pairing contract-check**: `type: manual` ⟺ `label: unverified`. Any finding with `type: manual` + `label: behavior-fix` or `doc-fix` violates the contract — backfill a real reproducer or demote the label to `unverified` before proceeding.

### Phase 7B: Oracle Gating

Run oracle reverify against every surviving finding:

```bash
~/.claude/bin/audit-skill-oracle.py reverify \
    ~/.claude/agent-memory/sentinel/audit-architecture-findings.yaml --json
```

- **STILL-FIRES**: include in the ranked report.
- **STALE**: drop — the bug is no longer reproducible. Do not act.
- **MANUAL**: surface for human review. These remain `[unverified]`.
- **ERROR**: report as an instrument problem. Do not act; fix the reproducer.

**Delta tracking**: Diff this run against the **newest prior dated snapshot** (`audit-architecture-findings-*.yaml`, excluding today's) — NOT the canonical file, which a concurrent session may have already overwritten or deleted. Also run `refresh-tracker` to stamp STALE on findings from a previous audit that no longer reproduce:

```bash
~/.claude/bin/audit-skill-oracle.py refresh-tracker \
    ~/.claude/agent-memory/sentinel/audit-architecture-findings.yaml
```

In the final report, include a "Changes since last audit" section: new findings (not in the previous file), resolved findings (now STALE), findings that changed score.

For `[behavior-fix]` findings only, also prepare Layer D fix-loop verification (run pre-fix and post-fix reproducer before reporting any fix as applied).

### Phase 7C: Pre-Action Gate (MANDATORY before any fix batch)

Before applying any fix — whether manual or dispatched — run:

```bash
~/.claude/bin/audit-skill-oracle.py act-on \
    ~/.claude/agent-memory/sentinel/audit-architecture-findings.yaml \
    --out ~/.claude/agent-memory/sentinel/audit-architecture-worklist.yaml
```

This re-runs reverify, drops STALE findings, and emits only STILL-FIRES + MANUAL + ERROR findings. Dispatch all fixes against `audit-architecture-worklist.yaml`, never the raw findings file.

> **Expected advisory — `DEPLOYED_PATH_PROBE`:** this skill audits the LIVE deployed config, so its reproducers intentionally probe `$HOME/.claude` (the deployed tree). The oracle's `DEPLOYED_PATH_PROBE` advisory ("adjudicates the deployed tree, not the tree under test") is therefore EXPECTED here, not an error to fix — a deployed-state audit cannot use repo-root-relative reproducers because the thing under audit IS the deployed tree. Treat these advisories as informational; do not rewrite the reproducers to silence them.

Consult the **Fix Safety Classification** in `references/scoring-and-output.md` to determine which fixes are auto-safe vs require user confirmation.

> **Repo-fix mechanics** (`references/run-history.md`)**:**
> - Any fix touching `skills/`, `hooks/`, or `rules/` needs `python3 scripts/build-marketplace.py` + `git add marketplace/ .claude-plugin/` BEFORE push — the pre-push guard rejects an out-of-sync marketplace, costing a round-trip per forgotten regen.
> - **The marketplace treadmill**: when a fix batch spans multiple PRs that each carry regenerated `marketplace/` + `.claude-plugin/plugin-versions.json`, EVERY merge invalidates every other open branch's generated files (DIRTY/conflict). Either batch all same-subsystem fixes into ONE PR, or merge serially and re-cut each remaining branch from fresh `origin/main` (`git checkout -B <branch> origin/main`, `git checkout <old-tip> -- <source paths>`, regenerate, force-with-lease). Never hand-merge generated files.
> - Worktree cleanup is part of the fix arc: after all PRs reach terminal MERGED state, `git -C ~/.claude worktree remove` BOTH audit worktrees (`cc-audit-base` and the fix worktree). Remove only paths this run created.

**Post-apply verification** (required): For each fix applied via Edit or Write, re-Read the target file immediately after and confirm the intended change is present. Report fixes as `Applied` only when verified on disk, `Attempted (reverted)` otherwise. Include the verification command in the final report.

### Phase 7D: Rank & Report

Score ALL STILL-FIRES findings using the ranking factors in `references/scoring-and-output.md`. Sort by composite score descending. Present top 10 with full detail.

Use the **Output Report Template** in `references/scoring-and-output.md`. The report must include: Coverage Matrix, Findings (ranked), Self-Improvement Loop Status, Scaling Outlook, System Health, and Changes Since Last Audit.

After presenting the report, ask:
```
Apply fixes? Enter "all", specific numbers (e.g. "1,3,5"), or "skip".
```

## Success Criteria

- `audit-context.md` read before Phase 0; `audit-suppress.yaml` consulted and suppressions logged
- Phase 0 runtime probes complete before static analysis begins; no probe failure stalls the audit
- All MCP servers discovered from config files (not hardcoded)
- Coverage matrix includes all 8 dimensions per server
- Every finding self-challenged before emitting to YAML (alternative explanation, data dependency, code verification)
- Every finding has a machine-checkable reproducer or is explicitly `[unverified]` (`manual` ⟺ `unverified`)
- Findings YAML written to `~/.claude/agent-memory/sentinel/audit-architecture-findings.yaml` plus a dated snapshot
- Oracle reverify runs before any finding appears in the ranked report; STALE findings dropped
- Pre-action gate (`act-on`) runs before any fix batch is dispatched
- 0 `[behavior-fix]` findings acted on without Layer D fix-loop verification (pre-fix fires + post-fix stale)
- 0 fixes applied without user confirmation (exception: auto-safe fixes per `references/scoring-and-output.md`)
- Delta section appears in the report when a previous findings file exists (or noted as first run)

## Examples

**Example 1: Routine architecture audit**
User says: "/audit-architecture"
Actions:
1. Phase 0: Run MCP connectivity probes, CPU check, FastMCP version check, knowledge capture health, credential scan
2. Phase 1: Discover 12 MCP servers, 6 agents, 10 skills, 16 hooks
3. Phases 2-6: Coverage matrix, consistency checks, routing health, scaling projections
4. Phase 7A: Screen 15 findings, emit 12 survivors to YAML with reproducers
5. Phase 7B: Oracle gating — 10 STILL-FIRES, 2 STALE (dropped), 0 ERROR
6. Phase 7D: Rank 10 findings — top: 1 broken MCP connection, 2 routing collisions, 1 stale ARCHITECTURE.md count
Result: Audit report with coverage matrix, ranked findings, and batch fix options.

**Example 2: Post-change validation**
User says: "I just added a new MCP server — audit the architecture"
Actions:
1. Phase 0: Connectivity probe finds the new server + checks existing servers
2. Phase 2: Coverage analysis flags gaps — no agent owns it, no routing rule, no pattern file
3. Phase 3: Consistency check finds ARCHITECTURE.md counts are stale
4. Phase 7A: 4 findings emitted with file_missing + grep_absent reproducers
5. Phase 7B: Oracle confirms all 4 STILL-FIRES
6. Phase 7D: User says "all" → 3 auto-safe fixes applied + verified; 1 routing rule fix requires confirmation
Result: System in sync after new server is fully wired in.
