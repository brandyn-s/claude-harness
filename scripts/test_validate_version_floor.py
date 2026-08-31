"""Contracts for automatic updates and Claude Code version floors."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "scripts" / "validate-version-floor.py"


def run_validator(settings: Path | None = None, managed: Path | None = None):
    command = [sys.executable, str(VALIDATOR)]
    if settings is not None:
        command.extend(["--settings", str(settings)])
    if managed is not None:
        command.extend(["--managed-template", str(managed)])
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def write_contract(tmp_path: Path, settings: dict, managed: dict):
    settings_path = tmp_path / "settings.json"
    managed_path = tmp_path / "managed-settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    managed_path.write_text(json.dumps(managed), encoding="utf-8")
    return settings_path, managed_path


def test_shipped_policy_enables_updates_with_aligned_floors():
    result = run_validator()
    assert result.returncode == 0, result.stderr

    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    managed = json.loads(
        (REPO / "templates" / "managed-settings.json").read_text(encoding="utf-8")
    )
    assert settings["minimumVersion"] == managed["requiredMinimumVersion"]
    assert "requiredMinimumVersion" not in settings
    blockers = {
        "DISABLE_AUTOUPDATER",
        "DISABLE_UPDATES",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    }
    assert blockers.isdisjoint(settings.get("env", {}))
    assert "autoUpdatesChannel" not in settings


@pytest.mark.parametrize(
    "blocker",
    [
        "DISABLE_AUTOUPDATER",
        "DISABLE_UPDATES",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    ],
)
def test_each_update_blocker_fails_closed(tmp_path: Path, blocker: str):
    settings_path, managed_path = write_contract(
        tmp_path,
        {"minimumVersion": "2.1.226", "env": {blocker: "1"}},
        {"requiredMinimumVersion": "2.1.226"},
    )
    result = run_validator(settings_path, managed_path)
    assert result.returncode == 1
    assert blocker in result.stderr


def test_explicit_update_channel_fails_closed(tmp_path: Path):
    settings_path, managed_path = write_contract(
        tmp_path,
        {
            "minimumVersion": "2.1.226",
            "autoUpdatesChannel": "stable",
            "env": {},
        },
        {"requiredMinimumVersion": "2.1.226"},
    )
    result = run_validator(settings_path, managed_path)
    assert result.returncode == 1
    assert "autoUpdatesChannel" in result.stderr
    assert "latest" in result.stderr


@pytest.mark.parametrize(
    ("settings", "managed", "message"),
    [
        ({"env": {}}, {"requiredMinimumVersion": "2.1.226"}, "minimumVersion"),
        ({"minimumVersion": "2.1.226", "env": {}}, {}, "requiredMinimumVersion"),
        (
            {"minimumVersion": "current", "env": {}},
            {"requiredMinimumVersion": "current"},
            "semantic version",
        ),
        (
            {"minimumVersion": "2.1.226", "env": {}},
            {"requiredMinimumVersion": "2.1.225"},
            "version floors differ",
        ),
        (
            {"minimumVersion": "2.1.225", "env": {}},
            {"requiredMinimumVersion": "2.1.225"},
            "qualified repository floor",
        ),
        (
            {
                "minimumVersion": "2.1.226",
                "requiredMinimumVersion": "2.1.226",
                "env": {},
            },
            {"requiredMinimumVersion": "2.1.226"},
            "managed-settings-only",
        ),
    ],
)
def test_malformed_or_misplaced_floors_fail_closed(
    tmp_path: Path, settings: dict, managed: dict, message: str
):
    settings_path, managed_path = write_contract(tmp_path, settings, managed)
    result = run_validator(settings_path, managed_path)
    assert result.returncode == 1
    assert message in result.stderr


def test_update_policy_is_wired_and_current_in_documentation():
    workflow = (REPO / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    architecture = (REPO / "ARCHITECTURE.md").read_text(encoding="utf-8")
    platform = (REPO / "docs" / "PLATFORM_NOTES.md").read_text(encoding="utf-8")

    assert "python scripts/validate-version-floor.py" in workflow
    assert "Automatic updates | Enabled" in architecture
    assert "does not block startup" in architecture
    assert "managed startup floor" in architecture
    assert "Automatic updates are intentionally enabled" in platform
    assert "fresh-session qualification" in platform


def test_reports_preserve_historical_evidence_with_current_addenda():
    markdown = (
        REPO / "docs" / "CLAUDE_CODE_ARCHITECTURE_REVIEW_2026-08-05.md"
    ).read_text(encoding="utf-8")
    html = (
        REPO / "docs" / "claude-code-architecture-modernization-report.html"
    ).read_text(encoding="utf-8")

    assert "Historical snapshot — evidence frozen 2026-08-06" in markdown
    assert "Current-state addendum — 2026-08-09" in markdown
    assert "PR #1937" in markdown and "closed unmerged" in markdown
    assert 'id="current-addendum"' in html
    assert "Historical snapshot — evidence frozen 2026-08-06" in html
    assert "Current-state addendum — 2026-08-09" in html
    markdown_current = markdown.split(
        "## Historical snapshot — evidence frozen 2026-08-06", 1
    )[0]
    html_current = html.split('<section id="executive">', 1)[0]
    for current in (markdown_current, html_current):
        assert "us.anthropic.claude-opus-5[1m]" in current
        assert "high" in current
        assert "switchModelsOnFlag" in current
        assert "true" in current
        assert "Automatic updates" in current or "automatic updates" in current
        assert "2.1.226" in current


def test_architecture_catalog_matches_tracked_components():
    result = subprocess.run(
        [
            sys.executable,
            str(
                REPO
                / "skills"
                / "audit-architecture"
                / "references"
                / "doc_accuracy_audit.py"
            ),
        ],
        cwd=REPO,
        env={"CLAUDE_CONFIG_DIR": str(REPO)},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout
    assert '"total_issues": 0' in result.stdout
