"""Tests for hooks/session_start_modules/index_autoheal.py.

The autoheal module is the only thing in the harness that ACTS on a stale
index instead of printing a sentence about it, so its guard rails matter more
than its happy path: a spawn storm across seven concurrent sessions, or a
retry loop against something that cannot be healed, would each be worse than
the warn-only behaviour it replaces.

Popen is stubbed in every test — nothing here starts a real healer.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import index_autoheal as ah  # noqa: E402 -- resolves via the sys.path insert above


class _SpawnRecorder:
    """Stand-in for subprocess.Popen that records instead of spawning."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return object()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolate every filesystem path the module touches."""
    cache = tmp_path / "cache"
    cache.mkdir()
    healer = tmp_path / "scripts" / "heal-code-index.py"
    healer.parent.mkdir(parents=True)
    healer.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(ah, "CACHE_DIR", cache)
    monkeypatch.setattr(ah, "LOCK_PATH", cache / ".autoheal.lock")
    monkeypatch.setattr(ah, "STATUS_PATH", cache / "autoheal-status.json")
    monkeypatch.setattr(ah, "HEAL_LOG", cache / "autoheal.log")
    monkeypatch.setattr(ah, "HEALER", healer)
    monkeypatch.delenv(ah.DISABLE_ENV, raising=False)

    rec = _SpawnRecorder()
    monkeypatch.setattr(ah.subprocess, "Popen", rec)
    return {"cache": cache, "healer": healer, "rec": rec}


def _candidates(monkeypatch, n=2):
    items = [
        {"name": f"proj-{i}", "root_path": f"/repos/proj-{i}", "reason": "stale"}
        for i in range(n)
    ]
    monkeypatch.setattr(ah, "heal_candidates", lambda: items)
    return items


def test_no_candidates_is_silent_and_spawns_nothing(env, monkeypatch):
    monkeypatch.setattr(ah, "heal_candidates", list)
    assert ah.autoheal_indexes() == []
    assert env["rec"].calls == []


def test_spawns_healer_when_work_exists(env, monkeypatch):
    _candidates(monkeypatch, 2)
    msgs = ah.autoheal_indexes()
    assert len(env["rec"].calls) == 1, "expected exactly one healer spawn"
    cmd, kwargs = env["rec"].calls[0]
    assert str(env["healer"]) in cmd
    # Must outlive the session that started it.
    assert kwargs.get("start_new_session") is True
    assert len(msgs) == 1 and "reindexing 2" in msgs[0]


def test_does_not_spawn_when_a_healer_is_already_running(env, monkeypatch):
    """Seven concurrent sessions start at once; only one healer may run."""
    _candidates(monkeypatch, 2)
    ah.LOCK_PATH.write_text(
        json.dumps({"pid": os.getpid(), "started": time.time()}), encoding="utf-8"
    )
    msgs = ah.autoheal_indexes()
    assert env["rec"].calls == [], "must not spawn while a healer holds the lock"
    assert "already running" in msgs[0]


def test_stale_lock_from_a_dead_pid_does_not_block_healing(env, monkeypatch):
    """A healer killed mid-run must not wedge healing forever."""
    _candidates(monkeypatch, 1)
    ah.LOCK_PATH.write_text(
        # A pid that cannot be alive.
        json.dumps({"pid": 2**30, "started": time.time()}), encoding="utf-8"
    )
    ah.autoheal_indexes()
    assert len(env["rec"].calls) == 1, "dead-pid lock must be ignored"


def test_backs_off_after_a_recent_run_left_work_undone(env, monkeypatch):
    """The anti-thrash guard: an unhealable project must not respawn a healer
    on every single session start."""
    _candidates(monkeypatch, 1)
    ah.STATUS_PATH.write_text(
        json.dumps(
            {
                "ran_at": datetime.now(timezone.utc).isoformat(),
                "remaining": ["proj-0"],
            }
        ),
        encoding="utf-8",
    )
    msgs = ah.autoheal_indexes()
    assert env["rec"].calls == [], "must not respawn inside the backoff window"
    assert "BACKING OFF" in msgs[0]
    # Silence would be the dangerous outcome here -- the index is still stale.
    assert "STALE" in msgs[0]
    assert "proj-0" in msgs[0]


def test_retries_once_the_backoff_window_has_passed(env, monkeypatch):
    """Control for the test above: the backoff must EXPIRE, not latch."""
    _candidates(monkeypatch, 1)
    old = datetime.now(timezone.utc) - timedelta(
        seconds=ah.AUTOHEAL_MIN_INTERVAL_SECS + 60
    )
    ah.STATUS_PATH.write_text(
        json.dumps({"ran_at": old.isoformat(), "remaining": ["proj-0"]}),
        encoding="utf-8",
    )
    ah.autoheal_indexes()
    assert len(env["rec"].calls) == 1, "backoff must expire"


def test_previous_clean_run_does_not_trigger_backoff(env, monkeypatch):
    """A recent run that healed everything is not a reason to back off."""
    _candidates(monkeypatch, 1)
    ah.STATUS_PATH.write_text(
        json.dumps(
            {"ran_at": datetime.now(timezone.utc).isoformat(), "remaining": []}
        ),
        encoding="utf-8",
    )
    ah.autoheal_indexes()
    assert len(env["rec"].calls) == 1


def test_env_var_disables_autoheal(env, monkeypatch):
    _candidates(monkeypatch, 3)
    monkeypatch.setenv(ah.DISABLE_ENV, "1")
    assert ah.autoheal_indexes() == []
    assert env["rec"].calls == []


def test_missing_healer_script_warns_instead_of_crashing(env, monkeypatch):
    _candidates(monkeypatch, 1)
    env["healer"].unlink()
    msgs = ah.autoheal_indexes()
    assert env["rec"].calls == []
    assert "will NOT self-heal" in msgs[0]


def test_spawn_failure_warns_instead_of_breaking_session_start(env, monkeypatch):
    _candidates(monkeypatch, 1)

    def boom(*a, **k):
        raise OSError("no fork for you")

    monkeypatch.setattr(ah.subprocess, "Popen", boom)
    msgs = ah.autoheal_indexes()
    assert len(msgs) == 1 and "could not start healer" in msgs[0]


def test_enumeration_failure_is_swallowed(env, monkeypatch):
    """SessionStart must survive a broken registry."""

    def boom():
        raise sqlite_error()

    def sqlite_error():
        return RuntimeError("registry exploded")

    monkeypatch.setattr(ah, "heal_candidates", boom)
    assert ah.autoheal_indexes() == []
