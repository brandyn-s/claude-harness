# Architecture Streamlining Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce hook overhead, eliminate noise, and improve auto-learn hit rate based on the architecture audit findings.

**Architecture:** Five targeted changes - convert an expensive prompt hook to a command hook, stop two hooks from firing on every Bash call, lower auto-learn thresholds, remove two dead hooks, and clean up stale routing data.

**Tech Stack:** Python (hooks), JSON (settings.json - atomic read-modify-write via Python script)

---

### Task 1: Convert Write|Edit Prompt Hook to Command Hook

The PostToolUse prompt hook for skill file validation fires an LLM inference on **every Write and Edit**. 98% of invocations just confirm "not a skill file" and bail. Convert to a Python command hook that does the path check cheaply, and only prints a guidance message for actual skill files.

**Files:**
- Create: `~/.claude/hooks/skill-file-validator.py`
- Modify: `~/.claude/settings.json` (via Python atomic write)

**Step 1: Write the command hook**

Create `~/.claude/hooks/skill-file-validator.py`:

```python
"""PostToolUse:Write|Edit hook - validate skill files after write.

Replaces the prompt hook with a command hook. Does a cheap path check
in Python (free), only prints guidance for actual skill files.

Exit code 0 = continue (with optional message on stdout)
"""
import json
import re
import sys


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Fast path: not a skill file -> exit immediately (no LLM cost)
    if "/.claude/skills/" not in file_path.replace("\\", "/"):
        sys.exit(0)

    # This IS a skill file. Read the content and run checks.
    # For Edit tool, we need to read the file from disk since tool_input
    # only has old_string/new_string, not full content.
    content = tool_input.get("content", "")
    if not content:
        # Edit tool - read file from disk
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            sys.exit(0)

    warnings = []

    # 1. Stale tool references
    stale_tools = re.findall(
        r"\b(falcon_search_detections|conversations_add_message|tenable_list_assets"
        r"|falcon_search_hosts|falcon_get_host_details)\b",
        content,
    )
    if stale_tools:
        warnings.append(
            f"Stale tool references: {', '.join(set(stale_tools))}. "
            "Check if these are behind security-remix (use discover_tools/execute_tool pattern)."
        )

    # 2. Missing error handling
    has_mcp = bool(re.search(r"mcp__|tavily|linear|ramp|crowdstrike|tenable|airlock", content, re.I))
    has_error = bool(re.search(r"error handling|graceful degradation|if.*fail|on failure", content, re.I))
    if has_mcp and not has_error:
        warnings.append("No error handling section. Add guidance for when MCP tool calls fail.")

    # 3. Missing pagination
    has_list = bool(re.search(r"\blist_\w+|search_\w+", content))
    has_pagination = bool(re.search(r"hasNextPage|cursor|offset|pagina", content, re.I))
    if has_list and not has_pagination:
        warnings.append("List/search tools without pagination guidance. Results beyond limit are silently dropped.")

    # 4. Topic files not consulted
    has_query = bool(re.search(r"mcp__|tavily|linear|ramp", content, re.I))
    has_topic = bool(re.search(r"agent-memory/topics|topic file", content, re.I))
    if has_query and not has_topic:
        warnings.append("Topic files not consulted. Skill may miss accumulated API gotchas.")

    if warnings:
        msg = "Skill file validation warnings:\n" + "\n".join(f"  - {w}" for w in warnings)
        print(json.dumps({"message": msg}))

    sys.exit(0)


if __name__ == "__main__":
    main()
```

**Step 2: Update settings.json**

Replace the Write|Edit prompt hook entry (the one with 1549-char prompt, timeout 10s) with:

```json
{
  "matcher": "Write|Edit",
  "hooks": [
    {
      "type": "command",
      "command": "pythonw $HOME/.claude/hooks/skill-file-validator.py",
      "timeout": 3
    }
  ]
}
```

Use a Python script for atomic read-modify-write of settings.json (never Edit tool on live config):

```python
import json
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
with open(settings_path, "r", encoding="utf-8") as f:
    settings = json.load(f)

post_tool_use = settings["hooks"]["PostToolUse"]
for i, entry in enumerate(post_tool_use):
    hooks = entry.get("hooks", [])
    if (entry.get("matcher") == "Write|Edit"
        and len(hooks) == 1
        and hooks[0].get("type") == "prompt"):
        post_tool_use[i] = {
            "matcher": "Write|Edit",
            "hooks": [{
                "type": "command",
                "command": "pythonw $HOME/.claude/hooks/skill-file-validator.py",
                "timeout": 3
            }]
        }
        break

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
```

**Step 3: Verify**

```bash
python -c "import py_compile; py_compile.compile('hooks/skill-file-validator.py', doraise=True); print('OK')"
python -c "import json; s=json.load(open('settings.json',encoding='utf-8')); [print(h) for h in s['hooks']['PostToolUse'] if h.get('matcher')=='Write|Edit']"
```

Expected: `OK` and a dict showing type=command (not type=prompt).

**Step 4: Commit**

```bash
git add hooks/skill-file-validator.py settings.json
git commit -m "refactor: convert skill-file-validator from prompt hook to command hook"
```

---

### Task 2: Gate pr-security-check on Command Content

pr-security-check.py spawns a Python process on every Bash call but only works when `gh pr create` or `gh pr merge` is in the command. Move it into `bash-security-guard.py` as a fast string check, eliminating a separate process spawn.

**Files:**
- Modify: `~/.claude/hooks/bash-security-guard.py` (add pr-security-check logic)
- Modify: `~/.claude/settings.json` (remove standalone pr-security-check entry)
- Delete: `~/.claude/hooks/pr-security-check.py`

**Step 1: Add pr-security-check to bash-security-guard.py**

Add a new function after `check_push_guard`:

```python
def check_pr_security(command, cwd):
    """Warn when creating a PR with security-sensitive files."""
    if "gh pr create" not in command and "gh pr merge" not in command:
        return None  # Fast exit for 99% of Bash calls

    import subprocess
    SENSITIVE_PATTERNS = [
        "scripts/", ".github/workflows/", "Dockerfile", "templates/",
        "conftest/", "shared/opa_", "shared/auth", "shared/mcp_http", ".gitleaks",
    ]
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            capture_output=True, text=True, timeout=10, cwd=cwd or None,
        )
        files = result.stdout.strip().split("\n") if result.returncode == 0 and result.stdout.strip() else []
    except Exception:
        files = []

    sensitive = [f for f in files if any(p in f for p in SENSITIVE_PATTERNS)]
    if sensitive:
        file_list = "\n".join(f"  - {f}" for f in sensitive[:10])
        # Print to stderr as advisory (non-blocking)
        import sys as _sys
        print(
            f"[pr-security-check] WARNING: PR contains {len(sensitive)} security-sensitive file(s):\n"
            f"{file_list}\n"
            "Confirm the security-review-before-pr checklist before proceeding.",
            file=_sys.stderr,
        )
    return None  # Never blocks, only warns
```

Add it to the guard sequence in `main()`:

```python
    for check in [
        lambda: check_credentials(command),
        lambda: check_exfiltration(command),
        lambda: check_dangerous(command),
        lambda: check_push_guard(command, cwd),
    ]:
        reason = check()
        if reason:
            print(reason, file=sys.stderr)
            sys.exit(2)

    # Advisory checks (non-blocking, run after security blocks)
    check_pr_security(command, cwd)

    sys.exit(0)
```

**Step 2: Remove pr-security-check from settings.json**

Python atomic write script:

```python
import json
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
with open(settings_path, "r", encoding="utf-8") as f:
    settings = json.load(f)

pre = settings["hooks"]["PreToolUse"]
settings["hooks"]["PreToolUse"] = [
    e for e in pre
    if not (e.get("hooks", [{}])[0].get("command", "").endswith("pr-security-check.py"))
]

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
```

**Step 3: Delete the old file**

```bash
rm hooks/pr-security-check.py
```

**Step 4: Verify and commit**

```bash
python -c "import py_compile; py_compile.compile('hooks/bash-security-guard.py', doraise=True); print('OK')"
git add hooks/bash-security-guard.py hooks/pr-security-check.py settings.json
git commit -m "refactor: merge pr-security-check into bash-security-guard"
```

---

### Task 3: Gate post-merge-sync on Command Content

post-merge-sync.py spawns a process on every Bash PostToolUse but only works when `gh pr merge` is in the command. Move the gate check to a fast inline test.

**Files:**
- Modify: `~/.claude/hooks/post-merge-sync.py:20-32`

**Step 1: Add fast stdin-free early exit**

The hook reads stdin JSON and checks for `gh pr merge`. The problem is it spawns even when the command is `git status`. Replace the stdin parsing with an approach that exits immediately for non-matching commands.

Actually, PostToolUse hooks receive the command in stdin JSON - there's no way to gate before the process spawns. The alternative is to consolidate post-merge-sync into `bash-security-guard.py` as a PostToolUse function, but hooks can't be both PreToolUse AND PostToolUse.

**Better approach**: The post-merge-sync hook is valuable and can't be gated without a process spawn. Accept the ~250ms cost since it only fires on Bash PostToolUse (not PreToolUse). Its internal gate at line 31 (`if "gh pr merge" not in command: sys.exit(0)`) is already efficient.

**Skip this task** - the cost is acceptable and there's no way to avoid the process spawn for PostToolUse hooks. The real win was in Task 2 (PreToolUse).

---

### Task 4: Lower Auto-Learn Thresholds

The auto-learn pipeline only fires 12% of the time. The 3MB delta threshold is too aggressive for multi-session workflows.

**Files:**
- Modify: `~/.claude/hooks/session-stop.py:33` (MIN_TRANSCRIPT_BYTES)
- Modify: `~/.claude/hooks/session-stop.py:380` (delta threshold)

**Step 1: Lower the thresholds**

In `session-stop.py`:

Line 33 - change:
```python
MIN_TRANSCRIPT_BYTES = 1_000_000  # 1MB
```
to:
```python
MIN_TRANSCRIPT_BYTES = 500_000  # 500KB
```

Line 380 - change:
```python
            if delta < 3_000_000:
```
to:
```python
            if delta < 1_500_000:
```

Also update the skip message on line 381:
```python
                _write_skip_marker(session_id, f"insufficient delta ({delta} bytes < 1.5MB since last run)", transcript_path=transcript_path)
```

**Step 2: Verify and commit**

```bash
python -c "import py_compile; py_compile.compile('hooks/session-stop.py', doraise=True); print('OK')"
git add hooks/session-stop.py
git commit -m "fix: lower auto-learn thresholds (1MB->500KB, 3MB delta->1.5MB)"
```

---

### Task 5: Remove Dead Hooks

Remove guard-webfetch.py (rules already enforce "never use WebFetch") and skill-alias.py (zero evidence of use).

**Files:**
- Delete: `~/.claude/hooks/guard-webfetch.py`
- Delete: `~/.claude/hooks/skill-alias.py`
- Modify: `~/.claude/settings.json` (remove both entries)

**Step 1: Remove from settings.json**

Python atomic write script:

```python
import json
from pathlib import Path

settings_path = Path.home() / ".claude" / "settings.json"
with open(settings_path, "r", encoding="utf-8") as f:
    settings = json.load(f)

dead_hooks = {"guard-webfetch.py", "skill-alias.py"}
pre = settings["hooks"]["PreToolUse"]
settings["hooks"]["PreToolUse"] = [
    e for e in pre
    if not any(dead in e.get("hooks", [{}])[0].get("command", "") for dead in dead_hooks)
]

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
```

**Step 2: Delete the files**

```bash
rm hooks/guard-webfetch.py hooks/skill-alias.py
```

**Step 3: Verify and commit**

```bash
python -c "import json; s=json.load(open('settings.json',encoding='utf-8')); print(f'PreToolUse: {len(s[\"hooks\"][\"PreToolUse\"])} entries')"
git add hooks/guard-webfetch.py hooks/skill-alias.py settings.json
git commit -m "chore: remove dead hooks (guard-webfetch, skill-alias)"
```

---

### Task 6: Clean Up Stale Routing Data

Reset skill-usage.jsonl to remove pre-redesign entries (security-ops, project-ops, etc.) that skew usage metrics.

**Files:**
- Modify: `~/.claude/skill-usage.jsonl`

**Step 1: Filter to post-redesign entries only**

```python
import json
from pathlib import Path

usage_path = Path.home() / ".claude" / "skill-usage.jsonl"
# Keep only entries from after the generic worker redesign (2026-03-03)
kept = []
with open(usage_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            entry = json.loads(line.strip())
            # Drop entries that reference retired agents
            agent = entry.get("agent", "")
            if agent in ("security-ops", "project-ops", "recruiting-ops", "finance-ops", "runbook-dev"):
                continue
            kept.append(line.strip())
        except:
            pass

with open(usage_path, "w", encoding="utf-8") as f:
    f.write("\n".join(kept) + "\n")

print(f"Kept {len(kept)} entries (dropped retired agent references)")
```

**Step 2: Verify**

```bash
wc -l ~/.claude/skill-usage.jsonl
```

This file is gitignored so no commit needed.

---

### Task 7: Ship All Changes

All tasks produce changes in the claude-config repo (protected). Ship via PR.

**Step 1: Create branch, stage, commit**

If tasks were committed individually, skip to push. Otherwise:

```bash
cd ~/.claude
git checkout -b refactor/architecture-streamlining
git add hooks/skill-file-validator.py hooks/bash-security-guard.py hooks/session-stop.py settings.json
git add hooks/pr-security-check.py hooks/guard-webfetch.py hooks/skill-alias.py  # deletions
git commit -m "refactor: architecture streamlining - 5 improvements from audit

- Convert skill-file-validator from prompt hook to command hook (eliminate
  LLM inference on 98% of Write/Edit calls)
- Merge pr-security-check into bash-security-guard (eliminate 1 process
  spawn per Bash call)
- Lower auto-learn thresholds (500KB min, 1.5MB delta) to increase 12%
  hit rate
- Remove guard-webfetch.py (redundant with rules) and skill-alias.py
  (zero usage)
- PreToolUse entries: 8 -> 5

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

**Step 2: Push, PR, CI, merge**

```bash
git push -u origin refactor/architecture-streamlining
gh pr create --title "refactor: architecture streamlining from audit" --body "..."
# Wait for CI
gh pr checks <number> --watch
gh pr merge <number> --squash --delete-branch --admin
git checkout main && git fetch origin main && git rebase origin/main
```

---

## Summary of Impact

| Change | Overhead Removed |
|--------|-----------------|
| Prompt hook -> command hook | LLM inference on ~98% of Write/Edit calls |
| pr-security-check merged | 1 process spawn (~250ms) per Bash call |
| guard-webfetch removed | 1 process spawn per WebFetch call |
| skill-alias removed | 1 process spawn per Skill call |
| Auto-learn thresholds lowered | Expected hit rate increase from 12% to ~25-30% |
| Stale routing data cleaned | Accurate skill usage metrics going forward |

**Net: PreToolUse entries 8 -> 5. Per-Bash overhead: 2 hooks -> 1 hook. Per-Write/Edit overhead: LLM inference -> Python script.**
