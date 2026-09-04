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


def _write_skill(skills_dir: Path, name: str, *, body_chars: int, metadata: str = "") -> None:
    (skills_dir / name).mkdir(parents=True)
    (skills_dir / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n{metadata}---\n\n# {name}\n\n" + "x" * body_chars + "\n",
        encoding="utf-8",
    )


def test_body_cap_exemption_is_counted_separately_and_excluded_from_cap_totals(tmp_path):
    """`metadata: {body-cap: exempt, body-cap-reason: ...}` marks a PERIODIC skill
    (docs/skill-cap-decisions.md). The measurement is still reported per row; only the
    corpus cap totals exclude it, and an exemption without a reason does not count."""
    skills = tmp_path / "skills"
    big = 30_000  # ~7,500 proxy tokens: over both the 6,000 soft cap and the 5,000 proxy
    _write_skill(skills, "periodic", body_chars=big,
                 metadata='metadata:\n  body-cap: exempt\n  body-cap-reason: "weekly report; size irrelevant"\n')
    _write_skill(skills, "workflow", body_chars=big)
    _write_skill(skills, "unreasoned", body_chars=big, metadata="metadata:\n  body-cap: exempt\n")
    _write_skill(skills, "small", body_chars=40,
                 metadata='metadata:\n  body-cap: exempt\n  body-cap-reason: "tiny anyway"\n')

    report = run_json("--skills-dir", str(skills), cwd=tmp_path)
    rows = {row["skill"]: row for row in report["skills"]}

    assert rows["periodic"]["body_cap"] == "exempt"
    assert rows["periodic"]["body_cap_reason"] == "weekly report; size irrelevant"
    assert rows["periodic"]["over_soft_body_cap"] is True, "the measurement itself is never hidden"
    assert rows["periodic"]["over_compaction_reattach_proxy"] is True
    assert rows["workflow"]["body_cap"] == "applies"
    assert rows["workflow"]["body_cap_reason"] is None
    assert rows["unreasoned"]["body_cap"] == "exempt-missing-reason"
    assert rows["small"]["body_cap"] == "exempt"

    assert report["skills_body_cap_exempt"] == 2
    assert report["skills_over_soft_body_cap"] == 2, "workflow + unreasoned count; periodic does not"
    assert report["skills_over_compaction_reattach_proxy"] == 2
    assert report["skills_over_soft_body_cap_exempt"] == 1
    assert report["skills_over_compaction_reattach_proxy_exempt"] == 1


def test_over_filter_keeps_exempt_rows_visible(tmp_path):
    skills = tmp_path / "skills"
    _write_skill(skills, "periodic", body_chars=30_000,
                 metadata='metadata:\n  body-cap: exempt\n  body-cap-reason: "sweep"\n')
    _write_skill(skills, "small", body_chars=40)
    report = run_json("--skills-dir", str(skills), "--over", "5000", cwd=tmp_path)
    assert [row["skill"] for row in report["skills"]] == ["periodic"]


def test_text_report_marks_exempt_skills_and_reports_them_separately(tmp_path):
    skills = tmp_path / "skills"
    _write_skill(skills, "periodic", body_chars=30_000,
                 metadata='metadata:\n  body-cap: exempt\n  body-cap-reason: "sweep"\n')
    _write_skill(skills, "workflow", body_chars=30_000)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--skills-dir", str(skills)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    table_row = next(line for line in proc.stdout.splitlines() if line.startswith("periodic"))
    assert "exempt" in table_row
    assert "Skills over 6000-token proxy body cap: 1 of 2 audited" in proc.stdout
    assert "1 exempt" in proc.stdout and "periodic" in proc.stdout


def _decisions_doc_rows() -> dict[str, tuple[str, str]]:
    """skill -> (classification, last cell) from docs/skill-cap-decisions.md's decision table."""
    doc = (SCRIPT.parent.parent / "docs" / "skill-cap-decisions.md").read_text(encoding="utf-8")
    rows = {}
    for line in doc.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].startswith("`") and cells[1] in ("WORKFLOW", "PERIODIC"):
            rows[cells[0].strip("`")] = (cells[1], cells[-1])
    return rows


def test_corpus_exemptions_match_the_documented_periodic_decisions():
    """The exempt set in the corpus IS the PERIODIC set in docs/skill-cap-decisions.md, every
    exemption carries a reason, and every WORKFLOW decision carries a split-or-slim proposal."""
    decisions = _decisions_doc_rows()
    assert len(decisions) == 10, sorted(decisions)
    periodic = {name for name, (kind, _) in decisions.items() if kind == "PERIODIC"}
    workflow = {name for name, (kind, _) in decisions.items() if kind == "WORKFLOW"}

    report = run_json()
    rows = {row["skill"]: row for row in report["skills"]}
    exempt = {name for name, row in rows.items() if row["body_cap"] == "exempt"}
    assert exempt == periodic
    assert not {name for name, row in rows.items() if row["body_cap"] == "exempt-missing-reason"}
    for name in periodic:
        assert rows[name]["body_cap_reason"], name
    for name in workflow:
        assert rows[name]["body_cap"] == "applies", name
        assert rows[name]["over_soft_body_cap"] is True, f"{name} is no longer over the cap; revisit the decision"
        assert len(decisions[name][1]) > 40, f"{name}: WORKFLOW rows need a concrete split-or-slim proposal"
    assert report["skills_body_cap_exempt"] == len(periodic)
    assert report["skills_over_soft_body_cap"] == sum(
        1 for row in rows.values() if row["over_soft_body_cap"] and row["body_cap"] != "exempt"
    )
