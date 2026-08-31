"""Executable release-contract oracles for /validate-changes."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
HELPER = SKILL_ROOT / "scripts" / "change_contract.py"
SKILL_TEXT = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
MANIFEST_TEXT = (SKILL_ROOT / "manifest.yaml").read_text(encoding="utf-8")


def _load_helper():
    spec = importlib.util.spec_from_file_location("change_contract", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "validation-test",
            "GIT_AUTHOR_EMAIL": "validation-test@example.com",
            "GIT_COMMITTER_NAME": "validation-test",
            "GIT_COMMITTER_EMAIL": "validation-test@example.com",
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


def _repo_with_two_commits_and_staged_change(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    base = _commit(repo, "base.txt", "base\n", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    _git(repo, "checkout", "-q", "-b", "feature/validation")
    _commit(repo, "first.py", "first\n", "first")
    _commit(repo, "second.py", "second\n", "second")
    (repo / "staged.py").write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "--", "staged.py")
    return repo


def test_auto_detection_includes_multi_commit_range_and_staged_lane(tmp_path: Path):
    repo = _repo_with_two_commits_and_staged_change(tmp_path)

    inventory = _load_helper().build_change_inventory(repo, "origin/main")

    assert inventory["commit_count"] == 2
    assert inventory["committed_paths"] == ["first.py", "second.py"]
    assert inventory["staged_paths"] == ["staged.py"]
    assert inventory["all_paths"] == ["first.py", "second.py", "staged.py"]


def test_contract_unverified_blocks_ship_even_when_internal_tests_pass():
    result = _load_helper().release_verdict(
        regression="PASS",
        effectiveness="PASS",
        ab="PASS",
        vendor_dependent=True,
        contract_status="UNVERIFIED",
    )

    assert result["contract"] == "CONTRACT UNVERIFIED"
    assert result["verdict"] == "FIX FIRST"


def test_verified_vendor_contract_preserves_existing_ship_gate():
    result = _load_helper().release_verdict(
        regression="PASS",
        effectiveness="PASS",
        ab="PASS",
        vendor_dependent=True,
        contract_status="VERIFIED",
    )

    assert result["contract"] == "CONTRACT VERIFIED"
    assert result["verdict"] == "SHIP"


def test_skill_contract_uses_executable_inventory_and_hard_contract_gate():
    for needle in (
        "scripts/change_contract.py inventory",
        "`committed_paths`",
        "`staged_paths`",
        "CONTRACT UNVERIFIED blocks SHIP",
    ):
        assert needle in SKILL_TEXT


def test_vendor_refresh_route_has_skill_dispatch_authority():
    frontmatter = SKILL_TEXT.split("---", 2)[1]
    assert "allowed-tools: AskUserQuestion Bash Glob Grep Read Skill " in frontmatter
    assert '\n  - Skill\n' in MANIFEST_TEXT


def test_model_migration_accepts_exact_parameterized_pair():
    result = _load_helper().model_migration_contract(
        baseline_model="model-alpha-20260101",
        treatment_model="model-beta-20260202",
        baseline_runtime="runtime-1.0",
        treatment_runtime="runtime-1.1",
    )

    assert result == {
        "baseline_model": "model-alpha-20260101",
        "treatment_model": "model-beta-20260202",
        "baseline_runtime": "runtime-1.0",
        "treatment_runtime": "runtime-1.1",
    }


def test_model_migration_rejects_missing_or_identical_model_ids():
    helper = _load_helper()
    for baseline, treatment in (
        ("", "model-beta"),
        ("model-alpha", ""),
        ("model-same", "model-same"),
    ):
        try:
            helper.model_migration_contract(baseline, treatment)
        except helper.ContractError:
            pass
        else:
            raise AssertionError("invalid model pair must fail closed")

    try:
        helper.model_migration_contract(
            "model-alpha",
            "model-beta",
            baseline_runtime=" ",
            treatment_runtime="runtime-1.1",
        )
    except helper.ContractError:
        pass
    else:
        raise AssertionError("blank runtime identity must fail closed")


def test_creative_migration_contract_has_no_implicit_model_pair():
    for needle in (
        "--baseline-model <exact-model-id>",
        "--treatment-model <exact-model-id>",
        "exact effective model IDs",
    ):
        assert needle in SKILL_TEXT
    assert "OR Opus 4.6" not in SKILL_TEXT
    assert "OR Opus 4.7" not in SKILL_TEXT
