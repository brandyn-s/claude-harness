"""Unit tests for the MCP zombie cleanup module.

Verifies the age-based classification logic and process killing without
spawning real MCP processes. Real-process integration is left to manual
verification (kill Claude Code → relaunch → check `.last-mcp-zombie-cleanup.json`).

The age classifier is the safety-critical part: getting it wrong kills
the current session's active MCPs and breaks the user's session.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import mcp_zombie_cleanup as mod  # noqa: E402


def test_classify_stale_keeps_recent_processes():
    """Processes within STALE_THRESHOLD_SECS of `now` are classified current."""
    now = datetime.now(timezone.utc)
    rows = [
        {"pid": 100, "created": (now - timedelta(seconds=10)).isoformat()},
        {"pid": 101, "created": (now - timedelta(seconds=30)).isoformat()},
    ]
    current, stale = mod._classify_stale(rows, now)
    assert current == [100, 101], f"expected both current, got current={current} stale={stale}"
    assert stale == []


def test_classify_stale_marks_old_processes_as_stale():
    """Processes older than STALE_THRESHOLD_SECS are stale."""
    now = datetime.now(timezone.utc)
    rows = [
        {"pid": 200, "created": (now - timedelta(minutes=5)).isoformat()},
        {"pid": 201, "created": (now - timedelta(hours=2)).isoformat()},
    ]
    current, stale = mod._classify_stale(rows, now)
    assert current == [], f"expected no current, got {current}"
    assert sorted(stale) == [200, 201]


def test_classify_stale_mixed_keeps_current_kills_stale():
    """The defining safety case: current MCP must NOT be killed when stale exists."""
    now = datetime.now(timezone.utc)
    rows = [
        {"pid": 300, "created": (now - timedelta(seconds=5)).isoformat()},   # current
        {"pid": 301, "created": (now - timedelta(minutes=30)).isoformat()},  # stale
        {"pid": 302, "created": (now - timedelta(hours=1)).isoformat()},     # stale
    ]
    current, stale = mod._classify_stale(rows, now)
    assert current == [300]
    assert sorted(stale) == [301, 302]


def test_classify_stale_boundary_at_threshold():
    """Process at exactly STALE_THRESHOLD_SECS is current (boundary inclusive)."""
    now = datetime.now(timezone.utc)
    boundary = mod.STALE_THRESHOLD_SECS
    rows = [
        {"pid": 400, "created": (now - timedelta(seconds=boundary)).isoformat()},
        {"pid": 401, "created": (now - timedelta(seconds=boundary + 1)).isoformat()},
    ]
    current, stale = mod._classify_stale(rows, now)
    assert current == [400], f"boundary should be inclusive: current={current}"
    assert stale == [401]


def test_classify_stale_skips_malformed_rows():
    """Rows missing 'created' or unparseable timestamps are skipped, not crashed."""
    now = datetime.now(timezone.utc)
    rows = [
        {"pid": 500, "created": "not-a-date"},
        {"pid": 501},  # missing 'created' — KeyError path
        {"pid": 502, "created": (now - timedelta(hours=1)).isoformat()},
    ]
    current, stale = mod._classify_stale(rows, now)
    assert current == []
    assert stale == [502]


def test_classify_stale_protects_concurrent_sessions_mcp():
    """THE 2026-06-12 incident case: an old process parented to a live
    `claude` session is a concurrent session's MCP, NOT a zombie. Age-only
    classification killed every other session's codebase-memory-mcp on
    every session start (35 forced restarts in ~28h)."""
    now = datetime.now(timezone.utc)
    rows = [
        # other live session's MCP — hours old, live claude ancestor
        {"pid": 600, "created": (now - timedelta(hours=3)).isoformat(),
         "ancestor_live_claude": True},
        # true zombie — hours old, orphaned (re-parented toward PID 1)
        {"pid": 601, "created": (now - timedelta(hours=3)).isoformat(),
         "ancestor_live_claude": False},
        # this session's fresh spawn — young, ancestry irrelevant
        {"pid": 602, "created": (now - timedelta(seconds=5)).isoformat(),
         "ancestor_live_claude": True},
    ]
    current, stale = mod._classify_stale(rows, now)
    assert sorted(current) == [600, 602], f"live session MCP must survive: {current}"
    assert stale == [601], f"only the orphan is stale: {stale}"


def test_classify_stale_without_ancestry_keeps_legacy_age_only():
    """Rows lacking the ancestry key (Windows path) keep age-only semantics."""
    now = datetime.now(timezone.utc)
    rows = [
        {"pid": 700, "created": (now - timedelta(hours=1)).isoformat()},
    ]
    current, stale = mod._classify_stale(rows, now)
    assert current == []
    assert stale == [700]


def test_has_live_claude_ancestor_walk():
    """Ancestry walk: MCP -> launcher zsh -> claude = protected;
    MCP re-parented to PID 1 = orphan; cycles and depth are bounded."""
    snap = {
        1: (0, "launchd"),
        100: (1, "claude"),                     # live session
        200: (100, "zsh"),                      # launcher
        300: (200, "codebase-memory-mcp"),      # live session's MCP
        400: (1, "codebase-memory-mcp"),        # orphan zombie
        500: (600, "codebase-memory-mcp"),      # cycle guard
        600: (500, "zsh"),
    }
    assert mod._has_live_claude_ancestor(300, snap) is True
    assert mod._has_live_claude_ancestor(400, snap) is False
    assert mod._has_live_claude_ancestor(500, snap) is False  # cycle, no claude
    assert mod._has_live_claude_ancestor(999, snap) is False  # unknown pid
    assert mod._has_live_claude_ancestor(300, {}) is False    # empty snapshot


def test_parse_etime_seconds_formats():
    """ps etime parses across its [[dd-]hh:]mm:ss forms; junk returns None."""
    assert mod._parse_etime_seconds("00:05") == 5
    assert mod._parse_etime_seconds("02:03") == 123
    assert mod._parse_etime_seconds("1:02:03") == 3723
    assert mod._parse_etime_seconds("2-01:02:03") == 2 * 86400 + 3723
    assert mod._parse_etime_seconds("") is None
    assert mod._parse_etime_seconds("garbage") is None
    assert mod._parse_etime_seconds("x-01:02:03") is None


def test_cleanup_returns_empty_when_no_processes_match_posix(monkeypatch, tmp_path):
    """macOS path: no matching processes → no kills, no warnings."""
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod, "_list_processes_by_pattern", lambda pattern: [])
    monkeypatch.setattr(mod, "_kill_pid", lambda pid: True)
    monkeypatch.setattr(mod, "LAST_RUN_MARKER", tmp_path / "marker.json")
    assert mod.cleanup_stale_mcps() == []


def test_cleanup_posix_kills_stale_and_reports(monkeypatch, tmp_path):
    """macOS path end-to-end: POSIX patterns resolve, stale PID killed."""
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    now = datetime.now(timezone.utc)
    fake_rows = {
        "code-search/mcp_server/server.py": [
            {"pid": 3001, "created": (now - timedelta(seconds=5)).isoformat()},   # current
            {"pid": 3002, "created": (now - timedelta(hours=2)).isoformat()},     # stale
        ],
    }
    killed_pids: list[int] = []
    monkeypatch.setattr(
        mod, "_list_processes_by_pattern",
        lambda pattern: fake_rows.get(pattern, []),
    )
    monkeypatch.setattr(mod, "_kill_pid", lambda pid: killed_pids.append(pid) or True)
    monkeypatch.setattr(mod, "LAST_RUN_MARKER", tmp_path / "marker.json")

    warnings = mod.cleanup_stale_mcps()
    assert killed_pids == [3002], f"only stale PID should be killed, got {killed_pids}"
    assert len(warnings) == 1
    assert "killed 1 stale" in warnings[0]


def test_posix_kill_refuses_pid_one_and_zero():
    """Safety rail: the POSIX killer never signals init or pid 0."""
    assert mod._kill_pid_posix(0) is False
    assert mod._kill_pid_posix(1) is False


def test_cleanup_returns_empty_when_no_processes_match(monkeypatch):
    """No matching processes → empty warnings."""
    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_list_processes_by_pattern", lambda pattern: [])
    monkeypatch.setattr(mod, "_kill_pid", lambda pid: True)
    assert mod.cleanup_stale_mcps() == []


def test_cleanup_kills_stale_and_reports(monkeypatch, tmp_path):
    """End-to-end: stale process → kill called → warning emitted."""
    monkeypatch.setattr(mod.sys, "platform", "win32")
    now = datetime.now(timezone.utc)
    fake_rows = {
        "code-search\\\\mcp_server\\\\server.py": [
            {"pid": 1001, "created": (now - timedelta(seconds=5)).isoformat()},   # current
            {"pid": 1002, "created": (now - timedelta(hours=2)).isoformat()},     # stale
        ],
    }
    killed_pids: list[int] = []
    monkeypatch.setattr(
        mod, "_list_processes_by_pattern",
        lambda pattern: fake_rows.get(pattern, []),
    )

    def fake_kill(pid: int) -> bool:
        killed_pids.append(pid)
        return True

    monkeypatch.setattr(mod, "_kill_pid", fake_kill)
    monkeypatch.setattr(mod, "LAST_RUN_MARKER", tmp_path / "marker.json")

    warnings = mod.cleanup_stale_mcps()
    assert killed_pids == [1002], f"only stale PID should be killed, got {killed_pids}"
    assert len(warnings) == 1
    assert "killed 1 stale" in warnings[0]
    assert "1002" in warnings[0]
    # 2026-07-05 banner-noise pass: current-session PIDs are debug detail —
    # kept OUT of the user-facing message, preserved in the marker file.
    assert "1001" not in warnings[0]
    marker = tmp_path / "marker.json"
    assert marker.exists()
    import json
    diag = json.loads(marker.read_text(encoding="utf-8"))
    assert 1001 in diag["groups"][0]["current"], \
        "current PID must remain in the diagnostics marker"


def test_cleanup_does_not_kill_current_when_only_one_pair(monkeypatch, tmp_path):
    """Steady state: only current MCP processes → no kills, no warnings."""
    monkeypatch.setattr(mod.sys, "platform", "win32")
    now = datetime.now(timezone.utc)
    fake_rows = {
        "code-search\\\\mcp_server\\\\server.py": [
            {"pid": 2001, "created": (now - timedelta(seconds=10)).isoformat()},
            {"pid": 2002, "created": (now - timedelta(seconds=15)).isoformat()},
        ],
    }
    killed_pids: list[int] = []
    monkeypatch.setattr(
        mod, "_list_processes_by_pattern",
        lambda pattern: fake_rows.get(pattern, []),
    )
    monkeypatch.setattr(mod, "_kill_pid", lambda pid: killed_pids.append(pid) or True)
    monkeypatch.setattr(mod, "LAST_RUN_MARKER", tmp_path / "marker.json")

    warnings = mod.cleanup_stale_mcps()
    assert killed_pids == []
    assert warnings == []
