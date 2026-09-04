"""Tests for bin/verdict-state.py -- digest-bound review verdicts.

Every test runs against a disposable git repository under tmp_path. Nothing
here reads or writes the live ~/.claude or this checkout's own state.

Run: pytest bin/test_verdict_state.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "verdict-state.py"
STATE = Path(".claude") / "verdicts.json"

# Isolate git from the operator's global config (signing, hooks, templates)
# and give commits an identity; the tool under test never needs either.
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True, env=GIT_ENV, timeout=30,
    )
    return proc.stdout


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd, capture_output=True, text=True, check=False, env=GIT_ENV, timeout=60,
    )


def record(repo: Path, verdict: str = "pass", plane: str = "tests", *extra: str):
    proc = run("record", "--plane", plane, "--verdict", verdict, *extra, cwd=repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def check(repo: Path, plane: str = "tests", *extra: str):
    return run("check", "--plane", plane, *extra, cwd=repo)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    (repo / "src.py").write_text("print(1)\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


# ── record + check on an unchanged tree ─────────────────────────────────


def test_record_then_check_is_fresh(repo: Path) -> None:
    record(repo)
    proc = check(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("fresh: tests pass @ "), proc.stdout


def test_state_file_shape(repo: Path) -> None:
    record(repo, "pass", "tests", "--note", "pytest: 12 passed")
    state = json.loads((repo / STATE).read_text(encoding="utf-8"))
    entry = state["tests"]
    assert set(entry) >= {"digest", "verdict", "note", "recorded_at", "files"}
    assert entry["verdict"] == "pass"
    assert entry["note"] == "pytest: 12 passed"
    assert len(entry["digest"]) == 64
    assert set(entry["files"]) == {"README.md", "src.py", ".gitignore"}


def test_record_keeps_other_planes(repo: Path) -> None:
    record(repo, "pass", "tests")
    record(repo, "fail", "review")
    state = json.loads((repo / STATE).read_text(encoding="utf-8"))
    assert state["tests"]["verdict"] == "pass"
    assert state["review"]["verdict"] == "fail"
    assert check(repo, "tests").returncode == 0


# ── anything that changes content makes the verdict stale ────────────────


def test_editing_tracked_file_is_stale_and_names_it(repo: Path) -> None:
    record(repo)
    (repo / "src.py").write_text("print(2)\n", encoding="utf-8")
    proc = check(repo)
    assert proc.returncode == 1
    assert proc.stdout.startswith("stale: tests pass @ "), proc.stdout
    assert "src.py" in proc.stdout
    assert "README.md" not in proc.stdout
    assert proc.stdout.count("\n") == 1, "reason must be one line"


def test_adding_untracked_file_is_stale_and_names_it(repo: Path) -> None:
    record(repo)
    (repo / "new_module.py").write_text("x = 1\n", encoding="utf-8")
    proc = check(repo)
    assert proc.returncode == 1
    assert "new_module.py" in proc.stdout


def test_deleting_tracked_file_is_stale_and_names_it(repo: Path) -> None:
    record(repo)
    (repo / "README.md").unlink()
    proc = check(repo)
    assert proc.returncode == 1
    assert "README.md" in proc.stdout


def test_many_changes_are_capped_to_one_line(repo: Path) -> None:
    record(repo)
    for i in range(9):
        (repo / f"f{i}.txt").write_text(str(i), encoding="utf-8")
    proc = check(repo)
    assert proc.returncode == 1
    assert proc.stdout.count("\n") == 1
    assert "+4 more" in proc.stdout, proc.stdout


# ── things that do NOT change content keep the verdict fresh ─────────────


def test_staging_and_committing_keep_verdict_fresh(repo: Path) -> None:
    (repo / "src.py").write_text("print(3)\n", encoding="utf-8")
    record(repo)
    git(repo, "add", "src.py")
    assert check(repo).returncode == 0, "staging changed no content"
    git(repo, "commit", "-q", "-m", "edit")
    assert check(repo).returncode == 0, "committing changed no content"


def test_ignored_file_does_not_affect_digest(repo: Path) -> None:
    record(repo)
    (repo / "debug.log").write_text("noise\n", encoding="utf-8")
    assert check(repo).returncode == 0


def test_state_file_itself_never_makes_the_tree_stale(tmp_path: Path) -> None:
    """A repo with no .gitignore cannot ignore .claude/verdicts.json, so the
    tool must exclude its own state file from the digest or every record
    would be stale the instant it was written."""
    repo = tmp_path / "bare"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")

    record(repo)
    assert not (repo / ".gitignore").exists(), "must not create a .gitignore"
    assert check(repo).returncode == 0
    record(repo)  # rewriting the state file is not a tree change either
    assert check(repo).returncode == 0


# ── verdict semantics ────────────────────────────────────────────────────


def test_fail_verdict_never_reads_fresh(repo: Path) -> None:
    record(repo, "fail")
    proc = check(repo)
    assert proc.returncode == 1
    assert "fail" in proc.stdout
    assert not proc.stdout.startswith("fresh")


def test_fail_then_pass_on_same_tree_is_fresh(repo: Path) -> None:
    record(repo, "fail")
    record(repo, "pass")
    assert check(repo).returncode == 0


def test_missing_verdict_message(repo: Path) -> None:
    proc = check(repo)
    assert proc.returncode == 1
    assert "no verdict" in proc.stdout
    assert "tests" in proc.stdout
    record(repo, "pass", "tests")
    other = check(repo, "review")
    assert other.returncode == 1
    assert "no verdict" in other.stdout and "review" in other.stdout


def test_corrupt_state_file_reads_as_no_verdict(repo: Path) -> None:
    (repo / STATE).parent.mkdir(parents=True)
    (repo / STATE).write_text("{not json", encoding="utf-8")
    proc = check(repo)
    assert proc.returncode == 1
    assert "no verdict" in proc.stdout
    record(repo)  # and record recovers rather than crashing
    assert check(repo).returncode == 0


# ── --root and repository resolution ─────────────────────────────────────


def test_root_flag_is_honoured_from_another_cwd(repo: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    proc = run("record", "--plane", "tests", "--verdict", "pass", "--root", str(repo), cwd=elsewhere)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (repo / STATE).is_file()
    assert not (elsewhere / STATE).exists()
    assert run("check", "--plane", "tests", "--root", str(repo), cwd=elsewhere).returncode == 0
    (repo / "src.py").write_text("changed\n", encoding="utf-8")
    assert run("check", "--plane", "tests", "--root", str(repo), cwd=elsewhere).returncode == 1


def test_subdirectory_root_resolves_to_the_repository(repo: Path) -> None:
    sub = repo / "pkg"
    sub.mkdir()
    (sub / "mod.py").write_text("1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "pkg")

    proc = run("record", "--plane", "tests", "--verdict", "pass", cwd=sub)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (repo / STATE).is_file() and not (sub / STATE).exists()
    (repo / "README.md").write_text("outside the subdir\n", encoding="utf-8")
    assert run("check", "--plane", "tests", cwd=sub).returncode == 1


def test_not_a_git_repository_fails_clearly(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    proc = run("check", "--plane", "tests", cwd=plain)
    assert proc.returncode == 2
    assert "git" in proc.stderr.lower()
    assert proc.stdout == ""


# ── .gitignore maintenance ───────────────────────────────────────────────


def test_gitignore_gains_the_state_path_exactly_once(repo: Path) -> None:
    record(repo)
    text = (repo / ".gitignore").read_text(encoding="utf-8")
    assert text == "*.log\n.claude/verdicts.json\n"
    assert subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-q", ".claude/verdicts.json"],
        env=GIT_ENV, check=False,
    ).returncode == 0
    record(repo)
    assert (repo / ".gitignore").read_text(encoding="utf-8") == text
    # The edit happens BEFORE the digest is taken, so the fresh record already
    # describes the tree that includes it.
    assert check(repo).returncode == 0


def test_gitignore_without_trailing_newline_is_appended_safely(repo: Path) -> None:
    (repo / ".gitignore").write_text("*.log", encoding="utf-8")
    record(repo)
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "*.log\n.claude/verdicts.json\n"


def test_already_ignored_directory_leaves_gitignore_alone(repo: Path) -> None:
    (repo / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "ignore dir")
    record(repo)
    assert (repo / ".gitignore").read_text(encoding="utf-8") == ".claude/\n"
    assert check(repo).returncode == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
