# Architecture Audit Finding Codes

Each finding emitted by `/audit-architecture` carries a code from the
table below. The code determines severity defaults and the reproducer
pattern to use. Always write the most specific reproducer type possible
(prefer `grep`/`file_missing` over `manual`).

## Code categories

### R — Runtime (Phase 0)

| Code | Default severity | Description |
|------|-----------------|-------------|
| R1 | drift | MCP probe failure — connectivity probe returned FAIL or timed out |
| R2 | drift | Stale file path — a path in config or a hook command does not exist on disk |
| R3 | drift | Config syntax error — JSON parse failure in `~/.mcp.json`, `settings.json`, etc. |
| R4 | drift | Credential exposure — API key or token found inline in config (not in env var) |
| R5 | info | Orphan process — MCP server has more instances than active Claude Code sessions |
| R6 | info | FastMCP version below 3.0 on a stdio Python MCP server |

**Reproducer patterns:**

```yaml
# R2 — stale file path
reproducer:
  type: file_missing
  path: /the/missing/path.py

# R3 — config syntax error
reproducer:
  type: bash
  command: |
    python3 -c "import json; json.load(open('~/.mcp.json'))"
  expected_exit: 1

# R4 — credential in config
reproducer:
  type: grep
  command: |
    grep -qE 'tskey-[a-zA-Z0-9]+' ~/.mcp.json
```

### C — Coverage (Phase 2)

| Code | Default severity | Description |
|------|-----------------|-------------|
| C1 | info | No owning agent — no agent's allowlist covers this MCP server |
| C2 | drift | No routing rule — server's keywords absent from `skill-rules.json` |
| C3 | info | No PreToolUse validation — no PreToolUse hook covers `mcp__{server}__*` |
| C4 | info | No topic file — no populated `agent-memory/topics/{server}.md` (topic-file tier covers agent memory) |
| C5 | info | No agent memory — owning agent's memory directory has 0 entries |
| C6 | info | Missing CLAUDE.md delegation row — server not mentioned in delegation table |

**Reproducer patterns:**

```yaml
# C2 — no routing rule
reproducer:
  type: grep_absent
  command: |
    grep -q 'server-keyword' ~/.claude/hooks/skill-rules.json

# C4 — no topic file
reproducer:
  type: file_missing
  path: /home/<user>/.claude/agent-memory/topics/<server>.md

# C6 — missing CLAUDE.md row
reproducer:
  type: grep_absent
  command: |
    grep -qi 'server-name' ~/.claude/projects/<encoded>/CLAUDE.md
```

### Q — Quality (Phase 2b)

| Code | Default severity | Description |
|------|-----------------|-------------|
| Q1 | info | Skill scores below 12/17 on skill_quality_audit.py |

### S — Self-audit (Phase 2c)

| Code | Default severity | Description |
|------|-----------------|-------------|
| S1 | info | Stale probe target — server name in `references/probe-targets.md` has no matching real server |
| S2 | drift | Broken path reference — path cited in SKILL.md or `references/*.md` doesn't exist |
| S3 | info | Stale fix classification — fix type in `references/scoring-and-output.md` no longer appears in current findings |

**Reproducer patterns:**

```yaml
# S2 — broken path reference
reproducer:
  type: file_missing
  path: skills/audit-architecture/references/the-missing-file.md
```

### D — Documentation (Phase 3)

| Code | Default severity | Description |
|------|-----------------|-------------|
| D1 | info | Agent denylist mismatch — `disallowedTools` in agent .md differs from what ARCHITECTURE.md documents |
| D2 | info | Routing rule/CLAUDE.md mismatch — rule in `skill-rules.json` has no matching delegation row, or vice versa |
| D3 | info | ARCHITECTURE.md count wrong — documented server/agent/hook count differs from actual |
| D4 | info | Documented phantom — server appears in ARCHITECTURE.md but not in any config |
| D5 | info | Undocumented server — server in config but missing from ARCHITECTURE.md |
| D6 | info | Agent template drift — agent `.md` drifted from the pattern in `TEMPLATE.md` |
| D7 | info | Registry mismatch — skill or agent listed in MEMORY.md but no corresponding file, or vice versa |

**Reproducer patterns:**

```yaml
# D4 — documented phantom server
reproducer:
  type: bash
  command: |
    grep -q 'phantom-server' ~/.claude/ARCHITECTURE.md && \
      ! python3 -c "
    import json
    cfg = json.load(open('$HOME/.mcp.json'))
    assert 'phantom-server' in cfg.get('mcpServers', {}), 'not in config'
    "
  expected_exit: 0

# D5 — undocumented server (in config but not in docs)
reproducer:
  type: grep_absent
  command: |
    grep -qi 'new-server-name' ~/.claude/ARCHITECTURE.md

# D3 — count wrong in ARCHITECTURE.md
reproducer:
  type: bash
  command: |
    documented=$(grep -oP '(?<=has )\d+(?= MCP)' ~/.claude/ARCHITECTURE.md | head -1)
    actual=$(python3 -c "import json; d=json.load(open('$HOME/.mcp.json')); print(len(d.get('mcpServers',{})))")
    [ "$documented" != "$actual" ]
  expected_exit: 0
```

### RH — Routing Health (Phase 4)

| Code | Default severity | Description |
|------|-----------------|-------------|
| RH1 | drift | Overly broad skip pattern — suppresses legitimate operational prompts |
| RH2 | drift | Keyword collision — same keyword in multiple rules; wrong rule wins |
| RH3 | drift | Coverage gap — realistic prompt for an MCP domain matches no routing rule |
| RH4 | info | Rule ordering violation — specific rule comes after a broad catch-all |

### SC — Scaling (Phase 5)

| Code | Default severity | Description |
|------|-----------------|-------------|
| SC1 | info | MEMORY.md approaching token capacity |
| SC2 | info | Denylist complexity growing quadratically with agents × MCPs |
| SC3 | info | Topic file stub not populated after multiple audit cycles |
| SC4 | info | Agent memory severely over-accumulated (>25 entries) or empty (0 entries, agent is in use) |

### L — Self-Improvement Loop (Phase 6)

| Code | Default severity | Description |
|------|-----------------|-------------|
| L1 | drift | Error learning gap — PostToolUseFailure matcher doesn't cover `mcp__.*\|Bash` universally |
| L2 | info | Missing cross-session memory — agent lacks `memory: user` or has no memory directory |
| L3 | info | Incomplete preflight — MCP server with destructive writes has no PreToolUse hook |
| L4 | info | Non-wildcard SubagentStop — matcher hardcoded to specific agents, misses new ones |

## Reproducer authoring guidance

1. **Prefer `grep` / `grep_absent`** for simple presence/absence checks in known files.
2. **Use `file_missing` / `file_exists`** for path existence checks — more reliable than bash `[ -f ... ]`.
3. **Use `bash`** when you need to combine multiple conditions or do light computation.
4. **Use `python`** when you need to parse JSON or compute non-trivial values.
5. **Use `manual`** only when no deterministic predicate is feasible. Findings with `type: manual` must have `label: unverified` — they cannot be acted on autonomously. The only extra field a manual reproducer accepts is `description:` (NOT `note:` — the oracle's Reproducer dataclass rejects unknown fields with a parse error):

   ```yaml
   reproducer:
     type: manual
     description: "friction evidence cannot be machine-checked; requires a real user prompt"
   ```
6. For any path embedded in a reproducer, use absolute paths or paths relative to the repo root (the oracle runs reproducers from `REPO`).
7. Don't embed absolute HOME paths — use `$HOME` in bash reproducers or `Path.home()` in python ones.
8. **Deployed-path probes are intentional for /audit-architecture.** This skill audits the LIVE
   deployed config, so its reproducers legitimately probe `$HOME/.claude` (the deployed tree).
   The oracle emits a `DEPLOYED_PATH_PROBE` advisory for these ("adjudicates the deployed tree,
   not the tree under test, and cannot flip pre-merge") — that advisory is EXPECTED here, not an
   error. A deployed-state audit cannot use repo-root-relative reproducers, because the artifact
   under audit IS the deployed tree. Do not rewrite these reproducers to silence the advisory.

## Reproducer fires-semantics (exit-code convention per type)

The oracle decides STILL-FIRES vs STALE from the reproducer's exit code, and **the convention differs per type** — getting it backwards silently mis-grades a real finding as STALE (observed 2026-06-16: a `python` reproducer written as `exit 0 = fires` was dropped STALE while the live behavior still reproduced):

| Type | Fires (bug present / STILL-FIRES) when… |
|------|------------------------------------------|
| `grep` | the pattern **matches** (exit 0) |
| `grep_absent` | the pattern is **absent** (exit 1) |
| `bash` | exit code **== `expected_exit`** (default `0`) — set `expected_exit` to the code that means "bug present" |
| `python` | the script exits **NON-ZERO** — `exit 0` = no-fire/STALE. This is the opposite of the intuitive "0 = success"; in a `python` reproducer, `sys.exit(1)` means *the bug is present*. |
| `file_missing` | the path **does not exist** |
| `file_exists` | the path **exists** |

Rule of thumb: write the predicate so **"the bug is present" maps to the firing exit code above**. For `python`, that is `sys.exit(0 if bug_is_gone else 1)`.
