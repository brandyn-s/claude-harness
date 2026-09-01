from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("fresh_laptop_doctor.py")
SPEC = importlib.util.spec_from_file_location("fresh_laptop_doctor", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _seed(root: Path, *, sandbox: bool = True) -> None:
    hooks = root / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "run-hook").write_text("#!/bin/sh\n", encoding="utf-8")
    (hooks / "guard.py").write_text("", encoding="utf-8")
    settings = {
        "permissions": {"defaultMode": "acceptEdits"},
        "sandbox": {"enabled": sandbox, "allowUnsandboxedCommands": True},
        "enableAllProjectMcpServers": False,
        "enabledMcpjsonServers": [],
        "hooks": {
            "PreToolUse": [{
                "matcher": "Bash",
                "hooks": [{
                    "type": "command",
                    "command": str(hooks / "run-hook"),
                    "args": ["guard.py"],
                }],
            }],
        },
    }
    (root / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


def test_config_ready_when_portable_contract_holds(tmp_path: Path) -> None:
    _seed(tmp_path)
    checks = MODULE.inspect_config(tmp_path)
    assert {check.status for check in checks} == {"PASS"}


def test_config_fails_on_disabled_sandbox_or_missing_hook(tmp_path: Path) -> None:
    _seed(tmp_path, sandbox=False)
    (tmp_path / "hooks" / "guard.py").unlink()
    checks = {check.name: check for check in MODULE.inspect_config(tmp_path)}
    assert checks["native sandbox"].status == "FAIL"
    assert checks["hook wiring"].status == "FAIL"
