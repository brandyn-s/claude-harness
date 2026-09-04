"""Unit tests for the derived-from-indexes staleness check.

These exercise the freshness logic without depending on live indexes:
- a temp git repo gives us a controllable HEAD (revision and timestamp),
- a temp codebase-memory-mcp cache dir lets us forge registry rows,
- a temp code-search projects dir lets us forge a FAISS index file mtime.

The graph side ENUMERATES the cache dir rather than consulting TRACKED_REPOS, so
several tests deliberately leave TRACKED_REPOS empty to prove coverage does not
depend on it (that dependency was the 2026-07-29 defect: a 5-entry list covered
3 of 19 indexed projects).
"""
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# Make the session_start_modules importable.
HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import index_staleness as mod  # noqa: E402 -- resolves via the sys.path insert above


def _git_env(commit_ts: int):
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "test"
    env["GIT_AUTHOR_EMAIL"] = "test@example.com"
    env["GIT_COMMITTER_NAME"] = "test"
    env["GIT_COMMITTER_EMAIL"] = "test@example.com"
    env["GIT_AUTHOR_DATE"] = f"@{commit_ts} +0000"
    env["GIT_COMMITTER_DATE"] = f"@{commit_ts} +0000"
    return env


def _head(repo_path: Path) -> str:
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _make_git_repo(repo_path: Path, commit_ts: int) -> str:
    """Create a git repo with a single commit at commit_ts. Returns the sha."""
    repo_path.mkdir(parents=True, exist_ok=True)
    env = _git_env(commit_ts)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_path, check=True, env=env)
    (repo_path / "f.txt").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=repo_path, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo_path, check=True, env=env)
    return _head(repo_path)


def _add_commit(repo_path: Path, commit_ts: int) -> str:
    """Add one commit at commit_ts. Returns the new sha."""
    env = _git_env(commit_ts)
    (repo_path / "f.txt").write_text(f"hi {commit_ts}", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=repo_path, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "more"], cwd=repo_path, check=True, env=env)
    return _head(repo_path)


def _forge_code_graph_db(
    cache_dir: Path,
    canonical: str,
    indexed_at_iso: str,
    root_path: Path | str = "",
    source_revision: str | None = None,
    identity_status: str | None = None,
    with_identity: bool = True,
):
    """Create a SQLite DB shaped like what codebase-memory-mcp writes.

    `projects` carries root_path in the real schema — the enumeration reads it to
    locate the checkout. `index_identity` is omitted entirely when
    with_identity=False, modelling a DB written before identity capture.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    db = cache_dir / f"{canonical}.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE projects "
            "(name TEXT PRIMARY KEY, indexed_at TEXT, root_path TEXT)"
        )
        conn.execute(
            "INSERT INTO projects (name, indexed_at, root_path) VALUES (?, ?, ?)",
            (canonical, indexed_at_iso, str(root_path)),
        )
        if with_identity:
            conn.execute(
                "CREATE TABLE index_identity "
                "(project TEXT PRIMARY KEY, source_revision TEXT, "
                "identity_status TEXT)"
            )
            conn.execute(
                "INSERT INTO index_identity "
                "(project, source_revision, identity_status) VALUES (?, ?, ?)",
                (canonical, source_revision or "", identity_status or "captured"),
            )
        conn.commit()
    finally:
        conn.close()
    return db


def _forge_code_search_index(projects_dir: Path, name: str, mtime_unix: int):
    """Create a code-search-style project dir with index/code.index at mtime_unix."""
    pdir = projects_dir / f"{name}_abc123"
    (pdir / "index").mkdir(parents=True, exist_ok=True)
    idx = pdir / "index" / "code.index"
    idx.write_bytes(b"")
    os.utime(idx, (mtime_unix, mtime_unix))


def _isolate(monkeypatch, cache=None, search=None, tracked=None):
    monkeypatch.setattr(mod, "CODE_GRAPH_DIR", cache if cache else Path("/nonexistent-cg"))
    monkeypatch.setattr(mod, "CODE_SEARCH_DIR", search if search else Path("/nonexistent-cs"))
    monkeypatch.setattr(mod, "TRACKED_REPOS", tracked if tracked is not None else {})


def test_project_name_from_path_matches_code_graph_mangling():
    # Retained contract check: project names in the registry are path-mangled.
    assert mod._project_name_from_path("/Users/me/proj") == "Users-me-proj"
    assert mod._project_name_from_path("C:\\Users\\me\\.claude") == "c-Users-me-.claude"
    assert mod._project_name_from_path("/") == "root"


def test_no_warnings_when_identity_matches_head(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"
    sha = _make_git_repo(repo, int(time.time()) - 3600)

    cache = tmp_path / "cg"
    _forge_code_graph_db(
        cache, mod._project_name_from_path(repo), "2099-01-01T00:00:00",
        root_path=repo, source_revision=sha, identity_status="captured",
    )
    _isolate(monkeypatch, cache=cache)

    assert mod.check_index_staleness() == []


def test_stale_via_identity_revision_mismatch(tmp_path, monkeypatch):
    """A moved HEAD is flagged even though indexed_at is in the future.

    This is the case a timestamp comparison cannot see, so indexed_at is set
    far in the future on purpose: only the revision comparison can fail here.
    """
    repo = tmp_path / "myrepo"
    first = _make_git_repo(repo, int(time.time()) - 3600)
    _add_commit(repo, int(time.time()) - 60)

    cache = tmp_path / "cg"
    _forge_code_graph_db(
        cache, mod._project_name_from_path(repo), "2099-01-01T00:00:00",
        root_path=repo, source_revision=first, identity_status="captured",
    )
    _isolate(monkeypatch, cache=cache)

    msgs = mod.check_index_staleness()
    assert len(msgs) == 1
    assert "STALE GRAPH" in msgs[0]
    assert "myrepo" in msgs[0]
    # Exactly one commit landed after the indexed revision.
    assert "(1 commits behind)" in msgs[0]


def test_registry_enumeration_covers_repo_absent_from_tracked_repos(tmp_path, monkeypatch):
    """The 2026-07-29 regression: coverage must not depend on TRACKED_REPOS.

    TRACKED_REPOS is empty here. Under the old hardcoded-list implementation this
    repo was invisible; enumeration must still flag it.
    """
    repo = tmp_path / "untracked-repo"
    first = _make_git_repo(repo, int(time.time()) - 3600)
    _add_commit(repo, int(time.time()) - 60)

    cache = tmp_path / "cg"
    _forge_code_graph_db(
        cache, mod._project_name_from_path(repo), "2099-01-01T00:00:00",
        root_path=repo, source_revision=first, identity_status="captured",
    )
    _isolate(monkeypatch, cache=cache, tracked={})

    msgs = mod.check_index_staleness()
    assert any("untracked-repo" in m for m in msgs), msgs


def test_identity_error_is_reported_separately(tmp_path, monkeypatch):
    """identity_status == error must surface even though every other rule is happy.

    The root_path here is a real directory with a real index and a future
    indexed_at — the api-docs shape. Only the identity bucket catches it.
    """
    plain = tmp_path / "api-docs"
    plain.mkdir()

    cache = tmp_path / "cg"
    _forge_code_graph_db(
        cache, mod._project_name_from_path(plain), "2099-01-01T00:00:00",
        root_path=plain, source_revision="", identity_status="error",
    )
    _isolate(monkeypatch, cache=cache)

    msgs = mod.check_index_staleness()
    assert len(msgs) == 1
    assert "INDEX IDENTITY ERROR" in msgs[0]
    assert "api-docs" in msgs[0]


def test_legacy_db_without_identity_falls_back_to_timestamp(tmp_path, monkeypatch):
    """A DB predating identity capture still gets the old timestamp comparison."""
    repo = tmp_path / "myrepo"
    _make_git_repo(repo, int(time.time()) - 60)

    cache = tmp_path / "cg"
    _forge_code_graph_db(
        cache, mod._project_name_from_path(repo), "2020-01-01T00:00:00",
        root_path=repo, with_identity=False,
    )
    _isolate(monkeypatch, cache=cache)

    msgs = mod.check_index_staleness()
    assert len(msgs) == 1
    assert "STALE GRAPH" in msgs[0]
    assert "myrepo" in msgs[0]


def test_config_db_is_not_treated_as_a_project(tmp_path, monkeypatch):
    cache = tmp_path / "cg"
    cache.mkdir(parents=True)
    # A registry bookkeeping DB with no projects table at all.
    conn = sqlite3.connect(cache / "_config.db")
    conn.execute("CREATE TABLE config (k TEXT, v TEXT)")
    conn.commit()
    conn.close()
    _isolate(monkeypatch, cache=cache)

    assert mod.check_index_staleness() == []


def test_missing_index_does_not_warn(tmp_path, monkeypatch):
    # A repo that isn't indexed at all produces no warning; staleness != missing.
    repo = tmp_path / "myrepo"
    _make_git_repo(repo, int(time.time()))
    _isolate(monkeypatch)

    assert mod.check_index_staleness() == []


def test_indexed_path_without_git_is_skipped(tmp_path, monkeypatch):
    """A captured entry whose root_path is not a checkout yields no staleness claim.

    Distinct from the identity-error case: identity says captured here, so there
    is nothing to compare and nothing to report.
    """
    plain = tmp_path / "plain"
    plain.mkdir()

    cache = tmp_path / "cg"
    _forge_code_graph_db(
        cache, mod._project_name_from_path(plain), "2020-01-01T00:00:00",
        root_path=plain, source_revision="deadbeef", identity_status="captured",
    )
    _isolate(monkeypatch, cache=cache)

    assert mod.check_index_staleness() == []


def test_stale_search_index_is_flagged(tmp_path, monkeypatch):
    """The split-backend side still keys off TRACKED_REPOS."""
    repo = tmp_path / "myrepo"
    head_ts = int(time.time()) - 60
    _make_git_repo(repo, head_ts)

    search = tmp_path / "cs"
    _forge_code_search_index(search, "myrepo", head_ts - 3600)
    _isolate(monkeypatch, search=search, tracked={"myrepo": repo})

    msgs = mod.check_index_staleness()
    assert len(msgs) == 1
    assert "Stale semantic indexes" in msgs[0]
    assert "myrepo" in msgs[0]


# --- Fast HEAD resolution + honest truncation (2026-08-04) ---
#
# The sweep spawned one `git rev-parse` per project; 19 spawns blew the 1.5s
# deadline and truncated the report WITHOUT naming what it skipped, so an
# unevaluated project was indistinguishable from a clean one. The fast path
# must agree with git on every layout -- a ref reader that silently returns
# the wrong sha would mark fresh indexes stale forever.


def test_head_revision_fast_matches_subprocess(tmp_path):
    repo = tmp_path / "r"
    _make_git_repo(repo, 1_700_000_000)
    assert mod._head_revision_fast(repo) == _head(repo)


def test_head_revision_fast_handles_detached_head(tmp_path):
    """Detached HEAD stores the sha directly instead of a `ref:` line."""
    repo = tmp_path / "r-detached"
    _make_git_repo(repo, 1_700_000_000)
    sha = _head(repo)
    subprocess.run(
        ["git", "checkout", "--detach", sha],
        cwd=str(repo), capture_output=True, text=True, timeout=10,
    )
    assert mod._head_revision_fast(repo) == sha


def test_head_revision_fast_handles_packed_refs(tmp_path):
    """After `git pack-refs --all` the loose ref file is GONE; the sha only
    exists in packed-refs. A reader that checks only loose refs returns None
    here and silently degrades every packed repo to the subprocess path."""
    repo = tmp_path / "r-packed"
    _make_git_repo(repo, 1_700_000_000)
    sha = _head(repo)
    subprocess.run(
        ["git", "pack-refs", "--all"],
        cwd=str(repo), capture_output=True, text=True, timeout=10,
    )
    assert not (repo / ".git" / "refs" / "heads" / "main").is_file(), (
        "fixture precondition: the loose ref must be packed away"
    )
    assert mod._head_revision_fast(repo) == sha


def test_head_revision_fast_handles_linked_worktree(tmp_path):
    """A linked worktree's `.git` is a FILE and its refs live in the COMMON
    dir. This host runs worktree-per-session, so this is the common case,
    not an edge case."""
    repo = tmp_path / "r-main"
    _make_git_repo(repo, 1_700_000_000)
    wt = tmp_path / "r-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "feat/wt", str(wt)],
        cwd=str(repo), capture_output=True, text=True, timeout=20,
    )
    assert (wt / ".git").is_file(), "fixture precondition: .git must be a file"
    assert mod._head_revision_fast(wt) == _head(wt)


def test_head_revision_fast_returns_none_for_non_repo(tmp_path):
    """Unrecognised layout -> None, so the caller falls back to git."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert mod._head_revision_fast(plain) is None


def test_truncated_sweep_names_the_unchecked_projects(tmp_path, monkeypatch):
    """A truncation that does not name what it skipped lets an UNEVALUATED
    project read as a clean one."""
    cache = tmp_path / "cache"
    cache.mkdir()
    repo = tmp_path / "r"
    _make_git_repo(repo, 1_700_000_000)
    for name in ("alpha-proj", "beta-proj", "gamma-proj"):
        _forge_code_graph_db(
            cache, name, str(repo), 1_700_000_000, _head(repo), "captured"
        )
    _isolate(monkeypatch, cache=cache, tracked={})
    # Negative deadline: the budget is already blown on entry, so nothing is
    # evaluated and every project must be named as unchecked.
    monkeypatch.setattr(mod, "GRAPH_SWEEP_DEADLINE_SECS", -1.0)

    stale, errors, unchecked = mod._check_graph_registry()
    assert len(unchecked) == 3, f"expected 3 unchecked, got {unchecked}"

    messages = mod.check_index_staleness()
    trunc = [m for m in messages if "NOT evaluated" in m]
    assert len(trunc) == 1, f"expected a truncation message, got {messages}"
    for name in ("alpha-proj", "beta-proj", "gamma-proj"):
        assert name in trunc[0], f"{name} missing from: {trunc[0]}"
    assert "UNKNOWN, not clean" in trunc[0]


def test_complete_sweep_reports_no_truncation(tmp_path, monkeypatch):
    """Control: with a real deadline the same fixture truncates nothing."""
    cache = tmp_path / "cache"
    cache.mkdir()
    repo = tmp_path / "r"
    _make_git_repo(repo, 1_700_000_000)
    for name in ("alpha-proj", "beta-proj"):
        _forge_code_graph_db(
            cache, name, str(repo), 1_700_000_000, _head(repo), "captured"
        )
    _isolate(monkeypatch, cache=cache, tracked={})

    stale, errors, unchecked = mod._check_graph_registry()
    assert unchecked == []
    assert [m for m in mod.check_index_staleness() if "NOT evaluated" in m] == []
