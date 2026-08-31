"""Semantic manifest compilation must honor deliberate prose-only MCP mentions."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("compile.py")
REPO = SCRIPT.parent.parent
SPEC = importlib.util.spec_from_file_location("manifest_compile", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_semantic_drift_ignores_prose_only_mcp_server_wildcards(tmp_path):
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "The retired `mcp__xai__*` server is not used. "
        "Call `mcp__actual__lookup` for current work.\n",
        encoding="utf-8",
    )
    components = {
        "demo": {
            "_source": "skills/demo/manifest.yaml",
            "type": "skill",
            "requires_tools": [],
            "prose_only_tools": ["mcp__xai__*"],
        }
    }

    issues = MODULE.validate_semantic(tmp_path, components)

    assert not [issue for issue in issues if "mcp__xai__*" in issue]
    assert len(issues) == 1
    assert "mcp__actual__*" in issues[0]


@pytest.mark.parametrize("prose_only", [[], ["mcp__other__*"]])
def test_semantic_drift_still_reports_removed_or_wrong_server_exclusions(
    tmp_path, prose_only
):
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "The retired `mcp__xai__*` server is not used.\n", encoding="utf-8"
    )
    components = {
        "demo": {
            "_source": "skills/demo/manifest.yaml",
            "type": "skill",
            "requires_tools": [],
            "prose_only_tools": prose_only,
        }
    }

    issues = MODULE.validate_semantic(tmp_path, components)

    assert len(issues) == 1
    assert "mcp__xai__*" in issues[0]


def test_strict_cli_rejects_real_manifest_when_prose_only_exclusion_is_removed(
    tmp_path,
):
    """The release gate must kill removal of a real deliberate non-grant."""
    copied = tmp_path / "claude-config"

    for manifest in REPO.glob("skills/*/manifest.yaml"):
        destination = copied / manifest.relative_to(REPO)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest, destination)
        shutil.copy2(manifest.parent / "SKILL.md", destination.parent / "SKILL.md")

    shutil.copytree(REPO / "hooks" / "manifests", copied / "hooks" / "manifests")
    shutil.copy2(
        REPO / "hooks" / "skill-rules.json", copied / "hooks" / "skill-rules.json"
    )
    shutil.copytree(REPO / "rules", copied / "rules")

    command = [
        sys.executable,
        str(SCRIPT),
        "--root",
        str(copied),
        "--check",
        "--strict-semantic",
        "--quiet",
        "--no-reindex",
    ]
    clean = subprocess.run(command, capture_output=True, text=True)
    assert clean.returncode == 0, clean.stdout + clean.stderr

    investigate = copied / "skills" / "investigate" / "manifest.yaml"
    original = investigate.read_text(encoding="utf-8")
    mutated = original.replace(
        "prose_only_tools:\n"
        "  - mcp__xai__*  # explicitly names the retired X-search MCP surface; execution uses bin/x-monitor.py\n",
        "",
    )
    assert mutated != original, "the real investigate exclusion fixture drifted"
    investigate.write_text(mutated, encoding="utf-8")

    rejected = subprocess.run(command, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "mcp__xai__*" in rejected.stdout
