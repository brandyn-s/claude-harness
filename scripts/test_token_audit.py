"""Runtime-aware token-audit CLI tests."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("token-audit.py")


def run_json(*args, cwd=None):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--json"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_json_report_separates_advertised_and_on_demand_costs():
    report = run_json("--skill", "capture", "--model", "claude-fable-5")
    assert report["model_tag"] == "claude-fable-5"
    row = report["skills"][0]
    assert row["skill"] == "capture"
    assert row["idle_loading"] == "advertisement_only"
    assert row["advertised_tokens_estimate"] > 0
    assert row["body_tokens_proxy"] > row["advertised_tokens_estimate"]
    assert "tokens_47_worst" not in row


def test_over_filter_does_not_corrupt_corpus_summary():
    full = run_json()
    filtered = run_json("--over", "8000")

    assert filtered["total_skills"] == full["total_skills"]
    assert (
        filtered["skills_over_soft_body_cap"]
        == full["skills_over_soft_body_cap"]
    )
    assert (
        filtered["skills_over_compaction_reattach_proxy"]
        == full["skills_over_compaction_reattach_proxy"]
    )
    assert len(filtered["skills"]) < len(full["skills"])


def test_report_exposes_documented_compaction_lifecycle_without_banner_policing():
    """Claude Code re-attaches an invoked skill's opening tokens after compaction
    by itself, so the audit reports the budget and no longer polices a
    '**Compaction continuity:**' banner (removed from skill bodies 2026-09-03)."""
    report = run_json()

    assert report["compaction_contract"] == {
        "per_invoked_skill_reattach_tokens": 5000,
        "combined_reattach_tokens": 25000,
        "ordering": "newest_invoked_first",
    }
    assert report["skills_over_compaction_reattach_proxy"] > 0
    assert "compaction_continuity_gaps" not in report
    for row in report["skills"]:
        assert "compaction_recovery_contract_present" not in row
        assert "compaction_continuity_ok" not in row


def test_default_skills_dir_is_repo_relative_not_cwd_relative(tmp_path):
    """Run from an unrelated cwd the audit must still find the repo's skills
    instead of silently reporting an empty corpus."""
    assert run_json(cwd=tmp_path)["total_skills"] > 0


def test_discovery_cost_includes_when_to_use_and_hides_user_only_skills(tmp_path):
    skills = tmp_path / "skills"
    visible = skills / "visible"
    hidden = skills / "hidden"
    visible.mkdir(parents=True)
    hidden.mkdir()
    (visible / "SKILL.md").write_text(
        """---
name: visible
description: short description
when_to_use: this additional routing text must be counted
---

# Visible
""",
        encoding="utf-8",
    )
    (hidden / "SKILL.md").write_text(
        """---
name: hidden
description: this must not enter the model discovery context
when_to_use: nor may this routing hint
disable-model-invocation: true
---

# Hidden
""",
        encoding="utf-8",
    )

    report = run_json("--skills-dir", str(tmp_path / "skills"), cwd=tmp_path)
    rows = {row["skill"]: row for row in report["skills"]}

    visible_description_only = (len("visible: short description") + 3) // 4
    assert rows["visible"]["advertised_tokens_estimate"] > visible_description_only
    assert rows["visible"]["listing_characters_before_cap"] == len(
        "short description this additional routing text must be counted"
    )
    assert rows["hidden"]["idle_loading"] == "not_advertised_to_model"
    assert rows["hidden"]["advertised_tokens_estimate"] == 0
    assert report["skills_hidden_from_model_discovery"] == 1
