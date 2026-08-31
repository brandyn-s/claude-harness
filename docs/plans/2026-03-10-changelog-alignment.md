# Changelog Alignment (2.1.51-2.1.63) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix factual errors and add a minor safety note in our Claude Code architecture docs after reviewing changelog versions 2.1.51 through 2.1.63.

**Architecture:** Two small independent doc tasks touching 3 files total. No code changes, no hook changes, no config changes.

**Tech Stack:** Markdown (docs/rules)

---

## Verification Summary (pre-implementation)

Six changes were originally proposed. Four were rejected after verification:

| Original Task | Verdict | Why |
|---------------|---------|-----|
| Block claude.ai MCP connectors | NOT NECESSARY | Feature flag is ON but zero connectors installed. Opt-in only. Solving a non-problem. |
| Raise context-compressor thresholds | WOULD DEGRADE | Built-in persists >50K to disk (context savings). Our hook injects summarization guidance at 20K-50K - a range the built-in doesn't cover. Raising thresholds removes useful guidance. |
| Document auto-memory overlap | MISLEADING | Built-in auto-memory IS our MEMORY.md system, not a competing one. Adding an "overlap warning" implies conflict where none exists. |
| Worktree auto-memory leakage | NOT NECESSARY | Auto-memory is main-session behavior. Subagents don't write auto-memory unless agent def has `memory: project` frontmatter (ours doesn't). Theoretical concern only. |

Two changes survived verification:

---

### Task 1: Fix simplify Skill Attribution in Docs

Our ARCHITECTURE.md (line 242) and MEMORY.md list `simplify` as a superpowers plugin skill. Verified: the superpowers plugin directory (`~/.claude/plugins/cache/superpowers-marketplace/superpowers/4.3.1/skills/`) does NOT contain a `simplify` directory. The system prompt lists `simplify` without a `superpowers:` prefix (unlike `superpowers:brainstorm` etc.). CC 2.1.63 changelog confirms: "Added `/simplify` and `/batch` bundled slash commands". The attribution is factually wrong.

**Files:**
- Modify: `~/.claude/ARCHITECTURE.md:242` (simplify line in Superpowers Plugin Skills section)
- Modify: `~/.claude/projects/<your-claude-project>/memory/MEMORY.md` (simplify reference)

**Step 1: Update ARCHITECTURE.md**

In the "Superpowers Plugin Skills" section (around line 242), remove the `simplify` bullet:

```markdown
- `simplify` - code review for reuse, quality, and efficiency
```

Add a new "Built-in Slash Commands" subsection after the Superpowers Plugin Skills section, before the Routing Precedence section:

```markdown
#### Built-in Slash Commands (from Claude Code)

Claude Code bundles slash commands that are not stored on disk but are available in every session:
- `/simplify` - review changed code for reuse, quality, and efficiency (added 2.1.63)
- `/batch` - batch operations (added 2.1.63)
- `/debug` - troubleshoot current session (added 2.1.30)
- `/copy` - copy code blocks or full response (added 2.1.59)
```

**Step 2: Update MEMORY.md**

In the Skills section, change:
```
- **simplify** (superpowers plugin): Code review for reuse, quality, and efficiency
```

To:
```
- **simplify** (built-in CC 2.1.63): Code review for reuse, quality, and efficiency
```

**Step 3: Commit**

```bash
git add ARCHITECTURE.md projects/<your-claude-project>/memory/MEMORY.md
git commit -m "docs: fix simplify attribution - built-in CC 2.1.63, not superpowers plugin"
```

---

### Task 2: Update platform-constraints.md - Config Write Safety Note

CC 2.1.61 fixed concurrent writes corrupting the config file on Windows. Our rule says to always use Python atomic read-modify-write. The fix improves safety but doesn't eliminate all race conditions (hooks and the running process can still collide). Add a note acknowledging the fix while keeping the workaround as defense-in-depth.

**Files:**
- Modify: `~/.claude/rules/platform-constraints.md:22` (the config race condition bullet)

**Step 1: Update the bullet point**

Change line 22 from:
```
- `~/.claude.json` is actively written by the running Claude Code process -- the Edit tool fails with race conditions. Use Python atomic read-modify-write (`json.load` -> modify -> `json.dump`) instead
```

To:
```
- `~/.claude.json` is actively written by the running Claude Code process. CC 2.1.61 improved concurrent write safety, but the Edit tool can still race with process writes during heavy hook activity. Use Python atomic read-modify-write (`json.load` -> modify -> `json.dump`) as defense-in-depth.
```

**Step 2: Verify no broken markdown**

Run: `python3 -c "open('$HOME/.claude/rules/platform-constraints.md', encoding='utf-8').read(); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add rules/platform-constraints.md
git commit -m "docs: note CC 2.1.61 config write fix, keep atomic workaround as defense-in-depth"
```

---

## Batch Commit Strategy

Both tasks are independent. Batch into a single commit:

```bash
git add ARCHITECTURE.md projects/<your-claude-project>/memory/MEMORY.md rules/platform-constraints.md
git commit -m "docs: align architecture docs with Claude Code 2.1.51-2.1.63

- Fix simplify skill attribution (built-in CC 2.1.63, not superpowers plugin)
- Add built-in slash commands section to ARCHITECTURE.md
- Note CC 2.1.61 config write safety improvement in platform-constraints"
```
