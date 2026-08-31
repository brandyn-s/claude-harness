#!/usr/bin/env python3
"""WorktreeRemove: snapshot uncommitted work before a worktree disappears.

WHY THIS SHAPE AND NOT A GATE
    The obvious design is "refuse removal when the worktree holds live work."
    That is NOT implementable. Per the hooks contract (code.claude.com/docs/en/hooks,
    "Exit code 2 behavior per event", read 2026-08-21):

        WorktreeRemove | Can block? No | Failures are logged in debug mode only

    and the event's own section adds that Claude Code "discards a WorktreeRemove
    hook's JSON output fields, such as systemMessage and continue." So there is no
    veto, no message to the user, and no way to make removal fail. An earlier
    proposal to use this event as a guard was refuted by that table.

    What IS available is the moment before the directory goes away. Upstream keeps
    regressing worktree cleanup into live directories -- #74386 closed 2026-08-17
    and #87547 / #88255 re-reported the same class on 08-18 and 08-20 -- so the
    reachable win is not prevention but RECOVERABILITY: capture dirty and untracked
    files, plus enough git identity to reconstruct, and leave them outside the tree
    being deleted.

CONTRACT
    stdin  : hook JSON, including `worktree_path` (the path WorktreeCreate returned)
    stdout : ignored by Claude Code
    exit   : ALWAYS 0. A non-zero exit is only debug-logged, and this hook must
             never be the reason cleanup misbehaves.

    Snapshots land in ~/.claude/worktree-snapshots/<utc>-<branch-or-dir>/ with a
    MANIFEST.txt naming the repo, branch, HEAD sha and every captured file.

INTERRUPTION: safe -- writes into a fresh timestamped directory and never mutates
the worktree. A kill mid-copy leaves a partial snapshot whose MANIFEST records
fewer files than were copied; nothing in the source tree is touched.
"""
import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

SNAP_ROOT = Path.home() / ".claude" / "worktree-snapshots"
MAX_TOTAL_BYTES = 64 * 1024 * 1024      # don't copy a build dir into ~
MAX_FILE_BYTES = 8 * 1024 * 1024
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             ".ruff_cache", ".pytest_cache", ".mypy_cache", "dist", "build"}


def _git(path, *args, timeout=10):
    """Run git in `path`; return stdout or None. Never raises."""
    try:
        r = subprocess.run(["git", "-C", str(path), *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _at_risk(worktree):
    """Return [(relpath, status)] for dirty + untracked files, or []."""
    out = _git(worktree, "status", "--porcelain=v1", "--untracked-files=all")
    if not out:
        return []
    rows = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        status, rel = line[:2], line[3:].strip()
        if " -> " in rel:                        # rename: keep the destination
            rel = rel.split(" -> ", 1)[1]
        rel = rel.strip('"')
        if any(part in SKIP_DIRS for part in Path(rel).parts):
            continue
        rows.append((rel, status))
    return rows


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    wt = payload.get("worktree_path") or payload.get("cwd")
    if not wt:
        return 0
    worktree = Path(wt)
    if not worktree.is_dir():
        return 0                                 # already gone; nothing to save

    at_risk = _at_risk(worktree)
    if not at_risk:
        return 0                                 # clean tree: nothing to lose

    branch = (_git(worktree, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    head = (_git(worktree, "rev-parse", "HEAD") or "").strip()
    origin = (_git(worktree, "config", "--get", "remote.origin.url") or "").strip()

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = (branch or worktree.name).replace("/", "-") or "worktree"
    dest = SNAP_ROOT / f"{stamp}-{label}"
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 0

    copied, skipped, total = [], [], 0
    for rel, status in at_risk:
        src = worktree / rel
        if not src.is_file():
            skipped.append((rel, status, "not a regular file"))
            continue
        try:
            size = src.stat().st_size
        except OSError:
            skipped.append((rel, status, "unstatable"))
            continue
        if size > MAX_FILE_BYTES:
            skipped.append((rel, status, f"{size}B > per-file cap"))
            continue
        if total + size > MAX_TOTAL_BYTES:
            skipped.append((rel, status, "total cap reached"))
            continue
        target = dest / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        except OSError as exc:
            skipped.append((rel, status, f"copy failed: {exc}"))
            continue
        copied.append((rel, status))
        total += size

    lines = [
        "# worktree-remove-snapshot",
        f"captured_utc   : {stamp}",
        f"worktree_path  : {worktree}",
        f"branch         : {branch or '(unknown)'}",
        f"head_sha       : {head or '(unknown)'}",
        f"origin_url     : {origin or '(none)'}",
        f"session_id     : {payload.get('session_id', '(none)')}",
        f"trigger_event  : {payload.get('hook_event_name', 'WorktreeRemove')}",
        f"files_copied   : {len(copied)}  ({total} bytes)",
        f"files_skipped  : {len(skipped)}",
        "",
        "# recover with:  cp -R <this dir>/<path> <a fresh worktree>/<path>",
        "",
        "## copied (git status code, path)",
    ]
    lines += [f"  {st}  {rel}" for rel, st in copied]
    if skipped:
        lines += ["", "## skipped"]
        lines += [f"  {st}  {rel}  -- {why}" for rel, st, why in skipped]
    try:
        (dest / "MANIFEST.txt").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8")
    except OSError:
        pass

    # stdout is discarded for this event; stderr reaches the debug log only.
    print(f"snapshotted {len(copied)} at-risk file(s) from {worktree} -> {dest}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                      # never break cleanup
        print(f"worktree-remove-snapshot: {exc}", file=sys.stderr)
        sys.exit(0)
