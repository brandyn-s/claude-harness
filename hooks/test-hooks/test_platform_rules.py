"""Tests for the platform-conditional rule loader.

Covers both new modules:
  - hooks/_platform.py                          (current_os / require_os)
  - hooks/session_start_modules/platform_rules.py (load_platform_rules)

The contract under test: on a given host, ONLY that host's platform-rules/<os>/
files are injected, and the OTHER platforms' files are never loaded. This is the
whole point of the system — a Windows-only DOMAIN must not reach a macOS session
and vice versa.
"""
import importlib
import os
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent          # .../hooks
REPO_ROOT = HOOKS_DIR.parent
PLATFORM_RULES = REPO_ROOT / "platform-rules"

sys.path.insert(0, str(HOOKS_DIR))
import _platform  # noqa: E402
from session_start_modules import platform_rules  # noqa: E402


def _load_with_os(osname, rules_dir=None):
    """Run load_platform_rules() as if the host OS were `osname`."""
    orig = platform_rules.current_os
    prev_env = os.environ.get("CLAUDE_PLATFORM_RULES_DIR")
    os.environ["CLAUDE_PLATFORM_RULES_DIR"] = str(rules_dir or PLATFORM_RULES)
    platform_rules.current_os = lambda: osname
    try:
        return platform_rules.load_platform_rules()
    finally:
        platform_rules.current_os = orig
        if prev_env is None:
            os.environ.pop("CLAUDE_PLATFORM_RULES_DIR", None)
        else:
            os.environ["CLAUDE_PLATFORM_RULES_DIR"] = prev_env


# ── _platform helper ──

def test_current_os_canonical_names():
    assert _platform.current_os() in {"macos", "windows", "linux", "other"}


def test_require_os_passes_through_on_match(monkeypatch):
    monkeypatch.setattr(_platform, "current_os", lambda: "macos")
    _platform.require_os("macos", "linux")  # must NOT raise / exit


def test_require_os_exits_on_mismatch(monkeypatch):
    monkeypatch.setattr(_platform, "current_os", lambda: "macos")
    try:
        _platform.require_os("windows")
    except SystemExit as e:
        assert e.code == 0
    else:
        raise AssertionError("require_os should sys.exit(0) on a non-matching OS")


# ── injector: per-OS isolation (the core contract) ──

def test_macos_injects_macos_excludes_windows():
    ctx, summary = _load_with_os("macos")
    assert ctx, "macOS host should inject macOS platform rules"
    assert any(k in ctx for k in ("Keychain", "Homebrew", "Bash sandbox", "caffeinate"))
    assert "pwsh" not in ctx and "PowerShell" not in ctx, "Windows content leaked into macOS context"
    assert "macos" in summary


def test_windows_injects_windows_excludes_macos():
    ctx, _ = _load_with_os("windows")
    assert ctx, "Windows host should inject Windows platform rules"
    assert "pwsh" in ctx or "PowerShell" in ctx
    assert "Keychain" not in ctx, "macOS Keychain content leaked into Windows context"


def test_linux_empty_until_rules_exist():
    # No platform-rules/linux/ files ship yet; the loader must return empty,
    # not crash. (When linux rules are added this test should be updated.)
    ctx, summary = _load_with_os("linux")
    assert ctx == "" and summary == ""


def test_missing_dir_fails_open():
    ctx, summary = _load_with_os("macos", rules_dir="/tmp/cc-platform-rules-does-not-exist-xyz")
    assert ctx == "" and summary == ""


def test_committed_trees_present():
    # The proof migration ships macos/ and windows/ trees; guard against an
    # accidental deletion that would silently drop platform rules.
    assert (PLATFORM_RULES / "macos" / "platform-constraints.md").is_file()
    assert (PLATFORM_RULES / "windows" / "platform-constraints.md").is_file()
