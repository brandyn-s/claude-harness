#!/usr/bin/env python3
"""Materialize a disposable release candidate for the current host."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from hook_exec_form import configured_hook_script
from wire_hooks import wire_hooks


REPO = Path(__file__).resolve().parent.parent
CONFIG_CHANGE_FIXTURE = (
    REPO / "hooks" / "test-hooks" / "fixtures" / "config-change-validate.py"
)


def _requires_config_change_fixture(settings: dict) -> bool:
    hooks = settings.get("hooks", {})
    groups = hooks.get("ConfigChange", []) if isinstance(hooks, dict) else []
    if not isinstance(groups, list):
        return False
    for group in groups:
        if not isinstance(group, dict):
            continue
        handlers = group.get("hooks", [])
        if not isinstance(handlers, list):
            continue
        if any(
            configured_hook_script(handler) == "config-change-validate.py"
            for handler in handlers
            if isinstance(handler, dict)
        ):
            return True
    return False


def materialize(config_root: Path) -> str:
    config_root = config_root.resolve()
    settings_path = config_root / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise TypeError("settings root must be an object")

    config_change = config_root / "hooks" / "config-change-validate.py"
    fixture_used = False
    if not config_change.is_file() and _requires_config_change_fixture(settings):
        if not CONFIG_CHANGE_FIXTURE.is_file():
            raise RuntimeError(f"integration fixture is missing: {CONFIG_CHANGE_FIXTURE}")
        config_change.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CONFIG_CHANGE_FIXTURE, config_change)
        fixture_used = True

    wire_hooks(settings_path, [], reconcile_existing=True)
    return "integration fixture" if fixture_used else "production hooks"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config_root", type=Path)
    args = parser.parse_args(argv)
    source = materialize(args.config_root)
    print(f"Materialized {args.config_root.resolve()} using {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
