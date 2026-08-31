"""Smoke tests for search-path-guard.py."""
from pathlib import Path

from conftest import make_glob_input, make_grep_input, run_hook

HOOK = "search-path-guard.py"
_HOME = str(Path.home())


def test_allow_scoped_glob():
    rc, _, _ = run_hook(HOOK, make_glob_input(
        "**/*.py", f"{_HOME}/Documents/GitHub/mcp-servers",
    ))
    assert rc == 0


def test_block_home_dir_glob():
    # Use the actual home dir so the hook's home-dir detection fires on any
    # platform (was hardcoded to C:/Users/you — Windows-only).
    rc, _, _ = run_hook(HOOK, make_glob_input("**/*.py", _HOME))
    assert rc == 2


def test_block_c_root_grep():
    rc, _, _ = run_hook(HOOK, make_grep_input("TODO", "C:/"))
    assert rc == 2


def test_allow_specific_hooks_dir():
    rc, _, _ = run_hook(HOOK, make_grep_input(
        "def main", f"{_HOME}/.claude/hooks",
    ))
    assert rc == 0
