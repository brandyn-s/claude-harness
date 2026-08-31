# Friction Reduction P0+P1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Address the 6 highest-impact remaining friction sources identified in the 14-day retrospective (505 false-positive friction events, 295 context limit events, 37-session MEMORY.md churn, 44 Edit failures, 24 tavily errors, 11-session hook monolith churn).

**Architecture:** Six independent tasks targeting P0 (metrics accuracy, compaction visibility, memory stability) and P1 (Edit retry, tavily validation, hook decomposition). All changes in claude-config repo.

**Tech Stack:** Python 3.14 (hooks), settings.json (statusline), .gitignore (config)

---

### Task 1: Exclude hook blocks from friction count

The friction extractor in session-stop.py counts hook blocks (BLOCKED, hook error) as both `tool_failure` AND `hook_block` - double-counting 505 events. The `tool_failure` regex matches "BLOCKED" and "hook error" which are guards working correctly, not failures.

**Files:**
- Modify: `hooks/session-stop.py:219-221`

**Step 1: Fix the tool_failure regex to exclude hook block patterns**

Change the `_FRICTION_PATTERNS` dict. The `tool_failure` pattern currently includes `BLOCKED` and `PreToolUse.*hook error` which overlap with `hook_block`. Remove those from `tool_failure`:

```python
_FRICTION_PATTERNS = {
    "tool_failure": re.compile(
        r"((?<!hook )error|failed|exception|traceback|exit code [1-9]|"
        r"timeout|timed out)", re.I
    ),
    "user_correction": re.compile(
        r"(try again|that'?s (wrong|not)|you already|revert|undo that|"
        r"go back|still broken|didn'?t work|not what I)", re.I
    ),
    "hook_block": re.compile(
        r"(hook error|silently reverted|unexpectedly modified|"
        r"File has been.*modified|reverted by|BLOCKED)", re.I
    ),
    "merge_conflict": re.compile(
        r"(merge conflict|Unmerged|both modified|CONFLICT|resolve conflict)", re.I
    ),
    "retry": re.compile(
        r"(let me try (a different|another)|alternative approach|"
        r"retrying|that didn'?t work.*let me)", re.I
    ),
}
```

Key change: removed `BLOCKED|PreToolUse.*hook error|PostToolUse.*error` from `tool_failure`. Added negative lookbehind `(?<!hook )` before `error` so "hook error" matches only `hook_block`, not `tool_failure`.

**Step 2: Verify session-stop.py compiles**

Run: `python -m py_compile hooks/session-stop.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add hooks/session-stop.py
git commit -m "fix: exclude hook blocks from tool_failure friction count"
```

---

### Task 2: Log compaction threshold in statusline

We don't know if the 70% autocompact override is working. The statusline already shows context `used_percentage`. Add logging that writes the percentage at the moment compaction fires, so we can measure the real threshold over multiple sessions.

**Files:**
- Modify: `statusline.py`

**Step 1: Add compaction event logging**

After the existing rate limit section (line 35), add compaction detection. The statusline runs on every render. If `used_percentage` drops significantly between renders, compaction happened. Log the pre-compaction percentage.

```python
# Compaction detection (logs threshold for empirical measurement)
_compact_log = Path.home() / ".claude" / "compaction-log.jsonl"
_last_pct_file = Path.home() / ".claude" / ".last-context-pct"
try:
    last_pct = int(_last_pct_file.read_text().strip()) if _last_pct_file.exists() else 0
    if last_pct > 30 and pct < last_pct - 20:
        # Context dropped significantly - compaction happened
        import time
        with open(_compact_log, "a", encoding="utf-8") as lf:
            lf.write(json.dumps({
                "ts": time.time(),
                "pre_pct": last_pct,
                "post_pct": pct,
                "model": model,
            }) + "\n")
    _last_pct_file.write_text(str(pct))
except Exception:
    pass
```

Add `from pathlib import Path` to the imports at line 3.

**Step 2: Add compaction-log.jsonl to .gitignore**

Append to the "Transient state files" section:

```
compaction-log.jsonl
.last-context-pct
```

**Step 3: Verify statusline still works**

Run: `echo '{"model":{"display_name":"test"},"context_window":{"used_percentage":50},"cost":{"total_cost_usd":1.5,"total_duration_ms":60000}}' | python statusline.py`
Expected: Renders statusline without error

**Step 4: Commit**

```bash
git add statusline.py .gitignore
git commit -m "feat: log compaction threshold for empirical measurement"
```

---

### Task 3: Separate auto-memory from MEMORY.md

MEMORY.md is touched in 37 of 223 sessions (17%) because Claude Code's auto-memory writes to it AND it contains manually curated reference content. This makes it a constant merge conflict source.

**Solution:** Gitignore MEMORY.md so auto-memory writes don't create dirty state. The curated content (Key Paths, tool facts, architecture summaries) is already duplicated across topic files, pattern files, and ARCHITECTURE.md - MEMORY.md is a convenience index, not the source of truth.

**Files:**
- Modify: `.gitignore`

**Step 1: Add MEMORY.md to gitignore**

In the "Transient state files" section, add:

```
# Auto-memory target (auto-modified by Claude Code, curated content lives in pattern files)
projects/*/memory/MEMORY.md
```

**Step 2: Remove from git tracking**

```bash
git rm --cached projects/<your-claude-project>/memory/MEMORY.md
```

**Step 3: Verify MEMORY.md still exists on disk**

Run: `test -f projects/<your-claude-project>/memory/MEMORY.md && echo "exists" || echo "MISSING"`
Expected: `exists`

**Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore MEMORY.md (auto-memory target, not source of truth)"
```

---

### Task 4: Tavily extract URL validation hook

24 friction events from `tavily_extract` receiving a bare string instead of a list for the `urls` parameter. This is the 5th consecutive session with this error (documented in CLAUDE.md line 91). Add a PreToolUse hook that validates the parameter before the call fires.

**Files:**
- Create: `hooks/tavily-extract-guard.py`
- Modify: `settings.json` (via Python script - hook cache prevents direct Edit)

**Step 1: Create the guard script**

```python
#!/usr/bin/env python3
"""PreToolUse guard: validate tavily_extract urls param is a list."""
import json
import sys

try:
    data = json.loads(sys.stdin.read())
except (json.JSONDecodeError, EOFError):
    sys.exit(0)

tool_name = data.get("tool_name", "")
if tool_name != "mcp__tavily__tavily_extract":
    sys.exit(0)

tool_input = data.get("tool_input", {})
urls = tool_input.get("urls")

if urls is not None and not isinstance(urls, list):
    print(
        "[tavily-guard] BLOCKED: `urls` must be a JSON array of strings, "
        'e.g. ["https://example.com"]. Got a bare string instead. '
        "Fix: wrap in square brackets.",
        file=sys.stderr,
    )
    sys.exit(2)

sys.exit(0)
```

**Step 2: Verify compiles**

Run: `python -m py_compile hooks/tavily-extract-guard.py`
Expected: No output (success)

**Step 3: Add test case**

Create `hooks/test-hooks/test_tavily_extract_guard.py`:

```python
"""Smoke tests for tavily-extract-guard.py."""
from conftest import run_hook

HOOK = "tavily-extract-guard.py"

def _make_extract_input(urls):
    return {
        "tool_name": "mcp__tavily__tavily_extract",
        "tool_input": {"urls": urls, "query": "test"},
    }

def test_allow_list_urls():
    rc, _, _ = run_hook(HOOK, _make_extract_input(["https://example.com"]))
    assert rc == 0

def test_block_string_url():
    rc, _, stderr = run_hook(HOOK, _make_extract_input("https://example.com"))
    assert rc == 2
    assert "array" in stderr.lower()

def test_allow_non_extract_tool():
    rc, _, _ = run_hook(HOOK, {
        "tool_name": "mcp__tavily__tavily_search",
        "tool_input": {"query": "test"},
    })
    assert rc == 0
```

**Step 4: Run tests**

Run: `python -m pytest hooks/test-hooks/test_tavily_extract_guard.py -v`
Expected: 3/3 pass

**Step 5: Register hook in settings.json**

Use a Python script to add the hook (settings.json Edit reverts):

```python
import json
from pathlib import Path

settings = Path.home() / ".claude" / "settings.json"
data = json.loads(settings.read_text(encoding="utf-8"))

# Add tavily extract guard to PreToolUse
pre = data["hooks"]["PreToolUse"]
if not any("tavily-extract-guard" in str(h) for h in pre):
    pre.append({
        "matcher": "mcp__tavily__tavily_extract",
        "hooks": [{
            "type": "command",
            "command": "C:/Users/you/AppData/Local/Programs/Python/Python314/pythonw.exe $HOME/.claude/hooks/tavily-extract-guard.py",
            "timeout": 3,
        }],
    })

settings.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

**Step 6: Commit**

```bash
git add hooks/tavily-extract-guard.py hooks/test-hooks/test_tavily_extract_guard.py settings.json
git commit -m "feat: add tavily_extract URL validation guard (prevents bare string urls)"
```

---

### Task 5: Add Edit "modified since read" retry guidance

44 friction events from "File has been modified since read" Edit errors. These happen when hooks modify files between Read and Edit calls. Add a PostToolUseFailure prompt hook that gives specific retry guidance.

**Files:**
- Modify: `settings.json` (via Python script)

**Step 1: Add the prompt hook**

The hook fires on Edit failures and provides actionable guidance:

```python
import json
from pathlib import Path

settings = Path.home() / ".claude" / "settings.json"
data = json.loads(settings.read_text(encoding="utf-8"))

# Add Edit retry guidance to PostToolUseFailure
post_fail = data["hooks"].get("PostToolUseFailure", [])
if not any("modified since read" in str(h) for h in post_fail):
    post_fail.append({
        "matcher": "Edit",
        "hooks": [{
            "type": "prompt",
            "prompt": "The Edit failed. If the error is 'File has been modified since read': a hook modified the file between your Read and Edit. Re-read the file with the Read tool, then retry the Edit with the updated content. If in ~/.claude/, consider using a Python script via Bash instead (hooks don't intercept Bash file writes). If the error is 'String to replace not found': the old_string doesn't match - re-read and use the exact text.",
            "timeout": 3,
        }],
    })

data["hooks"]["PostToolUseFailure"] = post_fail
settings.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

**Step 2: Commit**

```bash
git add settings.json
git commit -m "feat: add Edit failure retry guidance (modified-since-read, string-not-found)"
```

---

### Task 6: Decompose session-stop.py into modules

session-stop.py is edited in 11 of 223 sessions. It's a monolith that handles dirty repo checks, episodic memory, friction extraction, trajectory capture, session metrics, and stash management. Each new feature touches this one file.

**Solution:** Extract each concern into its own module in `hooks/session_stop_modules/`. The main `session-stop.py` becomes a thin dispatcher.

**Files:**
- Create: `hooks/session_stop_modules/__init__.py`
- Create: `hooks/session_stop_modules/dirty_repo.py`
- Create: `hooks/session_stop_modules/episodic_memory.py`
- Create: `hooks/session_stop_modules/friction_extraction.py`
- Modify: `hooks/session-stop.py`

**Step 1: Create the modules directory**

```python
# hooks/session_stop_modules/__init__.py
# (empty)
```

**Step 2: Extract dirty repo check**

Move the `REPOS` list, `run_dirty_repo_check()`, and `_stash_hook_repos()` functions into `dirty_repo.py`. Keep the same function signatures. Add the necessary imports (subprocess, sys, os, Path).

**Step 3: Extract episodic memory**

Move `RECENT_SESSIONS_PATH`, `MAX_RECENT_ENTRIES`, `RECENT_HEADER`, and `_update_episodic_memory()` into `episodic_memory.py`. Add the necessary imports (re, datetime, Path).

**Step 4: Extract friction extraction**

Move `FRICTION_PATH`, `MAX_FRICTION_ENTRIES`, `FRICTION_HEADER`, `_FRICTION_PATTERNS`, and `_extract_session_friction()` into `friction_extraction.py`. Add the necessary imports (json, re, datetime, Path).

**Step 5: Slim down session-stop.py**

Replace the function bodies with imports:

```python
from session_stop_modules.dirty_repo import run_dirty_repo_check, _stash_hook_repos
from session_stop_modules.episodic_memory import _update_episodic_memory
from session_stop_modules.friction_extraction import _extract_session_friction
```

The `main()` function stays in session-stop.py - it just calls the imported functions.

The `_extract_trajectory()` placeholder stays in session-stop.py (it's a no-op).

**Step 6: Verify all modules compile**

Run:
```bash
python -m py_compile hooks/session-stop.py
python -m py_compile hooks/session_stop_modules/dirty_repo.py
python -m py_compile hooks/session_stop_modules/episodic_memory.py
python -m py_compile hooks/session_stop_modules/friction_extraction.py
```
Expected: All succeed

**Step 7: Commit**

```bash
git add hooks/session-stop.py hooks/session_stop_modules/
git commit -m "refactor: decompose session-stop.py into modules (dirty_repo, episodic_memory, friction)"
```

---

### Task 7: Ship all changes

All 6 tasks on one feature branch:

```bash
git push -u origin feat/friction-reduction-p0-p1
gh pr create --title "feat: friction reduction P0+P1 - metrics, compaction, memory, tavily, Edit retry, hook decomp"
gh pr merge --auto --squash --delete-branch
```

---

## Verification Checklist

After merge:
- [ ] `python -m pytest hooks/test-hooks/ -v` passes (19+ test cases including new tavily tests)
- [ ] `python -m py_compile hooks/session-stop.py` succeeds
- [ ] `python hooks/validate-consistency.py` passes with 0 errors
- [ ] `hooks/topic-checksums.json` not in git
- [ ] `MEMORY.md` not in git (`git ls-files | grep MEMORY.md` returns empty)
- [ ] `compaction-log.jsonl` gitignored
- [ ] Statusline renders without error
- [ ] Friction extractor no longer double-counts hook blocks as tool failures
