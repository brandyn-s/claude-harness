---
name: context-budget
description: "Audit token overhead from loaded skills, rules, MCP tools, hooks, and CLAUDE.md."
when_to_use: "Audit token overhead from loaded skills, rules, MCP tools, hooks, and CLAUDE.md. Use when measuring how much of the context window the architecture consumes before a single user message is processed. Identifies bloat, redundant components, and produces prioritized token-savings recommendations. Trigger phrases: \"context budget\", \"token overhead\", \"how much context am I using\", \"what's loaded\", \"context audit\". Do NOT use for session cost analysis (out of scope — use `claude --usage` or the Anthropic Console) or response depth control."
argument-hint: "[optional: component type e.g. 'skills', 'rules', 'mcp']"
effort: high
metadata:
  author: example-security-engineering
  version: "1.0"
allowed-tools: Bash Read Grep Glob AskUserQuestion
---

# Context Budget — Token Overhead Audit

Measure how much of the active lane is consumed before a user task begins.
Unscoped rules and CLAUDE.md content load ambiently; skills advertise names and
descriptions while their bodies/references load on demand. MCP schemas may be
active or deferred, and hook scripts themselves do not load into context.

---

## Phase 1: Inventory

Scan all component directories and estimate token consumption.

### Native runtime snapshot first

Static file size is a proxy, not the assembled Claude Code context. In a fresh
session using the target configuration, capture the native diagnostics first:

- `/context` — effective context composition and what consumes the active lane.
- `/doctor` — skill-description truncation and collapsed discovery metadata.
- `/mcp` — connected servers and per-server tool/context cost.

Use those outputs as the primary runtime oracle and the scans below to attribute
cost back to source files. If the native snapshot cannot be collected, keep the
structural inventory but mark effective assembled-context claims **UNVERIFIED**.

**Structural estimation heuristic**: Use **chars / 4** as the primary proxy
for all content. This is simpler and more accurate than words x 1.3 — it
handles code, mixed content, and punctuation-heavy text uniformly.
Tag every report with the model/provider/context class. For a release or
qualification decision, use Anthropic's token-counting endpoint for the exact
target model; do not apply an Opus-era multiplier to Fable or Sonnet.

Static estimates and token-count responses are provisional release evidence.
When the target runtime and credentials are available, qualify an architecture
change with fresh-session, model/provider/context-labelled measurements: normal
configuration versus a safe/minimal control, and pre-change versus post-change.
Record input/cache tokens and cost from the same trivial deterministic prompt.
This is a bounded direct smoke/A-B test; it introduces no staged rollout or
observation period. If it cannot run, report runtime context impact as **UNVERIFIED**,
never PASS.
(Calibrated against florianbruniaux/claude-code-ultimate-guide token-audit;
source last verified 2026-04. If results look off for new content shapes
(e.g., very long tool-result blobs), re-check against the upstream guide.)

Run these scans via Bash scripts for speed — don't Read each file individually.

### Skills (`skills/*/SKILL.md`)

```bash
# Token estimate per skill (chars / 4)
for f in ~/.claude/skills/*/SKILL.md; do
  name=$(basename $(dirname "$f"))
  words=$(wc -w < "$f")
  tokens=$(echo "$(wc -c < "$f") / 4" | bc)
  echo "$tokens $name"
done | sort -rn
```

Also check for reference files that load on demand vs always:
```bash
find ~/.claude/skills -name "*.md" ! -name "SKILL.md" | wc -l
```

Initial invocation and post-compaction behavior are different. Claude Code
loads the full rendered skill when it is first invoked. After auto-compaction,
it reattaches only the first 5,000 tokens of each invoked skill, with a 25,000
token combined newest-first budget; older invoked skills can be omitted. Run
`python3 scripts/token-audit.py --json` from the source checkout to inventory
the conservative `chars/4` proxy, large-skill recovery contracts, and corpus
gaps. A target-model token count refines size estimates but does not replace the
runtime lifecycle check.

**Flag**: Overlong descriptions, overlapping trigger language, and rarely used
skills still advertised to the model. Claude Code advertises a skill's name and
description at startup; the full SKILL.md body loads only when the skill is invoked.
Use `skillOverrides: name-only` to preserve model invocation without
paying for a long description, `user-invocable-only` for explicit-only skills,
and `off` for broken or retired skills. `disable-model-invocation: true` is the
per-skill user-only equivalent. These controls apply to personal and project skills;
manage plugin skills through `/plugin`, because `skillOverrides` does
not govern plugin-provided skills.

### Rules (`rules/*.md`)

```bash
for f in ~/.claude/rules/*.md; do
  [ -f "$f" ] || continue
  name=$(basename "$f")
  words=$(wc -w < "$f")
  tokens=$(echo "$(wc -c < "$f") / 4" | bc)
  echo "$tokens $name"
done | sort -rn
```

**Flag**: Rules >150 lines (candidates for extraction to topic files loaded
on demand), rules with overlapping content.

### MCP Servers and Tools

Classify MCP schemas as active or deferred before estimating cost.
Do not charge a deferred full schema as ambient context.

```bash
# Count deferred tools from session (grep the available-deferred-tools list)
# This is session-dependent — report the count visible in current session
echo "Check the <available-deferred-tools> block in conversation for tool count"
```

**Flag**: Servers with >20 tools, servers wrapping simple CLI commands that
Claude can call directly (gh, git, npm).

### Hooks (`hooks/*.py`, `hooks/*.sh`)

Hook scripts don't load into context, but hook **registrations** in
settings.json do. Count the registration entries:

```bash
# Inline `python3 -c` over ~300 chars is blocked by the bash-security-guard
# hook — write the snippet to a temp .py file and run that instead.
cat > "${TMPDIR:-/tmp}/count_hook_registrations.py" <<'EOF'
import json, os
with open(os.path.expanduser('~/.claude/settings.json')) as f:
    d = json.load(f)
hooks = d.get('hooks', {})
total = sum(len(v) for v in hooks.values())
print(f'{total} hook registrations across {len(hooks)} events')
for event, entries in sorted(hooks.items()):
    print(f'  {event}: {len(entries)} hooks')
EOF
python3 "${TMPDIR:-/tmp}/count_hook_registrations.py"
```

### Hook Accumulated Overhead (hidden cost)

Hook registrations are small, but hook **stdout** accumulates across every
tool call in a session. A hook outputting 500 chars on 150 tool calls =
75K chars = ~19K tokens of invisible overhead.

For each `PreToolUse` and `PostToolUse` hook, estimate stdout per invocation:

```bash
# Run each hook manually and measure output size
for hook in ~/.claude/hooks/*.py; do
  [ -f "$hook" ] || continue
  name=$(basename "$hook")
  # Simulate a tool call to measure stdout
  output_size=$(echo '{"tool_name":"Read","tool_input":{}}' | python3 "$hook" 2>/dev/null | wc -c)
  echo "$output_size chars/call  $name"
done | sort -rn
```

Multiply output size by estimated tool calls per session (~100-200 for a
typical session) to get accumulated overhead:

| Hook | Chars/call | Calls/session | Total tokens |
|------|-----------|---------------|-------------|
| ... | ... | ~150 | chars x 150 / 4 |

**Red flags**: Hooks that `cat` files unconditionally, `git status` or
`git log` on every call, JSON blobs injected as context, multi-line echo
debugging output never removed.
(Pattern source: florianbruniaux/claude-code-ultimate-guide token-audit)

### CLAUDE.md Chain

```bash
for f in ~/.claude/CLAUDE.md \
         $(find ~/.claude/rules -mindepth 2 -maxdepth 2 -name CLAUDE.md 2>/dev/null) \
         ~/Documents/CLAUDE.md ~/Documents/.claude/CLAUDE.md; do
  if [ -f "$f" ]; then
    words=$(wc -w < "$f")
    tokens=$(echo "$(wc -c < "$f") / 4" | bc)
    echo "$tokens $(echo $f | sed 's|.*/||')"
  fi
done
```

### Memory Index

```bash
# Auto-memory indexes live under ~/.claude/projects/<munged-session-cwd>/memory/
# (the munged dir name varies per host and CWD) — find and measure each one.
find ~/.claude/projects -maxdepth 3 -path '*/memory/MEMORY.md' 2>/dev/null |
while IFS= read -r memory_path; do
  words=$(wc -w < "$memory_path")
  tokens=$(echo "$(wc -c < "$memory_path") / 4" | bc)
  echo "$tokens MEMORY.md ($memory_path, lines after 200 truncated)"
done
```

---

## Phase 2: Classify

Sort every component into a bucket:

| Bucket | Criteria | Action |
|--------|----------|--------|
| **Always loaded** | Rules, CLAUDE.md, MEMORY.md | Optimize size |
| **Advertised** | Skill names/descriptions visible to Claude | Optimize descriptions and visibility |
| **On-demand** | Invoked SKILL.md bodies, reference files, topic files | OK — loads when used |
| **Post-compaction reattached** | First 5,000 tokens per invoked skill; 25,000 combined newest-first | Keep invariants/recovery early; re-invoke to restore full body |
| **Deferred** | MCP tools in `<available-deferred-tools>` (schema not loaded until ToolSearch) | Low overhead |
| **Always active** | MCP tools NOT deferred (loaded at session start) | Optimize count |

**Key insight**: Full skill bodies are progressive-disclosure content and load
only on invocation. Idle overhead comes from the advertised name/description
listing, not SKILL.md line count. A user-only or `off` skill is absent from
Claude's discovery context; `name-only` keeps the route available at the lowest
description cost.

---

## Phase 3: Detect Issues

Scan for these problem patterns:

| Issue | Detection | Impact |
|-------|-----------|--------|
| **Verbose skill discovery** | long descriptions on broadly visible skills | fixed startup and child-context cost |
| **Heavy rules** | >150 lines | Loads every session |
| **Redundant content** | Same guidance in rule + skill + CLAUDE.md | 2-3x token waste |
| **MCP tool sprawl** | >200 deferred tools | ToolSearch overhead |
| **Stale rules** | Rules for fixed bugs or deprecated workarounds | Dead weight |
| **Bloated MEMORY.md** | >150 lines in index | Truncated after 200 lines anyway |
| **Compaction-fragile skill** | >4,000 `chars/4` proxy tokens without an early continuity contract | Tail gates can disappear after compaction |

---

## Phase 4: Report

```
CONTEXT BUDGET REPORT
======================================================

Model: {model} ({context_window} context)
Estimated overhead: ~{total}K tokens

Component Breakdown:
+-----------------------+--------+-----------+
| Component             | Count  | ~Tokens   |
+-----------------------+--------+-----------+
| Rules (always loaded) | {N}    | ~{N}K     |
| Skill advertisements | {N}    | ~{N}K     |
| Skill bodies on-demand| {N}    | (0 idle)  |
| Compaction continuity | {N} large / {N} gaps | 5K each / 25K combined |
| MCP tools (active)    | {N}    | ~{N}K     |
| MCP tools (deferred)  | {N}    | (0 idle)  |
| Hook registrations    | {N}    | ~{N}      |
| CLAUDE.md chain       | {N}    | ~{N}K     |
| MEMORY.md             | 1      | ~{N}      |
+-----------------------+--------+-----------+
| TOTAL OVERHEAD        |        | ~{N}K     |
+-----------------------+--------+-----------+

Effective available context: ~{remaining}K tokens ({pct}%)

ISSUES FOUND ({N}):
  [ranked by token savings, highest first]

  1. {component}: {issue} -> save ~{N}K tokens
     Action: {specific recommendation}

  2. ...

TOP 3 QUICK WINS:
  1. Apply `skillOverrides` to {N} verbose, explicit-only, or broken skills
     -> save ~{N}K advertised-context tokens
  2. Move {rule} detailed sections to topic file (on-demand)
     -> save ~{N}K tokens
  3. {specific recommendation}
     -> save ~{N}K tokens

Potential savings: ~{total_savings}K tokens ({pct}% of current overhead)

HEALTH ASSESSMENT: {verdict}
```

### Health Thresholds

| Fixed context | Assessment | Action |
|---------------|------------|--------|
| < 20K tokens | Healthy | No urgent action needed |
| 20-40K tokens | Moderate | Run classification, grab easy wins |
| 40-60K tokens | High | Rules audit worth an afternoon |
| > 60K tokens | Critical | Burning 30%+ of window before any task |

One upstream audit reported a ~48% reduction after a first-pass audit on a
heavily configured project, with no infrastructure changes — just removing
rarely-used files from auto-load. Treat this as an illustrative data point,
not a guaranteed outcome.
(Thresholds source: florianbruniaux/claude-code-ultimate-guide token-audit)

---

## Scoped Audit

If `$ARGUMENTS` specifies a component type, audit only that type:

- `/context-budget skills` — skills only
- `/context-budget rules` — rules only
- `/context-budget mcp` — MCP tools only

---

## Examples

**Example 1: Full audit**
```
/context-budget
```
Scans all components, finds 3 verbose skill advertisements and 2 rules with
overlapping CLAUDE.md content. Recommends targeted `skillOverrides` while
reporting the large skill bodies separately as on-demand cost.

**Example 2: Skills only**
```
/context-budget skills
```
Lists every skill sorted by estimated token size. Separates idle advertisement
cost from the on-demand skill body and flags verbose discovery metadata.

## Success Criteria

- Every component type inventoried with token estimates
- Components classified as always-loaded vs on-demand
- Invoked-skill compaction limits and continuity gaps are reported separately
  from initial on-demand loading
- Release claims include fresh-session runtime control measurements, or state
  explicitly that runtime context impact is UNVERIFIED
- Issues ranked by token savings (biggest wins first)
- Recommendations are specific and actionable (name the file, name the change)
- Report fits in one conversation turn

(Skill source: affaan-m/everything-claude-code context-budget — Context7 registry 2026-04-06.
Adapted for Example: added on-demand vs always-loaded classification, hook
registration counting, deferred tool awareness, and discovery-metadata
optimization.)
