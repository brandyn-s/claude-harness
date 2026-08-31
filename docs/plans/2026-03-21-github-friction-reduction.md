# GitHub Friction Reduction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Cut fix commit ratio from 40% to ~20% by addressing the six root causes of GitHub friction identified in the 7-day retrospective.

**Architecture:** Six independent workstreams (P0-P2), each targeting one friction category. P0 items address fix-spawns-fix chains (hook smoke tests) and hook interference (config/state separation). P1 items harden CI workflow changes and merge conflict handling. P2 addresses API integration churn with pre-PR reminders.

**Tech Stack:** Python 3.14 (hooks), pytest (CI tests), YAML (workflows), Markdown (rules/skills)

---

## Workstream A: Hook Smoke Tests in CI (P0 - fixes Category 1)

Prevents fix-spawns-fix chains by testing hooks against real input before merge. Targets the 12 PRs/week pattern where a hook change takes 3-5 PRs to land correctly.

### Task 1: Create test infrastructure

**Files:**
- Create: `hooks/test-hooks/conftest.py`
- Create: `hooks/test-hooks/__init__.py`

**Step 1: Create the test directory and conftest**

```python
# hooks/test-hooks/__init__.py
# (empty)
```

```python
# hooks/test-hooks/conftest.py
"""Shared fixtures for hook smoke tests."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

def run_hook(hook_name: str, hook_input: dict, timeout: int = 10) -> tuple[int, str, str]:
    """Invoke a hook script with JSON stdin, return (exit_code, stdout, stderr)."""
    hook_path = HOOKS_DIR / hook_name
    assert hook_path.exists(), f"Hook not found: {hook_path}"
    result = subprocess.run(
        [PYTHON, str(hook_path)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        cwd=str(HOOKS_DIR.parent),
    )
    return result.returncode, result.stdout, result.stderr

def make_bash_input(command: str, cwd: str = "") -> dict:
    """Build a PreToolUse:Bash hook input payload."""
    return {
        "tool_name": "Bash",
        "tool_input": {
            "command": command,
            "cwd": cwd or str(Path.home()),
        },
    }

def make_write_input(file_path: str, content: str = "") -> dict:
    """Build a PostToolUse:Write hook input payload."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": content,
        },
    }
```

**Step 2: Verify test infra works**

Run: `cd ~/.claude && python -m pytest hooks/test-hooks/ --collect-only`
Expected: `no tests ran` (collection succeeds, 0 tests found)

**Step 3: Commit**

```bash
git add hooks/test-hooks/
git commit -m "test: add hook smoke test infrastructure"
```

---

### Task 2: Bash security guard smoke tests

**Files:**
- Create: `hooks/test-hooks/test_bash_security_guard.py`

**Step 1: Write the test cases**

```python
# hooks/test-hooks/test_bash_security_guard.py
"""Smoke tests for bash-security-guard.py.

Tests the 12 guard functions against known-good and known-bad commands.
Exit 0 = allow, Exit 2 = block.
"""
from conftest import make_bash_input, run_hook

HOOK = "bash-security-guard.py"
CLAUDE_DIR_CWD = str(__import__("pathlib").Path.home() / ".claude")
MCP_SERVERS_CWD = str(__import__("pathlib").Path.home() / "Documents" / "GitHub" / "mcp-servers")

# ── Credential guard ──

def test_allow_normal_bash():
    rc, _, _ = run_hook(HOOK, make_bash_input("ls -la"))
    assert rc == 0

def test_block_cat_ssh_key():
    rc, _, stderr = run_hook(HOOK, make_bash_input("cat ~/.ssh/id_rsa"))
    assert rc == 2
    assert "credential" in stderr.lower() or "blocked" in stderr.lower()

def test_block_cat_aws_credentials():
    rc, _, stderr = run_hook(HOOK, make_bash_input("cat ~/.aws/credentials"))
    assert rc == 2

# ── Push guard ──

def test_block_push_main_protected():
    rc, _, stderr = run_hook(HOOK, make_bash_input(
        "git push origin main", cwd=MCP_SERVERS_CWD
    ))
    assert rc == 2
    assert "push" in stderr.lower() or "protected" in stderr.lower()

def test_allow_push_feature_branch():
    rc, _, _ = run_hook(HOOK, make_bash_input(
        "git push -u origin feat/my-feature", cwd=MCP_SERVERS_CWD
    ))
    assert rc == 0

# ── Commit-on-main guard ──

def test_block_commit_on_main_protected():
    """This test depends on the current branch. Skip if not on main."""
    rc, _, stderr = run_hook(HOOK, make_bash_input(
        'git commit -m "test"', cwd=CLAUDE_DIR_CWD
    ))
    # If on main, should block. If on feature branch, allowed.
    # We test the known case: claude-config is protected.
    # rc == 2 means guard fired (on main), rc == 0 means on feature branch.
    assert rc in (0, 2)

# ── Inline python guard ──

def test_block_long_inline_python():
    long_code = "x = " + "1 + " * 100 + "1"
    rc, _, stderr = run_hook(HOOK, make_bash_input(f'python -c "{long_code}"'))
    assert rc == 2
    assert "inline" in stderr.lower()

def test_allow_short_inline_python():
    rc, _, _ = run_hook(HOOK, make_bash_input('python -c "print(42)"'))
    assert rc == 0

# ── Dangerous command guard ──

def test_block_rm_rf_root():
    rc, _, stderr = run_hook(HOOK, make_bash_input("rm -rf /"))
    assert rc == 2

def test_allow_rm_specific_file():
    rc, _, _ = run_hook(HOOK, make_bash_input("rm /tmp/test.txt"))
    assert rc == 0

# ── MSYS pathconv reminder ──

def test_warn_gh_api_without_msys():
    rc, _, stderr = run_hook(HOOK, make_bash_input("gh api /repos/owner/repo"))
    # Should allow but warn (or block depending on implementation)
    # Main check: doesn't crash
    assert rc in (0, 2)

# ── AWS profile guard ──

def test_warn_aws_without_profile():
    rc, _, stderr = run_hook(HOOK, make_bash_input("aws s3 ls"))
    # Should warn or block about missing AWS_PROFILE
    assert rc in (0, 2)
```

**Step 2: Run tests**

Run: `cd ~/.claude && python -m pytest hooks/test-hooks/test_bash_security_guard.py -v`
Expected: All tests pass (adjust any that fail due to branch state)

**Step 3: Commit**

```bash
git add hooks/test-hooks/test_bash_security_guard.py
git commit -m "test: add bash-security-guard smoke tests (13 cases)"
```

---

### Task 3: Search path guard smoke tests

**Files:**
- Create: `hooks/test-hooks/test_search_path_guard.py`

**Step 1: Write the test cases**

```python
# hooks/test-hooks/test_search_path_guard.py
"""Smoke tests for search-path-guard.py."""
import json
from conftest import run_hook

HOOK = "search-path-guard.py"

def _make_glob_input(path: str) -> dict:
    return {
        "tool_name": "Glob",
        "tool_input": {"pattern": "**/*.py", "path": path},
    }

def _make_grep_input(path: str) -> dict:
    return {
        "tool_name": "Grep",
        "tool_input": {"pattern": "TODO", "path": path},
    }

def test_allow_scoped_path():
    rc, _, _ = run_hook(HOOK, _make_glob_input("$HOME/Documents/GitHub/mcp-servers"))
    assert rc == 0

def test_block_home_dir():
    rc, _, stderr = run_hook(HOOK, _make_glob_input("C:/Users/you"))
    assert rc == 2

def test_block_c_root():
    rc, _, stderr = run_hook(HOOK, _make_grep_input("C:/"))
    assert rc == 2

def test_allow_specific_project():
    rc, _, _ = run_hook(HOOK, _make_grep_input("$HOME/.claude/hooks"))
    assert rc == 0
```

**Step 2: Run tests**

Run: `cd ~/.claude && python -m pytest hooks/test-hooks/test_search_path_guard.py -v`
Expected: All pass

**Step 3: Commit**

```bash
git add hooks/test-hooks/test_search_path_guard.py
git commit -m "test: add search-path-guard smoke tests (4 cases)"
```

---

### Task 4: Add hook tests to CI workflow

**Files:**
- Modify: `.github/workflows/validate.yml`

**Step 1: Add the test step**

After the existing "Validate cross-file consistency" step, add:

```yaml
      - name: Smoke test hooks
        run: |
          pip install pytest --quiet
          python -m pytest hooks/test-hooks/ -v --tb=short
```

Note: This step runs on Ubuntu in CI. Some tests depend on Windows paths and local git state. Tests that can't run in CI should be marked with `@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")`.

**Step 2: Add platform skip markers to conftest**

Add to `hooks/test-hooks/conftest.py`:

```python
import platform

windows_only = pytest.mark.skipif(
    platform.system() != "Windows",
    reason="Requires Windows paths and local git repos"
)
```

Then apply `@windows_only` to tests that reference local Windows paths (push guard, commit guard tests).

**Step 3: Create platform-safe test subset**

Tests that work cross-platform (credential guard, dangerous command guard, inline python guard) should NOT have the marker. Tests that need local repo state get the marker.

**Step 4: Run locally to verify**

Run: `cd ~/.claude && python -m pytest hooks/test-hooks/ -v`
Expected: All pass locally

**Step 5: Commit**

```bash
git add .github/workflows/validate.yml hooks/test-hooks/
git commit -m "ci: add hook smoke tests to validate workflow"
```

---

## Workstream B: Config/State Separation (P0 - fixes Category 2)

Eliminates hook interference by separating tracked config from runtime state. Targets the 8 PRs/week caused by hooks mutating tracked files.

### Task 5: Gitignore topic-checksums.json

**Files:**
- Modify: `.gitignore`

**Step 1: Add to gitignore**

Append to the "Caches and databases" section of `.gitignore`:

```
# Hook runtime state (regenerable, changes every session)
hooks/topic-checksums.json
```

**Step 2: Remove from git tracking**

```bash
git rm --cached hooks/topic-checksums.json
```

**Step 3: Verify**

Run: `git status --short`
Expected: `.gitignore` modified, `hooks/topic-checksums.json` deleted (from index only, file still on disk)

**Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore topic-checksums.json (runtime state, not config)"
```

---

### Task 6: Add settings.json guard to bash-security-guard

**Files:**
- Modify: `hooks/bash-security-guard.py`

**Step 1: Add a new guard function after `check_commit_on_main`**

```python
def check_settings_json_staged(command, cwd):
    """Warn when settings.json is staged for commit.

    settings.json is overwritten by Claude Code on session stop from its
    in-memory cache. Committing it risks shipping cached state instead of
    intentional config changes.
    """
    if "git commit" not in command and "git add" not in command:
        return None

    # Check if we're in claude-config repo
    cwd_norm = cwd.replace("\\", "/").lower()
    if ".claude" not in cwd_norm:
        return None

    if "git add" in command and "settings.json" in command:
        return (
            "[settings-guard] WARNING: Staging settings.json. This file is "
            "overwritten by Claude Code on session stop. Verify these are "
            "intentional config changes, not cached session state."
        )

    # For commits, check if settings.json is in the staged diff
    if "git commit" in command:
        try:
            r = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True, text=True, encoding="utf-8",
                cwd=cwd, timeout=5, creationflags=CREATE_NO_WINDOW,
            )
            if "settings.json" in r.stdout:
                return (
                    "[settings-guard] WARNING: settings.json is in the staged diff. "
                    "This file is overwritten by Claude Code on session stop. "
                    "Verify these are intentional config changes."
                )
        except Exception:
            pass

    return None
```

**Step 2: Wire into main()**

In the main function, after `check_commit_on_main`, add:

```python
    warning = check_settings_json_staged(command, effective_cwd)
    if warning:
        print(warning, file=sys.stderr)
        # Non-blocking warning (exit 0, not 2)
```

Note: This is a WARNING, not a BLOCK. `settings.json` changes ARE sometimes intentional (like the PreCompact echo update). The guard just reminds to verify.

**Step 3: Add test**

Add to `hooks/test-hooks/test_bash_security_guard.py`:

```python
def test_warn_settings_json_add():
    rc, _, stderr = run_hook(HOOK, make_bash_input(
        "git add settings.json", cwd=CLAUDE_DIR_CWD
    ))
    # Should allow (warning only, not block)
    assert rc == 0
    assert "settings" in stderr.lower()
```

**Step 4: Run tests**

Run: `cd ~/.claude && python -m pytest hooks/test-hooks/test_bash_security_guard.py -v`
Expected: All pass including new test

**Step 5: Commit**

```bash
git add hooks/bash-security-guard.py hooks/test-hooks/test_bash_security_guard.py
git commit -m "feat: add settings.json staging warning to bash security guard"
```

---

### Task 7: Harden post-merge-sync with auto-cleanup

**Files:**
- Modify: `hooks/post-merge-sync.py`

**Step 1: Add auto-cleanup after sync**

After the sync commands succeed (after the `with git_lock` block in `main()`), add cleanup logic. Find the section after `clean = "clean" if not status.stdout.strip() else "dirty"` and add:

```python
    # Auto-cleanup hook artifacts after sync
    if clean == "dirty" and status.stdout.strip():
        dirty_files = status.stdout.strip().split("\n")
        hook_artifacts = [
            f for f in dirty_files
            if any(p in f for p in [
                "topic-checksums.json",
                "settings.json",
                "recent-sessions.md",
            ])
        ]
        if hook_artifacts:
            for f in hook_artifacts:
                # Extract filename (git status format: " M path/to/file")
                filepath = f.strip().split()[-1] if f.strip() else ""
                if filepath:
                    try:
                        subprocess.run(
                            ["git", "checkout", "--", filepath],
                            capture_output=True, text=True, encoding="utf-8",
                            cwd=cwd, timeout=5, creationflags=CREATE_NO_WINDOW,
                        )
                    except Exception:
                        pass
            results.append(f"Auto-cleaned {len(hook_artifacts)} hook artifact(s)")
```

**Step 2: Add conflict marker detection after stash pop**

Add a new helper function:

```python
def check_conflict_markers(cwd):
    """Check for unresolved conflict markers after git operations."""
    try:
        r = subprocess.run(
            ["git", "diff", "--check"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None
```

Call it after the sync and report any markers found.

**Step 3: Verify**

Run: `python -m py_compile hooks/post-merge-sync.py && echo OK`
Expected: `OK`

**Step 4: Commit**

```bash
git add hooks/post-merge-sync.py
git commit -m "feat: auto-cleanup hook artifacts and detect conflict markers after merge sync"
```

---

### Task 8: Document settings.json lifecycle

**Files:**
- Modify: `rules/platform-constraints.md`

**Step 1: Add lifecycle documentation**

After the existing `~/.claude.json` bullet (line 22), add:

```markdown
- `settings.json` has three versions during a session: (1) **git HEAD** (canonical config, committed), (2) **in-memory cache** (loaded at session start, used by Claude Code), (3) **working copy** (overwritten from cache on session stop). Edit via PR only - Write/Edit tool changes are overwritten on session stop. The bash-security-guard warns when `settings.json` is staged for commit. To make intentional changes: edit via Python script, commit on a feature branch, push + PR. The working copy will diverge until next session starts from the merged version.
```

**Step 2: Commit**

```bash
git add rules/platform-constraints.md
git commit -m "docs: document settings.json three-version lifecycle"
```

---

## Workstream C: CI Workflow Change Safety (P1 - fixes Category 4)

### Task 9: Add workflow change detection to ship skill

**Files:**
- Modify: `skills/ship/SKILL.md`

**Step 1: Add workflow gate to Phase 3**

After the "Security Review Gate" section (line 330), add a new section:

```markdown
---

## CI Workflow Gate

Before creating any PR, check if the diff includes CI workflow files:

```bash
git diff --cached --name-only | grep -q '\.github/workflows/'
```

If workflow files are in the diff:

1. **Do NOT queue `--auto` merge** - workflows must be verified manually
2. Print: "This PR modifies CI workflows. Wait for CI to run green on this PR before merging."
3. After `gh pr create`, run `gh pr checks <number> --watch` and wait for results
4. Only proceed to `gh pr merge` after all checks pass

Additionally, if a workflow references config files (grep for filenames like `ruff.toml`, `.eslintrc`, `pyproject.toml` in the workflow YAML), verify those files exist in the repo:

```bash
# Extract referenced config files from workflow
grep -oE '[a-z]+\.(toml|json|yml|yaml|rc)' .github/workflows/*.yml | sort -u
# Verify each exists
for f in $(grep -oE '[a-z]+\.(toml|json|yml|yaml|rc)' .github/workflows/*.yml | sort -u); do
  test -f "$f" || echo "WARNING: $f referenced in workflow but missing from repo"
done
```

If missing config files are found, add them in the same commit before creating the PR.
```

**Step 2: Commit**

```bash
git add skills/ship/SKILL.md
git commit -m "feat(ship): add CI workflow change gate - no auto-merge for workflow PRs"
```

---

## Workstream D: Merge Conflict Prevention (P1 - fixes Category 6)

### Task 10: Add stash-pop conflict detection to bash-security-guard

**Files:**
- Modify: `hooks/bash-security-guard.py`

This is a PostToolUse check, but since bash-security-guard is PreToolUse, we add the conflict marker check to `post-merge-sync.py` instead (already done in Task 7).

Instead, add a `git diff --check` validator to `validate-consistency.py` that catches conflict markers in any tracked file.

**Files:**
- Modify: `hooks/validate-consistency.py`

**Step 1: Add conflict marker check**

Add as Check 9 in `validate-consistency.py`, before the report section:

```python
    # =========================================================
    # CHECK 9: Conflict markers in tracked files
    # No file should have unresolved <<<<<<< / ======= / >>>>>>>
    # =========================================================
    import subprocess as _sp
    try:
        r = _sp.run(
            ["git", "diff", "--check", "HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(root), timeout=10,
        )
        if r.returncode != 0 and r.stdout.strip():
            for line in r.stdout.strip().split("\n")[:5]:
                errors.append(f"[conflict-markers] {line.strip()}")
    except Exception:
        pass  # git not available in CI - skip
    total_checks = 9
```

**Step 2: Run locally**

Run: `cd ~/.claude && python hooks/validate-consistency.py`
Expected: 9 checks, 0 errors

**Step 3: Commit**

```bash
git add hooks/validate-consistency.py
git commit -m "feat: add conflict marker detection to consistency validation (check 9)"
```

---

## Workstream E: API Integration Churn (P2 - fixes Category 5)

### Task 11: Add API client change reminder to bash-security-guard

**Files:**
- Modify: `hooks/bash-security-guard.py`

**Step 1: Add API doc reminder to `check_pr_security`**

In the existing `check_pr_security` function, after the current security-sensitive file checks, add:

```python
    # API client change reminder
    api_imports = ["voyageai", "httpx", "openai", "boto3", "falconpy", "msal"]
    if any(f"import {lib}" in diff_content or f"from {lib}" in diff_content for lib in api_imports):
        warnings.append(
            "[api-doc-check] PR modifies API client code. "
            "Verify response formats against current docs (Context7, Tavily, or SDK source)."
        )
```

This is a non-blocking warning printed during `gh pr create`, reminding about doc verification.

**Step 2: Commit**

```bash
git add hooks/bash-security-guard.py
git commit -m "feat: add API doc verification reminder to PR security check"
```

---

## Workstream F: Consistency CI Enhancement (P2 - fixes Category 3)

### Task 12: Add pre-ship consistency check to ship skill

**Files:**
- Modify: `skills/ship/SKILL.md`

**Step 1: Add consistency validation to Phase 3**

After the commit message generation in Phase 3, before creating the PR, add:

```markdown
### Pre-ship consistency check

Before creating the PR, run the consistency validator locally:

```bash
python hooks/validate-consistency.py
```

If errors are found, fix them before creating the PR. Warnings are acceptable but should be reviewed.

This catches cross-file drift at commit time (faster feedback than waiting for CI).
```

**Step 2: Commit**

```bash
git add skills/ship/SKILL.md
git commit -m "feat(ship): add pre-ship consistency validation step"
```

---

## Final Integration

### Task 13: Ship all changes

All tasks should be on a single feature branch. After all tasks pass locally:

```bash
git push -u origin feat/github-friction-reduction
gh pr create --title "feat: GitHub friction reduction - hook tests, config separation, CI safety" --body "..."
gh pr merge --auto --squash --delete-branch
```

Wait for CI (this PR modifies workflows - Task 9's own rule applies). Verify all new checks pass before merging.

---

## Verification Checklist

After merge, confirm:

- [ ] `python -m pytest hooks/test-hooks/ -v` passes locally (17+ test cases)
- [ ] `python hooks/validate-consistency.py` passes with 0 errors
- [ ] `hooks/topic-checksums.json` no longer appears in `git status`
- [ ] `settings.json` staging triggers a warning in bash-security-guard
- [ ] CI validate workflow includes hook smoke tests step
- [ ] Ship skill documents CI workflow gate and pre-ship consistency check
- [ ] `platform-constraints.md` documents settings.json lifecycle
