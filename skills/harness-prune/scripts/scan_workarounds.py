#!/usr/bin/env python3
"""Scan the harness (skills/hooks/rules) for model-version workarounds.

Deterministic source 1 of /harness-prune (split out of /garden's
"Harness Pruning Audit" 2026-06-11, B8c/F2): find places where a
    versioned model reference (Fable/Mythos/Opus/Sonnet/Haiku/Claude + an explicit
version token) sits near workaround language ("compensate",
"work around", "context anxiety", "context reset"). Those are the
candidates that rot when models move on — the scan finds the PAIRS;
whether each workaround is still needed is the skill's judgment step,
not this script's.

Output: JSON to stdout — {"candidates": [{file, line, model_ref,
signal, excerpt}], "scanned_files": N}. Exit 0 always when the scan ran
(an empty candidate list is a healthy result); exit 2 on bad arguments.

Usage:
  python3 scan_workarounds.py [--root ~/.claude] [--window 2]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MODEL_REF_RE = re.compile(
    r"\b(?:claude[- ])?(?:fable|mythos|sonnet|opus|haiku)[- ]?\d(?:[.-]\d)?\b"
    r"|\bclaude[- ]?[34](?:[.-]\d)?\b",
    re.IGNORECASE,
)
SIGNAL_RE = re.compile(
    r"compensat\w*|work[- ]?around\w*|context anxiety|context reset",
    re.IGNORECASE,
)

SCAN_GLOBS = [
    "skills/*/SKILL.md",
    "skills/_shared/*.md",
    "skills/*/references/*.md",
    "hooks/*.py",
    "rules/*.md",
    "agents/*.md",
    "docs/*.md",
]


def scan_file(path: Path, window: int) -> list:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return []
    out = []
    for i, line in enumerate(lines):
        m = MODEL_REF_RE.search(line)
        if not m:
            continue
        lo = max(0, i - window)
        hi = min(len(lines), i + window + 1)
        neighborhood = "\n".join(lines[lo:hi])
        sig = SIGNAL_RE.search(neighborhood)
        if sig:
            out.append({
                "file": str(path),
                "line": i + 1,
                "model_ref": m.group(0),
                "signal": sig.group(0),
                "excerpt": line.strip()[:200],
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Find versioned-model refs near workaround language.")
    ap.add_argument("--root", default=str(Path.home() / ".claude"),
                    help="Harness root to scan (default: ~/.claude)")
    ap.add_argument("--window", type=int, default=2,
                    help="Lines of proximity for the signal match (default 2)")
    args = ap.parse_args()

    if args.window < 0:
        print(f"error: --window must be >= 0 (got {args.window})",
              file=sys.stderr)
        print("hint: pass a non-negative line count, e.g. --window 2",
              file=sys.stderr)
        return 2

    root = Path(args.root).expanduser()
    if not root.is_dir():
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 2

    candidates = []
    scanned = 0
    for pattern in SCAN_GLOBS:
        for path in sorted(root.glob(pattern)):
            scanned += 1
            candidates.extend(scan_file(path, args.window))
    print(json.dumps({"candidates": candidates, "scanned_files": scanned},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
