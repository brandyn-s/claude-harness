"""Unit tests for hooks/_platform.py — shared OS detection.

Pure helpers, no I/O beyond platform.system(); tests stub the module's
platform lookup rather than the real host so they pass on every CI leg.
"""
import importlib.util
import os

import pytest

_HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "_platform", os.path.join(_HOOK_DIR, "_platform.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# ── current_os ─────────────────────────────────────────────────────────

def test_current_os_returns_canonical_name():
    # Whatever the host, the result must be one of the canonical names.
    assert _mod.current_os() in ("macos", "windows", "linux", "other")


def test_current_os_mapping_table(monkeypatch):
    import platform as _p
    for system, expected in (
        ("Darwin", "macos"),
        ("Windows", "windows"),
        ("Linux", "linux"),
        ("SunOS", "other"),
    ):
        monkeypatch.setattr(_p, "system", lambda s=system: s)
        assert _mod.current_os() == expected


# ── require_os ─────────────────────────────────────────────────────────

def test_require_os_noop_when_current_os_allowed(monkeypatch):
    monkeypatch.setattr(_mod, "current_os", lambda: "macos")
    # Must NOT exit when the current OS is in the allowed set.
    _mod.require_os("macos", "linux")  # no SystemExit


def test_require_os_exits_zero_on_mismatch(monkeypatch):
    monkeypatch.setattr(_mod, "current_os", lambda: "windows")
    with pytest.raises(SystemExit) as exc:
        _mod.require_os("macos")
    # Exit code 0 = clean no-op (a hook must not error on the wrong OS).
    assert exc.value.code == 0
