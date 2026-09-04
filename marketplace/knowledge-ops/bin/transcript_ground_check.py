#!/usr/bin/env python3
"""transcript_ground_check.py — deterministic grounding-validation gate for the map step.

WHY this exists (caught on the first real extraction, 2026-06-20): a per-chunk extractor subagent
returned 32 findings, 30 grounded to real records but 2 citing `rec n=1032`/`rec n=1035` in a chunk
that has only 436 records — hallucinated grounding past its read window (the classic
subagent-tool-discipline failure: cite_specific_line_numbers_without_reading_those_lines). On a
59-chunk fan-out that is 59 chances for fabricated citations to enter the synthesized artifact.

This gate is the fix: after a subagent returns findings, validate every finding's `rec n=N` against
the chunk's ACTUAL record count (known deterministically from the chunk file — no LLM needed).
Findings whose grounding is out of range are SEPARATED OUT (flagged), never silently kept and never
silently dropped — the caller decides (default: exclude from synthesis, report the count).

A finding with no parseable `rec n=N` is also flagged (ungrounded). Valid findings pass through
untouched. The gate NEVER calls an LLM and NEVER mutates a finding's content — it only partitions.

Usage:
  python3 transcript_ground_check.py --findings findings.json --chunk chunk_005.jsonl
  python3 transcript_ground_check.py --findings findings.json --record-count 436
Outputs JSON: {"valid": [...], "flagged": [...], "record_count": N,
               "n_valid": x, "n_flagged": y, "flag_reasons": {...}}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

REC_RE = re.compile(r"rec\s+n\s*=\s*(\d+)", re.IGNORECASE)


def chunk_record_count(chunk_path: str) -> int:
    """Count JSONL records in a chunk file — the authoritative upper bound for grounding.

    The extractor renders one `<<rec n=N>>` per non-empty JSONL line, numbering from 1, so the
    valid grounding range is [1, record_count]. We count non-empty lines (matching the renderer
    in transcript_fit_gate.render_chunk, which skips blank lines)."""
    n = 0
    with open(chunk_path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if raw.strip():
                n += 1
    return n


def parse_ground(ground) -> int | None:
    """Extract the integer record number from a finding's `ground` field. None if unparseable."""
    if ground is None:
        return None
    m = REC_RE.search(str(ground))
    return int(m.group(1)) if m else None


def validate(findings: list, record_count: int, start_index: int = 0):
    """Partition findings into valid / flagged against the chunk's GLOBAL record range.

    Records are numbered by global index (renderer's `start_index`), so the valid grounding range
    is [start_index+1, start_index+record_count] inclusive. `start_index=0` reproduces the old
    local [1, record_count] behavior (single-chunk / no-manifest fallback).
    """
    lo = start_index + 1
    hi = start_index + record_count
    valid, flagged = [], []
    reasons = {"out_of_range": 0, "ungrounded": 0, "nonpositive": 0}
    for f in findings:
        n = parse_ground(f.get("ground") if isinstance(f, dict) else None)
        if n is None:
            f2 = dict(f) if isinstance(f, dict) else {"raw": f}
            f2["_flag"] = "ungrounded"
            flagged.append(f2)
            reasons["ungrounded"] += 1
        elif n < lo:
            f2 = dict(f)
            f2["_flag"] = f"nonpositive rec n={n} < {lo}"
            flagged.append(f2)
            reasons["nonpositive"] += 1
        elif n > hi:
            f2 = dict(f)
            f2["_flag"] = f"out_of_range rec n={n} > {hi}"
            flagged.append(f2)
            reasons["out_of_range"] += 1
        else:
            valid.append(f)
    return valid, flagged, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True, help="JSON file: {chunk,...,findings:[...]} or a bare [...]")
    ap.add_argument("--chunk", help="chunk JSONL file (record count derived from it)")
    ap.add_argument("--record-count", type=int, help="explicit record count (alternative to --chunk)")
    ap.add_argument("--start-index", type=int, default=None,
                    help="global record offset for this chunk (records numbered start_index+1..). "
                         "Auto-loaded from <chunk_dir>/chunk_offsets.json when --chunk is given.")
    args = ap.parse_args()

    with open(args.findings, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and "findings" in data:
        findings = data["findings"]
    elif isinstance(data, list):
        findings = data
    else:
        print("ERROR: findings file must be a JSON list or an object with a 'findings' array",
              file=sys.stderr)
        sys.exit(2)

    if args.record_count is not None:
        rc = args.record_count
    elif args.chunk:
        rc = chunk_record_count(args.chunk)
    else:
        print("ERROR: pass --chunk or --record-count", file=sys.stderr)
        sys.exit(2)

    # Resolve the global start_index: explicit flag wins; else auto-load from the chunker's
    # offsets manifest sitting next to the chunk file; else 0 (local numbering fallback).
    start_index = args.start_index
    if start_index is None and args.chunk:
        off_path = os.path.join(os.path.dirname(os.path.abspath(args.chunk)), "chunk_offsets.json")
        if os.path.exists(off_path):
            cid = os.path.basename(args.chunk).replace("chunk_", "").replace(".jsonl", "")
            with open(off_path, encoding="utf-8") as fh:
                start_index = int(json.load(fh).get(cid, 0))
    if start_index is None:
        start_index = 0

    valid, flagged, reasons = validate(findings, rc, start_index=start_index)
    out = {
        "record_count": rc,
        "start_index": start_index,
        "valid_range": [start_index + 1, start_index + rc],
        "n_valid": len(valid),
        "n_flagged": len(flagged),
        "flag_reasons": reasons,
        "valid": valid,
        "flagged": flagged,
    }
    print(json.dumps(out, indent=2))
    # exit 1 if anything flagged, so callers/CI can gate on it
    sys.exit(1 if flagged else 0)


if __name__ == "__main__":
    main()
