"""Warn at SessionStart when code-graph or code-search MCP binaries are stale.

Two staleness shapes detected:

  (a) Local HEAD > deployed binary: source pulled but not rebuilt.
      Run `python ~/.claude/scripts/sync-code-mcp.py` to rebuild + swap.

  (b) origin/main > local HEAD: upstream PRs merged but local checkout
      hasn't pulled. Run `git pull` (then sync-code-mcp.py + restart).
      Added 2026-05-14 (Path E of the codebase-memory gap-closure plan)
      after the 2026-05-13 PSM tool-comparison battery surfaced that
      PR #308 had merged on origin but ~/bin/codebase-memory-mcp.exe
      was stale because local main hadn't been pulled, the user
      didn't know to pull, and the running MCP returned the wrong
      answers for ~24 hours.

Both checks are offline (use locally-cached refs; no network). If
`.git/FETCH_HEAD` is older than FETCH_STALE_SECONDS, the (b) warning
includes a "consider git fetch first" hint because the locally-cached
origin/main itself may be behind. (b) doesn't fire when origin/main
isn't tracked locally — rare but possible in fresh clones.

Self-healing: returns nothing once both rebuild and pull are current
(and the user restarts Claude Code).

Noise gate 2 (2026-08-04): the (b) upstream-ahead warning is suppressed when
origin/main and HEAD have IDENTICAL TREES. Our repos squash-merge, so a merged
branch's content reaches main under a new sha with a later timestamp and the
branch tip is never an ancestor -- meaning a checkout parked on a just-merged
branch reads as "behind" forever with nothing to pull. Content equality is the
only signal that survives a squash merge.

Noise gate (2026-07-05): the (a) rebuild-needed warning is suppressed when
every commit newer than the deployed artifact touches only non-shipped
paths (tests, docs, CI config). Incident: a test-only commit (c71e1d5,
tool_output_invariants_test.go) made the banner recommend a rebuild + full
Claude Code restart for a binary that was functionally identical to HEAD.
Unknown git state fails toward showing the warning.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
IS_WINDOWS = sys.platform == "win32"

CODE_GRAPH_REPO = Path.home() / "Documents" / "GitHub" / "code-graph"
# Windows host deployed to ~/bin/*.exe; macOS deploys to ~/.local/bin
# (execed by the Keychain launcher codebase-memory-mcp-launch).
CODE_GRAPH_DEPLOYED = (
    Path.home() / "bin" / "codebase-memory-mcp.exe"
    if IS_WINDOWS
    else Path.home() / ".local" / "bin" / "codebase-memory-mcp"
)

CODE_SEARCH_REPO = Path.home() / "Documents" / "GitHub" / "code-search"


def _code_search_install_marker() -> Path | None:
    """Newest dist-info RECORD across platform venv layouts.

    Windows venvs use .venv/Lib/site-packages; POSIX uses
    .venv/lib/python3.X/site-packages. Version-agnostic glob — the old
    hardcoded example_code_search-0.2.0 path was a second rot vector
    (any version bump would have re-broken the check)."""
    candidates = list(CODE_SEARCH_REPO.glob(
        ".venv/Lib/site-packages/example_code_search-*.dist-info/RECORD"))
    candidates += list(CODE_SEARCH_REPO.glob(
        ".venv/lib/python*/site-packages/example_code_search-*.dist-info/RECORD"))
    existing = [p for p in candidates if p.is_file()]
    if not existing:
        return None
    try:
        return max(existing, key=lambda p: p.stat().st_mtime)
    except OSError:
        return None

# If .git/FETCH_HEAD hasn't been touched in >FETCH_STALE_SECONDS, the
# locally-cached origin/main ref may itself be behind upstream and the
# upstream-ahead check could miss a recent merge. 86400 (1 day) balances
# noise vs miss-rate: tighter → more "consider fetching" hints in active
# sessions; looser → multi-day stale fetches silently mask real merges.
FETCH_STALE_SECONDS = 86400


def _head_commit_unix(repo: Path) -> int | None:
    if not (repo / ".git").exists():
        return None
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return None
        return int(r.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def _origin_main_commit_unix(repo: Path) -> int | None:
    """Commit time of origin/main as known to the local clone. Uses
    the locally-cached ref; does NOT fetch (no network call). Returns
    None when origin/main isn't tracked locally (rare; possible in
    fresh clones without a default branch tracked).
    """
    if not (repo / ".git").exists():
        return None
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "origin/main"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode != 0:
            return None
        return int(r.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def _fetch_head_age_seconds(repo: Path) -> int | None:
    """Seconds since .git/FETCH_HEAD was last modified. Approximates
    elapsed time since the last `git fetch` (or any operation that
    refreshes remote refs). Returns None when FETCH_HEAD doesn't exist.
    """
    fh = repo / ".git" / "FETCH_HEAD"
    if not fh.exists():
        return None
    try:
        return int(time.time() - fh.stat().st_mtime)
    except OSError:
        return None


def _file_mtime_unix(p: Path) -> int | None:
    if not p.exists():
        return None
    try:
        return int(p.stat().st_mtime)
    except OSError:
        return None


# Paths that never affect the deployed artifact. A commit touching ONLY
# these cannot make the built binary / installed venv stale. Anything NOT
# matched counts as shipped (conservative: Makefile, go.mod, source all
# warn). Directory names match at any depth; extensions match anywhere.
_NON_SHIPPED_RE = re.compile(
    r"(^|/)(docs|testdata|tests|fixtures|bench|\.github)/"
    r"|_test\.(go|py)$"
    r"|\.md$"
    # Repo-GOVERNANCE metadata: tracked in the tree, never compiled into or
    # packaged with the artifact. Added 2026-08-04 after CODEOWNERS slipped
    # through. A rename commit touched only .github/workflows/* (already
    # covered by the .github/ clause) and CODEOWNERS -- which sits at the
    # repo ROOT with no directory prefix and no extension, so no clause
    # matched it, one path counted as "shipped", and the banner demanded a
    # rebuild + full Claude Code restart for a binary that was behaviourally
    # identical to HEAD. Root-anchored and end-anchored so these can never
    # match a source path that merely CONTAINS the word.
    # Extension group is restricted to DOC extensions on purpose: a bare
    # `(\.[A-Za-z0-9]+)?$` also matches CODEOWNERS.go / LICENSE.go, which
    # would suppress a real source change. Caught by the known-negative
    # control on 2026-08-04, not by reading the regex.
    r"|(^|/)(CODEOWNERS|LICENSE|COPYING|NOTICE|AUTHORS|MAINTAINERS)"
    r"(\.(txt|md|rst))?$"
    r"|(^|/)\.(gitignore|gitattributes|gitmodules|editorconfig|dockerignore)$"
    r"|(^|/)(\.pre-commit-config\.ya?ml|renovate\.json|\.mergify\.ya?ml)$"
)


def _shipped_paths_changed_since(repo: Path, since_unix: int) -> bool | None:
    """True if any commit with commit time after `since_unix` touches a
    shipped path; False when every such commit touches only non-shipped
    paths (tests/docs/CI); None when git can't answer or returns nothing
    (callers must fail toward showing the warning on None).
    """
    from datetime import datetime, timezone
    since = datetime.fromtimestamp(since_unix, tz=timezone.utc).isoformat()
    try:
        r = subprocess.run(
            ["git", "log", f"--since={since}", "--name-only", "--format="],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    paths = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    if not paths:
        # head > artifact mtime but no commits found in the window —
        # clock skew or --since edge; can't confirm test-only.
        return None
    return any(not _NON_SHIPPED_RE.search(p) for p in paths)


def _trees_identical(repo: Path, rev_a: str, rev_b: str) -> bool:
    """True when two revisions have byte-identical trees.

    THE SQUASH-MERGE PROBLEM. Every repo in our orgs squash-merges, so a
    merged feature branch's content lands on main under a NEW sha with a
    LATER commit timestamp. The branch tip is therefore never an ancestor of
    main, and `origin/main` always looks "newer" than a checkout parked on
    the branch that was just merged -- permanently, with nothing to pull.
    Neither ancestry (`merge-base --is-ancestor`) nor timestamps can tell
    that state apart from a genuine missing pull. Only CONTENT can.

    Fails toward False (i.e. toward SHOWING the warning) when git cannot
    answer, matching this module's existing unknown-state convention.
    """
    try:
        r = subprocess.run(
            ["git", "diff", "--quiet", rev_a, rev_b],
            cwd=str(repo),
            capture_output=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    # --quiet: 0 == no differences, 1 == differences, >1 == error.
    return r.returncode == 0


def _check_upstream_ahead(repo: Path, repo_label: str) -> str | None:
    """Return a single warning string if origin/main is ahead of HEAD,
    else None. Includes a 'consider git fetch first' hint when the
    locally-cached origin/main ref itself is stale (FETCH_HEAD older
    than FETCH_STALE_SECONDS).
    """
    head = _head_commit_unix(repo)
    origin = _origin_main_commit_unix(repo)
    if head is None or origin is None:
        return None
    if origin <= head:
        return None
    # Timestamp says behind -- but on a squash-merge repo that is also what a
    # just-merged branch looks like forever. Ask the only question that can
    # separate the two: is there any CONTENT upstream we do not have?
    # (2026-08-04: code-graph sat on chore/github-rename-you-s after
    # PR #426 squash-merged it; origin/main was 6 minutes "newer" and the
    # tree diff was empty. The banner demanded a pull for zero content.)
    if _trees_identical(repo, "origin/main", "HEAD"):
        return None
    from datetime import datetime, timezone
    head_str = datetime.fromtimestamp(head, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    origin_str = datetime.fromtimestamp(origin, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    fetch_hint = ""
    fetch_age = _fetch_head_age_seconds(repo)
    if fetch_age is None or fetch_age > FETCH_STALE_SECONDS:
        hours = fetch_age // 3600 if fetch_age is not None else None
        age_str = f"{hours}h ago" if hours is not None else "unknown"
        fetch_hint = (
            f" Local origin/main ref last refreshed {age_str}; "
            f"consider `git fetch origin main` first to confirm the "
            f"upstream-ahead state is current."
        )

    return (
        f"MCP UPSTREAM AHEAD: {repo_label} origin/main ({origin_str}) "
        f"is ahead of local HEAD ({head_str}). New PRs have merged that "
        f"the local checkout hasn't pulled — the deployed MCP binary is "
        f"behind even if its rebuild status looks clean. Run "
        f"`cd {repo} && git pull origin main && python ~/.claude/scripts/"
        f"sync-code-mcp.py`, then restart Claude Code.{fetch_hint}"
    )


def _registered_mcp_server_names() -> set[str] | None:
    """MCP server names registered for this host, from ~/.claude.json
    (top-level `mcpServers` plus any per-project `mcpServers`).

    Gates staleness warnings on whether the server actually runs here.
    After code-search/code-graph were consolidated into codebase-memory-mcp
    (macOS), the old per-server clones linger on disk but run nothing — their
    on-disk staleness is not load-bearing and must not warn. Returns None when
    the config can't be read; callers then do NOT suppress (fail toward
    showing the warning, preserving pre-gate behavior).
    """
    import json

    cfg = Path.home() / ".claude.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    names: set[str] = set()
    top = data.get("mcpServers")
    if isinstance(top, dict):
        names.update(top.keys())
    projects = data.get("projects")
    if isinstance(projects, dict):
        for pcfg in projects.values():
            if isinstance(pcfg, dict):
                pms = pcfg.get("mcpServers")
                if isinstance(pms, dict):
                    names.update(pms.keys())
    return names


def check_mcp_binary_staleness() -> list[str]:
    """Return list of warning strings; empty when binaries match HEAD
    AND local HEAD matches origin/main on both repos.

    Emits up to four warnings (two per repo): one for
    HEAD-vs-deployed-binary mismatch (rebuild needed), one for
    origin/main-vs-HEAD mismatch (pull needed).
    """
    warnings: list[str] = []

    # Gate each repo's checks on its MCP server actually being registered on
    # this host. After code-search/code-graph were consolidated into
    # codebase-memory-mcp (macOS), the old clones linger on disk but run no
    # server — their on-disk staleness is not load-bearing. Unknown config
    # (None) -> fail toward showing the warning (don't suppress).
    registered = _registered_mcp_server_names()

    def _is_active(*aliases: str) -> bool:
        return registered is None or any(a in registered for a in aliases)

    # code-graph (deployed as the consolidated codebase-memory-mcp on macOS)
    cg_active = _is_active("code-graph", "codebase-memory-mcp")
    head = _head_commit_unix(CODE_GRAPH_REPO) if cg_active else None
    deployed = _file_mtime_unix(CODE_GRAPH_DEPLOYED)
    if head is not None and deployed is None:
        # Fail-honest: no artifact means we CANNOT determine staleness —
        # this is a first-deploy/migration state, not evidence of old code.
        warnings.append(
            f"MCP NOT DEPLOYED (this machine): code-graph source is present "
            f"but no built binary exists at {CODE_GRAPH_DEPLOYED}. If the "
            f"code-graph MCP server is configured here it cannot be running "
            f"current code. Run `python ~/.claude/scripts/sync-code-mcp.py` "
            f"to build for this platform (first deploy)."
        )
    elif (
        head is not None
        and head > deployed
        # Test/docs/CI-only deltas don't make the binary stale; None
        # (git couldn't answer) fails toward warning.
        and _shipped_paths_changed_since(CODE_GRAPH_REPO, deployed) is not False
    ):
        from datetime import datetime, timezone
        head_str = datetime.fromtimestamp(head, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        deployed_str = datetime.fromtimestamp(deployed, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        warnings.append(
            f"MCP STALE: code-graph deployed binary at {CODE_GRAPH_DEPLOYED} "
            f"(built {deployed_str}) is older than source HEAD ({head_str}). "
            f"The running MCP server has the OLD code. Run "
            f"`python ~/.claude/scripts/sync-code-mcp.py` to rebuild + swap, "
            f"then restart Claude Code."
        )

    # code-graph: upstream-ahead check (gated)
    upstream_warning = (
        _check_upstream_ahead(CODE_GRAPH_REPO, "code-graph") if cg_active else None
    )
    if upstream_warning is not None:
        warnings.append(upstream_warning)

    # code-search (not a separate server on macOS post-consolidation)
    cs_active = _is_active("code-search")
    head = _head_commit_unix(CODE_SEARCH_REPO) if cs_active else None
    marker_path = _code_search_install_marker()
    marker = _file_mtime_unix(marker_path) if marker_path else None
    if head is not None and marker is None:
        warnings.append(
            f"MCP NOT DEPLOYED (this machine): code-search source is present "
            f"but no installed venv package found under "
            f"{CODE_SEARCH_REPO}/.venv (checked both Windows and POSIX "
            f"layouts). Run `python ~/.claude/scripts/sync-code-mcp.py` to "
            f"install for this platform (first deploy)."
        )
    elif (
        head is not None
        and head > marker
        and _shipped_paths_changed_since(CODE_SEARCH_REPO, marker) is not False
    ):
        from datetime import datetime, timezone
        head_str = datetime.fromtimestamp(head, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        marker_str = datetime.fromtimestamp(marker, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        warnings.append(
            f"MCP STALE: code-search venv install at {CODE_SEARCH_REPO}/.venv "
            f"(installed {marker_str}) is older than source HEAD ({head_str}). "
            f"The running MCP server imported OLD modules. Run "
            f"`python ~/.claude/scripts/sync-code-mcp.py` to reinstall, "
            f"then restart Claude Code."
        )

    # code-search: upstream-ahead check (gated)
    upstream_warning = (
        _check_upstream_ahead(CODE_SEARCH_REPO, "code-search") if cs_active else None
    )
    if upstream_warning is not None:
        warnings.append(upstream_warning)

    return warnings
