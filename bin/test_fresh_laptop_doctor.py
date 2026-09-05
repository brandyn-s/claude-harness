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
    settings["enabledPlugins"] = {"superpowers@claude-plugins-official": True}
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


def test_doctor_accepts_auto_mode_as_the_operator_permission_mode(tmp_path: Path) -> None:
    """The operator overlay sets defaultMode auto (classifier + deny list + sandbox);
    the doctor must read that as a valid mode, not a FAIL."""
    _seed(tmp_path)
    settings_path = tmp_path / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["permissions"]["defaultMode"] = "auto"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    checks = {check.name: check for check in MODULE.inspect_config(tmp_path)}
    assert checks["permission mode"].status == "PASS"
    assert "auto" in checks["permission mode"].detail


def test_doctor_warns_when_the_superpowers_plugin_is_missing(tmp_path: Path) -> None:
    """The companion skills extend superpowers; a kernel without the plugin has
    nothing for them to extend, so the doctor must say so (review 2026-09-03)."""
    _seed(tmp_path)
    settings = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    settings.pop("enabledPlugins", None)
    (tmp_path / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    checks = {c.name: c for c in MODULE.inspect_config(tmp_path)}
    assert checks["superpowers plugin"].status == "WARN"  # advisory: the plugin is installed inside Claude Code, never by the installer
    settings["enabledPlugins"] = {"superpowers@claude-plugins-official": True}
    (tmp_path / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    checks = {c.name: c for c in MODULE.inspect_config(tmp_path)}
    assert checks["superpowers plugin"].status == "PASS"


# ── installed hooks must be able to import what they import ────────────────
#
# 2026-09-04: a targeted `--install hooks/bash-security-guard.py --apply` left
# the installed guard importing a `_environment_catalog` sibling the install had
# never received. The guard crashed on import, the fail-closed dispatcher
# blocked every Bash command, and this doctor had reported all PASS immediately
# before. The check is static (ast + importlib.util.find_spec); hook code is
# never executed.


def _hook(root: Path, name: str, source: str) -> None:
    (root / "hooks" / name).write_text(source, encoding="utf-8")


def _import_check(root: Path) -> MODULE.Check:
    return {check.name: check for check in MODULE.inspect_config(root)}["hook imports"]


def test_hook_import_check_fails_when_a_sibling_module_is_missing_and_passes_once_installed(tmp_path: Path) -> None:
    _seed(tmp_path)
    _hook(tmp_path, "guard.py", "import json\nfrom _loader import load_section\n")

    check = _import_check(tmp_path)
    assert check.status == "FAIL"
    assert "guard.py" in check.detail and "_loader" in check.detail
    assert "not installed beside it" in check.detail
    assert "--install hooks/_loader.py --apply" in check.detail
    assert "install.sh" in check.detail

    _hook(tmp_path, "_loader.py", "def load_section(name):\n    return {}\n")
    assert _import_check(tmp_path).status == "PASS"


def test_hook_import_check_passes_on_stdlib_imports_without_running_the_hook(tmp_path: Path) -> None:
    _seed(tmp_path)
    # sys.exit(3) at module level: if the doctor executed the hook this test process would die.
    _hook(tmp_path, "guard.py", "import json\nfrom pathlib import Path\nimport sys\nsys.exit(3)\n")

    check = _import_check(tmp_path)

    assert check.status == "PASS", check.detail
    assert "1 hook" in check.detail
    assert "no optional" in check.detail


def test_hook_import_check_fails_on_a_syntax_error_naming_the_file_and_line(tmp_path: Path) -> None:
    _seed(tmp_path)
    _hook(tmp_path, "guard.py", "import json\ndef broken(:\n    pass\n")

    check = _import_check(tmp_path)

    assert check.status == "FAIL"
    assert "guard.py" in check.detail and "line 2" in check.detail


def test_hook_import_check_treats_try_except_importerror_as_optional(tmp_path: Path) -> None:
    _seed(tmp_path)
    _hook(tmp_path, "guard.py",
          "import json\ntry:\n    import shiny_optional_extra\nexcept ImportError:\n    shiny_optional_extra = None\n")

    check = _import_check(tmp_path)

    assert check.status == "PASS", check.detail
    assert "1 optional" in check.detail
