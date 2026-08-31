#!/usr/bin/env python3
"""Inventory every path that could be transmitted by /ship.

The committed lane is the merge-base diff from the selected remote base to
HEAD.  The local lane is the union of staged, unstaged, and untracked paths.
Keeping those lanes explicit prevents a clean-but-ahead branch from looking
empty and prevents a staged-only check from missing part of the payload.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Sequence


class InventoryError(RuntimeError):
    """Raised when the repository or requested base cannot be inspected."""


def _git(repo: Path, args: Sequence[str], *, nul: bool = False):
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise InventoryError(message or f"git {' '.join(args)} failed")
    if nul:
        return [
            item.decode("utf-8", errors="surrogateescape")
            for item in result.stdout.split(b"\0")
            if item
        ]
    return result.stdout.decode("utf-8", errors="replace").strip()


def _lines(repo: Path, *args: str) -> list[str]:
    output = _git(repo, args)
    return output.splitlines() if output else []


def _paths(repo: Path, *args: str) -> list[str]:
    return sorted(set(_git(repo, (*args, "-z", "--"), nul=True)))


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode in (0, 1):
        return result.returncode == 0
    message = result.stderr.decode("utf-8", errors="replace").strip()
    raise InventoryError(message or "git merge-base --is-ancestor failed")


def _resolve_optional_commit(repo: Path, value: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{value}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace").strip()


def build_inventory(
    repo: str | Path,
    base: str = "origin/main",
    *,
    session_start: str | None = None,
) -> dict[str, object]:
    """Return committed and local lanes plus their outgoing union."""

    repo_path = Path(repo).resolve()
    head_oid = _git(repo_path, ("rev-parse", "HEAD"))
    base_oid = _git(repo_path, ("rev-parse", base))
    merge_base_oid = _git(repo_path, ("merge-base", base, "HEAD"))

    ahead_commits = _lines(repo_path, "rev-list", "--reverse", f"{base}..HEAD")
    committed_paths = _paths(repo_path, "diff", "--name-only", f"{base}...HEAD")
    staged_paths = _paths(repo_path, "diff", "--cached", "--name-only")
    unstaged_paths = _paths(repo_path, "diff", "--name-only")
    untracked_paths = sorted(
        set(
            _git(
                repo_path,
                ("ls-files", "--others", "--exclude-standard", "-z"),
                nul=True,
            )
        )
    )
    worktree_paths = sorted(set(staged_paths + unstaged_paths + untracked_paths))
    all_paths = sorted(set(committed_paths + worktree_paths))

    resolved_session_start = None
    session_provenance = "UNVERIFIED"
    session_commits: list[str] = []
    pre_session_ahead_commits = list(ahead_commits)
    if session_start:
        candidate = _resolve_optional_commit(repo_path, session_start)
        if candidate and _is_ancestor(repo_path, candidate, head_oid):
            resolved_session_start = candidate
            session_provenance = "VERIFIED"
            session_candidates = set(
                _lines(repo_path, "rev-list", "--reverse", f"{candidate}..HEAD")
            )
            session_commits = [
                commit for commit in ahead_commits if commit in session_candidates
            ]
            session_set = set(session_commits)
            pre_session_ahead_commits = [
                commit for commit in ahead_commits if commit not in session_set
            ]

    return {
        "repo": str(repo_path),
        "base": base,
        "base_oid": base_oid,
        "merge_base_oid": merge_base_oid,
        "head_oid": head_oid,
        "ahead_commits": ahead_commits,
        "ahead_count": len(ahead_commits),
        "committed_paths": committed_paths,
        "staged_paths": staged_paths,
        "unstaged_paths": unstaged_paths,
        "untracked_paths": untracked_paths,
        "worktree_paths": worktree_paths,
        "all_paths": all_paths,
        "changed_file_count": len(all_paths),
        "commit_required": bool(worktree_paths),
        "clean_ahead": bool(ahead_commits) and not worktree_paths,
        "session_start_oid": resolved_session_start,
        "session_provenance": session_provenance,
        "session_commits": session_commits,
        "pre_session_ahead_commits": pre_session_ahead_commits,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Git working tree to inspect")
    parser.add_argument("--base", default="origin/main", help="Fetched target ref")
    parser.add_argument(
        "--session-start",
        help="Pre-write HEAD proven by the current session or worktree receipt",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    args = parser.parse_args(argv)

    try:
        inventory = build_inventory(
            args.repo, args.base, session_start=args.session_start
        )
    except InventoryError as exc:
        parser.error(str(exc))
    print(json.dumps(inventory, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
