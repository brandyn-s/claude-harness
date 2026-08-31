"""Behavior tests for consistency checks.

check_14_mcp_server_inventory (the 2026-06-11 per-machine TOFU baseline
redesign) pins: first run on a machine seeds the baseline and reports
never-seen expected servers as ONE LOW summary (not a 29-name CRITICAL);
a server that was configured here and vanished is the CRITICAL; deleting
a baseline entry is the documented deliberate-removal path and silences it.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import consistency as mod  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location(
        "consistency_t",
        HOOKS_DIR / "session_start_modules" / "consistency.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _setup(tmp_path, mod, configured):
    mod.MCP_BASELINE_PATH = tmp_path / "baseline.json"
    # Without this, check_14 writes the REAL ~/.claude report-state during
    # tests AND the LOW assertion becomes order-dependent on real state
    # (2026-07-05 never-configured change-gate).
    mod.NEVER_CONFIGURED_STATE = tmp_path / "never-configured.json"
    mod.get_all_server_names = lambda: set(configured)


def test_first_run_seeds_baseline_no_critical(tmp_path):
    mod = _load()
    _setup(tmp_path, mod, {"code-search", "tavily"})
    findings = mod.check_14_mcp_server_inventory()
    assert not any("[CRITICAL]" in f for f in findings), findings
    baseline = json.loads(mod.MCP_BASELINE_PATH.read_text(encoding="utf-8"))
    assert set(baseline) == {"code-search", "tavily"}


def test_never_seen_expected_is_single_low_summary(tmp_path):
    mod = _load()
    _setup(tmp_path, mod, {"code-search"})
    findings = mod.check_14_mcp_server_inventory()
    lows = [f for f in findings if "[LOW]" in f]
    assert len(lows) == 1
    assert "never been" in lows[0] and "migration" in lows[0]


def test_disappeared_server_is_critical(tmp_path):
    mod = _load()
    _setup(tmp_path, mod, {"code-search", "tavily"})
    mod.check_14_mcp_server_inventory()  # seed
    mod.get_all_server_names = lambda: {"code-search"}
    findings = mod.check_14_mcp_server_inventory()
    crits = [f for f in findings if "[CRITICAL]" in f]
    assert len(crits) == 1
    assert "tavily" in crits[0] and "disappeared" in crits[0]
    assert "deliberate" in crits[0]  # documents the removal path


def test_deliberate_removal_via_baseline_edit_silences(tmp_path):
    mod = _load()
    _setup(tmp_path, mod, {"code-search", "tavily"})
    mod.check_14_mcp_server_inventory()  # seed
    baseline = json.loads(mod.MCP_BASELINE_PATH.read_text(encoding="utf-8"))
    del baseline["tavily"]
    mod.MCP_BASELINE_PATH.write_text(json.dumps(baseline), encoding="utf-8")
    mod.get_all_server_names = lambda: {"code-search"}
    findings = mod.check_14_mcp_server_inventory()
    assert not any("[CRITICAL]" in f for f in findings), findings


def test_corrupt_baseline_treated_as_empty(tmp_path):
    mod = _load()
    _setup(tmp_path, mod, {"code-search"})
    mod.MCP_BASELINE_PATH.write_text("{not json", encoding="utf-8")
    findings = mod.check_14_mcp_server_inventory()
    assert not any("[CRITICAL]" in f for f in findings), findings
    # And it self-heals: the next write produces valid JSON.
    baseline = json.loads(mod.MCP_BASELINE_PATH.read_text(encoding="utf-8"))
    assert "code-search" in baseline


# ---------------------------------------------------------------------------
# 2026-07-05 banner-noise gates.
#
# Two standing session-start lines fired identically every session:
#
#   - the LOW "N expected MCP server(s) have never been configured" finding
#     (unchanged since the macOS migration) — now reported only when the
#     never-configured SET changes (state: .last-never-configured-mcp-report.json)
#   - the "Memory review overdue" reminder (grew by one day per session once
#     past threshold) — now re-reminds at most every MEMORY_REVIEW_RENAG_DAYS
#     (state: .last-memory-review-nag.json)
#
# Both gates must fail toward SHOWING the line on unreadable state.
# ---------------------------------------------------------------------------


# --- check_14: never-configured set is reported only when it changes ---


def _patch_check14(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                   expected: set[str]) -> None:
    monkeypatch.setattr(mod, "MCP_BASELINE_PATH", tmp_path / "baseline.json")
    monkeypatch.setattr(
        mod, "NEVER_CONFIGURED_STATE", tmp_path / "never-configured.json")
    monkeypatch.setattr(mod, "EXPECTED_MCP_SERVERS", expected)
    monkeypatch.setattr(mod, "get_all_server_names", lambda: set())


def _never_configured_findings(findings: list[str]) -> list[str]:
    return [f for f in findings if "never been" in f]


def test_never_configured_reports_once_then_silent(tmp_path, monkeypatch):
    _patch_check14(monkeypatch, tmp_path, {"alpha", "beta"})

    first = _never_configured_findings(mod.check_14_mcp_server_inventory())
    assert len(first) == 1, f"first run must report, got: {first}"
    assert "alpha" in first[0] and "beta" in first[0]
    assert "re-reports only when this set changes" in first[0]

    second = _never_configured_findings(mod.check_14_mcp_server_inventory())
    assert second == [], f"unchanged set must be silent, got: {second}"


def test_never_configured_rereports_when_set_changes(tmp_path, monkeypatch):
    _patch_check14(monkeypatch, tmp_path, {"alpha"})
    assert len(_never_configured_findings(mod.check_14_mcp_server_inventory())) == 1
    assert _never_configured_findings(mod.check_14_mcp_server_inventory()) == []

    # A new expected server appears (or one got ported away) → the set
    # changed → one fresh report, then silent again.
    monkeypatch.setattr(mod, "EXPECTED_MCP_SERVERS", {"alpha", "gamma"})
    changed = _never_configured_findings(mod.check_14_mcp_server_inventory())
    assert len(changed) == 1 and "gamma" in changed[0]
    assert _never_configured_findings(mod.check_14_mcp_server_inventory()) == []


def test_never_configured_unreadable_state_fails_toward_showing(tmp_path, monkeypatch):
    _patch_check14(monkeypatch, tmp_path, {"alpha"})
    (tmp_path / "never-configured.json").write_text("not json", encoding="utf-8")
    findings = _never_configured_findings(mod.check_14_mcp_server_inventory())
    assert len(findings) == 1, "corrupt state must not suppress the report"


def test_never_configured_clears_state_when_set_empties(tmp_path, monkeypatch):
    """All expected servers configured → state records [] so a future
    regression (server removed from config AND baseline) re-reports."""
    _patch_check14(monkeypatch, tmp_path, {"alpha"})
    assert len(_never_configured_findings(mod.check_14_mcp_server_inventory())) == 1

    monkeypatch.setattr(mod, "get_all_server_names", lambda: {"alpha"})
    assert _never_configured_findings(mod.check_14_mcp_server_inventory()) == []
    state = json.loads((tmp_path / "never-configured.json").read_text(encoding="utf-8"))
    assert state == []


# --- memory-review nag: at most one reminder per RENAG window ---


def _write_claude_json(path: Path, days_ago: float) -> None:
    last_used_ms = (time.time() - days_ago * 86400) * 1000
    path.write_text(
        json.dumps({"skillUsage": {"review-learnings": {"lastUsedAt": last_used_ms}}}),
        encoding="utf-8",
    )


def _patch_nag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cj = tmp_path / ".claude.json"
    monkeypatch.setattr(mod, "CLAUDE_JSON", cj)
    monkeypatch.setattr(
        mod, "MEMORY_REVIEW_NAG_STATE", tmp_path / "nag-state.json")
    return cj


def test_nag_fires_once_then_throttles(tmp_path, monkeypatch):
    cj = _patch_nag(monkeypatch, tmp_path)
    # 21.5, not 21: the hook computes days from datetime.now().timestamp()
    # while this fixture writes time.time(). On Windows the former has
    # ~15.6ms granularity and can read a hair EARLIER than the fixture's
    # clock, so an exact-21-day write yields int(20.999...) == 20. A
    # mid-interval fixture keeps the exact "21 days ago" assertion while
    # tolerating millisecond clock skew between the two sources.
    _write_claude_json(cj, days_ago=21.5)

    first = mod.check_memory_review_overdue()
    assert first is not None and "21 days ago" in first
    assert mod.check_memory_review_overdue() is None, \
        "second call inside the renag window must be silent"


def test_nag_refires_after_renag_window(tmp_path, monkeypatch):
    cj = _patch_nag(monkeypatch, tmp_path)
    _write_claude_json(cj, days_ago=30)
    assert mod.check_memory_review_overdue() is not None

    # Backdate the nag state past the renag window.
    stale_ts = time.time() - (mod.MEMORY_REVIEW_RENAG_DAYS + 1) * 86400
    (tmp_path / "nag-state.json").write_text(
        json.dumps({"last_nag_ts": stale_ts}), encoding="utf-8")
    assert mod.check_memory_review_overdue() is not None


def test_nag_silent_when_not_overdue(tmp_path, monkeypatch):
    cj = _patch_nag(monkeypatch, tmp_path)
    _write_claude_json(cj, days_ago=5)
    assert mod.check_memory_review_overdue() is None
    assert not (tmp_path / "nag-state.json").exists(), \
        "no state write when not overdue"


def test_nag_corrupt_state_fails_toward_showing(tmp_path, monkeypatch):
    cj = _patch_nag(monkeypatch, tmp_path)
    _write_claude_json(cj, days_ago=21)
    (tmp_path / "nag-state.json").write_text("not json", encoding="utf-8")
    assert mod.check_memory_review_overdue() is not None
