# Audit Scoring & Output Format

## Finding Ranking Factors

| Factor | Score | Criteria |
|---|---|---|
| Frequency | 1-3 | 1 = rare edge case, 2 = specific workflows, 3 = every session |
| Severity | 1-3 | 1 = cosmetic/doc drift, 2 = degraded performance/missed routing, 3 = broken functionality/data loss |
| Blast radius | 1-3 | 1 = one component, 2 = one domain, 3 = system-wide |

Composite = Frequency x Severity x Blast radius (max 27).

Sort descending. Present **top 10** with full detail. Collapse remaining into count with score range.

Per-finding format:
```
[{category}] {title}
  Impact: {frequency} x {severity} x {blast} (score: {N})
  Fix: {exact change description}
  Files: {paths}
```

## Fix Safety Classification

| Fix type | Auto-safe? |
|---|---|
| FastMCP version < 3.0 on stdio server | Yes (upgrade recommendation) |
| Missing topic file (`agent-memory/topics/`) stub | Yes |
| Stale ARCHITECTURE.md counts/rows | Yes |
| Missing denylist entry in agent | Yes |
| Broken file path in config | Yes |
| Create sentinel baseline on first run | Yes |
| Missing routing rule | Ask first |
| Agent behavior change | Recommend only |
| Hook logic change | Recommend only |
| Security-confirmation gap | Recommend only |
| Credential inline in config | Recommend only |

## Output Report Template

```
## Architecture Audit Report — {date}

### Coverage Matrix
| MCP Server | Agent | Routing | PreToolUse | Topic | Memory | CLAUDE.md | Connect | CPU |
|---|---|---|---|---|---|---|---|---|
| remote-crowdstrike | security-ops | YES | YES | Populated | 3 entries | YES | OK | OK |
...

### Findings (ranked by impact, top 10)
[R1] {title} ...
[C2] {title} ...

{N} additional low-impact findings (scores {min}-{max})

### Self-Improvement Loop Status
| Loop | Status | Details |
|---|---|---|
| Error Learning | HEALTHY | Covers all MCPs via mcp__.* |
...

### Scaling Outlook
- MEMORY.md: {current_lines} lines (~{est_tokens} tokens / ~5K budget)
- Agents: {count} (denylist entries: {total})
- Routing rules: {count} (collision rate: {rate})
- Topic files: {populated}/{total} ({stubs} stubs)

### System Health
- MCP: {ok}/{total} connectivity OK, {ok}/{total} idle CPU OK
- Agents: {total} total, {with_memory} with memory, {stale} stale
- Hooks: {total} total, {ok} executing, {broken} broken
- Memory: {total_mb} MB total MCP footprint

### Apply fixes? [all / 1,3,5 / skip]
```
