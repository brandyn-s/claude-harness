"""Tests for hooks/session_start_modules/mcp_binary_staleness.py.

Focused on the 2026-05-14 (Path E) upstream-ahead check. The pre-existing
HEAD-vs-deployed-binary check has been in production since installation
of session-start.py; this test file pins the new origin/main awareness
without touching the live ~/Documents/GitHub/code-graph or code-search
repos (each test sets up an isolated git repo in a tmp dir and monkey-
patches the module's REPO + DEPLOYED constants).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Import the module under test by absolute path. The module lives at
# ~/.claude/hooks/session_start_modules/mcp_binary_staleness.py — add
# the parent of session_start_modules to sys.path so `from
# session_start_modules import ...` resolves.
HOOKS_DIR = Path(__file__).resolve().parent.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import mcp_binary_staleness as mbs  # noqa: E402


CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=CREATE_NO_WINDOW,
    )


def _init_repo(tmp_path: Path, name: str) -> Path:
    """Create a git repo with one initial commit on main. Returns the
    repo path.
    """
    repo = tmp_path / name
    repo.mkdir()
    _run(["git", "init", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@e"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    (repo / "README.md").write_text("v1\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "initial"], repo)
    return repo


def _add_fake_origin_main_ahead(repo: Path) -> None:
    """Create a clone-style 'origin' that's ahead of local HEAD. We
    fake this by branching local HEAD into refs/remotes/origin/main
    with a NEW commit applied on top — simulating a remote that
    received a merge after the user's last pull.
    """
    # Make a sibling bare repo to act as origin.
    origin = repo.parent / (repo.name + ".origin.git")
    _run(["git", "init", "--bare", "-b", "main"], origin.parent if origin.exists() else repo.parent)
    if not origin.exists():
        _run(["git", "clone", "--bare", str(repo), str(origin)], repo.parent)
    _run(["git", "remote", "remove", "origin"], repo)
    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "fetch", "origin"], repo)

    # Clone the bare-origin into a working copy, make a new commit,
    # push back. This advances origin/main beyond what the original
    # repo (`repo`) has locally.
    pusher = repo.parent / (repo.name + ".pusher")
    _run(["git", "clone", str(origin), str(pusher)], repo.parent)
    _run(["git", "config", "user.email", "t@e"], pusher)
    _run(["git", "config", "user.name", "t"], pusher)
    (pusher / "v2.md").write_text("upstream advance\n", encoding="utf-8")
    _run(["git", "add", "."], pusher)
    # Use a future commit time so origin/main commit_unix > HEAD commit_unix.
    future_ts = int(time.time()) + 60
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = str(future_ts)
    env["GIT_COMMITTER_DATE"] = str(future_ts)
    subprocess.run(
        ["git", "commit", "-m", "upstream advance"],
        cwd=str(pusher),
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=CREATE_NO_WINDOW,
    )
    _run(["git", "push"], pusher)

    # `repo` now needs a fresh fetch to know origin/main is ahead.
    _run(["git", "fetch", "origin"], repo)


def _patch_module(monkeypatch: pytest.MonkeyPatch, repo: Path, deployed: Path | None) -> None:
    """Point the module's CODE_GRAPH_REPO / CODE_GRAPH_DEPLOYED at our
    test fixtures. Code-search side is set to a non-existent path so
    code-search warnings stay quiet during code-graph tests.
    """
    monkeypatch.setattr(mbs, "CODE_GRAPH_REPO", repo)
    if deployed is not None:
        monkeypatch.setattr(mbs, "CODE_GRAPH_DEPLOYED", deployed)
    else:
        # Point to a missing path; the pre-existing HEAD-vs-deployed check
        # treats a missing binary as stale. For tests focused on the
        # upstream-ahead path, use a deployed binary newer than HEAD so
        # the existing-stale path doesn't fire.
        marker = repo / ".not-a-real-binary"
        monkeypatch.setattr(mbs, "CODE_GRAPH_DEPLOYED", marker)
    # Suppress code-search side noise by pointing it at a non-existent
    # repo (head resolves None -> that side is silent). The old
    # CODE_SEARCH_INSTALL_MARKER constant no longer exists — the install
    # marker is resolved by _code_search_install_marker() at call time.
    monkeypatch.setattr(mbs, "CODE_SEARCH_REPO", repo.parent / "nonexistent-cs")
    # Registration gate (2026-06-20): a repo's checks are skipped unless its
    # MCP server is registered here. The code-graph fixtures below assert
    # warnings, so register the consolidated server name to hold the gate
    # open. (Gate-specific tests override this with their own registration.)
    monkeypatch.setattr(
        mbs, "_registered_mcp_server_names", lambda: {"codebase-memory-mcp"}
    )


def _touch_deployed_after_head(repo: Path) -> Path:
    """Create a deployed-binary marker file with mtime newer than HEAD
    commit time so the existing HEAD-vs-deployed-binary stale check
    doesn't trip during upstream-ahead tests.
    """
    marker = repo / "fake-deployed-binary"
    marker.write_text("stub", encoding="utf-8")
    # Bump mtime to now + 60s (well after the initial commit's commit_ts).
    future = time.time() + 60
    os.utime(marker, (future, future))
    return marker


# --- Upstream-ahead path tests ---


def test_upstream_ahead_warns_when_origin_advances(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, "repo-up")
    _add_fake_origin_main_ahead(repo)
    deployed = _touch_deployed_after_head(repo)
    _patch_module(monkeypatch, repo, deployed)

    warnings = mbs.check_mcp_binary_staleness()
    upstream = [w for w in warnings if "UPSTREAM AHEAD" in w]
    assert len(upstream) == 1, f"expected 1 upstream warning, got: {warnings}"
    assert "code-graph" in upstream[0]
    assert "git pull origin main" in upstream[0]


def test_no_upstream_warning_when_main_already_pulled(tmp_path, monkeypatch):
    """If local HEAD == origin/main, no upstream warning fires."""
    repo = _init_repo(tmp_path, "repo-clean")
    _add_fake_origin_main_ahead(repo)
    # Pull the upstream into local HEAD.
    _run(["git", "pull", "origin", "main"], repo)
    deployed = _touch_deployed_after_head(repo)
    _patch_module(monkeypatch, repo, deployed)

    warnings = mbs.check_mcp_binary_staleness()
    upstream = [w for w in warnings if "UPSTREAM AHEAD" in w]
    assert len(upstream) == 0, f"expected 0 upstream warnings, got: {warnings}"


def test_upstream_warning_includes_fetch_hint_when_fetch_head_stale(tmp_path, monkeypatch):
    """When FETCH_HEAD mtime > FETCH_STALE_SECONDS old, the warning text
    must include the 'consider git fetch first' hint.
    """
    repo = _init_repo(tmp_path, "repo-up-stale-fetch")
    _add_fake_origin_main_ahead(repo)
    deployed = _touch_deployed_after_head(repo)
    _patch_module(monkeypatch, repo, deployed)

    # Backdate FETCH_HEAD to FETCH_STALE_SECONDS + 1 hour ago.
    fh = repo / ".git" / "FETCH_HEAD"
    assert fh.exists()
    backdated = time.time() - (mbs.FETCH_STALE_SECONDS + 3600)
    os.utime(fh, (backdated, backdated))

    warnings = mbs.check_mcp_binary_staleness()
    upstream = [w for w in warnings if "UPSTREAM AHEAD" in w]
    assert len(upstream) == 1, f"expected upstream warning, got: {warnings}"
    assert "consider `git fetch origin main` first" in upstream[0]


def test_upstream_warning_omits_fetch_hint_when_recent_fetch(tmp_path, monkeypatch):
    """Fresh FETCH_HEAD (just-now) → no fetch hint appended."""
    repo = _init_repo(tmp_path, "repo-up-fresh-fetch")
    _add_fake_origin_main_ahead(repo)
    deployed = _touch_deployed_after_head(repo)
    _patch_module(monkeypatch, repo, deployed)

    # FETCH_HEAD was set by _add_fake_origin_main_ahead's `git fetch` —
    # touch it to now to be unambiguous.
    fh = repo / ".git" / "FETCH_HEAD"
    if fh.exists():
        now = time.time()
        os.utime(fh, (now, now))

    warnings = mbs.check_mcp_binary_staleness()
    upstream = [w for w in warnings if "UPSTREAM AHEAD" in w]
    assert len(upstream) == 1, f"expected upstream warning, got: {warnings}"
    assert "consider `git fetch origin main` first" not in upstream[0]


def test_no_upstream_warning_when_origin_main_missing(tmp_path, monkeypatch):
    """A repo without a tracked origin/main ref → no warning (silently
    skips this check; the HEAD-vs-deployed-binary check still fires
    if applicable).
    """
    repo = _init_repo(tmp_path, "repo-no-origin")
    deployed = _touch_deployed_after_head(repo)
    _patch_module(monkeypatch, repo, deployed)

    warnings = mbs.check_mcp_binary_staleness()
    upstream = [w for w in warnings if "UPSTREAM AHEAD" in w]
    assert len(upstream) == 0, f"expected no upstream warning, got: {warnings}"


# --- Pre-existing HEAD-vs-deployed-binary path: regression check ---


def test_head_newer_than_deployed_still_warns(tmp_path, monkeypatch):
    """The pre-existing 'rebuild needed' warning continues to fire when
    HEAD commit time > deployed binary mtime AND the delta touches shipped
    code. (2026-07-05 noise gate: the fixture commits a .go source file —
    the original README.md-only fixture would now be correctly classified
    as a docs-only delta and suppressed.)
    """
    repo = _init_repo(tmp_path, "repo-rebuild")
    (repo / "main.go").write_text("package main\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "shipped code"], repo)
    # Deployed binary file with mtime older than HEAD commit time.
    marker = repo / "old-deployed-binary"
    marker.write_text("old", encoding="utf-8")
    past = time.time() - 3600
    os.utime(marker, (past, past))
    _patch_module(monkeypatch, repo, marker)

    warnings = mbs.check_mcp_binary_staleness()
    stale = [w for w in warnings if "MCP STALE: code-graph" in w]
    assert len(stale) == 1, f"expected stale warning, got: {warnings}"
    assert "sync-code-mcp.py" in stale[0]


# --- 2026-07-05 noise gate: test/docs-only deltas don't warn ---


def test_stale_suppressed_when_only_non_shipped_changed(tmp_path, monkeypatch):
    """THE 2026-07-05 incident case: the only commits newer than the
    deployed binary touch tests/docs — the binary is functionally current
    and the rebuild+restart recommendation must NOT fire."""
    repo = _init_repo(tmp_path, "repo-testonly")
    (repo / "internal").mkdir()
    (repo / "internal" / "tool_output_invariants_test.go").write_text(
        "package tools\n", encoding="utf-8")
    (repo / "NOTES.md").write_text("docs\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "test-only delta"], repo)
    marker = repo / "old-deployed-binary"
    marker.write_text("old", encoding="utf-8")
    past = time.time() - 3600
    os.utime(marker, (past, past))
    _patch_module(monkeypatch, repo, marker)

    warnings = mbs.check_mcp_binary_staleness()
    stale = [w for w in warnings if "MCP STALE: code-graph" in w]
    assert stale == [], f"test/docs-only delta must not warn, got: {warnings}"


def test_shipped_paths_changed_since_helper(tmp_path):
    """Unit coverage of the classifier: shipped → True, non-shipped-only →
    False, unanswerable (no repo) → None (callers fail toward warning)."""
    repo = _init_repo(tmp_path, "repo-helper")
    since_all = int(time.time()) - 7200  # before every commit

    # Initial commit touches only README.md → non-shipped-only.
    assert mbs._shipped_paths_changed_since(repo, since_all) is False

    (repo / "resolver.go").write_text("package r\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "shipped"], repo)
    assert mbs._shipped_paths_changed_since(repo, since_all) is True

    assert mbs._shipped_paths_changed_since(tmp_path / "no-such-repo", since_all) is None


# --- 2026-06-11 mac-port fixes: fail-honest NOT-DEPLOYED + platform paths ---


def test_missing_binary_reports_not_deployed_not_stale(tmp_path, monkeypatch):
    """A repo with NO deployed artifact is a first-deploy/migration state:
    the check must say NOT DEPLOYED (can't determine staleness), never the
    old "built <missing> is older than HEAD" STALE claim."""
    repo = _init_repo(tmp_path, "repo-nodeploy")
    _patch_module(monkeypatch, repo, repo / "missing-binary")

    warnings = mbs.check_mcp_binary_staleness()
    cg = [w for w in warnings if "code-graph" in w and "UPSTREAM" not in w]
    assert len(cg) == 1, f"expected one warning, got: {warnings}"
    assert "NOT DEPLOYED" in cg[0]
    assert "<missing>" not in cg[0]
    assert "MCP STALE" not in cg[0]
    assert "first deploy" in cg[0]


def test_current_binary_is_silent(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, "repo-current")
    marker = _touch_deployed_after_head(repo)
    _patch_module(monkeypatch, repo, marker)
    warnings = mbs.check_mcp_binary_staleness()
    assert [w for w in warnings
            if "code-graph" in w and "UPSTREAM" not in w] == []


def test_venv_marker_resolves_posix_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(mbs, "CODE_SEARCH_REPO", tmp_path)
    rec = (tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
           / "example_code_search-0.9.7.dist-info" / "RECORD")
    rec.parent.mkdir(parents=True)
    rec.write_text("x", encoding="utf-8")
    assert mbs._code_search_install_marker() == rec


def test_venv_marker_resolves_windows_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(mbs, "CODE_SEARCH_REPO", tmp_path)
    rec = (tmp_path / ".venv" / "Lib" / "site-packages"
           / "example_code_search-0.2.0.dist-info" / "RECORD")
    rec.parent.mkdir(parents=True)
    rec.write_text("x", encoding="utf-8")
    assert mbs._code_search_install_marker() == rec


def test_binary_name_is_platform_aware():
    name = mbs.CODE_GRAPH_DEPLOYED.name
    if sys.platform == "win32":
        assert name.endswith(".exe")
    else:
        assert not name.endswith(".exe")


# --- 2026-06-20 registration gate: a repo's checks are skipped unless its MCP
#     server is registered here (code-search/code-graph were consolidated into
#     codebase-memory-mcp on macOS; the old clones linger but run nothing). ---


def _stale_code_search_repo(tmp_path: Path, name: str) -> Path:
    """A git repo whose .venv RECORD mtime is older than HEAD (looks stale).
    Commits a shipped .py file so the 2026-07-05 non-shipped noise gate
    doesn't (correctly) suppress the staleness these tests assert on."""
    repo = _init_repo(tmp_path, name)
    (repo / "server.py").write_text("x = 1\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "shipped code"], repo)
    rec = (repo / ".venv" / "lib" / "python3.12" / "site-packages"
           / "example_code_search-0.9.7.dist-info" / "RECORD")
    rec.parent.mkdir(parents=True)
    rec.write_text("x", encoding="utf-8")
    past = time.time() - 3600
    os.utime(rec, (past, past))
    return repo


def test_code_search_skipped_when_not_registered(tmp_path, monkeypatch):
    """Stale code-search venv BUT code-search is not a registered server
    (the macOS post-consolidation state) → no warning."""
    repo = _stale_code_search_repo(tmp_path, "cs-unreg")
    monkeypatch.setattr(mbs, "CODE_SEARCH_REPO", repo)
    monkeypatch.setattr(mbs, "CODE_GRAPH_REPO", tmp_path / "nonexistent-cg")
    monkeypatch.setattr(
        mbs, "_registered_mcp_server_names",
        lambda: {"codebase-memory-mcp", "memory-search"},
    )
    warnings = mbs.check_mcp_binary_staleness()
    assert [w for w in warnings if "code-search" in w] == [], \
        f"code-search not registered → expected no warning, got: {warnings}"


def test_code_search_warns_when_registered(tmp_path, monkeypatch):
    """Split-host case: code-search IS registered → stale venv still warns.
    The gate suppresses only un-registered servers, not all of them."""
    repo = _stale_code_search_repo(tmp_path, "cs-reg")
    monkeypatch.setattr(mbs, "CODE_SEARCH_REPO", repo)
    monkeypatch.setattr(mbs, "CODE_GRAPH_REPO", tmp_path / "nonexistent-cg")
    monkeypatch.setattr(mbs, "_registered_mcp_server_names", lambda: {"code-search"})
    warnings = mbs.check_mcp_binary_staleness()
    stale = [w for w in warnings if "MCP STALE: code-search" in w]
    assert len(stale) == 1, f"registered + stale → expected 1 warning, got: {warnings}"


def test_unreadable_config_does_not_suppress(tmp_path, monkeypatch):
    """If the registered-servers config can't be read (None), the gate must
    NOT suppress — fail toward showing the warning (pre-gate behavior)."""
    repo = _init_repo(tmp_path, "cg-failopen")
    (repo / "main.go").write_text("package main\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "shipped code"], repo)
    marker = repo / "old-deployed-binary"
    marker.write_text("old", encoding="utf-8")
    past = time.time() - 3600
    os.utime(marker, (past, past))
    monkeypatch.setattr(mbs, "CODE_GRAPH_REPO", repo)
    monkeypatch.setattr(mbs, "CODE_GRAPH_DEPLOYED", marker)
    monkeypatch.setattr(mbs, "CODE_SEARCH_REPO", tmp_path / "nonexistent-cs")
    monkeypatch.setattr(mbs, "_registered_mcp_server_names", lambda: None)
    warnings = mbs.check_mcp_binary_staleness()
    assert [w for w in warnings if "MCP STALE: code-graph" in w], \
        f"None config must not suppress, got: {warnings}"


def test_registered_names_reads_top_and_project_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".claude.json").write_text(
        json.dumps({
            "mcpServers": {"codebase-memory-mcp": {}, "memory-search": {}},
            "projects": {"/p": {"mcpServers": {"linear-server": {}}}},
        }),
        encoding="utf-8",
    )
    names = mbs._registered_mcp_server_names()
    assert names == {"codebase-memory-mcp", "memory-search", "linear-server"}


def test_registered_names_returns_none_when_config_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert mbs._registered_mcp_server_names() is None


# --- Squash-merge / governance-metadata regressions (2026-08-04) ---
#
# Both fixes below close a FALSE POSITIVE that fired on a real session start.
# Each test pairs a known-positive (the warning must go away) with a
# known-negative control (a real change must STILL warn) -- an over-broad fix
# here is worse than the original noise, because it silently suppresses
# genuine staleness.


def _squash_merge_origin(repo: Path) -> None:
    """Reproduce the SQUASH-MERGE state that fired the 2026-08-04 false alarm.

    Local HEAD sits on the feature branch; origin/main carries the SAME
    CONTENT under a different sha with a LATER commit time. Every
    ancestry- and timestamp-based comparison reads this as "behind", and
    it can never clear -- but there is nothing to pull.
    """
    _run(["git", "checkout", "-b", "feat/x"], repo)
    (repo / "feat.txt").write_text("the change\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    past = int(time.time()) - 600
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = str(past)
    env["GIT_COMMITTER_DATE"] = str(past)
    subprocess.run(
        ["git", "commit", "-m", "feat: x"],
        cwd=str(repo), env=env, capture_output=True, text=True,
        timeout=10, creationflags=CREATE_NO_WINDOW,
    )

    origin = repo.parent / (repo.name + ".origin.git")
    _run(["git", "clone", "--bare", str(repo), str(origin)], repo.parent)

    # Pusher lands the IDENTICAL content on main as one squashed commit,
    # later in time -- exactly what `gh pr merge --squash` produces.
    pusher = repo.parent / (repo.name + ".pusher")
    _run(["git", "clone", str(origin), str(pusher)], repo.parent)
    _run(["git", "config", "user.email", "t@e"], pusher)
    _run(["git", "config", "user.name", "t"], pusher)
    _run(["git", "checkout", "main"], pusher)
    (pusher / "feat.txt").write_text("the change\n", encoding="utf-8")
    _run(["git", "add", "."], pusher)
    future = int(time.time()) + 60
    env2 = os.environ.copy()
    env2["GIT_AUTHOR_DATE"] = str(future)
    env2["GIT_COMMITTER_DATE"] = str(future)
    subprocess.run(
        ["git", "commit", "-m", "feat: x (#426)"],
        cwd=str(pusher), env=env2, capture_output=True, text=True,
        timeout=10, creationflags=CREATE_NO_WINDOW,
    )
    _run(["git", "push", "origin", "main"], pusher)

    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "fetch", "origin"], repo)


def test_no_upstream_warning_when_branch_was_squash_merged(tmp_path, monkeypatch):
    """KNOWN-POSITIVE: origin/main newer by timestamp, identical by content."""
    repo = _init_repo(tmp_path, "repo-squash")
    _squash_merge_origin(repo)
    deployed = _touch_deployed_after_head(repo)
    _patch_module(monkeypatch, repo, deployed)

    # Precondition: the timestamp comparison alone WOULD have warned.
    head = mbs._head_commit_unix(repo)
    origin = mbs._origin_main_commit_unix(repo)
    assert head is not None and origin is not None
    assert origin > head, "fixture must put origin/main later in time"

    warnings = mbs.check_mcp_binary_staleness()
    upstream = [w for w in warnings if "UPSTREAM AHEAD" in w]
    assert upstream == [], f"squash-merged branch must not warn, got: {upstream}"


def test_trees_identical_helper(tmp_path):
    """Unit: identical trees -> True; divergent trees -> False."""
    repo = _init_repo(tmp_path, "repo-trees")
    _squash_merge_origin(repo)
    assert mbs._trees_identical(repo, "origin/main", "HEAD") is True

    # Make the trees genuinely diverge; the helper must flip.
    (repo / "extra.txt").write_text("local only\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "local divergence"], repo)
    assert mbs._trees_identical(repo, "origin/main", "HEAD") is False


def test_trees_identical_fails_toward_warning_on_bad_rev(tmp_path):
    """Unknown revision -> False (fail toward SHOWING the warning)."""
    repo = _init_repo(tmp_path, "repo-badrev")
    assert mbs._trees_identical(repo, "no/such/ref", "HEAD") is False


def test_stale_suppressed_when_only_codeowners_changed(tmp_path, monkeypatch):
    """KNOWN-POSITIVE: CODEOWNERS is governance, never compiled in.

    This is the exact 2026-08-04 miss: the .github/ clause already covered
    the workflow files, but CODEOWNERS sits at the repo root with no
    directory prefix and no extension, so one path counted as shipped and
    the whole commit read as a rebuild trigger.
    """
    repo = _init_repo(tmp_path, "repo-codeowners")
    # OUTSIDE the repo on purpose: an in-repo stub gets swept up by the
    # commit and is itself a "shipped" path, which would make this test
    # fail for a reason unrelated to CODEOWNERS.
    deployed = tmp_path / "deployed-stub-codeowners"
    deployed.write_text("stub", encoding="utf-8")
    base = time.time() - 5
    os.utime(deployed, (base, base))

    (repo / "CODEOWNERS").write_text("* @example-org/team\n", encoding="utf-8")
    (repo / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    _run(["git", "add", "CODEOWNERS", ".github"], repo)
    _run(["git", "commit", "-m", "chore: rename org owner"], repo)

    _patch_module(monkeypatch, repo, deployed)
    warnings = mbs.check_mcp_binary_staleness()
    stale = [w for w in warnings if "MCP STALE" in w]
    assert stale == [], f"governance-only commit must not warn, got: {stale}"


def test_stale_still_warns_when_source_named_like_governance_changed(
    tmp_path, monkeypatch
):
    """KNOWN-NEGATIVE control: CODEOWNERS.go is SOURCE, not governance.

    Guards the over-suppression this fix nearly shipped -- an unrestricted
    optional-extension group matched CODEOWNERS.go / LICENSE.go and would
    have hidden real staleness. Caught by this control, not by review.
    """
    repo = _init_repo(tmp_path, "repo-governance-lookalike")
    # Outside the repo -- otherwise the stub itself is the shipped path and
    # this control passes for the wrong reason (see the positive test).
    deployed = tmp_path / "deployed-stub-lookalike"
    deployed.write_text("stub", encoding="utf-8")
    base = time.time() - 5
    os.utime(deployed, (base, base))

    (repo / "CODEOWNERS.go").write_text("package main\n", encoding="utf-8")
    _run(["git", "add", "CODEOWNERS.go"], repo)
    _run(["git", "commit", "-m", "feat: real source change"], repo)

    _patch_module(monkeypatch, repo, deployed)
    warnings = mbs.check_mcp_binary_staleness()
    stale = [w for w in warnings if "MCP STALE" in w]
    assert len(stale) == 1, f"real source change must still warn, got: {warnings}"


def test_non_shipped_regex_covers_governance_but_not_source():
    """Table check over the real 2026-08-04 paths plus lookalike negatives."""
    non_shipped = [
        "CODEOWNERS", "LICENSE", "LICENSE.txt", "NOTICE", "AUTHORS",
        ".gitignore", ".gitattributes", ".editorconfig", ".dockerignore",
        ".pre-commit-config.yaml", "renovate.json",
        ".github/workflows/release.yml", "docs/guide.md", "README.md",
    ]
    shipped = [
        "internal/pipeline/index.go", "cmd/server/main.go", "go.mod", "go.sum",
        "Makefile", "Dockerfile", "CODEOWNERS.go", "LICENSE.go",
        "internal/licensecheck/scan.go", "docs_generator/render.go",
        "internal/authors/model.go",
    ]
    for p in non_shipped:
        assert mbs._NON_SHIPPED_RE.search(p), f"{p} should be non-shipped"
    for p in shipped:
        assert not mbs._NON_SHIPPED_RE.search(p), f"{p} must remain shipped"
