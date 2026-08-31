"""Cross-surface contract checks for composed session skills."""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_retro_manifest_declares_documented_full_argument() -> None:
    manifest = yaml.safe_load(
        (REPO_ROOT / "skills" / "retro" / "manifest.yaml").read_text(encoding="utf-8")
    )
    full = manifest["input_contract"]["parameters"]["full"]
    assert full["type"] == "boolean"
    assert full["required"] is False
    assert "complete coverage" in full["description"]
    assert manifest["input_contract"]["scope_from"] == "argument"


def test_skill_catalog_describes_retro_recovery_and_shipping() -> None:
    catalog = (REPO_ROOT / "skills" / "README.md").read_text(encoding="utf-8")
    row = next(line for line in catalog.splitlines() if line.startswith("| `retro` |"))
    assert "/ship" in row
    assert "/mega-distill" in row
    assert "/mega-capture" in row


def test_distill_manifest_covers_clean_session_marker() -> None:
    manifest = yaml.safe_load(
        (REPO_ROOT / "skills" / "distill" / "manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert "distill_marker" in manifest["output_contract"]["produces"]
    assert manifest["preconditions"] == ["session_complete_or_explicit_distill_request"]

    skill = (REPO_ROOT / "skills" / "distill" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "scripts/write_marker.py" in skill
    assert "| # | Lesson | Friction | Tier | Target | Action |" in skill


def test_ship_manifest_declares_queue_only_mode() -> None:
    manifest = yaml.safe_load(
        (REPO_ROOT / "skills" / "ship" / "manifest.yaml").read_text(encoding="utf-8")
    )
    queue_only = manifest["input_contract"]["parameters"]["queue_only"]
    assert queue_only["type"] == "boolean"
    assert queue_only["required"] is False
    assert "terminal verification" in queue_only["description"]


def test_ship_treats_clean_ahead_commits_as_outgoing_payload() -> None:
    skill = (REPO_ROOT / "skills" / "ship" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "git rev-list --count origin/main..HEAD" in skill
    assert "Clean-but-ahead commits are payload" in skill
    assert "exact destination repository" in skill
    assert "full outgoing range" in skill


def test_retro_inventories_only_session_produced_clean_ahead_commits() -> None:
    skill = (REPO_ROOT / "skills" / "retro" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "session-produced clean-ahead" in skill
    assert "git log --oneline origin/main..HEAD" in skill
    assert "does not silently authorize transmission" in skill
    assert "/ship` owns that destination-and-payload approval gate" in skill


def test_validate_changes_requires_current_vendor_contract_evidence() -> None:
    skill = (REPO_ROOT / "skills" / "validate-changes" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "## Step 1a: Vendor Contract Freshness Gate" in skill
    assert "exact installed/runtime version" in skill
    assert "current first-party" in skill
    assert "CONTRACT UNVERIFIED" in skill
    assert "/gather-claude" in skill


def test_context_budget_separates_ambient_and_on_demand_costs() -> None:
    skill = (REPO_ROOT / "skills" / "context-budget" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "full SKILL.md body loads only when the skill is invoked" in skill
    assert "Do not charge a deferred full schema as ambient context" in skill
    assert "Skill advertisements" in skill
    assert "Skill bodies on-demand" in skill
    assert "descriptions (system prompt)" not in skill
    assert "consuming ~8K tokens unnecessarily" not in skill
    assert "disable-model-invocation as\nprimary optimization lever" not in skill


def test_context_budget_requires_direct_release_measurements() -> None:
    skill = (REPO_ROOT / "skills" / "context-budget" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "fresh-session" in skill
    assert "safe/minimal control" in skill
    assert "pre-change versus post-change" in skill
    assert "input/cache tokens and cost" in skill
    assert "bounded direct smoke/A-B test" in skill
    assert "runtime context impact as **UNVERIFIED**" in skill


def test_context_budget_uses_native_runtime_diagnostics_and_scoped_controls() -> None:
    skill = (REPO_ROOT / "skills" / "context-budget" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "`/context`" in skill
    assert "`/doctor`" in skill
    assert "`/mcp`" in skill
    assert "personal and project skills" in skill
    assert "plugin skills through `/plugin`" in skill


def test_worktree_claim_records_pre_write_commit_boundary() -> None:
    skill = (REPO_ROOT / "skills" / "work" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert 'SESSION_START_OID="$(git rev-parse "$BASE_REF")"' in skill
    assert '"session_start_oid": "$SESSION_START_OID"' in skill
    assert '"base_ref": "$BASE_REF"' in skill
    assert "captured from the fetched base before" in skill
    assert "the later HEAD is not a substitute" in skill
