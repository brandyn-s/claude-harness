"""Acceptance tests for the aggregate ambient-rule budget gate."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "scripts" / "check-rule-context-budget.py"
WORKFLOW = REPO / ".github" / "workflows" / "validate.yml"
PREFLIGHT = REPO / "bin" / "preflight-skill.py"


def _run(rules_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK), "--rules-dir", str(rules_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gate_blocks_only_ambient_top_level_bytes(tmp_path: Path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "ambient.md").write_text("a" * 250_001, encoding="utf-8")
    blocked = _run(rules)
    assert blocked.returncode == 1
    assert "250,001 bytes" in blocked.stderr

    (rules / "ambient.md").write_text(
        "---\npaths:\n  - '**/*.py'\n---\n" + "a" * 250_001,
        encoding="utf-8",
    )
    incidents = rules / "incidents"
    incidents.mkdir()
    (incidents / "history.md").write_text("b" * 300_000, encoding="utf-8")
    allowed = _run(rules)
    assert allowed.returncode == 0
    assert "0 bytes" in allowed.stdout


def test_hard_cap_boundary_and_ab_target_are_distinct(tmp_path: Path):
    rules = tmp_path / "rules"
    rules.mkdir()
    target = rules / "ambient.md"

    target.write_text("a" * 60_001, encoding="utf-8")
    advisory = _run(rules)
    assert advisory.returncode == 0
    assert "A/B target 50,000-60,000" in advisory.stdout

    target.write_text("a" * 250_000, encoding="utf-8")
    boundary = _run(rules)
    assert boundary.returncode == 0

    target.write_text("a" * 250_001, encoding="utf-8")
    blocked = _run(rules)
    assert blocked.returncode == 1


def test_malformed_or_escaping_input_is_infrastructure_failure(tmp_path: Path):
    rules = tmp_path / "rules"
    rules.mkdir()
    target = rules / "ambient.md"
    target.write_text("---\npaths:\n  - '**'\n", encoding="utf-8")
    malformed = _run(rules)
    assert malformed.returncode == 2

    target.write_text("---\npaths: [\n---\n" + ("x" * 300_000), encoding="utf-8")
    invalid_yaml = _run(rules)
    assert invalid_yaml.returncode == 2

    target.unlink()
    outside = tmp_path / "outside.md"
    outside.write_text("x", encoding="utf-8")
    target.symlink_to(outside)
    escaped = _run(rules)
    assert escaped.returncode == 2


def test_nonexistent_rules_directory_is_infrastructure_failure(tmp_path: Path):
    missing = _run(tmp_path / "missing-rules")

    assert missing.returncode == 2
    assert "rules directory does not exist" in missing.stderr


def test_gate_is_wired_into_ci_and_local_preflight():
    command = "scripts/check-rule-context-budget.py"
    assert CHECK.is_file()
    assert command in WORKFLOW.read_text(encoding="utf-8")
    preflight = PREFLIGHT.read_text(encoding="utf-8")
    assert command in preflight
    assert '"rule-context-budget"' in preflight
