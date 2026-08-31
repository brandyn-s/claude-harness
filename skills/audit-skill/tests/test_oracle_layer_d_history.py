"""Exercise run_layer_d_history.py on a synthetic git history (the real
script is seeded from actual fix-PRs, but the logic is verified here on a
constructed bug→fix pair, mirroring the fix_loop tests' git pattern)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_runner():
    p = REPO / "skills" / "audit-skill" / "scripts" / "run_layer_d_history.py"
    spec = importlib.util.spec_from_file_location("run_layer_d_history", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_layer_d_history"] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_verify_cases_on_synthetic_history(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "t.jsonl"))
    runner = _load_runner()
    repo = tmp_path / "r"
    repo.mkdir()
    _init(repo)
    (repo / "skill.md").write_text("bug-line here\n", encoding="utf-8")
    pre = _commit(repo, "bug present")
    (repo / "skill.md").write_text("clean now\n", encoding="utf-8")
    post = _commit(repo, "fix")

    cases = [
        # Real fix: reproducer fires pre, not post -> VERIFIED.
        {"id": "PRX", "pre_ref": pre, "post_ref": post,
         "finding": {"skill": "s", "code": "H1", "severity": "drift",
                     "label": "behavior-fix", "description": "bug-line present",
                     "reproducer": {"type": "grep", "command": "grep -q 'bug-line' skill.md"}}},
        # Non-bug: reproducer never fired pre -> STALE-PRE.
        {"id": "PRY", "pre_ref": pre, "post_ref": post,
         "finding": {"skill": "s", "code": "H2", "severity": "drift",
                     "label": "behavior-fix", "description": "absent token",
                     "reproducer": {"type": "grep", "command": "grep -q 'never-present' skill.md"}}},
    ]
    results = runner.verify_cases(str(repo), cases)
    by_id = {r["id"]: r for r in results}
    assert by_id["PRX"]["status"] == "VERIFIED"
    assert by_id["PRY"]["status"] == "STALE-PRE"

    summary = runner.summarize(results)
    assert summary["n"] == 2
    assert summary["verified"] == 1
    assert summary["verified_rate"] == 0.5
