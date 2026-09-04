"""Check codebase-memory-mcp (graph) and semantic-search index freshness.

Each indexing system is its own source of truth, so this check is self-healing:
refreshing an index through any path clears the warning on the next session start.

codebase-memory-mcp: ENUMERATES the registry — every `*.db` in
    `~/.cache/codebase-memory-mcp/` — and reads `projects.root_path` plus the
    `index_identity` row. Enumeration is deliberate: a hand-maintained repo list
    silently excludes every project added after it was written. On 2026-07-29 a
    5-entry list covered 3 of 19 indexed projects, and 11 stale indexes went
    unreported for two days as a result.

semantic search (split backend): stats the FAISS index file mtime under
    `~/.claude_code_search/projects/<name>_<hash>/index/code.index`. That side is
    still keyed by project name (the checkout's directory name), so it uses
    TRACKED_REPOS, built from the environment catalog's `repo_paths`.

Staleness signal, strongest available first:
  1. `index_identity.source_revision` != `git rev-parse HEAD` — exact. Catches a
     content change that does not move the HEAD commit date, which a timestamp
     comparison cannot see.
  2. `projects.indexed_at` older than the HEAD committer timestamp — the legacy
     fallback, used when a DB predates identity capture.

`identity_status == "error"` is reported separately: such an index is queryable
but its freshness is UNKNOWABLE (usual cause is a root_path that is not a git
checkout), and every path/timestamp rule scores it healthy.
"""

import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# The environment catalog lives beside the hooks, one level up from this package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _environment_catalog import load_section, repo_entries

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
CODE_GRAPH_DIR = Path.home() / ".cache" / "codebase-memory-mcp"
CODE_SEARCH_DIR = Path.home() / ".claude_code_search" / "projects"

# Registry bookkeeping DB, not a project.
NON_PROJECT_DBS = {"_config.db"}

# Wall-clock ceiling for the whole graph-side sweep. The module's documented
# budget is <2s; measured cost is ~0.5s for 19 projects (one sqlite read plus
# one `git rev-parse` each). A pathological registry stops early and reports
# what it got rather than blowing the SessionStart budget.
# Raised 1.5 -> 4.0 on 2026-08-04. The 1.5s budget was sized against a
# measured ~0.5s sweep, but that measurement predated the registry growing to
# 19 projects; the real cost was one `git rev-parse` SPAWN per project and the
# sweep silently truncated. `_head_revision_fast` removes those spawns, so this
# ceiling should now be unreachable -- it is a backstop for a pathological
# registry or a cold filesystem, not the operating point.
GRAPH_SWEEP_DEADLINE_SECS = 4.0

# A 40-char lowercase hex object name.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# Semantic-search (split backend) side only. The graph side enumerates instead —
# see the module docstring. Maps project name (== the checkout's directory name,
# which is what the search server registers) → repo path, from the catalog's
# `repo_paths`. Empty catalog -> nothing to compare on this side.
TRACKED_REPOS = {
    entry["path"].name: entry["path"]
    for entry in repo_entries(load_section("repo_paths"))
}


def _git(args, cwd):
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=CREATE_NO_WINDOW,
    )


def _head_committer_unix(repo_path):
    """HEAD commit's committer timestamp as unix epoch int. None on failure."""
    try:
        r = _git(["log", "-1", "--format=%ct", "HEAD"], str(repo_path))
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip())
    except Exception:
        pass
    return None


def _head_revision(repo_path):
    """Current HEAD sha as a string. None on failure."""
    try:
        r = _git(["rev-parse", "HEAD"], str(repo_path))
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _resolve_git_dir(repo_path):
    """Return (gitdir, commondir) for a checkout, or (None, None).

    A LINKED WORKTREE's `.git` is a FILE holding `gitdir: <path>`, and its
    refs live in the COMMON dir named by `<gitdir>/commondir` -- so a naive
    `<repo>/.git/refs/...` read returns nothing for every worktree. Both
    shapes are handled here because this host runs worktree-per-session.
    """
    dot = Path(repo_path) / ".git"
    if dot.is_dir():
        return dot, dot
    if not dot.is_file():
        return None, None
    try:
        txt = dot.read_text(encoding="utf-8").strip()
    except OSError:
        return None, None
    if not txt.startswith("gitdir:"):
        return None, None
    gitdir = Path(txt.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = (Path(repo_path) / gitdir).resolve()
    common = gitdir
    cf = gitdir / "commondir"
    if cf.is_file():
        try:
            c = Path(cf.read_text(encoding="utf-8").strip())
            common = c if c.is_absolute() else (gitdir / c).resolve()
        except OSError:
            pass
    return gitdir, common


def _head_revision_fast(repo_path):
    """HEAD sha read straight from the ref files -- no subprocess.

    WHY THIS EXISTS: the sweep used to spawn `git rev-parse HEAD` once per
    project. Nineteen spawns is what pushed it past its deadline on
    2026-08-04, truncating the report without naming what it skipped. Reading
    the refs costs microseconds. It is ALSO immune to the documented macOS
    sandbox failure where `git` invoked from a child process is not
    resolvable -- that mode makes the subprocess path return None for a
    perfectly valid checkout.

    Returns None for any layout it does not recognise; the caller falls back
    to the subprocess so correctness never rests on this path.
    """
    gitdir, common = _resolve_git_dir(repo_path)
    if gitdir is None:
        return None
    try:
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if _SHA_RE.match(head):
        return head  # detached HEAD holds the sha directly
    if not head.startswith("ref:"):
        return None
    ref = head.split(":", 1)[1].strip()
    # Loose ref: the worktree's own gitdir wins over the common dir.
    for base in (gitdir, common):
        try:
            p = base / ref
            if p.is_file():
                val = p.read_text(encoding="utf-8").strip()
                if _SHA_RE.match(val):
                    return val
        except OSError:
            pass
    # Packed refs live in the common dir.
    try:
        pr = common / "packed-refs"
        if pr.is_file():
            for line in pr.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line[0] in "#^":
                    continue
                parts = line.split(None, 1)
                if (
                    len(parts) == 2
                    and parts[1].strip() == ref
                    and _SHA_RE.match(parts[0])
                ):
                    return parts[0]
    except OSError:
        pass
    return None


def _commits_between(repo_path, from_rev):
    """Count commits in from_rev..HEAD. '?' if from_rev is unknown to the repo.

    A rebase or force-push can leave the indexed revision absent from history,
    in which case the count is genuinely unavailable rather than zero.
    """
    try:
        r = _git(["rev-list", "--count", f"{from_rev}..HEAD"], str(repo_path))
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "?"


def _commits_since_unix(repo_path, since_unix):
    """Count commits in HEAD after since_unix. Returns '?' on failure."""
    try:
        iso = datetime.fromtimestamp(since_unix, tz=timezone.utc).isoformat()
        r = _git(
            ["rev-list", "--count", f"--since={iso}", "HEAD"],
            str(repo_path),
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "?"


def _project_name_from_path(abs_path):
    """Mirror code-graph's pipeline.ProjectNameFromPath: slashes/colons → dashes."""
    s = str(abs_path).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0].lower() + s[1:]
    s = s.replace("/", "-").replace(":", "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s.lstrip("-") or "root"


def _iso_to_unix(value):
    """Parse an `indexed_at` ISO string to unix epoch int. None on failure."""
    try:
        dt = datetime.fromisoformat(str(value).rstrip("Z"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _read_graph_entry(db_path):
    """Read one project's registry row.

    Returns dict(name, root_path, indexed_unix, source_revision, identity_status)
    or None when the DB is unreadable or holds no project row. `index_identity`
    is absent in DBs written before identity capture, so its fields default to
    empty and the caller falls back to the timestamp comparison.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    except Exception:
        return None
    try:
        try:
            row = conn.execute(
                "SELECT name, indexed_at, root_path FROM projects LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return None
        if not row or not row[0]:
            return None
        name, indexed_at, root_path = row[0], row[1], row[2]

        source_revision = ""
        identity_status = ""
        try:
            irow = conn.execute(
                "SELECT source_revision, identity_status FROM index_identity "
                "WHERE project = ?",
                (name,),
            ).fetchone()
            if irow:
                source_revision = irow[0] or ""
                identity_status = irow[1] or ""
        except sqlite3.Error:
            # Pre-identity DB: fall back to the timestamp comparison.
            pass
    finally:
        conn.close()

    return {
        "name": name,
        "root_path": root_path or "",
        "indexed_unix": _iso_to_unix(indexed_at),
        "source_revision": source_revision,
        "identity_status": identity_status,
    }


def _short(name, root_path):
    """Display label: the repo's directory name, falling back to the project name."""
    if root_path:
        tail = str(root_path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if tail:
            return tail
    return name


def _check_graph_registry():
    """Return (stale, identity_errors, truncated) across the enumerated registry.

    stale: list of (label, commits_behind)
    identity_errors: list of label
    unchecked: labels the deadline prevented evaluating (empty when complete)
    """
    stale = []
    identity_errors = []
    if not CODE_GRAPH_DIR.exists():
        return stale, identity_errors, []

    dbs = [
        d
        for d in sorted(CODE_GRAPH_DIR.glob("*.db"))
        if d.name not in NON_PROJECT_DBS
    ]
    started = time.monotonic()
    unchecked = []
    for pos, db in enumerate(dbs):
        if time.monotonic() - started > GRAPH_SWEEP_DEADLINE_SECS:
            # Name what was skipped. A silent "results may be partial" makes
            # an UNEVALUATED project read exactly like a clean one, which is
            # the failure this reporting change exists to prevent.
            unchecked = [_short(d.stem, "") for d in dbs[pos:]]
            break

        entry = _read_graph_entry(db)
        if not entry:
            continue

        label = _short(entry["name"], entry["root_path"])
        verdict = classify_entry(entry)

        if verdict == "identity_error":
            identity_errors.append(label)
        elif verdict == "stale":
            stale.append((label, _behind_count(entry)))

    return stale, identity_errors, unchecked


# --- Shared classification -------------------------------------------------
#
# SINGLE SOURCE OF TRUTH for "is this index stale?", consumed by BOTH the
# SessionStart banner (above) and scripts/heal-code-index.py. Keeping these
# in two places would let the healer heal a different set than the banner
# reports -- producing a warning that never clears, which is strictly worse
# than not healing at all.


def classify_entry(entry):
    """Classify one registry row.

    Returns one of:
      "identity_error" — freshness is UNKNOWABLE (git identity capture failed)
      "stale"          — the index is behind its checkout
      "ok"             — index matches the checkout
      "skip"           — root_path is not a git checkout; nothing to compare
    """
    if entry["identity_status"] == "error":
        return "identity_error"

    root = entry["root_path"]
    if not root or not (Path(root) / ".git").exists():
        # Not a git checkout and identity did not flag it: nothing to compare
        # against, and "not indexed" is not a staleness finding.
        return "skip"

    indexed_rev = entry["source_revision"]
    if indexed_rev:
        # Fast ref read first; subprocess only if the layout is unusual.
        head_rev = _head_revision_fast(root) or _head_revision(root)
        if head_rev and head_rev != indexed_rev:
            return "stale"
        return "ok"

    # Legacy DB with no captured identity — timestamp fallback.
    head_ts = _head_committer_unix(root)
    idx_ts = entry["indexed_unix"]
    if head_ts and idx_ts is not None and idx_ts < head_ts:
        return "stale"
    return "ok"


def _behind_count(entry):
    """Display-only 'N commits behind'. Costs a subprocess, so it runs ONLY
    for rows already classified stale, never across the whole registry."""
    root = entry["root_path"]
    if entry["source_revision"]:
        return _commits_between(root, entry["source_revision"])
    idx_ts = entry["indexed_unix"]
    return _commits_since_unix(root, idx_ts) if idx_ts is not None else "?"


def heal_candidates():
    """Projects a reindex would fix: [{name, root_path, reason}].

    Deliberately has NO deadline — the healer runs detached, so truncating it
    would reintroduce the silent-partial-coverage bug in the one place that
    can actually fix things.
    """
    out = []
    if not CODE_GRAPH_DIR.exists():
        return out
    for db in sorted(CODE_GRAPH_DIR.glob("*.db")):
        if db.name in NON_PROJECT_DBS:
            continue
        entry = _read_graph_entry(db)
        if not entry:
            continue
        verdict = classify_entry(entry)
        if verdict in ("stale", "identity_error"):
            root = entry["root_path"]
            # An identity_error row may carry a root_path that is genuinely
            # not a checkout; reindexing only helps when one exists.
            if root and (Path(root) / ".git").exists():
                out.append(
                    {
                        "name": entry["name"],
                        "root_path": root,
                        "reason": verdict,
                    }
                )
    return out


def _code_search_indexed_unix(name):
    """FAISS index file mtime for the named semantic-search project. None if missing."""
    if not CODE_SEARCH_DIR.exists():
        return None
    for pdir in CODE_SEARCH_DIR.iterdir():
        if not pdir.is_dir():
            continue
        # Project dir is "<name>_<hash>"; split once on "_".
        parts = pdir.name.rsplit("_", 1)
        if parts[0] != name:
            continue
        idx = pdir / "index" / "code.index"
        if idx.exists():
            return int(idx.stat().st_mtime)
    return None


def _check_code_search():
    """Return list of (label, commits_behind) for stale split-backend indexes."""
    stale = []
    for name, repo_path in TRACKED_REPOS.items():
        if not (repo_path / ".git").exists():
            continue
        head_ts = _head_committer_unix(repo_path)
        if not head_ts:
            continue
        search_ts = _code_search_indexed_unix(name)
        if search_ts is not None and search_ts < head_ts:
            stale.append((name, _commits_since_unix(repo_path, search_ts)))
    return stale


def check_index_staleness():
    """Return list of warning messages for indexes that are behind their checkout."""
    stale_graph, identity_errors, unchecked = _check_graph_registry()
    stale_search = _check_code_search()

    messages = []
    if stale_graph:
        parts = ", ".join(f"{n} ({c} commits behind)" for n, c in stale_graph)
        messages.append(
            f"STALE GRAPH: {parts}. "
            f"Run /index-repo <repo> to refresh "
            f"(index_repository with skip_report=true)."
        )
    if identity_errors:
        parts = ", ".join(identity_errors)
        messages.append(
            f"INDEX IDENTITY ERROR: {parts}. Freshness is unknowable — usually a "
            f"root_path that is not a git checkout. Run /index-repo --audit."
        )
    if unchecked:
        names = ", ".join(unchecked)
        messages.append(
            f"Index staleness sweep stopped after "
            f"{GRAPH_SWEEP_DEADLINE_SECS}s with {len(unchecked)} project(s) "
            f"NOT evaluated: {names}. Their freshness is UNKNOWN, not clean. "
            f"Run /index-repo --audit for the full picture."
        )
    if stale_search:
        parts = ", ".join(f"{n} ({c} commits behind)" for n, c in stale_search)
        messages.append(
            f"Stale semantic indexes: {parts}. "
            f"Run /index-repo when convenient (blocks all search during indexing)."
        )
    return messages
