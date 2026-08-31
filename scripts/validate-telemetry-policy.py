#!/usr/bin/env python3
"""Fail closed on content-bearing managed telemetry configuration."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO / "contracts" / "telemetry-policy.json"
# Kept as a public module path for test/consumer compatibility. User settings
# are intentionally not consulted: DISABLE_TELEMETRY is not Claude Code's OTel
# enable/disable control.
SETTINGS_PATH = REPO / "settings.json"
CONTENT_ENV = {
    "OTEL_LOG_ASSISTANT_RESPONSES",
    "OTEL_LOG_RAW_API_BODIES",
    "OTEL_LOG_TOOL_CONTENT",
    "OTEL_LOG_TOOL_DETAILS",
    "OTEL_LOG_USER_PROMPTS",
}


def validate() -> list[str]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []

    if policy.get("schemaVersion") != 2:
        errors.append("telemetry policy schemaVersion must be 2")
    if policy.get("mode") != "metadata-only":
        errors.append("telemetry policy mode must be metadata-only")
    if policy.get("liveDeployment") != "unverified":
        errors.append("repository source must not claim the live managed deployment is verified")
    if "userTelemetryDefault" in policy:
        errors.append(
            "telemetry policy must not infer OTel state from a user telemetry default"
        )

    control = policy.get("otelControl")
    if not isinstance(control, dict):
        errors.append("telemetry policy must define the documented OTel enable control")
        control = {}
    if control.get("enableKey") != "CLAUDE_CODE_ENABLE_TELEMETRY":
        errors.append("documented OTel enable key must be CLAUDE_CODE_ENABLE_TELEMETRY")
    if control.get("enabledValue") != "1":
        errors.append("documented OTel enabled value must be 1")
    if "DISABLE_TELEMETRY" not in (control.get("notOtelControls") or []):
        errors.append("DISABLE_TELEMETRY must be identified as not an OTel control")

    source_validation = policy.get("sourceValidation")
    if (
        not isinstance(source_validation, dict)
        or source_validation.get("attestsLiveDeployment") is not False
    ):
        errors.append("source validation must explicitly not attest live deployment")

    effective_startup = policy.get("effectiveStartup")
    if (
        not isinstance(effective_startup, dict)
        or effective_startup.get("status") != "unverified"
    ):
        errors.append("effective startup telemetry state must remain unverified in source")

    backend_receipt = policy.get("backendReceipt")
    if (
        not isinstance(backend_receipt, dict)
        or backend_receipt.get("status") != "not-collected"
    ):
        errors.append("backend telemetry receipt must remain separate and not collected")

    content = policy.get("contentEnv")
    if not isinstance(content, dict) or set(content) != CONTENT_ENV:
        errors.append("telemetry policy contentEnv key set is incomplete")
        content = content if isinstance(content, dict) else {}
    for key in sorted(CONTENT_ENV):
        if content.get(key) != "0":
            errors.append(f"unsafe telemetry policy: {key} must be 0")

    sources = policy.get("managedSources")
    if not isinstance(sources, list) or not sources:
        errors.append("telemetry policy must name managed source templates")
        sources = []
    for rel in sources:
        path = REPO / rel
        if not path.is_file():
            errors.append(f"managed telemetry source missing: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        for key in sorted(CONTENT_ENV):
            pattern = rf"'{re.escape(key)}'\s*=\s*'0'"
            if not re.search(pattern, text):
                errors.append(f"unsafe managed telemetry source {rel}: {key} is not 0")
    return errors


def main() -> int:
    try:
        errors = validate()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"telemetry-policy validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"telemetry-policy validation failed: {error}", file=sys.stderr)
        return 1
    print("telemetry policy valid: source templates are metadata-only; live state unverified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
