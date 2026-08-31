# Retro P0/P1 Fixes - Mar 18, 2026

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close all P0 and P1 gaps from the Mar 16-18 retrospective: verify auto-stash fix, confirm auto-merge, expand the error classifier, and add Voyage/embedding skill routing.

**Architecture:** Two files change: `retro-extract.py` gets 6 new bash error patterns, `skill-rules.json` gets a new routing rule for Voyage/embedding/API integration keywords pointing to the preflight skill.

**Tech Stack:** Python (retro-extract.py), JSON (skill-rules.json)

---

## P0 Status: Already Resolved

Both P0 items are confirmed resolved before this plan was written:

- **dirty_working_tree auto-stash**: Fix deployed at `~/.claude/hooks/session-start.py:965-971`. The `_sync_tracked_repos()` function stashes dirty state before rebase and pops afterward. All 3 errors in the retro occurred before PR #256 merged.
- **code-search auto-merge**: Already enabled (`gh api /repos/example-apps-org/code-search --jq '.allow_auto_merge'` returns `true`).

No implementation needed for P0.

---

### Task 1: Add 6 Error Classifier Patterns to retro-extract.py

**Files:**
- Modify: `~/.claude/scripts/retro-extract.py:124-221` (inside `classify_bash_error()`)

These 6 patterns address the 25 "other" bash errors (35% of total) identified in the retro. Each pattern is inserted BEFORE the final `return "other"` at line 221.

**Step 1: Add pytest test failure pattern**

Insert before `return "other"` (line 221) in `classify_bash_error()`:

```python
    if "FAILED" in err_text and ("test" in err_text.lower() or "pytest" in err_text.lower()):
        return "test_failure"
    if "short test summary" in err_text:
        return "test_failure"
```

**Why:** pytest exits with code 1 and prints `FAILED` + `short test summary info`. This was the most common unclassified pattern (test runs during development).

**Step 2: Add WinError 32 / file locked pattern**

Insert after the test_failure pattern:

```python
    if "WinError 32" in err_text or "being used by another process" in err_text:
        return "file_locked"
```

**Why:** 3 occurrences in Session 81770294 from PermissionError on files locked by other processes. The existing `file_locked` pattern only matches `Device or resource busy` (Unix) and generic `lock.*file`.

**Step 3: Add GitHub Actions workflow rerun failure pattern**

Insert after the file_locked pattern:

```python
    if "cannot be rerun" in err_text or "cannot be retried" in err_text:
        return "workflow_rerun_blocked"
```

**Why:** `gh run rerun` fails when the workflow doesn't allow reruns. Multiple occurrences in the retro.

**Step 4: Add self-approval blocked pattern**

Insert after the workflow_rerun_blocked pattern:

```python
    if "Cannot approve your own pull request" in err_text:
        return "self_approval_blocked"
```

**Why:** New pattern from Session 81770294 where the model tried to approve its own PR.

**Step 5: Add background preload failure pattern**

Insert after the self_approval_blocked pattern:

```python
    if "preload" in err_text.lower() and "failed" in err_text.lower():
        return "background_preload_failure"
```

**Why:** Background model preload failures surfaced in the retro as unclassified.

**Step 6: Widen the existing jq_parse_error match**

The existing jq pattern at lines 205-208 requires BOTH `jq` AND (`parse` OR `Cannot iterate`). But some jq errors just have `jq: error` without those keywords.

Replace lines 205-208:

```python
    # Before:
    if "jq" in err_text and (
        "parse" in err_text.lower() or "Cannot iterate" in err_text
    ):
        return "jq_parse_error"

    # After:
    if "jq" in err_text and (
        "parse" in err_text.lower()
        or "Cannot iterate" in err_text
        or "error" in err_text.lower()
    ):
        return "jq_parse_error"
```

**Why:** Catches `jq: error (at <stdin>:0): Cannot iterate over null (null)` and similar variants.

**Step 7: Run the classifier against the latest extract to verify**

Run:
```bash
python3 ~/.claude/scripts/retro-extract.py --window 55 --depth deep 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
bash = data['aggregates']['error_breakdown'].get('bash_error', {})
other = bash.get('other', 0)
total = sum(bash.values())
print(f'bash_error breakdown: {json.dumps(bash, indent=2)}')
print(f'other: {other}/{total} ({other/total*100:.1f}%)' if total else 'no bash errors')
"
```

Expected: `other` count drops from 25 to ~10 or less. New categories `test_failure`, `file_locked`, `workflow_rerun_blocked`, `self_approval_blocked` appear.

**Step 8: Commit**

```bash
git add scripts/retro-extract.py
git commit -m "feat: expand error classifier with 6 patterns (retro P1)"
```

---

### Task 2: Add Voyage/Embedding Skill Routing Rule

**Files:**
- Modify: `~/.claude/hooks/skill-rules.json` (add one rule object to the `rules` array)

**Step 1: Add the routing rule**

Add a new rule object to the `rules` array in `skill-rules.json`, after the `deep-dive` rule (line 78) and before the `capture` rule (line 80):

```json
    {
      "pattern": "\\b(voyage|embedding\\w*|vector (search|db|index)|semantic search|api integration.{0,20}(key|env|token))\\b",
      "skill": "preflight",
      "agent": null,
      "desc": "Pre-flight checks for external API integrations (env vars, keys, docs)",
      "priority": "medium"
    },
```

**Why:** Session 8385fd9b had 8 of 11 errors from Voyage AI integration - missing env vars, rate limits, and API format mismatches. The preflight skill exists (PR #249) but wasn't triggered because no routing rule matched "Voyage" or "embedding" keywords.

**Step 2: Validate the JSON**

Run:
```bash
python3 -c "import json; json.load(open('$HOME/.claude/hooks/skill-rules.json')); print('valid')"
```

Expected: `valid`

**Step 3: Test the routing match**

Run:
```bash
echo '{"prompt": "Add Voyage AI embeddings to the search system"}' | python3 ~/.claude/hooks/skill-routing-hint.py
```

Expected: JSON output containing `"Routing hint [SUGGESTED]: Skill: /preflight"` and `[matched: 'Voyage']` or similar.

**Step 4: Test negative - ensure existing rules still win**

Run:
```bash
echo '{"prompt": "triage the CrowdStrike detection on host XYZ"}' | python3 ~/.claude/hooks/skill-routing-hint.py
```

Expected: Routes to `triage`, not `preflight` (triage has `critical` priority, preflight has `medium`).

**Step 5: Commit**

```bash
git add hooks/skill-rules.json
git commit -m "feat: route Voyage/embedding keywords to preflight skill (retro P1)"
```

---

## Verification Checklist

After both tasks:

- [ ] `retro-extract.py` classifies pytest failures as `test_failure`
- [ ] `retro-extract.py` classifies WinError 32 as `file_locked`
- [ ] `retro-extract.py` classifies workflow reruns as `workflow_rerun_blocked`
- [ ] `retro-extract.py` "other" drops below 20% of bash errors
- [ ] `skill-rules.json` is valid JSON
- [ ] "Voyage" prompt routes to preflight skill
- [ ] "triage CrowdStrike" prompt still routes to triage (not preflight)
- [ ] Both commits on a feature branch, PR created, auto-merge queued
