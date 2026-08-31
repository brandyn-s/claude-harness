"""Regression tests for home-scratch-guard.py.

Warn-only guard: rc is always 0; the signal is whether a nudge appears on
stdout (additionalContext). Origin: 2026-06-14 home-directory hygiene audit.
"""
from pathlib import Path

from conftest import run_hook

HOOK = "home-scratch-guard.py"
# Resolve at runtime — the hook compares against Path.home(), so test paths
# must match that resolution on every platform (literal $HOME strings are
# not expanded by the hook).
_HOME = str(Path.home())


def _write(file_path, content="x"):
    return {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": content}}


def test_warn_home_root_py():
    rc, stdout, _ = run_hook(HOOK, _write(f"{_HOME}/scratch.py"))
    assert rc == 0
    assert "home root" in stdout


def test_warn_home_root_report_md():
    rc, stdout, _ = run_hook(HOOK, _write(f"{_HOME}/aws-commercial-security-audit-2026-06-13.md"))
    assert rc == 0
    assert "home root" in stdout


def test_warn_home_root_install_log():
    rc, stdout, _ = run_hook(HOOK, _write(f"{_HOME}/az-install.log"))
    assert rc == 0
    assert "home root" in stdout


def test_no_warn_dotfile():
    # .zshrc / .gitconfig etc. legitimately live in the home root.
    rc, stdout, _ = run_hook(HOOK, _write(f"{_HOME}/.zshrc"))
    assert rc == 0
    assert not stdout.strip()


def test_no_warn_subdir_document():
    rc, stdout, _ = run_hook(HOOK, _write(f"{_HOME}/Documents/report.md"))
    assert rc == 0
    assert not stdout.strip()


def test_no_warn_nested_project_code():
    rc, stdout, _ = run_hook(HOOK, _write(f"{_HOME}/code/proj/main.py"))
    assert rc == 0
    assert not stdout.strip()


def test_no_warn_tmp_claude_scratch():
    rc, stdout, _ = run_hook(HOOK, _write("/tmp/claude/scratch.py"))
    assert rc == 0
    assert not stdout.strip()


def test_no_warn_no_scratch_suffix():
    # Brewfile / Makefile-style files (no scratch suffix) do not nag.
    rc, stdout, _ = run_hook(HOOK, _write(f"{_HOME}/Brewfile"))
    assert rc == 0
    assert not stdout.strip()


def test_edit_home_root_txt_warns():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "Edit",
        "tool_input": {"file_path": f"{_HOME}/notes.txt", "old_string": "a", "new_string": "b"},
    })
    assert rc == 0
    assert "home root" in stdout


def test_missing_file_path_allows():
    rc, stdout, _ = run_hook(HOOK, {"tool_name": "Write", "tool_input": {}})
    assert rc == 0
    assert not stdout.strip()
