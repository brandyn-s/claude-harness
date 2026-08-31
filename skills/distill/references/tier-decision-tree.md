# Tier Decision Tree

Quick reference for classifying distill pain points. Use this when the
boundary between tiers is ambiguous.

## Decision Flow

```
Is this pain point specific to a single skill?
  YES → Route fix to that skill's SKILL.md (Step 1c override)
  NO  → Continue below

If Claude forgets this, does output break SILENTLY?
  YES → T0 (Enforce)
    Does it need to fire on every tool call of a type? → T0-hook
    Must it be true at session start?                  → T0-startup
    Must it be true before merge?                      → T0-ci
  NO  → Continue below

Does it apply regardless of domain or tool?
  YES → Is it confirmed by 2+ sessions or hits in 2+ repos?
    YES → T1 (Rule) — add to rules/*.md
    NO  → Run the Step 1d cross-cutting audit before assigning T1.
          Not audited → report "T1 candidate, audit pending"; do not write.
          0 hits across 3+ sibling repos → T4 in the originating domain topic.
  NO  → Continue below

Should every session have this in context?
  YES → T2 (System fact) — add to MEMORY.md
  NO  → Continue below

Is it domain-specific — API behavior (response shape, parameters, error
codes) OR workflow (investigation approach, tool coordination)?
  YES → T4 (Topic memory) — add to topics/*.md
        (T3 retired 2026-06-10; API gotchas also dual-write to
        ~/Documents/api-docs/{api}/gotchas.md)
  NO  → T5 (Skip) — too specific or already captured
```

## Boundary Examples

### T0 vs T1 (enforce vs rule)

| Scenario | Tier | Why |
|----------|------|-----|
| cp1252 encoding mangles Unicode silently | **T0-hook** | Output looks correct but data corrupted. Rule can't prevent — Claude forgets |
| Never commit to main on protected repos | **T1** | Git push will fail visibly. Rule is sufficient reminder |
| settings.json must have X field at start | **T0-startup** | Missing field causes silent misconfiguration |
| Always use `--repo` for fork PRs | **T1** | gh CLI errors visibly without it |

### T1 vs T4 (rule vs domain topic)

| Scenario | Tier | Why |
|----------|------|-----|
| Always `encoding='utf-8'` in Python open() | **T1** | Applies to ALL Python, regardless of domain |
| Tenable severity expects lowercase strings | **T4** | Only matters when using pyTenable (API gotcha → topics/tenable.md + api-docs dual-write) |
| CRLF handling in str.replace() | **T1** | Applies to ALL file editing on Windows |
| CrowdStrike FQL dates need single quotes | **T4** | Only matters when writing FQL queries (topics/crowdstrike.md) |
| Graph API returns `@odata.nextLink` for pagination | **T4** | API behavior — response format (dual-write to api-docs) |
| Start CrowdStrike triage with severity filter, then IOC | **T4** | Workflow — investigation approach |

### T4 vs T5 (topic memory vs skip)

| Scenario | Tier | Why |
|----------|------|-----|
| Airlock API returns double-serialized JSON | **T4** | Operational gotcha with reuse value |
| Fixed a typo in line 42 of script.py | **T5** | No reuse value |
| memory_search cosine 0.75 is the dedup threshold | **T4** | Operational parameter worth remembering |
| User preferred table format over bullet list | **T5** | Session-specific preference |
