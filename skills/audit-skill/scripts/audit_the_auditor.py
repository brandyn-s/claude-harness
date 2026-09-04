#!/usr/bin/env python3
"""Trace-replay audit-the-auditor (build-measurement-harness Phase 9).

Sample oracle trace records per layer for hand verification, then apply
the Phase-9 decision rule to the human labels:

  >= 60% INSTRUMENT  -> fix the oracle/harness; do NOT file a system bug
  >= 60% REAL        -> real failure mode; proceed to fix
  else (mixed)       -> expand the sample

The verdict the trace records is the oracle's claim; this script is how a
human periodically confirms the oracle isn't drifting (the inverse of the
oracle auditing the skills). Emits a markdown worksheet with an editable
classification column; the decision rule is unit-tested.

Usage:
  python3 audit_the_auditor.py [--trace PATH] [--sample 5] [--out worksheet.md]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

VALID_LABELS = ("REAL", "INSTRUMENT", "UNCLEAR")


def read_records(trace_path) -> list[dict]:
    p = Path(trace_path)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def sample_records(records: list[dict], per_layer: int = 5, seed: int = 0) -> dict:
    """Up to ``per_layer`` records per layer, deterministically sampled."""
    rng = random.Random(seed)
    by_layer: dict = {}
    for r in records:
        by_layer.setdefault(r.get("layer", "?"), []).append(r)
    return {layer: (rng.sample(recs, min(per_layer, len(recs))) if recs else [])
            for layer, recs in by_layer.items()}


def classify_axis(labels: list[str]) -> str:
    """Phase-9 decision over labels in VALID_LABELS. Threshold is a 60%
    majority (ceil) — i.e. >=3 of 5, the rule promoted to T1 on 2026-05-02."""
    n = len(labels)
    if n == 0:
        return "no-sample"
    thr = math.ceil(0.6 * n)
    if labels.count("INSTRUMENT") >= thr:
        return "fix-instrument"
    if labels.count("REAL") >= thr:
        return "real-failure-mode"
    return "expand-sample"


def render_worksheet(sampled: dict) -> str:
    lines = [
        "# audit-the-auditor worksheet",
        "",
        "Classify each record **REAL** / **INSTRUMENT** / **UNCLEAR**, then "
        "feed each layer's labels to `classify_axis`.",
        "",
    ]
    for layer, recs in sorted(sampled.items()):
        lines.append(f"## Layer {layer} ({len(recs)} sampled)")
        lines.append("")
        for r in recs:
            fid = str(r.get("finding_id", "?"))[:8]
            lines.append(
                f"- [ ] `{r.get('verdict', '?')}` {r.get('skill', '?')}/{fid} — "
                f"{str(r.get('evidence', ''))[:100]}  **class:** ____"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Trace-replay audit-the-auditor (Phase 9)")
    ap.add_argument("--trace", default=str(Path.home() / ".claude" / "oracle-trace.jsonl"))
    ap.add_argument("--sample", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", help="write the worksheet here (default: stdout)")
    args = ap.parse_args(argv)
    records = read_records(args.trace)
    sampled = sample_records(records, per_layer=args.sample, seed=args.seed)
    worksheet = render_worksheet(sampled)
    if args.out:
        Path(args.out).write_text(worksheet, encoding="utf-8")
    else:
        print(worksheet)
    print(f"# sampled { {layer: len(v) for layer, v in sampled.items()} } "
          f"from {len(records)} records", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
