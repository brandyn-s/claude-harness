"""Tests for post-merge-sync.py.

Validates routing logic — non-Bash ignored, no-merge ignored, error results ignored.
Full git sync is not tested (requires live git repos).
"""
import subprocess

from conftest import HOOKS_DIR, PYTHON, run_hook

HOOK = "post-merge-sync.py"


def make_posttool_bash(command, tool_result="", is_error=False):
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_result": tool_result,
        "is_error": is_error,
    }


# ── Routing / filtering ──


def test_non_bash_tool_ignored():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/test.py"},
        "tool_result": "",
    })
    assert rc == 0


def test_bash_without_merge_ignored():
    rc, stdout, _ = run_hook(HOOK, make_posttool_bash("git status"))
    assert rc == 0


def test_bash_with_git_push_ignored():
    rc, stdout, _ = run_hook(
        HOOK, make_posttool_bash("git push -u origin feat/my-branch")
    )
    assert rc == 0


def test_merge_with_error_result_ignored():
    rc, stdout, _ = run_hook(
        HOOK,
        make_posttool_bash(
            "gh pr merge 42 --auto --squash",
            tool_result="error: pull request is not mergeable",
        ),
    )
    assert rc == 0


def test_merge_with_failed_result_ignored():
    rc, stdout, _ = run_hook(
        HOOK,
        make_posttool_bash(
            "gh pr merge 42 --auto --squash",
            tool_result="failed to merge: branch protection requires reviews",
        ),
    )
    assert rc == 0


# gh's real failure texts contain neither "error" nor "failed" — both
# observed 2026-06-12 causing the hook to sync (checkout main) mid-flow
# right after a FAILED merge command. The strong assertion is "no sync
# attempted" (empty stdout), not just rc == 0: the hook exits 0 either way.

def _failed_merge_input(tmp_path, tool_result):
    return {
        "tool_name": "Bash",
        "tool_input": {
            "command": "gh pr create --title x --body y && gh pr merge --auto --squash --delete-branch",
            "cwd": str(tmp_path),  # non-git dir: harmless even if the guard regresses
        },
        "tool_result": tool_result,
        "is_error": True,
    }


def test_merge_auto_not_allowed_does_not_sync(tmp_path):
    rc, stdout, _ = run_hook(HOOK, _failed_merge_input(
        tmp_path,
        "https://github.com/org/repo/pull/7\n"
        "GraphQL: Auto merge is not allowed for this repository (enablePullRequestAutoMerge)",
    ))
    assert rc == 0
    assert "AUTO-SYNC" not in stdout


def test_merge_clean_status_does_not_sync(tmp_path):
    rc, stdout, _ = run_hook(HOOK, _failed_merge_input(
        tmp_path,
        "https://github.com/org/repo/pull/30\n"
        "GraphQL: Pull request Pull request is in clean status (enablePullRequestAutoMerge)",
    ))
    assert rc == 0
    assert "AUTO-SYNC" not in stdout


def test_pip_compile_no_crash():
    """pip-compile cleanup runs without crash even with no lock files."""
    rc, stdout, _ = run_hook(
        HOOK,
        make_posttool_bash("pip-compile requirements.in --output-file requirements.lock"),
    )
    assert rc == 0


# ── Linked-worktree guard ──


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )


def test_linked_worktree_skips_sync(tmp_path):
    """In a linked worktree the hook must skip — never checkout main there.

    2026-06-11 incident: a clean worktree on a feature branch passed the
    dirty guard and got checked out to main by this hook after a
    `gh pr merge` call, yanking it off its branch mid-work.
    """
    import json as _json

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "init")
    wt = tmp_path / "wt"
    r = _git(repo, "worktree", "add", str(wt), "-b", "feature/x")
    assert r.returncode == 0, r.stderr

    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr merge 1 --auto", "cwd": str(wt)},
        "tool_result": "queued to merge",
    })
    assert rc == 0
    assert stdout.strip(), "expected a skip message, got silence"
    reason = _json.loads(stdout).get("reason", "")
    assert "linked worktree" in reason.lower()
    # The worktree must still be on its feature branch
    branch = _git(wt, "branch", "--show-current").stdout.strip()
    assert branch == "feature/x"


def test_main_checkout_not_flagged_as_worktree(tmp_path):
    """The main checkout must NOT trip the worktree guard (sync proceeds
    to the dirty-tree guard, which fires here via the untracked file)."""
    import json as _json

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "init")
    (repo / "dirty.txt").write_text("y", encoding="utf-8")  # arm dirty guard

    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr merge 1 --auto", "cwd": str(repo)},
        "tool_result": "queued to merge",
    })
    assert rc == 0
    reason = _json.loads(stdout).get("reason", "") if stdout.strip() else ""
    assert "linked worktree" not in reason.lower()


# ── Edge cases ──


def test_invalid_json_exits_clean():
    result = subprocess.run(
        [PYTHON, str(HOOKS_DIR / HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0


def test_empty_command_ignored():
    rc, _, _ = run_hook(HOOK, make_posttool_bash(""))
    assert rc == 0
