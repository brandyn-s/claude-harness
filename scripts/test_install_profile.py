from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-profile.py"


def _run(target: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), "--target", str(target), *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_preview_is_read_only_and_does_not_print_existing_values(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    original = {"env": {"PRIVATE_TOKEN": "do-not-print"}, "hooks": {"Stop": []}}
    target.write_text(json.dumps(original), encoding="utf-8")

    result = _run(target)

    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text(encoding="utf-8")) == original
    assert "do-not-print" not in result.stdout
    assert "No files written" in result.stdout


def test_apply_preserves_unmanaged_keys_and_creates_backup(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    original = {"env": {"KEEP": "1"}, "hooks": {"Stop": []}}
    target.write_text(json.dumps(original), encoding="utf-8")

    result = _run(target, "--apply")

    assert result.returncode == 0, result.stderr
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["env"] == original["env"]
    assert merged["hooks"] == original["hooks"]
    assert merged["permissions"]["defaultMode"] == "acceptEdits"
    assert merged["sandbox"]["enabled"] is True
    assert merged["sandbox"]["allowUnsandboxedCommands"] is True
    backups = list(tmp_path.glob("settings.json.bak.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original


def test_apply_is_idempotent_after_first_write(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    first = _run(target, "--apply")
    second = _run(target, "--apply")

    assert first.returncode == second.returncode == 0
    assert "already matches" in second.stdout
    assert not list(tmp_path.glob("settings.json.bak.*"))


def test_apply_appends_permission_lists_instead_of_replacing(tmp_path: Path) -> None:
    """Measured 2026-09-03: applying fresh-laptop over a curated settings.json cut
    permissions.allow from 34 entries to 3. Profile lists union with the existing
    ones so a user's own allow/deny decisions survive the merge."""
    target = tmp_path / "settings.json"
    original = {"permissions": {"allow": ["Bash(gitleaks detect *)"], "deny": ["Read(~/.private/**)"]}}
    target.write_text(json.dumps(original), encoding="utf-8")

    result = _run(target, "--apply")

    assert result.returncode == 0, result.stderr
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert "Bash(gitleaks detect *)" in merged["permissions"]["allow"]
    assert "Read(~/.private/**)" in merged["permissions"]["deny"]
    assert "Edit(~/.ssh/**)" in merged["permissions"]["deny"]
    assert len(merged["permissions"]["deny"]) == len(set(merged["permissions"]["deny"]))


def test_fresh_laptop_profile_grants_no_allow_entries() -> None:
    """Read, Glob and Grep never prompt, so an allow entry for them is a no-op
    that reads as if the profile grants something. It must not carry one."""
    profile = json.loads((ROOT / "profiles" / "fresh-laptop" / "settings.json").read_text(encoding="utf-8"))
    assert "allow" not in profile["permissions"]
