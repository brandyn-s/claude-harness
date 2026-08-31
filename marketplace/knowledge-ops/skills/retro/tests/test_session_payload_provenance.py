"""Negative controls for /retro's current-session shipping boundary."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SHIP_HELPER = SKILL_ROOT.parent / "ship" / "scripts" / "outgoing_payload.py"
SKILL_TEXT = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")


def _load_helper():
    spec = importlib.util.spec_from_file_location("outgoing_payload", SHIP_HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "retro-test",
            "GIT_AUTHOR_EMAIL": "retro-test@example.com",
            "GIT_COMMITTER_NAME": "retro-test",
            "GIT_COMMITTER_EMAIL": "retro-test@example.com",
        }
    )
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, path: str, content: str, message: str) -> str:
    target = repo / path
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", "--", path)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo_with_old_and_current_ahead_commits(
    tmp_path: Path,
) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    base = _commit(repo, "base.txt", "base\n", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    _git(repo, "checkout", "-q", "-b", "feature/retro")
    old_commit = _commit(repo, "older.txt", "older\n", "older session")
    current_commit = _commit(repo, "current.txt", "current\n", "current session")
    return repo, old_commit, current_commit


def test_session_start_separates_older_ahead_from_current_session(tmp_path: Path):
    repo, old_commit, current_commit = _repo_with_old_and_current_ahead_commits(
        tmp_path
    )

    inventory = _load_helper().build_inventory(
        repo, "origin/main", session_start=old_commit
    )

    assert inventory["session_provenance"] == "VERIFIED"
    assert inventory["session_commits"] == [current_commit]
    assert inventory["pre_session_ahead_commits"] == [old_commit]


def test_missing_session_start_does_not_claim_ahead_commits(tmp_path: Path):
    repo, old_commit, current_commit = _repo_with_old_and_current_ahead_commits(
        tmp_path
    )

    inventory = _load_helper().build_inventory(repo, "origin/main")

    assert inventory["session_provenance"] == "UNVERIFIED"
    assert inventory["session_commits"] == []
    assert inventory["pre_session_ahead_commits"] == [old_commit, current_commit]


def test_retro_contract_requires_evidence_before_session_attribution():
    for needle in (
        "first pre-write HEAD",
        "session_provenance",
        "pre_session_ahead_commits",
        "/ship --queue-only --session-start <oid>",
        "do not label ahead commits as session-produced",
    ):
        assert needle in SKILL_TEXT
