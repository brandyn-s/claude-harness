# Retrospective Gap Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the 5 remaining actionable gaps from the 2026-03-20 48h retrospective.

**Architecture:** All changes are in claude-config (`~/.claude`). Hooks are Python scripts registered in settings.json. Rules are markdown files in `rules/`. The skill-rules.json file drives skill routing. retro-extract.py is the metrics classifier.

**Tech Stack:** Python 3.12, JSON, Markdown, Git Bash

---

## Gap Summary

| # | Gap | Priority | Effort |
|---|-----|----------|--------|
| 1 | ToolSearch 95.9% empty — no diagnostics | P0 | 15 min |
| 2 | 38 "other" bash errors unclassified | P0 | 30 min |
| 3 | Worktree dispatch from non-git CWD (12 errors) | P1 | 10 min |
| 4 | cc-monitor routing misses "show me chats" | P3 | 5 min |
| 5 | inline-python-guard — add retry guidance to post-failure-guide | P1 | 10 min |

**Not included (already resolved):**
- Auto-learn: deprecated in PR #296
- cost-analyze skill: already exists at `skills/cost-analyze/SKILL.md`
- inline-python threshold: already at 400 chars (retro was wrong about 200)

---

### Task 1: ToolSearch Query Logging

**Why:** 95.9% empty rate for 5 consecutive retros. We have no data on what queries are failing. Need logs before we can fix.

**Files:**
- Modify: `hooks/toolsearch-intercept.py`

**Step 1: Add query logging to toolsearch-intercept.py**

The hook currently blocks vague queries but doesn't log anything. Add logging of every query (allowed and blocked) so retro-extract.py can analyze patterns.

Write a Python apply script (`~/fix-toolsearch-log.py`) that reads `hooks/toolsearch-intercept.py` and adds logging. The changes:

1. After `import sys`, add:
```python
from pathlib import Path
from datetime import datetime
```

2. At the top of `main()`, after the query is extracted (line ~22, after `query = tool_input.get("query", "")`), add logging before ANY exit:
```python
    # Log every ToolSearch query for retro analysis
    log_dir = Path.home() / ".claude" / "debug"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "toolsearch-queries.log"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}|{query}|{tool_input.get('max_results', 5)}\n")
    except OSError:
        pass  # Never block on logging failure
```

3. Add `.claude/debug/` to `.gitignore` if not already there (check first).

**Step 2: Verify the hook still works**

Run manually to confirm:
```bash
echo '{"tool_name":"ToolSearch","tool_input":{"query":"memory search","max_results":5}}' | python ~/.claude/hooks/toolsearch-intercept.py
```
Expected: exit code 2 (blocked, vague 2-word query), AND a line appended to `~/.claude/debug/toolsearch-queries.log`.

```bash
echo '{"tool_name":"ToolSearch","tool_input":{"query":"select:Read,Edit,Grep","max_results":3}}' | python ~/.claude/hooks/toolsearch-intercept.py
```
Expected: exit code 0 (allowed), AND a line logged.

**Step 3: Verify .gitignore coverage**

```bash
cd ~/.claude && grep "debug/" .gitignore
```
If missing, add `debug/` to `.gitignore`.

---

### Task 2: Expand Bash Error Classifier

**Why:** 38 "other" bash errors (29% of all bash errors) are unclassified. Without classification, we can't target fixes.

**Files:**
- Modify: `scripts/retro-extract.py` (function `classify_bash_error` starting at line 127)

**Step 1: Analyze the "other" errors**

The 38 unclassified errors need pattern analysis. Based on the retro's error categories and common Windows/Git Bash failure modes, add these patterns BEFORE the final `return "other"` line (line 240):

Write a Python apply script (`~/fix-classifier.py`) that reads `scripts/retro-extract.py` and inserts new patterns before `return "other"`. New patterns to add:

```python
    # Git config and remote failures
    if "fatal: not a git repository" in err_text:
        return "not_git_repo"
    if "fatal: ambiguous argument" in err_text:
        return "git_ambiguous_arg"
    # pip/package install failures
    if "pip install" in err_text or "pip3 install" in err_text:
        if "ERROR" in err_text or "Could not" in err_text:
            return "pip_install_failure"
    # CKLB/SCA script informational exits
    if "cklb" in err_text.lower() or "stig" in err_text.lower():
        if "exit" in err_text.lower() or "complete" in err_text.lower():
            return "sca_script_exit"
    # PowerShell errors
    if "pwsh" in err_text.lower() or "powershell" in err_text.lower():
        return "powershell_error"
    # gh CLI auth/scope
    if "gh auth" in err_text or "not logged into" in err_text:
        return "gh_auth_failure"
    # UnicodeEncodeError (cp1252 stdout)
    if "UnicodeEncodeError" in err_text or "codec can't encode" in err_text:
        return "encoding_error"
    # Empty output / no result from command
    if err_text.strip() == "" or "exit code 1" in err_text.lower() and len(err_text) < 50:
        return "empty_error_output"
    # taskkill / process management
    if "taskkill" in err_text.lower() or "tasklist" in err_text.lower():
        return "process_management_error"
    # AWS CLI errors not caught above
    if "aws" in err_text.lower() and ("error" in err_text.lower() or "exception" in err_text.lower()):
        return "aws_cli_error"
```

**Step 2: Verify no syntax errors**

```bash
python -c "import ast; ast.parse(open('$HOME/.claude/scripts/retro-extract.py', encoding='utf-8').read()); print('OK')"
```
Expected: `OK`

**Step 3: Quick smoke test**

```bash
python -c "
import sys; sys.path.insert(0, '$HOME/.claude/scripts')
from retro_extract import classify_bash_error
tests = [
    ('fatal: not a git repository', 'not_git_repo'),
    ('pip install boto3\nERROR: Could not find', 'pip_install_failure'),
    ('UnicodeEncodeError: charmap', 'encoding_error'),
    ('something random', 'other'),
]
for text, expected in tests:
    result = classify_bash_error(text)
    status = 'PASS' if result == expected else f'FAIL (got {result})'
    print(f'{status}: {expected}')
"
```

Note: This test may need to be written to a .py file first (platform constraint: no inline Python > 400 chars). Write it to `~/test-classifier.py` and run `python ~/test-classifier.py`.

---

### Task 3: Worktree CWD Pre-Check in Agent Delegation

**Why:** 12 "Cannot create agent worktree: not in a git repository" errors from dispatching agents with `isolation: worktree` when CWD is `C:\Users\you` (not a git repo).

**Files:**
- Modify: `rules/agent-delegation.md`

**Step 1: Add CWD check to dispatch protocol**

In `rules/agent-delegation.md`, the dispatch protocol section (numbered list starting with "1. Detect tools needed"), add a new step between step 5 (pre-dispatch auth check) and step 6 (worktree isolation). Write a Python apply script that inserts:

After the line starting with `5. Pre-dispatch auth check:`, and before `6. **MANDATORY**:`, insert:

```markdown
5b. **CWD check for worktree isolation**: If the task requires `isolation: "worktree"` and the current CWD is NOT inside the target repo, include `cd $HOME/Documents/GitHub/<repo-name>` at the start of the agent prompt. Worktree creation requires a git repo as CWD. Target repo paths are listed in `rules/subagent-verification.md`.
```

**Step 2: Verify the rule file is valid markdown**

Read back the modified file and confirm the numbered list flows correctly.

---

### Task 4: Fix cc-monitor Routing Pattern

**Why:** Session `a4bc679b8321` asked "Show me you's last 5 chats" — this should route to cc-monitor but doesn't match the current pattern `\\b(claude (spend|cost|usage)|transcript\\w*|active users|who used claude|compliance api|OTel|telemetry|invite user|workspace\\w*)\\b`.

**Files:**
- Modify: `hooks/skill-rules.json`

**Step 1: Update the cc-monitor pattern**

The pattern needs to also match "chats", "chat history", "conversations", "last N chats/conversations". Write a Python apply script that reads `hooks/skill-rules.json`, finds the cc-monitor entry, and replaces the pattern:

Old pattern:
```
\\b(claude (spend|cost|usage)|transcript\\w*|active users|who used claude|compliance api|OTel|telemetry|invite user|workspace\\w*)\\b
```

New pattern (adds chat/conversation variants):
```
\\b(claude (spend|cost|usage)|transcript\\w*|chat\\w*|conversation\\w*|active users|who used claude|compliance api|OTel|telemetry|invite user|workspace\\w*)\\b
```

The change: added `chat\\w*|conversation\\w*` to the alternation group.

**Step 2: Verify JSON validity**

```bash
python -c "import json; json.load(open('$HOME/.claude/hooks/skill-rules.json', encoding='utf-8')); print('Valid JSON')"
```

**Step 3: Verify pattern matches**

```bash
python -c "
import re
pattern = r'\\b(claude (spend|cost|usage)|transcript\\w*|chat\\w*|conversation\\w*|active users|who used claude|compliance api|OTel|telemetry|invite user|workspace\\w*)\\b'
tests = [
    ('Show me last 5 chats', True),
    ('chat history for you', True),
    ('conversations this week', True),
    ('claude spend this month', True),
    ('fix this bug', False),
]
for text, should_match in tests:
    matched = bool(re.search(pattern, text, re.IGNORECASE))
    status = 'PASS' if matched == should_match else 'FAIL'
    print(f'{status}: \"{text}\" -> match={matched}')
"
```

Write to `~/test-routing.py` first if needed (platform constraint).

---

### Task 5: Add Inline-Python Retry Guidance to Post-Failure Guide

**Why:** When inline-python-guard blocks a `python -c` command, the model retries inline instead of writing to a file. The post-failure-guide hook already handles tool failures — extend it to also guide bash failures with inline-python pattern.

**Files:**
- Modify: `hooks/post-failure-guide.py`

**Step 1: Add inline-python pattern to PATTERNS dict**

In `hooks/post-failure-guide.py`, the `PATTERNS` dict (line 23) already has `"SyntaxError"` mapping. Add a new entry:

```python
    "inline-python-guard": "Write the same code to a .py file with the Write tool, then run: python script.py",
```

This catches the hook block message which contains "inline-python-guard" in the error text.

**Step 2: Verify the hook still runs**

```bash
echo '{"tool_name":"Bash","error":"PreToolUse: inline-python-guard BLOCKED: Long inline python -c code"}' | python ~/.claude/hooks/post-failure-guide.py
```
Expected: JSON output with message containing "Write the same code to a .py file".

---

### Task 6: Commit and PR

**Files:**
- Modified: `hooks/toolsearch-intercept.py`, `scripts/retro-extract.py`, `rules/agent-delegation.md`, `hooks/skill-rules.json`, `hooks/post-failure-guide.py`
- Possibly modified: `.gitignore`

**Step 1: Review all changes**

```bash
cd ~/.claude && git diff --stat
```

**Step 2: Create branch, commit, push, PR**

```bash
cd ~/.claude && git checkout -b fix/retro-gap-fixes
git add hooks/toolsearch-intercept.py scripts/retro-extract.py rules/agent-delegation.md hooks/skill-rules.json hooks/post-failure-guide.py .gitignore
git commit -m "fix: address 5 retro gaps — ToolSearch logging, classifier, CWD check, routing, retry guide"
git push -u origin fix/retro-gap-fixes
gh pr create --title "fix: address 5 retro gaps from 48h retrospective" --body "..."
gh pr merge --auto --squash --delete-branch
```

**Step 3: Sync local main**

```bash
# After merge completes
git checkout main && git fetch origin main && git rebase origin/main
```

---

## Dependency Summary

```
[1 | 2 | 3 | 4 | 5] → 6
```

Tasks 1-5 are independent. Task 6 (commit) depends on all completing.

## Verification

After PR merges:
- [ ] `~/.claude/debug/toolsearch-queries.log` created after next ToolSearch call
- [ ] `python -c "from scripts.retro_extract import classify_bash_error"` works
- [ ] `rules/agent-delegation.md` has CWD check step
- [ ] `hooks/skill-rules.json` cc-monitor pattern matches "chats"
- [ ] `hooks/post-failure-guide.py` emits inline-python guidance
