#!/usr/bin/env python3
"""Validate restrictive cross-session and current subagent runtime settings."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SETTINGS = REPO / "settings.json"
CROSS_SESSION_INBOUND_VALUES = frozenset({"accept", "hold", "refuse"})
DIALOG_EXPIRY_VALUES = frozenset({"60s", "5m", "10m", "never"})
SUPERSEDED_AGENT_LIMITS = {
    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": (
        "legacy concurrent-subagent limit must remain absent; current Claude Code "
        "uses CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY"
    ),
    "CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION": (
        "removed per-session subagent limit must remain absent"
    ),
}
DEPTH_LIMIT = "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"


def _object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def validate(settings_path: Path = SETTINGS) -> list[str]:
    settings = _object(settings_path)
    errors: list[str] = []

    if settings.get("crossSessionInbound") not in CROSS_SESSION_INBOUND_VALUES:
        errors.append(
            "crossSessionInbound must be one of 'accept', 'hold', or 'refuse'"
        )
    elif settings["crossSessionInbound"] != "refuse":
        errors.append("crossSessionInbound must be 'refuse' for the shipped policy")
    if settings.get("dialogExpiry") not in DIALOG_EXPIRY_VALUES:
        errors.append(
            "dialogExpiry must be one of '60s', '5m', '10m', or 'never'"
        )
    elif settings["dialogExpiry"] != "5m":
        errors.append("dialogExpiry must be '5m' for the shipped policy")
    if settings.get("isolatePeerMachines") is not True:
        errors.append("isolatePeerMachines must be true")
    env = settings.get("env", {})
    if not isinstance(env, dict):
        errors.append("settings env must be an object")
    else:
        for variable, message in SUPERSEDED_AGENT_LIMITS.items():
            if variable in env:
                errors.append(message)
        if env.get(DEPTH_LIMIT) != "1":
            errors.append(
                f"{DEPTH_LIMIT} must be the string '1' as defense in depth; "
                "active agent tool allowlists/denials remain the primary nesting control"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=SETTINGS)
    args = parser.parse_args(argv)
    try:
        errors = validate(args.settings)
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        print(f"cross-session settings validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"cross-session settings validation failed: {error}", file=sys.stderr)
        return 1
    print(
        "runtime settings valid: inbound refused; dialogs expire in 5m; "
        "peer machines isolated; superseded agent limits absent; depth defense set"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
