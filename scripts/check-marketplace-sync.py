#!/usr/bin/env python3
"""Verify marketplace/ and .claude-plugin/ are in sync with canonical sources.

Mirrors the `Verify marketplace is in sync with canonical sources` step in
.github/workflows/validate.yml, so a local run and CI agree by construction
rather than by two hand-maintained copies of the same shell.

MUTATES THE TREE, deliberately and idempotently: build-marketplace.py always
writes, so the only way to know whether the committed output matches its sources
is to regenerate and diff. When the tree was already in sync the rewrite is
byte-identical and `git status` stays clean; when it was not, the regenerated
files are exactly what you needed to commit anyway.

Uses `git status --porcelain` rather than `git diff --quiet` for the same reason
CI does: the builder can CREATE a file in marketplace/ that was never committed,
and `git diff` is blind to untracked files, so that file would silently never
ship (claude-config PR #1151 was the live instance).

Exit: 0 in sync - 1 out of sync or the builder failed - 2 setup error.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PATHS = ["marketplace/", ".claude-plugin/"]


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    builder = root / "scripts" / "build-marketplace.py"
    if not builder.exists():
        print(f"check-marketplace-sync: {builder} not found", file=sys.stderr)
        return 2

    r = subprocess.run(
        [sys.executable, str(builder)],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(
            "build-marketplace.py FAILED — a published SKILL.md most likely "
            "references a file not shipped into its plugin (see its link-check "
            "output below).",
            file=sys.stderr,
        )
        sys.stderr.write(r.stdout[-4000:])
        sys.stderr.write(r.stderr[-4000:])
        return 1

    s = subprocess.run(
        ["git", "status", "--porcelain", *PATHS],
        cwd=root,
        capture_output=True,
        text=True,
    )
    drift = s.stdout.strip()
    if drift:
        print("marketplace/ is OUT OF SYNC with skills/, hooks/, rules/.")
        print("The builder just regenerated these — commit them:")
        for line in drift.splitlines():
            print(f"  {line}")
        return 1

    print("marketplace sync: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
