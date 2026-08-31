# Harden Skill + Distill T0 Tier Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a T0 ("Hook") tier to `/distill` that flags lessons needing automated enforcement, and create a new `/harden` skill that takes those T0 findings and implements them as hooks - writing the script, registering it in settings.json, and testing it.

**Architecture:** Two changes work together. Distill gains classification awareness that some lessons belong as hooks, not rules. Harden is a separate skill that builds the enforcement. Distill diagnoses; harden implements. This follows the existing pattern where distill identifies and other skills act (e.g., distill flags a rule gap, user manually adds a rule).

**Tech Stack:** Markdown (SKILL.md), Python (hook scripts), JSON (settings.json)

---

### Task 1: Add T0 tier to distill SKILL.md

**Files:**
- Modify: `~/.claude/skills/distill/SKILL.md`

**Step 1: Update the classification table in Step 2**

In `SKILL.md` around line 109, the tier table currently has T1-T5. Add T0 above T1:

```markdown
| Tier | Name | Criteria | Target | Approval |
|------|------|----------|--------|----------|
| **T0** | Hook | Pattern that MUST be enforced every time - Claude skipping it causes data loss, broken output, or security risk. Rules (T1) failed or would fail to prevent it. | `/harden` handoff | **Confirm** |
| **T1** | Rule | Platform constraint, universal anti-pattern, or mistake repeated across 2+ sessions | `~/.claude/rules/*.md` | **Confirm** |
```

**Step 2: Add T0 classification heuristic**

After the existing heuristics block (around line 122), add before the "When uncertain between T3 and T4" line:

```markdown
- Must happen every time without exception, and a rule wouldn't reliably prevent it? -> **T0** (hook)
- The key test: "If Claude forgets this instruction, does output break silently?" If yes, T0. If Claude forgetting means suboptimal but not broken output, T1.
```

**Step 3: Add T0 writing rules in Step 4**

After the "Writing rules by tier:" header (around line 179), add before the T1 section:

```markdown
**T0 (Hook):**
Do NOT build the hook in distill. Present the finding with:
- What must be enforced (the invariant)
- What breaks when it's not enforced (the failure mode)
- Which hook event it belongs to (PreToolUse, PostToolUse, etc.)
- Which tool matcher it applies to (Write|Edit, Bash, mcp__*, etc.)

Then tell the user: "This is a T0 finding - run `/harden` to implement it as a hook."
Write the T0 finding to `~/.claude/harden-queue.json` so `/harden` can pick it up:

```python
import json, pathlib, datetime
queue_path = pathlib.Path.home() / ".claude" / "harden-queue.json"
queue = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
queue.append({
    "id": f"t0-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}",
    "invariant": "description of what must always happen",
    "failure_mode": "what breaks when it doesn't",
    "hook_event": "PostToolUse|PreToolUse|etc",
    "matcher": "Write|Edit|Bash|etc",
    "evidence": "brief session reference",
    "timestamp": datetime.datetime.now().isoformat()
})
queue_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
```
```

**Step 4: Add T0 example**

After the existing Example 4 (around line 332), add:

```markdown
**Example 5: Pattern needing automated enforcement**

User invokes `/distill` after Claude rewrote a markdown file with double
blank lines, breaking all GFM tables on GitHub for a week.

| # | Lesson | Tier | Action |
|---|--------|------|--------|
| 1 | Claude double-spaces markdown on full file rewrites, breaking GFM tables | T0: Hook | QUEUE for /harden (PostToolUse on Write|Edit, .md files) |

Result: Finding written to harden-queue.json. User told to run `/harden`.
```

**Step 5: Update the marker schema in Step 5**

In the marker JSON template (around line 258), the `tier` field in lessons should document that `"T0"` is now valid:

No code change needed - the existing `"tier": "T3"` examples are illustrative. T0 will just work.

**Step 6: Update Success Criteria**

Add to the success criteria list (around line 282):

```markdown
- T0 findings written to harden-queue.json with invariant, failure mode, hook event, and matcher
- T0 findings NOT implemented as hooks by distill (that's /harden's job)
```

**Step 7: Commit**

```bash
git add skills/distill/SKILL.md
git commit -m "feat: add T0 (Hook) tier to distill for automated enforcement findings"
```

---

### Task 2: Create the harden skill directory

**Files:**
- Create: `~/.claude/skills/harden/SKILL.md`

**Step 1: Create the skill directory and SKILL.md**

```bash
mkdir -p ~/.claude/skills/harden
```

**Step 2: Write SKILL.md with full content**

Create `~/.claude/skills/harden/SKILL.md` with:

```markdown
---
name: harden
description: >
  Implement automated enforcement hooks from distill T0 findings or ad-hoc
  requests. Reads harden-queue.json, builds a PostToolUse/PreToolUse hook
  script, registers it in settings.json, and tests it with a throwaway file.
  Trigger phrases: "harden", "make it a hook", "enforce this", "automate this
  check". Do NOT use for writing rules (use /distill T1), documenting patterns
  (use /distill T3-T4), or building MCP servers.
---

# Harden - Build Enforcement Hooks from Lessons

Take a lesson that needs automated enforcement and implement it as a Claude
Code hook - the strongest form of prevention in this architecture.

**Input sources:**
1. `~/.claude/harden-queue.json` - T0 findings from `/distill`
2. Ad-hoc user request - "make X a hook" or "enforce Y automatically"

**Output:**
- A Python hook script in `~/.claude/hooks/`
- A registration entry in `~/.claude/settings.json`
- A passing test that proves the hook works

---

## Step 1: Load the Finding

Check `~/.claude/harden-queue.json` for pending T0 findings:

```python
import json, pathlib
queue_path = pathlib.Path.home() / ".claude" / "harden-queue.json"
if queue_path.exists():
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    pending = [f for f in queue if not f.get("implemented")]
else:
    queue = []
    pending = []
```

If the queue is empty and the user didn't provide an ad-hoc request, report
"No pending T0 findings. Run `/distill` first or describe what to enforce."

If there are pending findings, present them:

```
## Pending T0 Findings

| # | Invariant | Hook Event | Matcher |
|---|-----------|------------|---------|
| 1 | GFM tables must have contiguous rows | PostToolUse | Write|Edit |
```

Ask the user which finding to implement (or "all").

---

## Step 2: Design the Hook

For each finding, determine:

| Decision | Options | How to choose |
|----------|---------|---------------|
| **Hook event** | PreToolUse (before), PostToolUse (after), PreToolUse blocking | If the hook validates/fixes output -> PostToolUse. If it prevents a bad action -> PreToolUse. |
| **Matcher** | Tool name pattern (e.g., `Write\|Edit`, `Bash`, `mcp__.*`) | Match the tool(s) that produce the problem. Use `\|` for multiple. |
| **Hook type** | `command` (Python script) | Always command. Prompt hooks block continuation. |
| **Behavior** | Fix silently, warn via message, block via exit code 2 | PostToolUse fixes should be silent. PreToolUse blocks should print reason to stderr. |
| **Timeout** | 3-8 seconds | Simple file checks: 3s. Subprocess calls (ruff, etc.): 8s. |

Present the design to the user:

```
## Hook Design

- **Script**: `~/.claude/hooks/{name}.py`
- **Event**: PostToolUse
- **Matcher**: Write|Edit
- **Behavior**: Fix silently (modify file in-place)
- **Timeout**: 8s
- **Graceful degradation**: If anything fails, exit silently (never block Claude)
```

---

## Step 3: Write the Hook Script

Follow the established hook pattern. Every hook script MUST:

1. Read JSON from stdin: `data = json.loads(sys.stdin.read())`
2. Extract tool_input: `tool_input = data.get("tool_input", {})`
3. Get the file_path: `file_path = tool_input.get("file_path", "")`
4. Check preconditions early (file extension, file exists) and return if not applicable
5. Use `encoding="utf-8"` on all file operations
6. Wrap all I/O in try/except - **never crash, never block Claude Code**
7. For PostToolUse fixes: modify in-place only if content changed
8. For PreToolUse blocks: `sys.exit(2)` with reason on stderr

**Template:**

```python
"""[Event] hook: [One-line description].

[Longer explanation of what invariant this enforces and why.]

Graceful degradation: if anything fails, exits silently.
"""
import json
import os
import sys

def main():
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        return

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path or not file_path.endswith(".EXTENSION"):
        return

    if not os.path.isfile(file_path):
        return

    # --- ENFORCEMENT LOGIC HERE ---

if __name__ == "__main__":
    main()
```

Write the script to `~/.claude/hooks/{name}.py`.

---

## Step 4: Register in settings.json

Read `~/.claude/settings.json`, find the correct event array, and add the
hook entry. Use Python atomic read-modify-write (NOT the Edit tool - it
races with the running Claude process):

```python
import json, pathlib

settings_path = pathlib.Path.home() / ".claude" / "settings.json"
settings = json.loads(settings_path.read_text(encoding="utf-8"))

event = "PostToolUse"  # or PreToolUse, etc.
matcher = "Write|Edit"  # from Step 2

hook_entry = {
    "type": "command",
    "command": f"pythonw $HOME/.claude/hooks/{{name}}.py",
    "timeout": 8
}

# Find existing matcher group or create new one
event_hooks = settings.get("hooks", {}).get(event, [])
found = False
for group in event_hooks:
    if group["matcher"] == matcher:
        group["hooks"].append(hook_entry)
        found = True
        break

if not found:
    event_hooks.append({"matcher": matcher, "hooks": [hook_entry]})

settings.setdefault("hooks", {})[event] = event_hooks
settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
```

**IMPORTANT**: Use `pythonw` (not `python`) for hooks - it runs without a
console window on Windows.

**STOP - present the registration diff to the user before writing.**

---

## Step 5: Test the Hook

Create a throwaway test file that triggers the problem, then verify the hook
fixes it (PostToolUse) or blocks it (PreToolUse).

**For PostToolUse hooks:**

1. Write a test file with the known-bad pattern using the Write tool
2. Read it back - the hook should have fixed it
3. Verify the fix: compare content against expected output
4. Delete the test file

**For PreToolUse hooks:**

1. Attempt the blocked action - the hook should reject it (exit 2)
2. Verify the rejection message appears
3. Attempt an allowed action - the hook should let it through

Report results:

```
## Test Results

- Wrote test file with broken GFM table (blank lines between rows)
- Read back: table rows are contiguous (hook fixed it)
- PASS: Hook enforces the invariant
```

If the test fails, diagnose and fix the hook script before continuing.

---

## Step 6: Mark Finding as Implemented

Update `harden-queue.json` to mark the finding as done:

```python
import json, pathlib, datetime
queue_path = pathlib.Path.home() / ".claude" / "harden-queue.json"
queue = json.loads(queue_path.read_text(encoding="utf-8"))
for finding in queue:
    if finding["id"] == "THE_ID":
        finding["implemented"] = True
        finding["hook_script"] = "hooks/{name}.py"
        finding["implemented_at"] = datetime.datetime.now().isoformat()
queue_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
```

---

## Step 7: Report

```
## Harden Summary

| Finding | Hook | Event | Matcher | Test |
|---------|------|-------|---------|------|
| GFM table enforcement | auto-format-markdown.py | PostToolUse | Write|Edit | PASS |

1 hook implemented, 0 failed.
Queue: 0 pending, 1 complete.
```

---

## Success Criteria

- Hook script follows the established pattern (stdin JSON, graceful degradation, encoding utf-8)
- Hook registered in settings.json under the correct event and matcher
- Test proves the hook enforces the invariant (not just that it doesn't crash)
- Finding marked as implemented in harden-queue.json
- User confirmed the design before writing

## Examples

**Example 1: PostToolUse fix from distill T0**

```
/harden
```
> "1 pending T0 finding: GFM tables must have contiguous rows (PostToolUse on Write|Edit)"
> Shows hook design, writes auto-format-markdown.py, registers in settings.json, tests with broken table file.
> "PASS. Hook implemented."

**Example 2: Ad-hoc enforcement request**

```
/harden "block gh pr merge if CI hasn't passed"
```
> Designs a PreToolUse hook on Bash that regex-matches `gh pr merge` without a prior `gh pr checks` pass.
> Writes, registers, tests. "PASS."

**Example 3: No pending findings**

```
/harden
```
> "No pending T0 findings. Run `/distill` first or describe what to enforce."
```

**Step 3: Commit**

```bash
git add skills/harden/SKILL.md
git commit -m "feat: add /harden skill for implementing enforcement hooks"
```

---

### Task 3: Add harden to skill-routing-hint.py

**Files:**
- Modify: `~/.claude/hooks/skill-routing-hint.py`
- Modify: `~/.claude/hooks/skill-rules.json`

**Step 1: Read current skill-rules.json**

Read `~/.claude/hooks/skill-rules.json` and add an entry for the harden skill.

**Step 2: Add harden routing keywords**

Add to skill-rules.json:

```json
{
  "skill": "harden",
  "keywords": ["harden", "make it a hook", "enforce this", "automate this check", "needs a hook", "should be a hook"],
  "negative": ["mcp-forge", "build server"]
}
```

**Step 3: Commit**

```bash
git add hooks/skill-rules.json
git commit -m "feat: add harden skill to routing hints"
```

---

### Task 4: Update architecture documentation

**Files:**
- Modify: `~/.claude/ARCHITECTURE.md`
- Modify: `~/.claude/agent-memory/topics/architecture.md`

**Step 1: Add harden to the skill inventory in ARCHITECTURE.md**

In the "System Maintenance Skills" table, add a row:

```markdown
| `harden` | Implement enforcement hooks from distill T0 findings | Distill flagged T0, ad-hoc "make this a hook" |
```

**Step 2: Update skill count**

Update "24 skills on disk" to "25 skills on disk" in ARCHITECTURE.md.

**Step 3: Update the distill description**

In the Operations Skills table, update the distill row to mention T0:

```markdown
| `distill` | Extract errors/fixes from sessions, classify T0-T5, queue hooks for /harden | After sessions with debugging pain, failed approaches |
```

**Step 4: Add a note to architecture topic file**

In `agent-memory/topics/architecture.md`, update the existing distill-related content or add:

```markdown
### Distill -> Harden pipeline
- `/distill` classifies T0 findings (needs automated enforcement) and writes to `~/.claude/harden-queue.json`
- `/harden` reads the queue, builds the hook script, registers in settings.json, tests it
- Distill diagnoses, harden implements. Separation of concerns.
```

**Step 5: Commit**

```bash
git add ARCHITECTURE.md agent-memory/topics/architecture.md
git commit -m "docs: add harden skill and distill T0 tier to architecture docs"
```

---

### Task 5: Update MEMORY.md skills list

**Files:**
- Modify: `~/.claude/projects/<your-claude-project>/memory/MEMORY.md`

**Step 1: Add harden to the skills list**

In the `## Skills` section of MEMORY.md, add:

```markdown
- **harden**: Implement enforcement hooks from distill T0 findings or ad-hoc requests
```

**Step 2: Update skill count**

Change "Skills (20 on disk + superpowers plugin skills)" to reflect the new count (or whatever the current number is + 1).

**Step 3: Commit**

```bash
git add projects/<your-claude-project>/memory/MEMORY.md
git commit -m "docs: add harden skill to MEMORY.md"
```

---

### Task 6: End-to-end validation

**Step 1: Verify distill SKILL.md loads cleanly**

```bash
head -15 ~/.claude/skills/distill/SKILL.md
```

Check YAML frontmatter is valid.

**Step 2: Verify harden SKILL.md loads cleanly**

```bash
head -15 ~/.claude/skills/harden/SKILL.md
```

Check YAML frontmatter is valid, name matches directory.

**Step 3: Verify skill-rules.json is valid JSON**

```bash
python3 -c "import json; json.load(open(os.path.expanduser('~/.claude/hooks/skill-rules.json'))); print('OK')"
```

**Step 4: Verify settings.json is still valid JSON**

```bash
python3 -c "import json; json.load(open(os.path.expanduser('~/.claude/settings.json'))); print('OK')"
```

**Step 5: Test the pipeline end-to-end**

Write a test harden-queue.json entry manually, then invoke the skill conceptually:

```python
import json, pathlib
queue_path = pathlib.Path.home() / ".claude" / "harden-queue.json"
queue = [{
    "id": "t0-test-20260312",
    "invariant": "Test invariant - can be deleted",
    "failure_mode": "Test failure mode",
    "hook_event": "PostToolUse",
    "matcher": "Write|Edit",
    "evidence": "Test entry for validation",
    "timestamp": "2026-03-12T00:00:00"
}]
queue_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
print("Queue written. /harden should pick this up.")
```

Verify the file exists and is readable, then clean it up.

**Step 6: Final commit (if any cleanup needed)**

```bash
git status
# If clean, done. If not, commit any remaining changes.
```
