"""Tests for session_start_modules/red_mains.py (red-main banner)."""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_MODULE = (Path(__file__).resolve().parent.parent
           / "session_start_modules" / "red_mains.py")
_spec = importlib.util.spec_from_file_location("red_mains", _MODULE)
red_mains = importlib.util.module_from_spec(_spec)
sys.modules["red_mains"] = red_mains
_spec.loader.exec_module(red_mains)


def _write_state(tmp_path, monkeypatch, red, age_hours=1):
    state = tmp_path / "red-mains.json"
    gen = (datetime.now(timezone.utc) - timedelta(hours=age_hours))
    state.write_text(json.dumps({
        "generated_at": gen.isoformat(timespec="seconds"),
        "repos_swept": 74,
        "red": red,
        "errors": [],
    }), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_RED_MAINS_STATE", str(state))
    return state


def test_absent_state_file_is_silent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_RED_MAINS_STATE", str(tmp_path / "nope.json"))
    assert red_mains.check_red_mains() == []


def test_fresh_reds_produce_compact_banner(tmp_path, monkeypatch):
    red = [{"repo": f"org/repo{i}", "workflow": f"wf{i}",
            "conclusion": "failure", "last_run_at": "x", "url": "u"}
           for i in range(7)]
    _write_state(tmp_path, monkeypatch, red)
    msgs = red_mains.check_red_mains()
    assert len(msgs) == 1
    assert msgs[0].startswith("RED MAINS (7):")
    assert "repo0/wf0" in msgs[0] and "(+2 more)" in msgs[0]


def test_fresh_green_state_is_silent(tmp_path, monkeypatch):
    _write_state(tmp_path, monkeypatch, red=[])
    assert red_mains.check_red_mains() == []


def test_stale_state_warns_even_when_green(tmp_path, monkeypatch):
    """A dead launchd job must not read as 'all green' — the staleness
    warning is the banner-side half of the instrument-failure contract."""
    _write_state(tmp_path, monkeypatch, red=[], age_hours=80)
    msgs = red_mains.check_red_mains()
    assert len(msgs) == 1
    assert "stale" in msgs[0] and "com.example.red-main-sweep" in msgs[0]


def test_unreadable_state_is_reported_not_swallowed(tmp_path, monkeypatch):
    state = tmp_path / "red-mains.json"
    state.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_RED_MAINS_STATE", str(state))
    msgs = red_mains.check_red_mains()
    assert len(msgs) == 1 and "unreadable" in msgs[0]
