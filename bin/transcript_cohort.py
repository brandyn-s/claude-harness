#!/usr/bin/env python3
"""transcript_cohort.py — mega-distill corpus-mode Phase B1: cohort selection + coverage report.

Selects the SEMANTIC-layer cohort (the bounded, expensive LLM layer runs only on this subset) and
prints the mandatory coverage line so there is NEVER silent truncation. The friction spine (Phase A)
covers the FULL corpus; the semantic layer is bounded to the large sessions where prose meta-lessons
concentrate (a 200-line session rarely holds a "I optimized completeness over diagnosis" lesson; a
>1MB compacted session usually does).

Selection filters (compose):
  --all            every transcript across all project dirs (friction-spine cohort)
  --min-size N     only sessions whose .jsonl is >= N bytes (e.g. 1M) — the default semantic cohort
  --min-lines N    only sessions with >= N lines
  --compacted      only sessions with >=1 compaction boundary
  <explicit files> positional paths override the scan (cohort = exactly those)

Emits cohort.txt (one path per line) + prints the coverage report:
  Full corpus: 1209.  Semantic cohort (>=1MB): 97 (8.0%).  1112 covered by friction spine only.

Usage:
  python3 transcript_cohort.py --root ~/.claude/projects --min-size 1048576 --out cohort.txt
  python3 transcript_cohort.py --all --root ~/.claude/projects --out cohort.txt
"""
from __future__ import annotations

import argparse
import glob
import os
import sys


def _scan(root):
    """All *.jsonl under root, recursively (the corpus spans many per-repo/per-tmp project dirs —
    a single-dir scan misses ~63% of the corpus, FLAW-3 2026-06-20)."""
    return sorted(glob.glob(os.path.join(os.path.expanduser(root), "**", "*.jsonl"), recursive=True))


def _count_compaction(path):
    n = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"isCompactSummary":true' in line or '"isCompactSummary": true' in line:
                    n += 1
    except OSError:
        pass
    return n


def select(root, explicit, want_all, min_size, min_lines, compacted):
    full = _scan(root) if not explicit else sorted(os.path.abspath(p) for p in explicit)
    full_n = len(full)
    if want_all or (not min_size and not min_lines and not compacted and not explicit):
        return full, full, full_n  # cohort == full corpus

    cohort = []
    for p in full:
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        if min_size and size < min_size:
            continue
        if min_lines:
            with open(p, encoding="utf-8", errors="replace") as fh:
                nl = sum(1 for _ in fh)
            if nl < min_lines:
                continue
        if compacted and _count_compaction(p) < 1:
            continue
        cohort.append(p)
    return cohort, full, full_n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="explicit transcript paths (overrides scan)")
    ap.add_argument("--root", default="~/.claude/projects")
    ap.add_argument("--all", action="store_true", help="cohort = full corpus (friction-spine cohort)")
    ap.add_argument("--min-size", type=int, default=0, help="bytes; e.g. 1048576 for 1MB")
    ap.add_argument("--min-lines", type=int, default=0)
    ap.add_argument("--compacted", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cohort, _full, full_n = select(args.root, args.files, args.all,
                                    args.min_size, args.min_lines, args.compacted)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(cohort) + ("\n" if cohort else ""))

    n = len(cohort)
    not_covered = full_n - n
    pct = (100.0 * n / full_n) if full_n else 0.0
    label = "full corpus" if (args.all or n == full_n) else (
        f">= {args.min_size}B" if args.min_size else "filtered")
    # The MANDATORY coverage line — no silent truncation.
    print(f"COVERAGE: full corpus {full_n} sessions. "
          f"Semantic cohort ({label}): {n} ({pct:.1f}%). "
          f"{not_covered} session(s) covered by friction spine only.")
    print(f"cohort written: {args.out} ({n} paths)")
    if n == 0:
        print("WARNING: cohort is empty — no sessions matched the filter.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
