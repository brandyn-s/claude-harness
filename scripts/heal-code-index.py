#!/usr/bin/env python3
"""Reindex every stale / identity-broken codebase-memory-mcp project.

WHY THIS EXISTS
---------------
Before this, every index-freshness path in the harness only WARNED. The
SessionStart banner said "Run /index-repo <repo>" and then waited for a human
to do it. On 2026-08-04 that produced nine stale graphs, plus a `claude-hud`
index that had been sitting at 1 node / 0 edges with a broken git identity
since 01:39 -- effectively invisible to code search -- because a transient
failure during one index run was reported once and then never retried.

The server has its own auto-sync, but it only covers the project of the
CURRENT session. Nothing healed the other eighteen. This closes that gap: it
generalises auto-sync to the whole registry, out of band.

DESIGN NOTES
------------
* Classification is imported from `index_staleness.classify_entry`, the same
  function the SessionStart banner uses. Two copies would let the healer heal
  a different set than the banner reports -- a warning that never clears.
* Indexing goes through `codebase-memory-mcp-launch`, NOT the raw binary, so
  it inherits the launcher's Keychain key loading (VOYAGE_API_KEY for
  embeddings). No new credential handling is introduced here.
* `skip_report=true` on every call: without it the indexer writes
  ARCHITECTURE_REPORT.md into the repo root, dirtying every repo it touches.
* Single-instance via a pid lockfile. Seven concurrent Claude Code sessions
  is normal on this host, and they all start at once.
* SELF-VERIFYING: after healing it RE-CLASSIFIES and reports what is still
  broken. "The command exited 0" is not evidence the index is fresh.

Usage:
  heal-code-index.py                 # heal everything stale, then verify
  heal-code-index.py --dry-run       # list candidates, change nothing
  heal-code-index.py --json          # machine-readable summary on stdout

Exit codes: 0 nothing-to-do or all healed | 1 something still broken
            | 2 another healer holds the lock
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import index_staleness as ist
# Shared, CI-hardened liveness probe -- a hand-rolled os.kill(pid, 0) is
# wrong on Windows (see index_autoheal).
from session_start_modules.concurrent_session import _pid_alive

CACHE_DIR = Path.home() / ".cache" / "codebase-memory-mcp"
LOCK_PATH = CACHE_DIR / ".autoheal.lock"
STATUS_PATH = CACHE_DIR / "autoheal-status.json"

# A single reindex of the largest project here (~133k nodes) takes well under
# a minute; 10 minutes is a generous ceiling that still guarantees the healer
# cannot wedge forever holding the lock.
PER_REPO_TIMEOUT_SECS = 600
# A lock older than this is treated as abandoned even if the pid is somehow
# still present -- belt and braces against a wedged healer.
LOCK_MAX_AGE_SECS = 3600

IS_WINDOWS = sys.platform == "win32"


def _launcher() -> Path | None:
    """The MCP launcher, which exports Keychain keys then execs the binary.

    Falls back to the bare binary: indexing still works without
    VOYAGE_API_KEY, just with no embeddings (the server treats keys as
    optional), so a missing launcher degrades rather than fails.
    """
    candidates = [
        Path.home() / ".local" / "bin" / "codebase-memory-mcp-launch",
        Path.home() / ".local" / "bin" / "codebase-memory-mcp",
        Path.home() / "bin" / "codebase-memory-mcp.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def acquire_lock() -> bool:
    """True if we now hold the lock. Reclaims an abandoned lock.

    A lock whose owning pid is gone is stale by definition -- a healer killed
    mid-run must not block healing forever.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        try:
            data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            owner = int(data.get("pid", -1))
            started = float(data.get("started", 0))
        except (OSError, ValueError):
            owner, started = -1, 0.0
        age = time.time() - started
        if _pid_alive(owner) and age < LOCK_MAX_AGE_SECS:
            return False
        # Stale: fall through and overwrite.
    try:
        LOCK_PATH.write_text(
            json.dumps({"pid": os.getpid(), "started": time.time()}),
            encoding="utf-8",
        )
    except OSError:
        return False
    return True


def release_lock() -> None:
    try:
        if LOCK_PATH.exists():
            data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            if int(data.get("pid", -1)) == os.getpid():
                LOCK_PATH.unlink()
    except (OSError, ValueError):
        pass


def reindex(launcher: Path, repo_path: str) -> tuple[bool, str]:
    """Reindex one repo. Returns (ok, detail)."""
    payload = json.dumps({"repo_path": repo_path, "skip_report": True})
    try:
        r = subprocess.run(
            [str(launcher), "cli", "index_repository", payload],
            # cwd inside the repo: the CLI derives its *display* project name
            # from the working directory, so running from elsewhere prints a
            # misleading `db:` line (the write itself goes to the right DB).
            cwd=repo_path if Path(repo_path).is_dir() else None,
            capture_output=True,
            text=True,
            timeout=PER_REPO_TIMEOUT_SECS,
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout after {PER_REPO_TIMEOUT_SECS}s"
    except OSError as e:
        return False, f"spawn failed: {e}"
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit {r.returncode}"
        # Contention with a live MCP server is transient, not corruption.
        if "locked" in detail.lower() or "busy" in detail.lower():
            detail = f"transient DB contention: {detail}"
        return False, detail
    return True, "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="list candidates without reindexing")
    ap.add_argument("--json", action="store_true",
                    help="emit a machine-readable summary on stdout")
    args = ap.parse_args()

    def say(msg: str) -> None:
        if not args.json:
            print(msg, flush=True)

    candidates = ist.heal_candidates()
    if not candidates:
        say("index autoheal: nothing stale")
        if args.json:
            print(json.dumps({"healed": [], "failed": [], "remaining": []}))
        return 0

    if args.dry_run:
        for c in candidates:
            say(f"  would heal {c['name']}  ({c['reason']})")
        if args.json:
            print(json.dumps({"candidates": candidates}))
        return 0

    if not acquire_lock():
        say("index autoheal: another healer holds the lock; skipping")
        return 2

    launcher = _launcher()
    if launcher is None:
        release_lock()
        say("index autoheal: no codebase-memory-mcp binary found")
        return 1

    healed, failed = [], []
    started = time.time()
    try:
        for c in candidates:
            ok, detail = reindex(launcher, c["root_path"])
            label = ist._short(c["name"], c["root_path"])
            if ok:
                healed.append(label)
                say(f"  healed  {label}  ({c['reason']})")
            else:
                failed.append({"project": label, "error": detail})
                say(f"  FAILED  {label}: {detail}")
    finally:
        release_lock()

    # SELF-VERIFY. Exit codes say a command ran, not that the index is fresh;
    # re-classifying is the only thing that answers the actual question.
    remaining = [ist._short(c["name"], c["root_path"])
                 for c in ist.heal_candidates()]

    status = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_secs": round(time.time() - started, 1),
        "attempted": len(candidates),
        "healed": healed,
        "failed": failed,
        "remaining": remaining,
    }
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(status, indent=2), encoding="utf-8")
    except OSError:
        pass

    if args.json:
        print(json.dumps(status))
    else:
        say(
            f"index autoheal: {len(healed)} healed, {len(failed)} failed, "
            f"{len(remaining)} still stale ({status['elapsed_secs']}s)"
        )
    return 0 if not remaining else 1


if __name__ == "__main__":
    sys.exit(main())
