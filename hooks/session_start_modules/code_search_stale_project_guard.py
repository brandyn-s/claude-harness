"""Detect and delete bogus semantic-search project entries at SessionStart.

The semantic-search MCP server registers a project from its working directory
on startup. When the server's CWD is the user's home directory, root, or
a system directory, this creates a "project" entry that will trigger
endless full-index attempts of huge unindexable trees (~/.cache,
AppData, Documents, etc.), blocking all search requests with the
harness returning `-32001: user-cancel` while the server is stuck.

This module audits ~/.claude_code_search/projects/* on SessionStart,
detects entries with project_path matching forbidden patterns (home dir,
root, Windows system dirs, .cache, AppData), and deletes them. The
deletion is safe — these projects never succeed at indexing and only
consume the server's reindex slot.

INCIDENT 2026-05-13: you_8bbeb258 entry created with
project_path=C:\\Users\\you. Across 8 hours, 4 zombie
search-server processes accumulated, each stuck trying to full-index
the entire home directory. Every parallel search call returned
-32001:user-cancel because the server was busy. /mcp reconnect spawned
new servers that immediately re-created the same entry from CWD.

Companion to mcp_zombie_cleanup module: zombie_cleanup kills the
processes; this module deletes the bogus project entry that caused them
to hang in the first place.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude_code_search" / "projects"


def _forbidden_paths() -> tuple[set[Path], set[Path]]:
    """Return (exact_match_only, scope_anywhere) sets of forbidden paths.

    `exact_match_only` — project_path must EQUAL one of these to be
        rejected. Children are fine (~/code/foo is a legit project even
        though its parent ~/ is in this set).
    `scope_anywhere` — project_path EQUAL OR INSIDE any of these is
        rejected. Used for system dirs and cache dirs where any subpath
        is a wrong project root.
    """
    exact = {Path.home(), Path.home().parent}

    if sys.platform == "win32":
        exact.add(Path("C:/"))
        scope = {
            Path.home() / "AppData",
            Path.home() / ".cache",
            Path.home() / ".npm",
            Path("C:/Windows"),
            Path("C:/Program Files"),
            Path("C:/Program Files (x86)"),
            Path("C:/ProgramData"),
        }
    else:
        exact.add(Path("/"))
        scope = {
            Path("/etc"),
            Path("/var"),
            Path("/usr"),
            Path("/opt"),
            Path.home() / ".cache",
            Path.home() / ".npm",
        }

    def _safe_resolve(paths: set[Path]) -> set[Path]:
        out: set[Path] = set()
        for p in paths:
            try:
                out.add(p.resolve())
            except OSError:
                pass
        return out

    return _safe_resolve(exact), _safe_resolve(scope)


def _is_forbidden(
    project_path: str,
    exact_set: set[Path],
    scope_set: set[Path],
) -> bool:
    """Return True if project_path should be deleted.

    Two-tier check:
      1. Exact match against exact_set (home dir, drive root, etc.)
      2. Equal-or-inside check against scope_set (system dirs, .cache,
         AppData — every subpath of these is wrong)
    """
    if not project_path:
        return False
    try:
        resolved = Path(project_path).resolve()
    except (OSError, ValueError):
        return False

    if resolved in exact_set:
        return True

    for bad in scope_set:
        try:
            resolved.relative_to(bad)
            return True
        except ValueError:
            continue
    return False


def _scan_projects(
    projects_dir: Path,
    exact_set: set[Path],
    scope_set: set[Path],
) -> list[tuple[Path, str]]:
    """Return [(project_dir, project_path), ...] for entries to delete."""
    if not projects_dir.exists():
        return []
    bogus: list[tuple[Path, str]] = []
    for proj_dir in projects_dir.iterdir():
        if not proj_dir.is_dir():
            continue
        info_file = proj_dir / "project_info.json"
        if not info_file.exists():
            continue
        try:
            with open(info_file, "r", encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        project_path = info.get("project_path", "")
        if _is_forbidden(project_path, exact_set, scope_set):
            bogus.append((proj_dir, project_path))
    return bogus


def _delete_project(proj_dir: Path) -> tuple[bool, str | None]:
    """Delete a project directory. Returns (success, error_message)."""
    try:
        shutil.rmtree(proj_dir)
        return True, None
    except OSError as e:
        return False, str(e)


def cleanup_stale_projects() -> list[str]:
    """Scan and delete bogus semantic-search project entries.

    Returns list of warning messages for the SessionStart summary.
    Empty list if nothing found.
    """
    messages: list[str] = []
    exact_set, scope_set = _forbidden_paths()
    bogus = _scan_projects(PROJECTS_DIR, exact_set, scope_set)
    if not bogus:
        return messages
    for proj_dir, project_path in bogus:
        ok, err = _delete_project(proj_dir)
        if ok:
            messages.append(
                f"semantic-search registry: deleted bogus project entry {proj_dir.name} "
                f"(project_path={project_path!r} - home/root/system dir, "
                f"would block reindex)"
            )
        else:
            messages.append(
                f"semantic-search registry: tried to delete bogus project entry "
                f"{proj_dir.name} (project_path={project_path!r}) but failed: "
                f"{err}. Likely a running MCP holds the file lock - restart "
                f"Claude Code or run /mcp."
            )
    return messages
