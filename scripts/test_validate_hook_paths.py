"""Parser and orphan contracts for hook path validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate-hook-paths.py")
SPEC = importlib.util.spec_from_file_location("validate_hook_paths", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_exec_form_and_declared_non_script_targets_fail_closed(tmp_path):
    assert MODULE.extract_script(
        "/absolute/config/hooks/run-hook", ["session-end.py"]
    ) == "session-end.py"
    assert MODULE.extract_script(
        '"$HOME/.claude/hooks/run-hook" session-start.py', []
    ) == "session-start.py"

    declared = tmp_path / "test_declared.py"
    declared.write_text(
        "# validate-hook-paths-target: settings.json\n", encoding="utf-8"
    )
    escaping = tmp_path / "test_escape.py"
    escaping.write_text(
        "# validate-hook-paths-target: ../outside.json\n", encoding="utf-8"
    )
    assert MODULE.declared_test_target_exists(declared)
    assert not MODULE.declared_test_target_exists(escaping)


def test_retired_session_stop_modules_cannot_mask_an_orphan(tmp_path, monkeypatch):
    hooks = tmp_path / "hooks"
    tests = hooks / "test-hooks"
    retired = hooks / "session_stop_modules"
    tests.mkdir(parents=True)
    retired.mkdir()
    (tests / "test_dead_path.py").write_text("def test_placeholder(): pass\n")
    (retired / "dead-path.py").write_text("# retired target\n")

    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "HOOKS_DIR", hooks)
    monkeypatch.setattr(MODULE, "TEST_HOOKS_DIR", tests)

    errors = MODULE.check_test_orphans()
    assert any("test_dead_path.py" in error for error in errors)
