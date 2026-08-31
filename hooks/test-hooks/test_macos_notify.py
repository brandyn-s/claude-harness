"""Unit tests for the macOS notification helper."""
from __future__ import annotations

import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

import macos_notify as mod  # noqa: E402


class _FakeResult:
    def __init__(self, returncode=0):
        self.returncode = returncode


def test_notify_is_darwin_only(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "linux")
    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call osascript off-darwin")),
    )
    assert mod.notify("t", "m") is False


def test_notify_respects_kill_switch(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setenv("CLAUDE_NOTIFY", "0")
    monkeypatch.setattr(
        mod.subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("kill switch must not call osascript")),
    )
    assert mod.notify("t", "m") is False


def test_notify_passes_strings_via_argv(monkeypatch):
    """Title/message travel as argv items, never embedded in the script —
    quotes and newlines in messages cannot produce AppleScript injection."""
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_NOTIFY", raising=False)
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return _FakeResult(0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    evil = 'done" with title "spoof\n'
    assert mod.notify("Claude", evil) is True
    cmd = calls["cmd"]
    assert cmd[0] == "osascript"
    assert cmd[2] == mod._OSA_SCRIPT  # script is the fixed constant
    assert cmd[3] == "Claude"
    assert cmd[4] == evil  # delivered verbatim as an argv item


def test_notify_truncates_long_message(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_NOTIFY", raising=False)
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return _FakeResult(0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    mod.notify("t" * 500, "m" * 500)
    assert len(calls["cmd"][3]) == mod._TITLE_MAX
    assert len(calls["cmd"][4]) == mod._MESSAGE_MAX


def test_notify_never_raises(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_NOTIFY", raising=False)

    def boom(*a, **k):
        raise OSError("osascript exploded")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    assert mod.notify("t", "m") is False


def test_notify_reports_failure_returncode(monkeypatch):
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.delenv("CLAUDE_NOTIFY", raising=False)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _FakeResult(1))
    assert mod.notify("t", "m") is False
