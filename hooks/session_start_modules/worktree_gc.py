"""Session-start worktree garbage collection.

Worktrees created by /work and skills accumulate: `git worktree remove` fails
on Windows file locks (a .pyc handle, AV scan) and nothing pruned them.
2026-05-29 root-cause analysis found 20 worktrees in ~/.claude.

Conservative by design:
  1. `git worktree prune` — drop metadata for worktrees whose directory is
     already gone (always safe, fast).
  2. For worktrees whose branch is [gone] (PR squash-merged + remote-deleted),
     attempt `git worktree remove --force`, TOLERATING lock failures. A locked
     worktree is one another session may still be holding — leaving it is the
     correct outcome (the lock failure protects active sessions).

Never touches worktrees on live branches (unmerged work) or the main worktree.
With heavy concurrency (multiple sessions), only [gone]-branch worktrees — whose
PR already merged — are candidates, so an active session's worktree is safe.
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Repos that accumulate worktrees (the /work + skill hot paths).
_REPOS = [
    Path.home() / ".claude",
    Path.home() / "Documents" / "knowledge-base",
]

# Throttle the expensive pass (fetch --prune + remove) to once per window so it
# doesn't add latency to every session start. The fast metadata `git worktree
# prune` still runs every time. Stamp lives in the OS temp dir — NOT in any
# repo — so it can never re-introduce the dirty-tree problem this whole arc
# fixes (step 1, gitignore).
_STAMP = Path(tempfile.gettempdir()) / "claude-worktree-gc.stamp"
_THROTTLE_SECS = 6 * 3600


def _expensive_pass_due() -> bool:
    """True if the fetch+remove pass hasn't run within the throttle window."""
    try:
        if _STAMP.exists() and (time.time() - _STAMP.stat().st_mtime) < _THROTTLE_SECS:
            return False
    except Exception:
        pass
    return True


def _touch_stamp() -> None:
    try:
        _STAMP.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


def _git(repo, args, timeout=20):
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def _gone_branches(repo) -> set:
    """Local branches whose upstream was deleted ([gone]) = merged + remote-pruned."""
    r = _git(repo, ["for-each-ref", "--format=%(refname:short) %(upstream:track)",
                    "refs/heads/"])
    gone = set()
    if r.returncode != 0:
        return gone
    for line in r.stdout.splitlines():
        if "[gone]" in line.lower():
            gone.add(line.split(" ", 1)[0])
    return gone


def _parse_worktrees(repo):
    """Return [(path, branch)] from `git worktree list --porcelain`.

    branch is None for the main worktree's detached entries or bare repos.
    """
    r = _git(repo, ["worktree", "list", "--porcelain"])
    out = []
    if r.returncode != 0:
        return out
    path = branch = None
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
            branch = None
        elif line.startswith("branch "):
            branch = line[len("branch "):].replace("refs/heads/", "")
        elif line == "":
            if path:
                out.append((path, branch))
            path = branch = None
    if path:
        out.append((path, branch))
    return out


def _prune_one_repo(repo: Path, do_expensive: bool = True) -> list:
    warnings: list = []
    repo = Path(repo)
    if not (repo / ".git").exists():
        return warnings
    try:
        _git(repo, ["worktree", "prune"])  # fast metadata cleanup, always safe
        if not do_expensive:
            return warnings
        # Populate [gone] markers for merged-and-deleted branches. Bounded;
        # tolerate offline / slow networks (this is opportunistic cleanup).
        try:
            _git(repo, ["fetch", "--prune", "origin"], timeout=20)
        except Exception:
            pass
        gone = _gone_branches(repo)
        if not gone:
            return warnings
        main_path = str(repo).replace("\\", "/").rstrip("/")
        removed, stuck = 0, []
        for wt_path, wt_branch in _parse_worktrees(repo):
            norm = wt_path.replace("\\", "/").rstrip("/")
            if norm == main_path or not wt_branch:
                continue  # main worktree or detached — never touch
            if wt_branch not in gone:
                continue  # live branch (unmerged work) — keep
            rm = _git(repo, ["worktree", "remove", "--force", wt_path], timeout=15)
            if rm.returncode == 0:
                removed += 1
            else:
                stuck.append(Path(wt_path).name)
        if removed:
            warnings.append(
                f"[worktree-gc:{repo.name}] removed {removed} merged-branch "
                f"worktree(s)."
            )
        if stuck:
            warnings.append(
                f"[worktree-gc:{repo.name}] {len(stuck)} worktree(s) kept (locked "
                f"or in use): {', '.join(stuck[:5])}. Retry once locks clear."
            )
    except Exception:
        pass  # never block session start
    return warnings


def prune_worktrees() -> list:
    """Prune dead + merged-branch worktrees across the hot-path repos.

    The fast metadata prune runs every session; the fetch+remove pass is
    throttled to once per _THROTTLE_SECS so it doesn't add latency to every
    session start.

    INTERRUPTION: safe. Each `git worktree remove` is atomic; a killed worker
    leaves the worktree in place (the conservative outcome). No partial state.
    """
    due = _expensive_pass_due()
    warnings: list = []
    for repo in _REPOS:
        warnings.extend(_prune_one_repo(repo, do_expensive=due))
    if due:
        _touch_stamp()
    return warnings
