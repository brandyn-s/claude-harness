"""Behavior tests for git-empty-push-guard.py.

Contract: PreToolUse:Bash. BLOCK (exit 2) when a `git push` would push a
branch that is 0 commits ahead of its upstream (the cross-session-index-
race signature). Allow (0) for: non-push commands, --force/tags/delete,
no-upstream (first push), branch ahead of upstream, and the
CLAUDE_GIT_PUSH_ALLOW_EMPTY=1 bypass.

The branch-ahead cases need a real git repo, so this file is registered
in conftest._NEEDS_GIT and skips in sandboxes that can't make commits.
"""
import os
import subprocess

import pytest

from conftest import run_hook, make_bash_input

HOOK = "git-empty-push-guard.py"

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.com",
}


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, env=_ENV, check=True,
                   capture_output=True, timeout=10)


@pytest.fixture
def repo_zero_ahead(tmp_path):
    """A repo where `feature` tracks local `main` and is 0 commits ahead."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    _git(["commit", "-q", "--allow-empty", "-m", "init"], r)
    _git(["checkout", "-q", "-b", "feature"], r)
    # Point feature's upstream at local main (no network needed).
    _git(["config", "branch.feature.remote", "."], r)
    _git(["config", "branch.feature.merge", "refs/heads/main"], r)
    return r


# ── early-return ALLOW cases (no git state needed) ─────────────────────

def test_non_push_command_allowed():
    code, _o, _e = run_hook(HOOK, make_bash_input("git status"))
    assert code == 0


def test_if_prefilter_is_superset_of_guard_trigger():
    """settings.json wires this guard with `if: "Bash(git push*)"` so Claude Code
    skips the Python spawn on non-push commands (latency). That prefilter MUST be a
    superset of what the guard acts on, or a real push could silently bypass it.
    The guard's trigger is PUSH_RE — every command it acts on contains `git push`,
    which the if: matches (including compound commands; CC fails open on
    unparseable ones). Non-push commands are no-ops, so filtering them loses no
    coverage. Pins the contract: if the trigger ever widens past `git push`,
    update the settings.json `if:` to match."""
    import importlib.util
    hook_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(
        "git_empty_push_guard", os.path.join(hook_dir, "git-empty-push-guard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Everything the guard acts on contains "git push" → the if: matches it.
    assert mod.PUSH_RE.search("git push origin main")
    assert mod.PUSH_RE.search("git push")
    assert mod.PUSH_RE.search("cd repo && git push origin feature")
    # Non-push commands → guard no-ops → safe for the if: to filter out.
    assert not mod.PUSH_RE.search("git status")
    assert not mod.PUSH_RE.search("git commit -m x")
    assert not mod.PUSH_RE.search("ls -la")


def test_force_push_skipped():
    # --force pushes are out of scope (target parse returns skip).
    code, _o, _e = run_hook(HOOK, make_bash_input("git push --force origin feature"))
    assert code == 0


# ── git-state cases ────────────────────────────────────────────────────

def test_blocks_zero_commits_ahead(repo_zero_ahead):
    code, _o, err = run_hook(HOOK, make_bash_input("git push", cwd=str(repo_zero_ahead)))
    assert code == 2
    assert "0 commits" in err


def test_bypass_env_allows_zero_ahead(monkeypatch, repo_zero_ahead):
    monkeypatch.setenv("CLAUDE_GIT_PUSH_ALLOW_EMPTY", "1")
    code, _o, _e = run_hook(HOOK, make_bash_input("git push", cwd=str(repo_zero_ahead)))
    assert code == 0


def test_allows_when_ahead(repo_zero_ahead):
    # Add a commit on feature -> 1 ahead of upstream main -> allowed.
    _git(["commit", "-q", "--allow-empty", "-m", "work"], repo_zero_ahead)
    code, _o, _e = run_hook(HOOK, make_bash_input("git push", cwd=str(repo_zero_ahead)))
    assert code == 0


def test_allows_no_upstream(tmp_path):
    # Branch with no upstream set = first push of a new branch, not the shape.
    r = tmp_path / "repo2"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    _git(["commit", "-q", "--allow-empty", "-m", "init"], r)
    code, _o, _e = run_hook(HOOK, make_bash_input("git push", cwd=str(r)))
    assert code == 0
