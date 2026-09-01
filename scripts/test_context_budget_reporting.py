"""Acceptance tests for human-readable ambient-context measurements."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CHECK = REPO / "scripts" / "check-rule-context-budget.py"
sys.path.insert(0, str(REPO / "hooks"))
from rule_context_budget import estimate_tokens  # noqa: E402


def test_budget_report_labels_byte_targets_and_prints_token_equivalents(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "ambient.md").write_text("x" * 61_200, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(CHECK), "--rules-dir", str(rules)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "A/B target 50,000-60,000 bytes" in result.stdout
    assert "~18,266-21,919 tokens" in result.stdout
    assert "warn 225,000 bytes" in result.stdout
    assert "hard cap 250,000 bytes" in result.stdout


def test_readme_effective_load_tracks_the_shipped_broad_rule_set():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    broad_bytes = sum(
        (REPO / "rules" / name).stat().st_size
        for name in ("tdd-quality.md", "tdd-mutation-testing.md")
    )
    broad_tokens = estimate_tokens(broad_bytes)
    effective_tokens = 97_380 + broad_tokens

    assert (
        f"| plus broadly-scoped rules that load in most coding sessions | "
        f"~{round(broad_tokens, -3):,} |"
    ) in readme
    assert (
        f"| **effective coding session** | **~{round(effective_tokens, -3):,}** |"
    ) in readme
