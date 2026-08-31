"""Executable oracles for /ship's full outgoing-payload inventory."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
HELPER = SKILL_ROOT / "scripts" / "outgoing_payload.py"
SKILL_TEXT = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")


def _load_helper():
    spec = importlib.util.spec_from_file_location("outgoing_payload", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "payload-test",
            "GIT_AUTHOR_EMAIL": "payload-test@example.com",
            "GIT_COMMITTER_NAME": "payload-test",
            "GIT_COMMITTER_EMAIL": "payload-test@example.com",
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
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", "--", path)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo_with_remote_base(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    base = _commit(repo, "README.md", "base\n", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    _git(repo, "checkout", "-q", "-b", "feature/payload")
    return repo, base


def test_clean_ahead_commit_remains_in_outgoing_inventory(tmp_path: Path):
    repo, _ = _repo_with_remote_base(tmp_path)
    commit = _commit(repo, "committed.py", "print('outgoing')\n", "outgoing")

    inventory = _load_helper().build_inventory(repo, "origin/main")

    assert inventory["ahead_commits"] == [commit]
    assert inventory["committed_paths"] == ["committed.py"]
    assert inventory["all_paths"] == ["committed.py"]
    assert inventory["worktree_paths"] == []
    assert inventory["commit_required"] is False
    assert inventory["clean_ahead"] is True


def test_inventory_unions_committed_staged_unstaged_and_untracked(tmp_path: Path):
    repo, _ = _repo_with_remote_base(tmp_path)
    _commit(repo, "committed.py", "committed\n", "committed")

    staged = repo / "staged.py"
    staged.write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "--", "staged.py")
    (repo / "README.md").write_text("unstaged\n", encoding="utf-8")
    (repo / "untracked.py").write_text("untracked\n", encoding="utf-8")

    inventory = _load_helper().build_inventory(repo, "origin/main")

    assert inventory["committed_paths"] == ["committed.py"]
    assert inventory["staged_paths"] == ["staged.py"]
    assert inventory["unstaged_paths"] == ["README.md"]
    assert inventory["untracked_paths"] == ["untracked.py"]
    assert inventory["all_paths"] == [
        "README.md",
        "committed.py",
        "staged.py",
        "untracked.py",
    ]
    assert inventory["commit_required"] is True
    assert inventory["clean_ahead"] is False


def test_ship_contract_drives_all_gates_from_full_payload_inventory():
    for needle in (
        "scripts/outgoing_payload.py",
        "`all_paths`",
        "`commit_required`",
        "skip `git commit`",
        "full committed outgoing range",
    ):
        assert needle in SKILL_TEXT
