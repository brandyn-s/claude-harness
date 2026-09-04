#!/usr/bin/env python3
"""Digest-bound verdicts: a "tests passed" claim that expires when the tree changes.

A verdict ("the tests pass", "review clean") is evidence only for the exact
content it was measured on. Skills that cite one hours later are citing a tree
that may no longer exist. This tool binds each verdict to a content digest of
the working tree and answers ONE question: does the recorded verdict still
describe the tree in front of you?

    verdict-state.py record --plane tests --verdict pass|fail [--note TEXT] [--root DIR]
    verdict-state.py check  --plane tests [--root DIR]

`check` exits 0 and prints `fresh: <plane> pass @ <time>` only when a `pass`
verdict exists for the current digest; otherwise it exits 1 with a one-line
reason (no verdict / recorded fail / the files that changed since). It never
blocks anything by itself -- it is a tool skills call before claiming a result.

THE DIGEST is a sha256 over `{path: blob-id}` for every file the working tree
holds: the index ids from `git ls-files -s`, overlaid with `git hash-object` of
the worktree copy for every path `git diff` reports as modified or deleted, plus
every untracked non-ignored file (`git ls-files --others --exclude-standard`).
Any edit, addition or deletion of tracked, staged, or new content changes it.
Staging or committing does NOT: the index ids already encode staged content, so
`git diff --cached` adds nothing, and a commit moves no bytes. A verdict
therefore survives `git add` + `git commit` and dies on the next edit -- which
is exactly what "the tests passed on this code" means.

State lives in <repo>/.claude/verdicts.json (added to the repo's .gitignore when
one exists and does not already cover it) and is excluded from its own digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_REL = ".claude/verdicts.json"
MAX_NAMED = 5

# Repository resolution must come from `-C <root>` alone. An inherited GIT_DIR
# or GIT_WORK_TREE would silently point every read at a different repository.
_GIT_ENV = {
    k: v for k, v in os.environ.items()
    if k not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                 "GIT_OBJECT_DIRECTORY"}
}


class GitError(RuntimeError):
    pass


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            input=data, capture_output=True, check=False, env=_GIT_ENV,
        )
    except FileNotFoundError as exc:  # no git binary
        raise GitError("git is not installed or not on PATH") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
        raise GitError(f"git {args[0]}: {detail}")
    return proc.stdout


def _decode(path: bytes) -> str:
    return path.decode("utf-8", "surrogateescape")


def toplevel(root: Path) -> Path:
    return Path(_decode(_git(root, "rev-parse", "--show-toplevel").strip()))


def tree_state(root: Path) -> dict[str, str]:
    """Map every file the working tree holds to its git blob id (no odb writes)."""
    files: dict[bytes, bytes] = {}
    for rec in _git(root, "ls-files", "-s", "-z").split(b"\0"):
        if rec:
            meta, path = rec.split(b"\t", 1)
            files[path] = meta.split(b" ")[1]
    modified = _git(root, "diff", "--name-only", "-z").split(b"\0")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")

    to_hash: list[bytes] = []
    for path in [p for p in modified + untracked if p]:
        full = root / _decode(path)
        if full.is_symlink():
            target = os.fsencode(os.readlink(full))
            files[path] = _git(root, "hash-object", "--stdin", data=target).strip()
        elif full.is_file():
            to_hash.append(path)
        elif not full.exists():
            files.pop(path, None)  # deleted from the worktree
        # directories (submodules, embedded repos) keep their index entry; their
        # insides are not this repository's content.

    # One process for every regular file. --stdin-paths is newline-delimited,
    # so a path that itself contains a newline goes through argv instead.
    batch = [p for p in to_hash if b"\n" not in p]
    if batch:
        out = _git(root, "hash-object", "--stdin-paths", data=b"\n".join(batch) + b"\n")
        for path, oid in zip(batch, out.split(), strict=True):
            files[path] = oid
    for path in to_hash:
        if b"\n" in path:
            files[path] = _git(root, "hash-object", "--", _decode(path)).strip()

    files.pop(STATE_REL.encode(), None)  # never digest our own state file
    return {_decode(p): oid.decode() for p, oid in files.items()}


def digest_of(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(f"{files[path]} {path}\0".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def ensure_ignored(root: Path) -> None:
    """Append the state path to an existing .gitignore that does not cover it."""
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return
    probe = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", "--", STATE_REL],
        capture_output=True, check=False, env=_GIT_ENV,
    )
    if probe.returncode == 0:
        return
    text = gitignore.read_text(encoding="utf-8", errors="surrogateescape")
    if text and not text.endswith("\n"):
        text += "\n"
    gitignore.write_text(text + STATE_REL + "\n", encoding="utf-8", errors="surrogateescape")


def describe_changes(old: dict[str, str] | None, new: dict[str, str]) -> str:
    if not isinstance(old, dict):
        return "the tree (no file list was recorded)"
    changed = sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))
    shown = ", ".join(changed[:MAX_NAMED])
    more = len(changed) - MAX_NAMED
    return shown + (f" (+{more} more)" if more > 0 else "")


def cmd_record(args: argparse.Namespace) -> int:
    root = toplevel(args.root)
    ensure_ignored(root)  # before the digest: the .gitignore edit is itself a tree change
    files = tree_state(root)
    digest = digest_of(files)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state_path = root / STATE_REL
    state = load_state(state_path)
    state[args.plane] = {
        "digest": digest,
        "verdict": args.verdict,
        "note": args.note,
        "recorded_at": now,
        "files": files,
    }
    save_state(state_path, state)
    print(f"recorded: {args.plane} {args.verdict} @ {now} ({len(files)} files, digest {digest[:12]})")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = toplevel(args.root)
    entry = load_state(root / STATE_REL).get(args.plane)
    if not isinstance(entry, dict) or entry.get("verdict") not in ("pass", "fail"):
        print(f"no verdict recorded for plane '{args.plane}'"
              f" (record one: verdict-state.py record --plane {args.plane} --verdict pass|fail)")
        return 1
    when = entry.get("recorded_at", "?")
    files = tree_state(root)
    if digest_of(files) != entry.get("digest"):
        print(f"stale: {args.plane} {entry['verdict']} @ {when} predates changes to "
              f"{describe_changes(entry.get('files'), files)}")
        return 1
    if entry["verdict"] != "pass":
        print(f"fail: {args.plane} verdict was fail @ {when}; the tree is unchanged since")
        return 1
    print(f"fresh: {args.plane} pass @ {when}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record", help="bind a verdict to the current tree digest")
    record.add_argument("--verdict", choices=("pass", "fail"), required=True)
    record.add_argument("--note", default="", help="free text stored with the verdict")
    record.set_defaults(func=cmd_record)
    check = sub.add_parser("check", help="exit 0 iff a pass verdict matches the current tree")
    check.set_defaults(func=cmd_check)
    for sp in (record, check):
        sp.add_argument("--plane", required=True, help="what the verdict is about, e.g. tests")
        sp.add_argument("--root", type=Path, default=Path.cwd(),
                        help="any directory inside the git working tree (default: cwd)")
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except GitError as exc:
        print(f"verdict-state: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
