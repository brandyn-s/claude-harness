"""Sync code-graph and code-search MCP server binaries to current main HEAD.

Idempotent. Safe to run anytime. Compares source commit time to the deployed
binary mtime; rebuilds + propagates only if source is newer.

What it does (platform-aware: Windows ~/bin/*.exe + .venv/Scripts;
macOS ~/.local/bin + .venv/bin):
  code-graph:
    - cd ~/Documents/GitHub/code-graph
    - if HEAD commit time > deployed binary mtime:
      - go build (static MinGW linking on Windows only)
      - rename-then-copy swap into the deploy path (rename-first is
        REQUIRED on macOS — in-place overwrite SIGKILLs, see
        rules/platform-constraints.md)
  code-search:
    - cd ~/Documents/GitHub/code-search
    - if HEAD commit time > venv install marker:
      - <venv python> -m pip install -e .

Notes:
  - The running MCP server processes loaded the OLD binary into memory.
    Restarting Claude Code is required to pick up newly-deployed binaries.
    This script reports when restart is needed.
  - Does NOT git pull — assumes the user has already pulled main if they
    want the latest. Builds from whatever HEAD is checked out.

Usage:
  python ~/.claude/scripts/sync-code-mcp.py             # check + sync if stale
  python ~/.claude/scripts/sync-code-mcp.py --check     # check only, no build
  python ~/.claude/scripts/sync-code-mcp.py --force     # rebuild even if fresh
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout/stderr so the report's Unicode arrow ("→") prints under
# Windows cp1252 without requiring PYTHONUTF8=1 in the caller's environment.
# reconfigure() is available on Python 3.7+ TextIOWrapper streams; guard for
# the case where stdout has been replaced with a non-reconfigurable stream
# (pipe, subprocess wrapper, test capture).
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
IS_WINDOWS = sys.platform == "win32"

CODE_GRAPH_REPO = Path.home() / "Documents" / "GitHub" / "code-graph"
# Windows host deployed to ~/bin/*.exe; macOS deploys to ~/.local/bin (the
# Keychain launcher at codebase-memory-mcp-launch execs this path).
CODE_GRAPH_DEPLOYED = (
    Path.home() / "bin" / "codebase-memory-mcp.exe"
    if IS_WINDOWS
    else Path.home() / ".local" / "bin" / "codebase-memory-mcp"
)

CODE_SEARCH_REPO = Path.home() / "Documents" / "GitHub" / "code-search"
CODE_SEARCH_VENV_PY = (
    CODE_SEARCH_REPO / ".venv" / "Scripts" / "python.exe"
    if IS_WINDOWS
    else CODE_SEARCH_REPO / ".venv" / "bin" / "python"
)


def _code_search_install_marker() -> Path:
    """Locate the editable-install RECORD, any version, both venv layouts."""
    if IS_WINDOWS:
        pattern = "Lib/site-packages/example_code_search-*.dist-info/RECORD"
    else:
        pattern = "lib/python*/site-packages/example_code_search-*.dist-info/RECORD"
    hits = sorted((CODE_SEARCH_REPO / ".venv").glob(pattern))
    if hits:
        return hits[-1]
    # Missing marker → file_mtime_unix returns None → treated as stale.
    return CODE_SEARCH_REPO / ".venv" / "INSTALL_MARKER_MISSING"


CODE_SEARCH_INSTALL_MARKER = _code_search_install_marker()


def run(cmd, cwd=None, env=None, timeout=300):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def head_commit_unix(repo: Path) -> int | None:
    if not (repo / ".git").exists():
        return None
    r = run(["git", "log", "-1", "--format=%ct", "HEAD"], cwd=repo, timeout=10)
    if r.returncode != 0:
        return None
    try:
        return int(r.stdout.strip())
    except (ValueError, AttributeError):
        return None


def file_mtime_unix(p: Path) -> int | None:
    if not p.exists():
        return None
    return int(p.stat().st_mtime)


def fmt_ts(unix_ts: int | None) -> str:
    if unix_ts is None:
        return "<missing>"
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def sync_code_graph(check_only: bool, force: bool) -> dict:
    head = head_commit_unix(CODE_GRAPH_REPO)
    deployed = file_mtime_unix(CODE_GRAPH_DEPLOYED)
    state = {
        "system": "code-graph",
        "source_repo": str(CODE_GRAPH_REPO),
        "head_commit_at": fmt_ts(head),
        "deployed_at": fmt_ts(deployed),
        "stale": False,
        "rebuilt": False,
        "swapped": False,
        "restart_needed": False,
        "errors": [],
    }
    if head is None:
        state["errors"].append(f"Cannot read HEAD commit time at {CODE_GRAPH_REPO}")
        return state
    if deployed is None or head > deployed:
        state["stale"] = True
    if force:
        state["stale"] = True

    if not state["stale"]:
        return state
    if check_only:
        return state

    # Windows needs the MinGW static-link flags (PR #98); macOS/clang links
    # cleanly with just the version stamp.
    version_proc = run(
        ["git", "describe", "--tags", "--always", "--dirty"],
        cwd=CODE_GRAPH_REPO,
    )
    version = version_proc.stdout.strip() or "dev"
    out_path = CODE_GRAPH_REPO / "bin" / ("codebase-memory-mcp.exe" if IS_WINDOWS else "codebase-memory-mcp")
    if IS_WINDOWS:
        ldflags = f"-extldflags '-static' -X main.version={version}"
    else:
        ldflags = f"-X main.version={version}"
    build = run(
        ["go", "build", "-ldflags", ldflags, "-o", str(out_path), "./cmd/codebase-memory-mcp/"],
        cwd=CODE_GRAPH_REPO,
        env={**__import__("os").environ, "CGO_ENABLED": "1"},
        timeout=600,
    )
    if build.returncode != 0:
        state["errors"].append(f"go build failed:\n{build.stderr or build.stdout}")
        return state
    state["rebuilt"] = True
    state["built_path"] = str(out_path)
    state["built_version"] = version

    # Swap via rename-then-copy. On Windows this permits replacing a running
    # .exe; on macOS it is REQUIRED to be rename-first — overwriting a Mach-O
    # in place invalidates the kernel's per-inode code-signature cache and
    # SIGKILLs both the copy target and any process running it (see
    # rules/platform-constraints.md FAILURE macos_in_place_binary_overwrite_
    # sigkill, 2026-06-11). rename moves the old inode aside; copy2 creates
    # a fresh inode at the deploy path.
    backup = CODE_GRAPH_DEPLOYED.with_name(CODE_GRAPH_DEPLOYED.name + f".old.{int(time.time())}")
    try:
        if CODE_GRAPH_DEPLOYED.exists():
            CODE_GRAPH_DEPLOYED.rename(backup)
        shutil.copy2(out_path, CODE_GRAPH_DEPLOYED)
        state["swapped"] = True
        state["backup"] = str(backup)
        state["restart_needed"] = True
    except OSError as exc:
        state["errors"].append(f"binary swap failed: {exc}")

    return state


def sync_code_search(check_only: bool, force: bool) -> dict:
    head = head_commit_unix(CODE_SEARCH_REPO)
    marker = file_mtime_unix(CODE_SEARCH_INSTALL_MARKER)
    state = {
        "system": "code-search",
        "source_repo": str(CODE_SEARCH_REPO),
        "head_commit_at": fmt_ts(head),
        "venv_install_at": fmt_ts(marker),
        "stale": False,
        "reinstalled": False,
        "restart_needed": False,
        "errors": [],
    }
    if head is None:
        state["errors"].append(f"Cannot read HEAD commit time at {CODE_SEARCH_REPO}")
        return state
    if not CODE_SEARCH_VENV_PY.exists():
        state["errors"].append(f"venv python missing: {CODE_SEARCH_VENV_PY}")
        return state
    if marker is None or head > marker:
        state["stale"] = True
    if force:
        state["stale"] = True

    if not state["stale"]:
        return state
    if check_only:
        return state

    install = run(
        [str(CODE_SEARCH_VENV_PY), "-m", "pip", "install", "-e", "."],
        cwd=CODE_SEARCH_REPO,
        timeout=600,
    )
    if install.returncode != 0:
        state["errors"].append(f"pip install -e . failed:\n{install.stderr or install.stdout}")
        return state
    state["reinstalled"] = True
    state["restart_needed"] = True
    return state


def report(states: list[dict]) -> int:
    any_restart = False
    any_error = False
    print("=== MCP Binary Sync Report ===")
    for s in states:
        print(f"\n[{s['system']}]")
        for k in ("source_repo", "head_commit_at", "deployed_at", "venv_install_at"):
            if k in s:
                print(f"  {k}: {s[k]}")
        if s.get("stale"):
            print("  state: STALE — source newer than deployed")
        else:
            print("  state: fresh")
        if s.get("rebuilt"):
            print(f"  built: {s.get('built_version', 'unknown')} → {s.get('built_path')}")
        if s.get("swapped"):
            print(f"  swapped → {CODE_GRAPH_DEPLOYED}  (backup: {s.get('backup')})")
        if s.get("reinstalled"):
            print(f"  reinstalled into venv")
        if s.get("restart_needed"):
            any_restart = True
            print("  restart_needed: YES (running MCP server still has old binary in memory)")
        for e in s.get("errors", []):
            any_error = True
            print(f"  ERROR: {e}")

    if any_restart:
        print("\n>>> Restart Claude Code to activate the new binaries in the running MCP servers.")
    elif all(not s.get("stale") for s in states):
        print("\nAll binaries match HEAD. No action needed.")
    return 1 if any_error else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Sync code-graph + code-search MCP binaries to current HEAD")
    p.add_argument("--check", action="store_true", help="Check staleness only; do not rebuild")
    p.add_argument("--force", action="store_true", help="Rebuild even if not stale")
    args = p.parse_args()

    states = [
        sync_code_graph(check_only=args.check, force=args.force),
        sync_code_search(check_only=args.check, force=args.force),
    ]
    return report(states)


if __name__ == "__main__":
    sys.exit(main())
