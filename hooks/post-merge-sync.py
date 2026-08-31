#!/usr/bin/env python3
"""
PostToolUse:Bash hook - auto-sync local main after `gh pr merge`.

When a Bash command contains `gh pr merge`, this hook runs:
    git checkout main && git fetch origin main && git rebase origin/main

This implements the "After merging a PR (MANDATORY sync)" step from
git-hygiene.md, removing the need to remember it manually.

Outputs a JSON message describing what was synced on success.
Exits 0 silently if the command doesn't match `gh pr merge`.
"""

import sys

if sys.platform == "win32":
    import ctypes
    _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if _hwnd:
        ctypes.windll.user32.ShowWindow(_hwnd, 0)
import json
import os
import subprocess
import sys

# Windows: suppress console windows for child processes
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Add scripts dir to path for git_lock import
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "scripts"))
try:
    from git_lock import git_lock
except ImportError:
    from contextlib import contextmanager

    @contextmanager
    def git_lock(repo_path, timeout=30):
        yield  # Graceful degradation - no locking if import fails

# Atomic write helper
sys.path.insert(0, os.path.join(os.path.expanduser("~"), ".claude", "hooks"))
from atomic_write import atomic_write

# ── PIP-COMPILE WINDOWS PACKAGE STRIPPING ────────────────────────────

_WINDOWS_ONLY_PREFIXES = ["pywin32==", "pywin32-ctypes==", "pypiwin32=="]


def cleanup_pip_compile(command, cwd):
    """Strip Windows-only packages from pip-compile output lock files."""
    if "pip-compile" not in command:
        return
    import glob
    import re
    import time

    # Try to find output file from --output-file flag
    lock_files = []
    m = re.search(r"--output-file[=\s]+(\S+)", command)
    if m:
        lock_files.append(m.group(1))

    # Fallback: find recently modified .lock files in cwd
    if not lock_files:
        now = time.time()
        for lf in glob.glob(os.path.join(cwd, "**", "requirements.lock"), recursive=True):
            if now - os.path.getmtime(lf) < 30:
                lock_files.append(lf)

    stripped_total = 0
    for lock_file in lock_files:
        if not os.path.isabs(lock_file):
            lock_file = os.path.join(cwd, lock_file)
        if not os.path.isfile(lock_file):
            continue
        try:
            with open(lock_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            filtered = [
                line for line in lines
                if not any(line.strip().lower().startswith(p) for p in _WINDOWS_ONLY_PREFIXES)
            ]
            if len(filtered) < len(lines):
                atomic_write(lock_file, "".join(filtered))
                stripped_total += len(lines) - len(filtered)
        except OSError:
            pass

    if stripped_total > 0:
        print(
            f"Auto-stripped {stripped_total} Windows-only package(s) from pip-compile output.",
            file=sys.stderr,
        )



# ── POST-INFRA DEPLOY TRIGGER ────────────────────────────────────────

_INFRA_TRIGGER_PATHS = ["ecs", "iam", "alb", "main.tf", "secrets"]


def trigger_deploy_if_infra(cwd):
    """After merging in mcp-infra, trigger mcp-servers deploy workflow."""
    cwd_norm = cwd.replace("\\", "/").lower()
    if "mcp-infra" not in cwd_norm:
        return
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--name-only", "--format="],
            capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return
        changed = result.stdout.strip().lower()
    except Exception:
        return
    if not any(p in changed for p in _INFRA_TRIGGER_PATHS):
        return
    try:
        result = subprocess.run(
            ["gh", "workflow", "run", "Build and Deploy MCP Services",
             "--repo", "example-org/mcp-servers", "--ref", "main"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=15, creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            print("AUTO-TRIGGER: mcp-servers deploy started (infra change in mcp-infra)", file=sys.stderr)
        else:
            print(f"AUTO-TRIGGER: failed: {result.stderr[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"AUTO-TRIGGER: error: {e}", file=sys.stderr)


def _is_linked_worktree(repo_path):
    """True when repo_path is a linked git worktree (not the main checkout).

    A linked worktree's --absolute-git-dir lives under
    <main>/.git/worktrees/<name>, while --git-common-dir points at the main
    checkout's .git. Equal (normalized) paths = main checkout. Returns False
    on any probe failure so the caller falls through to existing behavior.
    """
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir", "--git-common-dir"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return False
        lines = r.stdout.strip().splitlines()
        if len(lines) != 2:
            return False
        git_dir, common_dir = lines[0].strip(), lines[1].strip()
        if not os.path.isabs(common_dir):
            common_dir = os.path.join(repo_path, common_dir)
        norm = lambda p: os.path.normcase(os.path.realpath(p))
        return norm(git_dir) != norm(common_dir)
    except Exception:
        return False


def _is_repo_dirty(repo_path):
    """Check if a repo has uncommitted changes (excluding known transients)."""
    try:
        r = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return False  # Can't determine — assume clean
        transients = [
            "settings.json", "last-distill.json", "topic-checksums.json",
            "recent-sessions.md", "session-friction-patterns.md",
            "mcp-needs-auth-cache.json", ".precompact-state.json",
        ]
        for line in r.stdout.strip().splitlines():
            filename = line.strip().split()[-1] if line.strip() else ""
            if not any(t in filename for t in transients):
                return True
        return False
    except Exception:
        return False


def _stash_and_rebase(repo_path):
    """Sync local main with origin/main. Uses reset when diverged (RC3 fix).

    After squash-merge, local main has pre-squash commits that cause cascading
    rebase conflicts. This detects the divergence and uses reset --hard instead.
    250 merge_conflict friction events traced to this root cause.
    """
    dirty = _is_repo_dirty(repo_path)
    stashed = False

    if dirty:
        r = subprocess.run(
            ["git", "stash", "--include-untracked"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=repo_path, timeout=15, creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0 and "No local changes" not in r.stdout:
            stashed = True
        elif r.returncode != 0:
            return False, f"stash failed: {r.stderr.strip()[:100]}"

    # RC3: detect if local main has diverged from origin/main
    # This happens after squash-merge: local has pre-squash commits
    diverged = False
    try:
        r = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0 and r.stdout.strip().isdigit():
            local_ahead = int(r.stdout.strip())
            if local_ahead > 0:
                diverged = True
    except Exception:
        pass

    if diverged:
        # Local main has commits not on remote. The intent here is to
        # discard "pre-squash" commits whose content already lives in
        # the squashed origin/main. But if a diverging commit has REAL
        # unpushed work, reset --hard silently destroys it. Verify each
        # diverging commit's tree is reachable from origin/main before
        # resetting; if any commit has a non-empty diff vs origin/main,
        # bail out and tell the operator to handle it.
        local_safe = True
        unsafe_commits = []
        try:
            commits_r = subprocess.run(
                ["git", "rev-list", "origin/main..HEAD"],
                capture_output=True, text=True, encoding="utf-8",
                cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
            )
            commits = [c for c in commits_r.stdout.strip().splitlines() if c]
            for commit in commits:
                # Empty diff vs origin/main → content is already on remote
                # (the squashed PR). Non-empty diff → real divergence.
                diff_r = subprocess.run(
                    ["git", "diff", "--quiet", "origin/main", commit, "--"],
                    capture_output=True, text=True, encoding="utf-8",
                    cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
                )
                # `git diff --quiet` exits 0 if no diff, 1 if diff exists.
                if diff_r.returncode != 0:
                    local_safe = False
                    unsafe_commits.append(commit[:8])
        except Exception:
            # Defensive: if the check itself fails, refuse to reset.
            local_safe = False

        if not local_safe:
            # Pop the stash so the operator's working tree is intact, then
            # bail out without destructive action.
            if stashed:
                subprocess.run(
                    ["git", "stash", "pop"],
                    capture_output=True, text=True, encoding="utf-8",
                    cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
                )
            sample = ", ".join(unsafe_commits[:3]) if unsafe_commits else "diff-check failed"
            return False, (
                f"refused to reset --hard origin/main: local has "
                f"{local_ahead} diverging commit(s) with non-empty diffs vs "
                f"remote (sample: {sample}). Resolve manually."
            )

        # Belt-and-braces: stash a recovery ref so the user can recover
        # via `git update-ref refs/heads/main refs/backup/post-merge-sync`
        # if the reset turned out to be wrong after all.
        subprocess.run(
            ["git", "update-ref", "refs/backup/post-merge-sync", "HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=repo_path, timeout=5, creationflags=CREATE_NO_WINDOW,
        )

        r = subprocess.run(
            ["git", "reset", "--hard", "origin/main"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        method = f"reset (diverged by {local_ahead}, all squashed-equivalent)"
    else:
        # Normal case: fast-forward rebase
        r = subprocess.run(
            ["git", "rebase", "origin/main"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=repo_path, timeout=30, creationflags=CREATE_NO_WINDOW,
        )
        method = "rebase"

    if r.returncode != 0:
        if not diverged:
            subprocess.run(
                ["git", "rebase", "--abort"],
                capture_output=True, text=True, encoding="utf-8",
                cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
            )
        if stashed:
            subprocess.run(
                ["git", "stash", "pop"],
                capture_output=True, text=True, encoding="utf-8",
                cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
            )
        return False, f"{method} failed: {r.stderr.strip()[:100]}"

    if stashed:
        r = subprocess.run(
            ["git", "stash", "pop"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=repo_path, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return True, f"{method} OK but stash pop conflict: {r.stderr.strip()[:100]}"

    return True, f"stash+{method}+pop" if stashed else method


# NOTE: cross-repo sync (sync_other_repos) was removed 2026-05-03 after a
# silent-data-loss incident. The function fetched + stash+rebased every
# managed repo on main after any PR merge, which corrupted in-flight
# untracked files when a long-running process (roundtable harness) was
# writing to a managed repo at the time the hook fired. The opportunistic
# convenience of "your other local mains stay fresh" did not justify the
# silent data-loss footgun. Other repos now require a manual `git pull`.


# ── AUTO-MERGE MARKER TRACKING (RC2) ─────────────────────────────────

_AUTO_MERGE_MARKER = os.path.join(os.path.expanduser("~"), ".claude", ".auto-merge-active.json")


def _update_auto_merge_marker(command, cwd, tool_result):
    """Track auto-merge state for the push-after-auto-merge guard in bash-security-guard.py.

    Writes a marker when --auto merge is queued. Clears when PR is actually merged.
    The marker is checked by bash-security-guard.py to block pushes to branches
    with active auto-merge (RC2: PR #421 lost 6 commits this way).
    """
    result_str = str(tool_result).lower()

    if "--auto" in command and "--disable-auto" not in command:
        # Auto-merge was queued — write marker
        if "will be automatically merged" in result_str or "auto-merge" in result_str:
            try:
                branch = subprocess.run(
                    ["git", "branch", "--show-current"],
                    capture_output=True, text=True, encoding="utf-8",
                    cwd=cwd, timeout=5, creationflags=CREATE_NO_WINDOW,
                )
                branch_name = branch.stdout.strip()
                if branch_name and branch_name not in ("main", "master"):
                    markers = {}
                    if os.path.isfile(_AUTO_MERGE_MARKER):
                        with open(_AUTO_MERGE_MARKER, "r", encoding="utf-8") as f:
                            markers = json.load(f)
                    from datetime import datetime, timezone
                    markers[branch_name] = {"ts": datetime.now(timezone.utc).isoformat()}
                    # Atomic write: a crash mid-json.dump left invalid JSON,
                    # which the next read swallowed (bare except), silently
                    # disabling the lost-commits push-guard this marker backs.
                    atomic_write(_AUTO_MERGE_MARKER, json.dumps(markers))
            except Exception:
                pass

    # PR was actually merged — clear the marker for the branch
    if "merged" in result_str and ("squash" in result_str or "merge" in result_str):
        try:
            if os.path.isfile(_AUTO_MERGE_MARKER):
                with open(_AUTO_MERGE_MARKER, "r", encoding="utf-8") as f:
                    markers = json.load(f)
                # We're likely on main now (post-merge sync already checked out main),
                # so we can't determine the old branch. Clear ALL markers since a merge
                # just completed — the queued auto-merge has fired.
                if markers:
                    atomic_write(_AUTO_MERGE_MARKER, json.dumps({}))
        except Exception:
            pass


# ── MAIN ─────────────────────────────────────────────────────────────


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    command = hook_input.get("tool_input", {}).get("command", "")
    cwd = hook_input.get("tool_input", {}).get("cwd", None) or os.getcwd()

    # pip-compile cleanup (independent of merge sync)
    cleanup_pip_compile(command, cwd)

    if "gh pr merge" not in command:
        sys.exit(0)

    # RC2: track auto-merge state for push guard. PostToolUse delivers the
    # result under one of three keys across Claude Code versions; tool_response
    # is canonical (see hook_input.py). Reading only tool_result meant the
    # auto-merge marker silently went unwritten on versions emitting
    # tool_response — re-opening the lost-commits class this guard prevents.
    tool_result = (
        hook_input.get("tool_response")
        or hook_input.get("tool_result")
        or hook_input.get("response")
        or ""
    )
    _update_auto_merge_marker(command, cwd, tool_result)

    # Check if the merge actually succeeded by looking at tool_result
    result_str = str(tool_result).lower()
    # If the merge failed or was blocked, don't try to sync. gh's real
    # failure texts often contain NEITHER "error" NOR "failed" — observed
    # 2026-06-12 (twice in one session, hook synced + checked out main
    # mid-flow off a feature branch):
    #   "GraphQL: Auto merge is not allowed for this repository (enablePullRequestAutoMerge)"
    #   "GraphQL: Pull request Pull request is in clean status (enablePullRequestAutoMerge)"
    # "graphql:" catches the whole gh API-error class (success output never
    # contains it). "merged" remains the success override: a compound result
    # that ultimately reports a merge still syncs.
    _MERGE_FAILURE_SIGNS = ("error", "failed", "graphql:", "not allowed", "clean status")
    if any(s in result_str for s in _MERGE_FAILURE_SIGNS) and "merged" not in result_str:
        sys.exit(0)

    # Guard: never sync inside a LINKED WORKTREE. The sync's `git checkout
    # main` either fails ('main' is held by another checkout) or — worse —
    # succeeds and yanks the worktree off its feature branch mid-work. Both
    # shapes hit the 2026-06-11 mac-port convergence: a clean worktree passed
    # the dirty guard below, got checked out to main after a `gh pr merge`
    # nudge, and a later `checkout && rebase` chain then ran against the
    # wrong branch of the live config. The main checkout's main syncs on the
    # next merge from it (or via repo_sync at session start).
    if _is_linked_worktree(cwd):
        json.dump({
            "decision": "approve",
            "reason": (
                f"POST-MERGE SYNC SKIPPED: {cwd} is a linked worktree — "
                "syncing here would move it off its feature branch. The main "
                "checkout syncs on the next merge from it (or at session start)."
            ),
        }, sys.stdout)
        sys.exit(0)

    # Guard: skip sync if working tree has uncommitted changes.
    # The sync does `git checkout main` which discards or conflicts with
    # uncommitted edits started for the next task. Warn and bail instead.
    try:
        dirty_check = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        dirty_files = [
            line for line in dirty_check.stdout.strip().splitlines()
            if line.strip() and not any(
                skip in line for skip in ["topic-checksums.json", "recent-sessions.md"]
            )
        ]
        if dirty_files:
            msg = (
                f"POST-MERGE SYNC SKIPPED: {len(dirty_files)} uncommitted file(s) in {cwd}. "
                f"Files: {', '.join(f.split()[-1] for f in dirty_files[:5])}. "
                "Run `git stash` or commit before syncing to avoid losing edits."
            )
            json.dump({"decision": "approve", "reason": msg}, sys.stdout)
            sys.exit(0)
    except Exception:
        pass  # If the check itself fails, proceed with sync

    # Run the post-merge sync sequence under git lock
    results = []
    try:
        with git_lock(cwd, timeout=15):
            # Step 1: checkout main
            r = subprocess.run(
                ["git", "checkout", "main"],
                capture_output=True, text=True, encoding="utf-8",
                cwd=cwd, timeout=30, creationflags=CREATE_NO_WINDOW,
            )
            if r.returncode != 0:
                results.append(f"git checkout main: FAILED ({r.stderr.strip()[:150]})")
            else:
                results.append("git checkout main: OK")

                # Step 2: fetch
                r = subprocess.run(
                    ["git", "fetch", "origin", "main"],
                    capture_output=True, text=True, encoding="utf-8",
                    cwd=cwd, timeout=30, creationflags=CREATE_NO_WINDOW,
                )
                if r.returncode != 0:
                    results.append(f"git fetch origin main: FAILED ({r.stderr.strip()[:150]})")
                else:
                    results.append("git fetch origin main: OK")

                    # Step 3: stash-aware rebase (handles dirty trees from concurrent sessions)
                    ok, msg = _stash_and_rebase(cwd)
                    if ok:
                        results.append(f"git rebase origin/main: OK ({msg})")
                    else:
                        results.append(f"git rebase origin/main: FAILED ({msg})")

                    # Step 4: prune local branches whose upstream is gone AND whose tip
                    # is already merged (squash-merge cleanup).
                    # `--delete-branch` on `gh pr merge` removes the remote branch but leaves
                    # the local clone tracking a [gone] upstream. Without this prune, repos
                    # accumulate hundreds of stale local branches over months.
                    #
                    # SAFETY CHANGED 2026-07-26 (audit finding H3). This used to run
                    # `git branch -D` on every [gone] branch, justified by "gone-upstream
                    # means GitHub already accepted+removed the remote; divergent local-only
                    # history would require a non-tracking branch." That is FALSE: [gone] is
                    # a fact about the UPSTREAM REF, not about local history, so any commit
                    # made after the last push is invisible to it. Reproduced on a disposable
                    # repo -- a [gone] branch carrying one local-only commit was
                    # force-deleted, leaving reflog as the only way back.
                    #
                    # Now: require the tip to be contained in an accepted base, write a
                    # recovery ref first, and use `-d` so git independently refuses anything
                    # unmerged. A branch failing the check is LEFT ALONE -- a stale branch is
                    # cosmetic; destroying unpushed work is not.
                    #
                    # Duplicated from session_start_modules/repo_sync.py by design: this hook
                    # must stay import-free of the session-start package. Both copies carry
                    # the same guards; change them together.
                    try:
                        prune_fetch = subprocess.run(
                            ["git", "fetch", "--prune", "origin"],
                            capture_output=True, text=True, encoding="utf-8",
                            cwd=cwd, timeout=20, creationflags=CREATE_NO_WINDOW,
                        )
                        if prune_fetch.returncode == 0:
                            listing = subprocess.run(
                                ["git", "for-each-ref",
                                 "--format=%(refname:short) %(upstream:track)",
                                 "refs/heads/"],
                                capture_output=True, text=True, encoding="utf-8",
                                cwd=cwd, timeout=10, creationflags=CREATE_NO_WINDOW,
                            )
                            if listing.returncode == 0:
                                gone = []
                                for line in listing.stdout.strip().splitlines():
                                    if "[gone]" in line.lower():
                                        branch = line.split(" ", 1)[0]
                                        if branch and branch not in ("main", "master"):
                                            gone.append(branch)

                                def _g(args, _cwd=cwd):
                                    return subprocess.run(
                                        ["git", *args],
                                        capture_output=True, text=True, encoding="utf-8",
                                        cwd=_cwd, timeout=10,
                                        creationflags=CREATE_NO_WINDOW,
                                    )

                                deleted = 0
                                preserved = 0
                                for branch in gone:
                                    merged = False
                                    for base in ("origin/main", "origin/master",
                                                 "main", "master"):
                                        if _g(["rev-parse", "--verify", "--quiet",
                                               base]).returncode != 0:
                                            continue
                                        if _g(["merge-base", "--is-ancestor", branch,
                                               base]).returncode == 0:
                                            merged = True
                                            break
                                    if not merged:
                                        preserved += 1
                                        continue
                                    _g(["update-ref",
                                        f"refs/gone-recovery/{branch}", branch])
                                    r = _g(["branch", "-d", branch])
                                    if r.returncode == 0:
                                        deleted += 1
                                    else:
                                        _g(["update-ref", "-d",
                                            f"refs/gone-recovery/{branch}"])
                                if deleted > 0:
                                    results.append(f"prune gone branches: {deleted} deleted")
                                if preserved > 0:
                                    results.append(
                                        f"prune gone branches: {preserved} PRESERVED "
                                        "(unmerged local commits)"
                                    )
                    except Exception:
                        pass  # Cleanup is opportunistic; never block the merge sync
    except TimeoutError:
        results.append(
            "SKIPPED: could not acquire git lock (another session is syncing)"
        )

    # Check final state
    try:
        status = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        clean = "clean" if not status.stdout.strip() else "dirty"
        # Auto-cleanup hook artifacts (runtime state, not config)
        if clean == "dirty":
            hook_artifacts = [
                line.strip().split()[-1]
                for line in status.stdout.strip().split("\n")
                if any(p in line for p in [
                    "topic-checksums.json", "recent-sessions.md",
                ])
            ]
            for filepath in hook_artifacts:
                try:
                    subprocess.run(
                        ["git", "checkout", "--", filepath],
                        capture_output=True, text=True, encoding="utf-8",
                        cwd=cwd, timeout=5, creationflags=CREATE_NO_WINDOW,
                    )
                except Exception:
                    pass
            if hook_artifacts:
                results.append(f"Auto-cleaned {len(hook_artifacts)} hook artifact(s)")
    except Exception:
        clean = "unknown"

    # Check for conflict markers
    try:
        conflict_check = subprocess.run(
            ["git", "diff", "--check"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=cwd, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        if conflict_check.returncode != 0 and conflict_check.stdout.strip():
            results.append(
                f"WARNING: Conflict markers detected: {conflict_check.stdout.strip()[:200]}"
            )
    except Exception:
        pass

    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        current_branch = branch.stdout.strip()
    except Exception:
        current_branch = "unknown"

    sync_summary = "; ".join(results)
    message = (
        f"POST-MERGE AUTO-SYNC completed in {cwd}. "
        f"Branch: {current_branch}, State: {clean}. "
        f"Steps: {sync_summary}"
    )

    # Trigger mcp-servers deploy if this was an infra change
    trigger_deploy_if_infra(cwd)

    json.dump({"decision": "approve", "reason": message}, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)