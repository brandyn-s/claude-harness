"""Unit tests for healthcheck/references/_check_freshness.py (Check 0).

Pins the freshness verdict: on-main-and-current → PASS(0); on a feature
branch → WARN(1); behind the threshold → WARN(1); not a git repo → SKIP(2).
Check 0 gates the staleness stamp on every other check, so its verdict is
load-bearing. git is stubbed via _git so the test is hermetic.
"""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_freshness",
    Path(__file__).resolve().parent.parent / "references" / "_check_freshness.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


def _stub_git(branch, head, origin, behind, ahead, dirty=(), untracked=()):
    table = {
        ("fetch", "origin", "main"): (0, "", ""),
        ("rev-parse", "--abbrev-ref", "HEAD"): (0, branch, ""),
        ("rev-parse", "--short", "HEAD"): (0, head, ""),
        ("rev-parse", "--short", "origin/main"): (0, origin, ""),
        ("rev-list", "--count", "HEAD..origin/main"): (0, str(behind), ""),
        ("rev-list", "--count", "origin/main..HEAD"): (0, str(ahead), ""),
        ("diff", "--name-only", "HEAD"): (0, "\n".join(dirty), ""),
        ("ls-files", "--others", "--exclude-standard"): (0, "\n".join(untracked), ""),
    }
    return lambda args, timeout=10: table.get(tuple(args), (-1, "", "unknown"))


def _gitdir(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_on_main_and_current_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git("main", "aaaa", "aaaa", 0, 0))
    rc = hc.check_freshness(do_fetch=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS" in out and "on main" in out


# ── staleness is not only a COMMIT-POSITION property ───────────────────
# 2026-08-30: on main, 0 behind, 0 ahead, with an uncommitted settings.json
# rewrite, this check returned PASS. The orchestrator keys its
# `[POSSIBLY STALE]` stamping AND its WIP-FAIL labelling on that exit status,
# so 19 working-tree-manufactured findings were printed as clean current state
# and the run declared UNHEALTHY. Worse, the reported fix for 11 of them was to
# ADD entries ARCHITECTURE.md already contained — 11 duplicates.

def test_dirty_tracked_file_warns_even_on_current_main(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git(
        "main", "aaaa", "aaaa", 0, 0, dirty=["settings.json"]))
    rc = hc.check_freshness(do_fetch=False)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "1 tracked file(s) modified" in out
    assert "settings.json" in out, "the WARN must name the file that can manufacture findings"
    assert "MANUFACTURE" in out


def test_untracked_only_still_passes(tmp_path, monkeypatch, capsys):
    """The permanent-floor guard: untracked must never set the exit status.

    The deployed dir carries a large permanent untracked population (measured
    2026-08-30: 48 — `.locks/`, `run/`, `tmp/`, `projects/`) against 1 tracked
    modification. Triggering on untracked would engage the stamp on every run,
    and a permanently-engaged interlock is indistinguishable from a disabled
    one (`grading-discipline`, destructive gates).
    """
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git(
        "main", "aaaa", "aaaa", 0, 0,
        untracked=[f"run/artifact-{i}.json" for i in range(48)]))
    rc = hc.check_freshness(do_fetch=False)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PASS" in out
    assert "48 untracked" in out, "untracked belongs in the report as context"


def test_clean_main_pass_says_clean(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git("main", "aaaa", "aaaa", 0, 0))
    rc = hc.check_freshness(do_fetch=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "clean" in out


def test_dirty_list_is_truncated_with_a_count(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git(
        "main", "aaaa", "aaaa", 0, 0,
        dirty=[f"rules/r{i}.md" for i in range(9)]))
    rc = hc.check_freshness(do_fetch=False)
    out = capsys.readouterr().out
    assert rc == 1
    assert "9 tracked file(s) modified" in out
    assert "…" in out, "a long dirty list must be truncated but counted"


def test_feature_branch_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git("feat/x", "bbbb", "aaaa", 0, 1))
    rc = hc.check_freshness(do_fetch=False)
    out = capsys.readouterr().out
    assert rc == 1
    assert "WARN" in out and "instead of main" in out


def test_behind_threshold_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git("main", "bbbb", "zzzz", 29, 0))
    rc = hc.check_freshness(do_fetch=False, max_behind=5)
    out = capsys.readouterr().out
    assert rc == 1
    assert "29 commits behind" in out


def test_behind_within_threshold_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git("main", "bbbb", "cccc", 3, 0))
    rc = hc.check_freshness(do_fetch=False, max_behind=5)
    assert rc == 0
    assert "PASS" in capsys.readouterr().out


def test_not_a_git_repo_skips(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hc, "CLAUDE_DIR", tmp_path)  # no .git
    rc = hc.check_freshness(do_fetch=False)
    out = capsys.readouterr().out
    assert rc == 2
    assert "SKIP" in out and "not a git repo" in out


def test_diverged_reports_both_directions_and_no_ff_only(tmp_path, monkeypatch, capsys):
    """2026-08-22: a checkout 131 behind AND 278 ahead was reported as just
    '131 commits behind' with `git pull --ff-only` as the recovery — a command
    that fails outright on a diverged checkout. Divergence must be named in
    both directions and the advice must not suggest ff-only."""
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git("main", "a8ce4e54", "e9a8d226", 131, 278))
    rc = hc.check_freshness(do_fetch=False, max_behind=5)
    out = capsys.readouterr().out
    assert rc == 1
    assert "diverged" in out and "131" in out and "278" in out
    assert "--ff-only" not in out
    assert "reconcile deliberately" in out


def test_behind_only_still_advises_ff_only(tmp_path, monkeypatch, capsys):
    # The plain behind-only case keeps the fast-forward recovery line.
    monkeypatch.setattr(hc, "CLAUDE_DIR", _gitdir(tmp_path))
    monkeypatch.setattr(hc, "_git", _stub_git("main", "bbbb", "zzzz", 29, 0))
    rc = hc.check_freshness(do_fetch=False, max_behind=5)
    out = capsys.readouterr().out
    assert rc == 1
    assert "--ff-only" in out and "diverged" not in out
