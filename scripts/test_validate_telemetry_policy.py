"""Tests for the metadata-only managed telemetry policy."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "scripts" / "validate-telemetry-policy.py"
POLICY = REPO / "contracts" / "telemetry-policy.json"

SPEC = importlib.util.spec_from_file_location("telemetry_policy", VALIDATOR)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_repository_telemetry_policy_is_metadata_only_source_intent():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert set(policy["contentEnv"].values()) == {"0"}
    assert policy["liveDeployment"] == "unverified"


def test_repository_contract_separates_source_startup_and_backend_evidence():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy["schemaVersion"] == 2
    assert policy["otelControl"]["enableKey"] == "CLAUDE_CODE_ENABLE_TELEMETRY"
    assert "DISABLE_TELEMETRY" in policy["otelControl"]["notOtelControls"]
    assert policy["sourceValidation"]["attestsLiveDeployment"] is False
    assert policy["effectiveStartup"]["status"] == "unverified"
    assert policy["backendReceipt"]["status"] == "not-collected"
    assert "userTelemetryDefault" not in policy


def test_validator_does_not_treat_disable_telemetry_as_an_otel_control(
    tmp_path, monkeypatch
):
    content = {key: "0" for key in MODULE.CONTENT_ENV}
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    policy["managedSources"] = ["managed.ps1"]
    policy["contentEnv"] = content
    (tmp_path / "settings.json").write_text(
        json.dumps({"env": {}}), encoding="utf-8"
    )
    (tmp_path / "policy.json").write_text(
        json.dumps(policy),
        encoding="utf-8",
    )
    (tmp_path / "managed.ps1").write_text(
        "\n".join(f"'{key}' = '0'" for key in content), encoding="utf-8"
    )
    monkeypatch.setattr(MODULE, "REPO", tmp_path)
    monkeypatch.setattr(MODULE, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(MODULE, "POLICY_PATH", tmp_path / "policy.json")

    findings = MODULE.validate()

    assert not any("DISABLE_TELEMETRY" in finding for finding in findings)


def test_validator_detects_unsafe_managed_precedence_state(tmp_path, monkeypatch):
    content = {
        key: "0"
        for key in (
            "OTEL_LOG_ASSISTANT_RESPONSES",
            "OTEL_LOG_RAW_API_BODIES",
            "OTEL_LOG_TOOL_CONTENT",
            "OTEL_LOG_TOOL_DETAILS",
            "OTEL_LOG_USER_PROMPTS",
        )
    }
    (tmp_path / "settings.json").write_text(
        json.dumps({"env": {}}), encoding="utf-8"
    )
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    policy["managedSources"] = ["managed.ps1"]
    policy["contentEnv"] = content
    (tmp_path / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    (tmp_path / "managed.ps1").write_text(
        "\n".join(f"'{key}' = '1'" for key in content), encoding="utf-8"
    )
    monkeypatch.setattr(MODULE, "REPO", tmp_path)
    monkeypatch.setattr(MODULE, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(MODULE, "POLICY_PATH", tmp_path / "policy.json")

    findings = MODULE.validate()

    assert all(any(key in finding for finding in findings) for key in content)


@pytest.mark.parametrize(
    ("path", "value", "needle"),
    [
        (("schemaVersion",), 1, "schemaVersion"),
        (("liveDeployment",), "verified", "live managed deployment"),
        (("otelControl", "enableKey"), "DISABLE_TELEMETRY", "enable key"),
        (("otelControl", "enabledValue"), "0", "enabled value"),
        (("otelControl", "notOtelControls"), [], "not an OTel control"),
        (("sourceValidation", "attestsLiveDeployment"), True, "source validation"),
        (("effectiveStartup", "status"), "verified", "effective startup"),
        (("backendReceipt", "status"), "observed", "backend telemetry receipt"),
        (
            ("contentEnv", "OTEL_LOG_USER_PROMPTS"),
            "1",
            "OTEL_LOG_USER_PROMPTS",
        ),
        (("userTelemetryDefault",), "disabled", "user telemetry default"),
    ],
)
def test_validator_kills_telemetry_contract_mutations(
    tmp_path, monkeypatch, path, value, needle
):
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    cursor = policy
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    policy["managedSources"] = ["managed.ps1"]
    (tmp_path / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    (tmp_path / "managed.ps1").write_text(
        "\n".join(f"'{key}' = '0'" for key in MODULE.CONTENT_ENV),
        encoding="utf-8",
    )
    monkeypatch.setattr(MODULE, "REPO", tmp_path)
    monkeypatch.setattr(MODULE, "POLICY_PATH", tmp_path / "policy.json")

    findings = MODULE.validate()

    assert any(needle in finding for finding in findings), findings
