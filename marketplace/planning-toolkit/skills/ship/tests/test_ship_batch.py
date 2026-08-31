"""Tests for /ship branch, commit, and merge git mechanics.

Pytest port of the former standalone tests/test-ship-batch.py (hyphen-named,
so pytest never collected it and it lacked the sandbox git probe — it failed
6/9 in environments with forced commit signing). Validates the feature-branch +
squash-merge flow. Collected by the CI `pytest skills/` step; skips cleanly
where ad-hoc git commits are rejected.
"""
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


def _git_env() -> dict:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "probe",
        "GIT_AUTHOR_EMAIL": "probe@example.com",
        "GIT_COMMITTER_NAME": "probe",
        "GIT_COMMITTER_EMAIL": "probe@example.com",
    })
    return env


def _can_create_test_commits() -> bool:
    """Same probe as hooks/test-hooks/conftest.py — forced-signing
    environments reject ad-hoc fixture commits."""
    with tempfile.TemporaryDirectory() as td:
        try:
            env = _git_env()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=td,
                           check=True, env=env, timeout=5)
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", "probe"],
                cwd=td, check=True, env=env, timeout=5, capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            return False


SKILL_TEXT = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(
    encoding="utf-8"
)
FAILURE_PATHS = (
    Path(__file__).resolve().parents[1] / "references" / "failure-paths.md"
).read_text(encoding="utf-8")


def _run(cmd: list, cwd) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                          timeout=30, env=_git_env())


@pytest.fixture(scope="module")
def batch_repo(tmp_path_factory):
    """A repo with main + a feat/batch-test branch carrying two commits."""
    if not _can_create_test_commits():
        pytest.skip("Sandbox env rejects ad-hoc git commits (forced signing). Runs in CI.")
    repo = tmp_path_factory.mktemp("ship-batch")
    _run(["git", "init", "-q", "-b", "main"], repo)
    (repo / "README.md").write_text("# Test repo\n", encoding="utf-8")
    _run(["git", "add", "README.md"], repo)
    _run(["git", "commit", "-q", "-m", "initial"], repo)

    _run(["git", "checkout", "-q", "-b", "feat/batch-test"], repo)
    (repo / "file1.py").write_text("# change 1\n", encoding="utf-8")
    _run(["git", "add", "file1.py"], repo)
    _run(["git", "commit", "-q", "-m", "feat: first change"], repo)
    (repo / "file2.py").write_text("# change 2\n", encoding="utf-8")
    _run(["git", "add", "file2.py"], repo)
    _run(["git", "commit", "-q", "-m", "feat: second change"], repo)
    return repo


def test_contract_requires_feature_branch_and_pr_for_every_repo():
    assert "All repos require feature branches. This is mandatory for all active repos." in SKILL_TEXT
    assert "direct-push" not in SKILL_TEXT
    assert "push confirmation for unprotected" not in SKILL_TEXT


def test_contract_delegates_merge_state_to_verified_helper():
    assert '"$CONFIG_ROOT/bin/pr-merge-verified.py"' in SKILL_TEXT
    assert '"$PR_NUMBER" --repo "$REPO_SLUG"' in SKILL_TEXT
    assert "--queue-only" in SKILL_TEXT
    assert "terminal `MERGED`" in SKILL_TEXT


def test_contract_queries_effective_required_check_contexts():
    assert ".parameters.required_status_checks[]?.context" in SKILL_TEXT
    assert "bounded registration window" in SKILL_TEXT


def test_contract_pins_security_gate_scope():
    assert "**Applies to `mcp-servers`, `mcp-infra`, AND `compliance-access-framework`**" in SKILL_TEXT
    assert ".github/workflows/*.yaml" in SKILL_TEXT


def test_contract_covers_remote_failure_recovery():
    for needle in (
        "effective required-status rules query",
        "bounded registration window",
        "merge-queue silent drop",
        "Linked-worktree cleanup",
        "full preflight aggregator",
    ):
        assert needle in FAILURE_PATHS


def test_absent_checks_hold_during_actions_webhook_incidents():
    for needle in (
        "official Actions status/incident feed",
        "active webhook incident is a hold",
        "retired merge-group SHA",
    ):
        assert needle in SKILL_TEXT
    assert "official Actions status plus incident feed" in FAILURE_PATHS
    assert "make no PR/repository changes and retry later" in FAILURE_PATHS


def test_batch_commit_exists_on_feature_branch(batch_repo):
    r = _run(["git", "log", "--oneline", "feat/batch-test"], batch_repo)
    assert "first change" in r.stdout


def test_batch_two_commits_ahead_of_main(batch_repo):
    r = _run(["git", "log", "--oneline", "main..feat/batch-test"], batch_repo)
    assert len(r.stdout.strip().splitlines()) == 2


def test_batch_not_pushed_no_remote(batch_repo):
    r = _run(["git", "config", "branch.feat/batch-test.remote"], batch_repo)
    assert r.returncode != 0 or r.stdout.strip() == ""


def test_flush_diff_has_both_files(batch_repo):
    r = _run(["git", "diff", "main..feat/batch-test", "--stat"], batch_repo)
    assert "file1.py" in r.stdout and "file2.py" in r.stdout


def test_flush_log_has_both_messages(batch_repo):
    r = _run(["git", "log", "--oneline", "main..feat/batch-test"], batch_repo)
    assert "first change" in r.stdout and "second change" in r.stdout


def test_flush_squash_merge_single_commit_and_files(batch_repo):
    _run(["git", "checkout", "-q", "main"], batch_repo)
    _run(["git", "merge", "--squash", "feat/batch-test"], batch_repo)
    _run(["git", "commit", "-q", "-m", "feat: combined batch"], batch_repo)
    r = _run(["git", "log", "--oneline", "-3", "main"], batch_repo)
    assert "combined batch" in r.stdout
    assert (batch_repo / "file1.py").exists()
    assert (batch_repo / "file2.py").exists()


def test_default_mode_single_commit_on_fresh_branch(batch_repo):
    _run(["git", "checkout", "-q", "main"], batch_repo)
    _run(["git", "checkout", "-q", "-b", "feat/normal-ship"], batch_repo)
    (batch_repo / "file3.py").write_text("# normal\n", encoding="utf-8")
    _run(["git", "add", "file3.py"], batch_repo)
    _run(["git", "commit", "-q", "-m", "feat: normal ship"], batch_repo)
    r = _run(["git", "log", "--oneline", "main..feat/normal-ship"], batch_repo)
    assert len(r.stdout.strip().splitlines()) == 1
