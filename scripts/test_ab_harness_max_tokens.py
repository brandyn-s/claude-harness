"""The five research-skill A/B harnesses expose an equal-arms `--max-tokens` budget.

Why: the frozen 2026-05-31 budgets (700-2000 tokens) were sized for Opus 4.8
report lengths. A rerun on a newer model must be able to raise the ceiling for
BOTH arms without editing source, while the default still reproduces the
historical budget, and the plan receipt must record whichever value ran.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HISTORICAL_BUDGET = {
    "deep-dive": 1500,
    "triage": 1500,
    "gather-research": 2000,
    "gather-intel": 2000,
    "evaluate-repos": 700,
}


def _plan(skill: str, tmp_path: Path, *extra: str) -> dict:
    script = REPO / "skills" / skill / "harness" / "run_live.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--plan-only", "--model", "claude-fable-5-1",
         "--output", str(tmp_path / "out.json"), *extra],
        capture_output=True, text=True, timeout=60, cwd=str(script.parent),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize("skill,budget", sorted(HISTORICAL_BUDGET.items()))
def test_default_budget_matches_the_frozen_baseline(skill, budget, tmp_path):
    assert _plan(skill, tmp_path)["max_tokens"] == budget


@pytest.mark.parametrize("skill", sorted(HISTORICAL_BUDGET))
def test_budget_override_is_recorded_in_the_receipt(skill, tmp_path):
    assert _plan(skill, tmp_path, "--max-tokens", "4000")["max_tokens"] == 4000
