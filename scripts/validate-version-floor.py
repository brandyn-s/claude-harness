#!/usr/bin/env python3
"""Validate automatic updates and the repository's two version floors."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SETTINGS = REPO / "settings.json"
MANAGED_TEMPLATE = REPO / "templates" / "managed-settings.json"
SEMANTIC_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
QUALIFIED_REPOSITORY_FLOOR = "2.1.226"
UPDATE_BLOCKERS = (
    "DISABLE_AUTOUPDATER",
    "DISABLE_UPDATES",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
)


def _object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate(
    settings_path: Path = SETTINGS,
    managed_path: Path = MANAGED_TEMPLATE,
) -> list[str]:
    settings = _object(settings_path)
    managed = _object(managed_path)
    errors: list[str] = []

    if "requiredMinimumVersion" in settings:
        errors.append(
            "requiredMinimumVersion is managed-settings-only; remove it from settings.json"
        )

    env = settings.get("env", {})
    if not isinstance(env, dict):
        errors.append("settings env must be a JSON object when present")
        env = {}
    for blocker in UPDATE_BLOCKERS:
        if blocker in env:
            errors.append(
                f"settings env must leave {blocker} unset so automatic updates remain enabled"
            )

    if "autoUpdatesChannel" in settings:
        errors.append(
            "settings must leave autoUpdatesChannel unset so the documented "
            "default latest channel remains authoritative"
        )

    updater_floor = settings.get("minimumVersion")
    startup_floor = managed.get("requiredMinimumVersion")
    if not updater_floor:
        errors.append(
            "settings.json must declare minimumVersion as the updater downgrade floor"
        )
    if not startup_floor:
        errors.append(
            "managed template must declare requiredMinimumVersion as the startup floor"
        )
    for label, value in (
        ("settings minimumVersion", updater_floor),
        ("managed requiredMinimumVersion", startup_floor),
    ):
        if value and (
            not isinstance(value, str) or not SEMANTIC_VERSION.fullmatch(value)
        ):
            errors.append(f"{label} must be a semantic version (major.minor.patch)")
    if updater_floor and startup_floor and updater_floor != startup_floor:
        errors.append(
            "version floors differ: "
            f"settings minimumVersion={updater_floor!r}, "
            f"managed requiredMinimumVersion={startup_floor!r}"
        )
    if (
        updater_floor
        and startup_floor
        and updater_floor == startup_floor
        and updater_floor != QUALIFIED_REPOSITORY_FLOOR
    ):
        errors.append(
            "qualified repository floor must remain "
            f"{QUALIFIED_REPOSITORY_FLOOR}; requalify and update this contract "
            "before changing both floors"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=SETTINGS)
    parser.add_argument("--managed-template", type=Path, default=MANAGED_TEMPLATE)
    args = parser.parse_args(argv)
    try:
        errors = validate(args.settings, args.managed_template)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"version-floor validation failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"version-floor validation failed: {error}", file=sys.stderr)
        return 1
    print(
        "version-floor contract valid: automatic updates enabled; "
        "downgrade and managed startup floors aligned"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
