#!/usr/bin/env python3
"""How far a private overlay has drifted from the harness it vendors.

THE CONTRACT (docs/consuming-from-a-private-overlay.md)
    A private overlay -- an organisation's own Claude Code configuration -- vendors
    this repository's CORE PATHS verbatim at a pinned commit and records the pin in
    UPSTREAM.json at its root:

        {"repo": "https://github.com/brandyn-s/claude-harness",
         "version": "1.0.0",
         "commit": "<40-hex sha>",
         "paths": ["hooks/", "rules/", "manifests/", "scripts/", "bin/", "profiles/", "contracts/"],
         "overrides": ["hooks/protected-repos.json"]}

    Code flows one way: from the public core into the overlay, mechanically. A
    change an overlay needs in a core file is an upstream pull request (after the
    residue gate), not a local edit -- a local edit is a fork that stops receiving
    fixes. `overrides` names the files an overlay edits ON PURPOSE (data files
    whose shipped default is empty); they are reported, never failed.

WHAT THIS TOOL DOES
    Compares the blob SHA of every file under the vendored paths in THIS tree
    (the overlay, as committed) with the same path at the pinned upstream commit,
    and, when the upstream default branch is reachable, with its tip:

        identical         same blob as the pin
        modified          differs from the pin and is not an override   <- the fork
        override          differs from the pin and is listed in overrides
        only-downstream   under a core path, absent upstream (an unlisted overlay file)
        only-upstream     at the pin, missing here (a file the vendoring dropped)
        behind            files that changed upstream between the pin and the tip

    --check exits 1 when any file is `modified` or `only-upstream`. `behind` is
    information (how much you are missing), not failure: staying pinned is a
    choice, forking is a mistake.

WHERE THE UPSTREAM OBJECTS COME FROM
    --upstream-dir PATH   a local clone of the harness (fastest; offline)
    --fetch               `git fetch <repo> <commit>` (and the default branch) into
                          this repository's object store, then read from there
    neither               use whatever this repository already has (a previous
                          --fetch, or the harness added as a remote)

    Nothing is written to the working tree. No network without --fetch.

USAGE
    python3 bin/upstream-check.py                    # report
    python3 bin/upstream-check.py --check            # gate (CI in the overlay)
    python3 bin/upstream-check.py --fetch --check
    python3 bin/upstream-check.py --json
    python3 bin/upstream-check.py --downstream /path/to/overlay --upstream-dir /path/to/harness
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

UPSTREAM_FILE = "UPSTREAM.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout


def _git_ok(args: list[str], cwd: Path) -> bool:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True).returncode == 0


def load_pin(downstream: Path) -> dict:
    path = downstream / UPSTREAM_FILE
    try:
        pin = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"upstream-check: no {UPSTREAM_FILE} at {downstream} ({exc}); this tree is not a pinned overlay")
    except ValueError as exc:
        raise SystemExit(f"upstream-check: {path} is not valid JSON: {exc}")
    for key in ("repo", "commit", "paths"):
        if key not in pin:
            raise SystemExit(f"upstream-check: {UPSTREAM_FILE} lacks {key!r}")
    if not SHA_RE.match(str(pin["commit"])):
        raise SystemExit(f"upstream-check: commit must be a full 40-hex sha, got {pin['commit']!r}")
    if not isinstance(pin["paths"], list) or not pin["paths"]:
        raise SystemExit(f"upstream-check: {UPSTREAM_FILE} paths must be a non-empty list")
    pin.setdefault("overrides", [])
    pin.setdefault("branch", "main")
    return pin


def tree_blobs(repo: Path, rev: str, paths: list[str]) -> dict[str, str]:
    """path -> blob sha for every file under `paths` at `rev`."""
    out: dict[str, str] = {}
    listing = _git(["ls-tree", "-r", rev, "--", *paths], repo)
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and parts[1] == "blob":
            out[path] = parts[2]
    return out


def resolve_upstream(downstream: Path, pin: dict, upstream_dir: Path | None, fetch: bool) -> tuple[Path, str, str | None]:
    """(repo to read upstream objects from, pin rev, tip rev or None)."""
    commit = pin["commit"]
    branch = pin.get("branch", "main")
    if upstream_dir is not None:
        repo = upstream_dir
        if not _git_ok(["cat-file", "-e", f"{commit}^{{commit}}"], repo):
            raise SystemExit(f"upstream-check: {upstream_dir} does not contain the pinned commit {commit[:12]}")
        for tip in (f"origin/{branch}", branch, "HEAD"):
            if _git_ok(["rev-parse", "--verify", "--quiet", tip], repo):
                return repo, commit, _git(["rev-parse", tip], repo).strip()
        return repo, commit, None
    repo = downstream
    if fetch:
        subprocess.run(["git", "fetch", "--quiet", pin["repo"], commit], cwd=str(repo), check=True)
        tip = None
        proc = subprocess.run(["git", "fetch", "--quiet", pin["repo"], branch], cwd=str(repo), capture_output=True, text=True)
        if proc.returncode == 0:
            tip = _git(["rev-parse", "FETCH_HEAD"], repo).strip()
        return repo, commit, tip
    if not _git_ok(["cat-file", "-e", f"{commit}^{{commit}}"], repo):
        raise SystemExit(f"upstream-check: the pinned commit {commit[:12]} is not in this repository; "
                         f"pass --fetch or --upstream-dir")
    tip = None
    for ref in (f"harness/{branch}", f"upstream/{branch}"):
        if _git_ok(["rev-parse", "--verify", "--quiet", ref], repo):
            tip = _git(["rev-parse", ref], repo).strip()
            break
    return repo, commit, tip


def compare(downstream: Path, pin: dict, upstream_repo: Path, pin_rev: str, tip_rev: str | None) -> dict:
    paths = [p.rstrip("/") for p in pin["paths"]]
    overrides = set(pin.get("overrides") or [])
    here = tree_blobs(downstream, "HEAD", paths)
    there = tree_blobs(upstream_repo, pin_rev, paths)
    report = {"identical": [], "modified": [], "override": [], "only_downstream": [], "only_upstream": []}
    for path in sorted(set(here) | set(there)):
        h, t = here.get(path), there.get(path)
        if h and t:
            if h == t:
                report["identical"].append(path)
            elif path in overrides:
                report["override"].append(path)
            else:
                report["modified"].append(path)
        elif h:
            report["only_downstream"].append(path)
        else:
            report["only_upstream"].append(path)
    behind: dict = {"tip": tip_rev, "commits": None, "files": []}
    if tip_rev and tip_rev != pin_rev:
        try:
            behind["commits"] = int(_git(["rev-list", "--count", f"{pin_rev}..{tip_rev}"], upstream_repo).strip())
        except (subprocess.CalledProcessError, ValueError):
            behind["commits"] = None
        tip_blobs = tree_blobs(upstream_repo, tip_rev, paths)
        behind["files"] = sorted(p for p in set(there) | set(tip_blobs) if there.get(p) != tip_blobs.get(p))
    return {
        "upstream": pin["repo"],
        "version": pin.get("version"),
        "pin": pin_rev,
        "paths": paths,
        "counts": {k: len(v) for k, v in report.items()},
        **report,
        "behind": behind,
        "ok": not report["modified"] and not report["only_upstream"],
    }


def render(result: dict) -> str:
    c = result["counts"]
    lines = [
        f"upstream   {result['upstream']}" + (f"  (version {result['version']})" if result.get("version") else ""),
        f"pin        {result['pin'][:12]}   paths: {', '.join(result['paths'])}",
        f"identical  {c['identical']:>5}",
        f"override   {c['override']:>5}   (edited on purpose; listed in UPSTREAM.json overrides)",
        f"modified   {c['modified']:>5}   <- a fork: send the change upstream, or list it as an override",
        f"only here  {c['only_downstream']:>5}   (under a core path but not in the harness)",
        f"missing    {c['only_upstream']:>5}   (in the harness at the pin, absent here)",
    ]
    for key, label in (("modified", "modified"), ("only_upstream", "missing"), ("override", "override")):
        for p in result[key]:
            lines.append(f"    {label:<9} {p}")
    b = result["behind"]
    if b["tip"] is None:
        lines.append("behind     unknown (upstream tip not reachable; pass --fetch or --upstream-dir with a fetched clone)")
    elif b["tip"] == result["pin"]:
        lines.append("behind     0 commits — pinned at the upstream tip")
    else:
        n = b["commits"]
        lines.append(f"behind     {n if n is not None else '?'} commit(s), {len(b['files'])} core file(s) changed since the pin "
                     f"(tip {b['tip'][:12]})")
        for p in b["files"][:25]:
            lines.append(f"    changed   {p}")
        if len(b["files"]) > 25:
            lines.append(f"    ... {len(b['files']) - 25} more")
    lines.append("")
    lines.append("OK: the vendored core matches the pin." if result["ok"]
                 else "DRIFT: files under a core path differ from the pin or are missing. Code flows upstream->downstream; "
                      "fix by re-vendoring, by an upstream PR, or by listing a deliberate data-file edit under overrides.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--downstream", default=".", help="the overlay repository (default: cwd)")
    ap.add_argument("--upstream-dir", default=None, help="a local clone of the harness to read objects from")
    ap.add_argument("--fetch", action="store_true", help="git fetch the pinned commit (and default branch) from the upstream repo")
    ap.add_argument("--check", action="store_true", help="exit 1 on modified or missing core files")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()
    downstream = Path(args.downstream).resolve()
    if not _git_ok(["rev-parse", "--git-dir"], downstream):
        print(f"upstream-check: {downstream} is not a git repository", file=sys.stderr)
        return 2
    pin = load_pin(downstream)
    upstream_dir = Path(args.upstream_dir).resolve() if args.upstream_dir else None
    try:
        repo, pin_rev, tip = resolve_upstream(downstream, pin, upstream_dir, args.fetch)
        result = compare(downstream, pin, repo, pin_rev, tip)
    except subprocess.CalledProcessError as exc:
        print(f"upstream-check: git failed: {exc.stderr or exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else render(result))
    if args.check and not result["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
    raise SystemExit(main())
