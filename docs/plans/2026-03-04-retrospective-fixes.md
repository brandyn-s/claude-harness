# Retrospective Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 5 issues identified in the first /retrospective run - remove hook noise, fix retry metric, deduplicate sessions, add MSYS rule, fix user request capture.

**Architecture:** All changes are in `~/.claude/` (claude-config repo). Three changes to `retro-extract.py`, one rule addition to `platform-constraints.md`, one plugin hook configuration. Single commit at the end.

**Tech Stack:** Python 3.12 stdlib, Markdown rules files.

---

### Task 1: Fix retry metric to only count retries after errors

The current retry detection counts ANY sequential same-tool call as a retry (e.g., Bash -> Bash -> Bash = 2 retries). This inflates the retry rate to 60.6%. The fix: only count a sequential same-tool call as a retry when the *previous* call to that tool resulted in an error.

**Files:**
- Modify: `~/.claude/scripts/retro-extract.py:62-170`

**Step 1: Replace the retry tracking logic**

In `extract_session()`, the current retry tracking uses `last_tool_name` and `sequential_same_tool`. Replace with error-aware retry detection. The key change: track whether the last tool call errored, and only count a same-tool follow-up as a retry if the previous call had an error.

Replace lines 79-82:
```python
    # Track sequential same-tool calls for retry detection
    last_tool_name = None
    sequential_same_tool = 0
    retry_count = 0
```

With:
```python
    # Track error-aware retry detection
    last_tool_name = None
    last_tool_errored = False
    retry_count = 0
```

Then replace the retry detection block inside the `tool_use` handler (lines 153-163):
```python
                            # Retry detection: sequential calls to the same tool
                            if tool_name == last_tool_name:
                                sequential_same_tool += 1
                                if sequential_same_tool == 1:
                                    # First repeat = first retry
                                    retry_count += 1
                                else:
                                    retry_count += 1
                            else:
                                sequential_same_tool = 0
                            last_tool_name = tool_name
```

With:
```python
                            # Retry detection: same tool called after previous errored
                            if tool_name == last_tool_name and last_tool_errored:
                                retry_count += 1
                            last_tool_name = tool_name
                            last_tool_errored = False
```

And in the error detection block (after `errors.append(err_msg)` around line 132), add:
```python
                                # Mark that this tool call errored (for retry detection)
                                last_tool_errored = True
```

**Step 2: Verify**

Run: `python3 ~/.claude/scripts/retro-extract.py --window 48 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Retry rate: {d[\"aggregates\"][\"retry_rate_pct\"]}%')"`

Expected: Retry rate should drop from ~60% to somewhere between 2-10%.

---

### Task 2: Deduplicate sessions by session ID

The transcript directory has multiple snapshots of the same session ID at different save points (e.g., `2026-03-02-07-21-5247f309.jsonl` and `2026-03-02-08-01-5247f309.jsonl` are the same session). Keep only the latest (largest timestamp) file per session ID.

**Files:**
- Modify: `~/.claude/scripts/retro-extract.py:355-372`

**Step 1: Add deduplication after candidate collection**

After the candidates list is built and sorted (line 376), add deduplication logic before the extraction loop. Group by session ID (the hex suffix), keep the file with the latest timestamp.

Replace lines 375-383:
```python
    # Sort by filename (chronological)
    candidates.sort(key=lambda p: p.name)

    # Extract per-session metrics
    sessions = []
    for filepath in candidates:
        session_data = extract_session(filepath)
        if session_data is None:
            continue
```

With:
```python
    # Sort by filename (chronological)
    candidates.sort(key=lambda p: p.name)

    # Deduplicate: keep only the latest file per session ID
    by_session_id = {}
    for filepath in candidates:
        m = FILENAME_RE.match(filepath.name)
        if not m:
            continue
        session_id = m.group(6)
        # Later file (sorted chronologically) overwrites earlier
        by_session_id[session_id] = filepath
    candidates = sorted(by_session_id.values(), key=lambda p: p.name)

    # Extract per-session metrics
    sessions = []
    for filepath in candidates:
        session_data = extract_session(filepath)
        if session_data is None:
            continue
```

**Step 2: Verify**

Run: `python3 ~/.claude/scripts/retro-extract.py --window 48 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Sessions: {d[\"aggregates\"][\"session_count\"]}')"`

Expected: Session count should drop from 24 to ~15 (fewer unique session IDs).

---

### Task 3: Fix user request capture for slash-command sessions

Sessions started via `/plugin`, `/mcp`, or other slash commands have `<local-command-caveat>` boilerplate as the first human message instead of the actual user request.

**Files:**
- Modify: `~/.claude/scripts/retro-extract.py:109-111`

**Step 1: Update the first_human_message capture**

Replace the first human message detection (lines 109-111):
```python
                    # First human text message (not tool results)
                    if first_human_message is None and isinstance(content, str) and content.strip():
                        first_human_message = content.strip()[:300]
```

With:
```python
                    # First human text message (skip system boilerplate)
                    if isinstance(content, str) and content.strip():
                        text = content.strip()
                        # Skip local-command-caveat boilerplate and command messages
                        if (
                            "<local-command-caveat>" in text
                            or "<command-name>" in text
                            or "<command-message>" in text
                            or text.startswith("<system-reminder>")
                        ):
                            pass
                        elif first_human_message is None:
                            first_human_message = text[:300]
```

**Step 2: Verify**

Run: `python3 ~/.claude/scripts/retro-extract.py --window 48 2>&1 | python3 -c "import sys,json; d=json.load(sys.stdin); [print(s['user_request'][:80] if s['user_request'] else 'null') for s in d['sessions'][:5]]"`

Expected: No `<local-command-caveat>` strings in the output. Real user requests or `null` (for sessions with no human text at all).

---

### Task 4: Add MSYS path rewriting rule for gh api

**Files:**
- Modify: `~/.claude/rules/platform-constraints.md:29`

**Step 1: Update the MSYS path expansion bullet**

The existing bullet on line 29 mentions `MSYS_NO_PATHCONV=1` set in `~/.bashrc`. Append a concrete instruction for `gh api`:

Find the bullet that starts with `- Git Bash filesystem and text-processing commands fail intermittently` and after it, add a new bullet:

```
- `gh api` calls with path arguments starting with `/` get MSYS-rewritten (e.g., `/apps/123` becomes `C:/Program Files/Git/apps/123`). The global `MSYS_NO_PATHCONV=1` env var doesn't reach Claude Code's non-interactive shell. Fix: always prefix `gh api` calls with `MSYS_NO_PATHCONV=1`, e.g., `MSYS_NO_PATHCONV=1 gh api /apps/123`. (Confirmed 2026-03-04, 4+ occurrences in 48h retro.)
```

**Step 2: Verify**

Read the file and confirm the new bullet appears after the MSYS bullet.

---

### Task 5: Remove superpowers security_reminder_hook noise

The superpowers plugin's `security_reminder_hook.py` fires on every GitHub Actions workflow edit, creating ~40 false "errors" per 48h window. Our own `security-review-before-pr.md` rule is superior (checks at PR time, not per-edit).

**Files:**
- Modify: `~/.claude/settings.json` (disable the hook via settings, not by deleting plugin files)

**Step 1: Check current hook configuration**

The superpowers plugin hooks are registered in `installed_plugins.json` or the plugin's own config. Since we can't edit plugin files (they get restored), the cleanest approach is to add the hook to the `disabledHooks` list in `settings.json`.

Read `~/.claude/settings.json` to find the current hooks configuration. Then add the security_reminder_hook to `disabledHooks` (or equivalent exclusion mechanism).

If `settings.json` doesn't support `disabledHooks`, the alternative is to use a Python script to atomically modify `installed_plugins.json` and remove the hook entry for `security_reminder_hook.py`.

**Step 2: Verify**

After the change, edit a `.github/workflows/*.yml` file and confirm the hook no longer fires.

---

### Task 6: Commit all changes

**Step 1: Stage and commit**

```bash
cd ~/.claude
git checkout -b fix/retrospective-improvements
git add scripts/retro-extract.py rules/platform-constraints.md settings.json
git commit -m "fix: improve retrospective metrics - retry detection, session dedup, request capture"
```

**Step 2: Push, PR, merge**

```bash
git push origin fix/retrospective-improvements -u
gh pr create --title "fix: improve retrospective metrics accuracy" --body "..."
gh pr checks --watch
gh pr merge --squash --delete-branch --admin
git checkout main && git fetch origin main && git rebase origin/main
```
