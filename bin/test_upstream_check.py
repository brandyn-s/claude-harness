#!/usr/bin/env python3
"""bin/upstream-check.py: a pinned overlay against the harness it vendors.

Two throwaway git repositories: an "upstream" with two commits (the pin and a
later tip), and a "downstream" that vendored the core paths at the pin, then
edited one core file (a fork), edited one listed override, dropped one file,
and added one of its own under a core path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent / "upstream-check.py"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL="/dev/null")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True, env=ENV).stdout.strip()


def _commit_all(cwd: Path, msg: str) -> str:
    _git(cwd, "add", "-A")
    _git(cwd, "commit", "-q", "-m", msg)
    return _git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path):
    up = tmp_path / "harness"
    up.mkdir()
    _git(up, "init", "-q", "-b", "main")
    (up / "hooks").mkdir()
    (up / "rules").mkdir()
    (up / "hooks" / "guard.py").write_text("print('v1')\n", encoding="utf-8")
    (up / "hooks" / "protected-repos.json").write_text("{}\n", encoding="utf-8")
    (up / "hooks" / "dropped.py").write_text("x = 1\n", encoding="utf-8")
    (up / "rules" / "core.md").write_text("# core\n", encoding="utf-8")
    (up / "README.md").write_text("upstream readme\n", encoding="utf-8")
    pin = _commit_all(up, "pin")
    (up / "hooks" / "guard.py").write_text("print('v2')\n", encoding="utf-8")
    (up / "hooks" / "new-hook.py").write_text("print('new')\n", encoding="utf-8")
    tip = _commit_all(up, "tip")

    down = tmp_path / "overlay"
    down.mkdir()
    _git(down, "init", "-q", "-b", "main")
    (down / "hooks").mkdir()
    (down / "rules").mkdir()
    (down / "hooks" / "guard.py").write_text("print('v1')  # forked locally\n", encoding="utf-8")   # modified
    (down / "hooks" / "protected-repos.json").write_text('{"repos": ["org/x"]}\n', encoding="utf-8")  # override
    (down / "rules" / "core.md").write_text("# core\n", encoding="utf-8")                                 # identical
    (down / "hooks" / "org-only.py").write_text("print('org')\n", encoding="utf-8")                      # only downstream
    (down / "skills").mkdir()
    (down / "skills" / "org-skill.md").write_text("not a core path\n", encoding="utf-8")
    (down / "UPSTREAM.json").write_text(json.dumps({
        "repo": str(up), "version": "1.0.0", "commit": pin, "branch": "main",
        "paths": ["hooks/", "rules/"], "overrides": ["hooks/protected-repos.json"]}), encoding="utf-8")
    _commit_all(down, "vendor at pin")
    return up, down, pin, tip


def _run(down: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), "--downstream", str(down), *args],
                          capture_output=True, text=True, timeout=120, env=ENV)


def test_classification_against_a_local_clone(repos):
    up, down, pin, tip = repos
    res = _run(down, "--upstream-dir", str(up), "--json")
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout)
    assert r["identical"] == ["rules/core.md"]
    assert r["modified"] == ["hooks/guard.py"]
    assert r["override"] == ["hooks/protected-repos.json"]
    assert r["only_downstream"] == ["hooks/org-only.py"]
    assert r["only_upstream"] == ["hooks/dropped.py"]
    assert r["ok"] is False
    assert r["behind"]["tip"] == tip and r["behind"]["commits"] == 1
    assert sorted(r["behind"]["files"]) == ["hooks/guard.py", "hooks/new-hook.py"]
    assert "skills/org-skill.md" not in json.dumps(r), "paths outside the core are not the tool's business"


def test_check_fails_on_a_fork_and_passes_once_re_vendored(repos):
    up, down, pin, tip = repos
    assert _run(down, "--upstream-dir", str(up), "--check").returncode == 1
    (down / "hooks" / "guard.py").write_text("print('v1')\n", encoding="utf-8")
    (down / "hooks" / "dropped.py").write_text("x = 1\n", encoding="utf-8")
    _commit_all(down, "re-vendor")
    res = _run(down, "--upstream-dir", str(up), "--check")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "OK: the vendored core matches the pin" in res.stdout
    assert "behind     1 commit(s)" in res.stdout


def test_fetch_path_reads_objects_from_the_upstream_repo(repos):
    up, down, pin, tip = repos
    res = _run(down, "--fetch", "--json")
    assert res.returncode == 0, res.stderr
    r = json.loads(res.stdout)
    assert r["pin"] == pin and r["modified"] == ["hooks/guard.py"]
    assert r["behind"]["tip"] == tip


def test_missing_or_malformed_pin_is_a_clear_error(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    _git(d, "init", "-q")
    res = _run(d)
    assert res.returncode != 0 and "not a pinned overlay" in res.stderr
    (d / "UPSTREAM.json").write_text(json.dumps({"repo": "x", "commit": "abc", "paths": ["hooks/"]}), encoding="utf-8")
    res = _run(d)
    assert res.returncode != 0 and "40-hex" in res.stderr


def test_pin_can_be_read_from_outside_the_overlay(repos, tmp_path):
    up, down, pin, tip = repos
    (down / "UPSTREAM.json").unlink()
    _commit_all(down, "not yet adopted")
    external = tmp_path / "candidate.json"
    external.write_text(json.dumps({"repo": str(up), "commit": pin, "paths": ["hooks/", "rules/"],
                                    "overrides": ["hooks/protected-repos.json"]}), encoding="utf-8")
    assert _run(down, "--upstream-dir", str(up)).returncode != 0, "no pin in the tree"
    res = _run(down, "--upstream-dir", str(up), "--pin", str(external), "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["modified"] == ["hooks/guard.py"]
