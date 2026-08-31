"""Contracts for restrictive Claude Code cross-session settings."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
VALIDATOR = Path(__file__).with_name("validate_cross_session_settings.py")


def run_validator(settings: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(VALIDATOR)]
    if settings is not None:
        command.extend(["--settings", str(settings)])
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _metadata_blocks_agent_tool(metadata: dict) -> bool:
    allowed = metadata.get("tools")
    denied = metadata.get("disallowedTools", [])
    denied_names = (
        {item.strip() for item in denied.split(",")}
        if isinstance(denied, str)
        else set(denied)
    )
    if allowed is None:
        return "Agent" in denied_names
    if isinstance(allowed, str):
        allowed_names = {item.strip() for item in allowed.split(",")}
        return "Agent" not in allowed_names
    return "Agent" not in allowed


def test_shipped_settings_use_restrictive_cross_session_contract():
    result = run_validator()
    assert result.returncode == 0, result.stderr

    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    assert settings["crossSessionInbound"] == "refuse"
    assert settings["dialogExpiry"] == "5m"
    assert settings["isolatePeerMachines"] is True
    env = settings.get("env", {})
    assert "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS" not in env
    assert "CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION" not in env
    assert env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"] == "1"


def test_active_agents_make_agent_tool_fence_the_primary_nesting_control():
    agent_paths = sorted(
        path
        for path in (REPO / "agents").glob("*.md")
        if path.name not in {"README.md", "TEMPLATE.md"}
    )
    assert [path.stem for path in agent_paths] == [
        "api-ingest-worker",
        "data-flow-analyzer",
        "exploitability-verifier",
        "poc-builder",
        "semgrep-scanner",
        "worker",
    ]

    for path in agent_paths:
        text = path.read_text(encoding="utf-8")
        _, frontmatter, _ = text.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        assert _metadata_blocks_agent_tool(metadata), f"{path.name} allows Agent"


@pytest.mark.parametrize(
    "metadata",
    [
        {"tools": "Read, Agent"},
        {"tools": ["Read", "Agent"]},
        {"disallowedTools": ["Bash"]},
    ],
)
def test_agent_tool_policy_parser_rejects_agent_grants(metadata: dict):
    assert not _metadata_blocks_agent_tool(metadata)


def test_subagent_depth_docs_do_not_restore_superseded_worker_rationale():
    incident = (REPO / "rules" / "incidents" / "subagent-verification.md").read_text(
        encoding="utf-8"
    )
    readme = (REPO / "agents" / "README.md").read_text(encoding="utf-8")

    assert "depth-1 would break worker parallel-sub-dispatch" not in incident
    assert "#84974" in incident
    assert "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1" in incident
    assert "primary" in incident.lower() and "Agent" in incident
    assert "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1" in readme
    assert "#84974" in readme


def test_cross_session_contract_is_wired_into_ci_and_local_preflight():
    workflow = (REPO / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    preflight = (REPO / "bin" / "preflight-skill.py").read_text(
        encoding="utf-8"
    )
    validator = "runtime-qualification/validate_cross_session_settings.py"

    assert validator in workflow
    assert validator in preflight


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (300, "must be one of"),
        ("30s", "must be one of"),
        ("10m", "must be '5m' for the shipped policy"),
    ],
)
def test_dialog_expiry_distinguishes_schema_from_policy(
    tmp_path: Path, value: object, message: str
):
    settings = {
        "crossSessionInbound": "refuse",
        "dialogExpiry": value,
        "isolatePeerMachines": True,
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")

    result = run_validator(path)

    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("deny", "must be one of"),
        ("hold", "must be 'refuse' for the shipped policy"),
    ],
)
def test_cross_session_inbound_distinguishes_schema_from_policy(
    tmp_path: Path, value: object, message: str
):
    settings = {
        "crossSessionInbound": value,
        "dialogExpiry": "5m",
        "isolatePeerMachines": True,
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")

    result = run_validator(path)

    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize(
    ("variable", "message"),
    [
        (
            "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS",
            "legacy concurrent-subagent limit",
        ),
        (
            "CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION",
            "removed per-session subagent limit",
        ),
    ],
)
def test_agent_runtime_policy_rejects_superseded_installed_limits(
    tmp_path: Path, variable: str, message: str
):
    settings = {
        "crossSessionInbound": "refuse",
        "dialogExpiry": "5m",
        "isolatePeerMachines": True,
        "env": {
            variable: "1",
            "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
        },
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")

    result = run_validator(path)

    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize("value", [None, 1, "0", "2", "3"])
def test_agent_runtime_policy_requires_depth_one_as_defense_in_depth(
    tmp_path: Path, value: object
):
    env = {}
    if value is not None:
        env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"] = value
    settings = {
        "crossSessionInbound": "refuse",
        "dialogExpiry": "5m",
        "isolatePeerMachines": True,
        "env": env,
    }
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")

    result = run_validator(path)

    assert result.returncode == 1
    assert "must be the string '1' as defense in depth" in result.stderr
