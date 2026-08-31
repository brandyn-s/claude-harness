#!/usr/bin/env python3
"""transcript_chunk.py — split a Claude Code session JSONL into window-fitting chunks
WITHOUT dropping any record.

WHY this exists: very large sessions (50-60MB, 20k lines, 10+ auto-compactions) cannot be
processed in-context — after compaction ~90% of history is gone from the live window, and the
raw file is 12-60x a 1M-token window. Each compaction *segment* is still 1.2-2.2M tokens
(measured), so even one-pass-per-segment overflows. This chunker tiles the COMPLETE file into
pieces that each fit a budget, so a fan-out of subagents (one per chunk) can extract findings
from 100% of the record. Nothing is filtered or dropped — that is the load-bearing invariant,
and it is machine-checked by the test suite (byte-exact reconstruction / exact-margin coverage).

It does NOT call an LLM. Token budgeting here uses a fast char-based ESTIMATE; the real-token
fit gate (count_message_tokens) runs separately in Phase B and re-chunks if the estimate was
optimistic. Estimate-here / verify-there keeps this script dependency-free and instantly testable.

Two cross-chunk modes (both preserve completeness, differently):
  - non-overlap (default): every line lands in EXACTLY ONE chunk. concat(chunks) is byte-exact
    equal to the input. This is the clean, audit-trivial mode.
  - overlap: each chunk after the first repeats the last `overlap_lines` lines of the previous
    chunk, so a finding spanning a chunk boundary is never split. Completeness here is
    UNION-coverage (every input line appears in >=1 chunk) plus an exact-duplication accounting
    (duplicated lines == sum of declared per-boundary margins). Used to A/B cross-chunk recall
    against the carry-forward-summary arm in the extraction skill.

Usage:
  python3 transcript_chunk.py <transcript.jsonl> --out <dir> [--mode non-overlap|overlap]
                              [--budget-tokens 600000] [--overlap-lines 40]
  python3 transcript_chunk.py <transcript.jsonl> --stat-only   # just print the chunk plan

Boundary rules (applied in order):
  1. NEVER split mid-line (JSONL is line-atomic).
  2. PREFER to start a new chunk at a compaction boundary (a record with isCompactSummary=true):
     these are natural session-segment edges (MemGPT-style flush points).
  3. Otherwise start a new chunk when the running token estimate would exceed the budget.

The compaction-boundary preference is soft: if a single segment exceeds the budget (the common
case — segments are 1.2-2.2M tokens), the chunk is force-split mid-segment at the budget. No
record is ever skipped to honor a boundary.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Fast char-based token proxy. CALIBRATED 2026-06-20 against the real tokenizer: a JSON-dense
# rendered transcript payload measured 849,354 chars = 457,083 tokens => 1.858 chars/token (NOT
# the 3.0 a prose assumption gives — rendered tool-output/code tokenizes ~1.6x denser than prose).
# We use 2.0 (slightly below the measured 1.858) so the estimate OVER-counts tokens => chunks come
# out a bit SMALL => they comfortably pass the authoritative real count_message_tokens gate in
# Phase B. The estimate is a PLANNING PROXY ONLY; the real-token gate is authoritative and must run
# (it re-chunks any segment the estimate got wrong). Under-counting (the old 3.0) would have
# produced chunks that fail the real gate mid-fan-out. See plan-flaws log, Phase B entry.
CHARS_PER_TOKEN = 2.0


def estimate_tokens(num_bytes: int) -> int:
    return int(num_bytes / CHARS_PER_TOKEN)


def is_compaction_boundary(raw_line: str) -> bool:
    """True if this JSONL record marks an auto-compaction boundary.

    The transcript records the boundary as a top-level "isCompactSummary": true field. We do a
    cheap substring pre-check before the JSON parse to stay fast on 20k-line files; only lines
    that contain the marker substring are actually parsed.
    """
    if "isCompactSummary" not in raw_line:
        return False
    try:
        rec = json.loads(raw_line)
    except (json.JSONDecodeError, ValueError):
        return False
    return bool(rec.get("isCompactSummary"))


def plan_chunks(path: str, budget_tokens: int, overlap_lines: int, mode: str):
    """Stream the file once and produce a chunk plan: a list of (start_line, end_line_exclusive)
    index pairs over the file's lines, plus per-line byte lengths.

    Streaming, line-by-line — never loads the whole file into memory as parsed JSON. We DO hold
    the list of line byte-lengths and boundary flags (one small int + bool per line; ~20k entries
    for the biggest sessions = trivial), which is what lets us compute overlap windows and verify
    completeness without a second pass.
    """
    line_bytes: list[int] = []
    boundary_at: list[int] = []  # line indices that are compaction boundaries

    with open(path, "rb") as fh:
        # Read as bytes to measure true on-disk size per line; decode per line for the marker check.
        for idx, raw in enumerate(fh):
            line_bytes.append(len(raw))
            # decode just for the boundary check; errors='replace' never raises
            if b"isCompactSummary" in raw and is_compaction_boundary(
                raw.decode("utf-8", errors="replace")
            ):
                boundary_at.append(idx)

    n_lines = len(line_bytes)
    boundary_set = set(boundary_at)

    # First pass: greedy non-overlap chunk spans honoring budget + boundary preference.
    spans: list[tuple[int, int]] = []
    start = 0
    running = 0
    for i in range(n_lines):
        # If we're at a compaction boundary (and not at the very start of the current chunk),
        # close the current chunk here and start fresh — natural segment edge.
        if i in boundary_set and i > start:
            spans.append((start, i))
            start = i
            running = 0
        tok = estimate_tokens(line_bytes[i])
        # If adding this line would blow the budget (and the chunk isn't empty), close before it.
        if running + tok > budget_tokens and i > start:
            spans.append((start, i))
            start = i
            running = 0
        running += tok
    if start < n_lines:
        spans.append((start, n_lines))

    if mode == "non-overlap":
        return spans, line_bytes, boundary_at, n_lines

    # Overlap mode: extend each chunk (except the first) backward by overlap_lines, clamped to 0.
    # The forward end stays the same, so union-coverage is preserved and the only duplication is
    # the prepended margin.
    ov_spans: list[tuple[int, int]] = []
    for k, (s, e) in enumerate(spans):
        if k == 0:
            ov_spans.append((s, e))
        else:
            ov_spans.append((max(0, s - overlap_lines), e))
    return ov_spans, line_bytes, boundary_at, n_lines


def write_chunks(path: str, spans, out_dir: str):
    """Write each span to out_dir/chunk_NNN.jsonl by re-streaming the source file once.

    Re-streams rather than buffering all lines in memory — keeps peak memory flat regardless of
    a 60MB input. For each line index we know which chunk(s) it belongs to (overlap lines belong
    to two adjacent chunks); we open the needed output handles and write as we go.
    """
    os.makedirs(out_dir, exist_ok=True)
    # Build, per line index, the list of chunk ids that include it.
    # spans may overlap (overlap mode), so a line can map to 1 or 2 chunks.
    n_chunks = len(spans)
    paths = [os.path.join(out_dir, f"chunk_{i:03d}.jsonl") for i in range(n_chunks)]
    handles = [open(p, "wb") for p in paths]
    # Count NON-EMPTY records before each chunk's start line, so the renderer can number records
    # by GLOBAL record index (the renderer skips blank lines, so a raw line offset would drift).
    # nonblank_before[L] = number of non-empty lines with index < L.
    try:
        # For efficiency, precompute for each chunk its (start,end); iterate file once and write
        # each line to every chunk whose span contains it. Track non-blank prefix counts at the
        # span starts we care about.
        starts_needed = {s for s, _ in spans}
        nonblank_before = {}
        nonblank = 0
        with open(path, "rb") as fh:
            for idx, raw in enumerate(fh):
                if idx in starts_needed:
                    nonblank_before[idx] = nonblank
                if raw.strip():
                    nonblank += 1
                for cid, (s, e) in enumerate(spans):
                    if s <= idx < e:
                        handles[cid].write(raw)
    finally:
        for h in handles:
            h.close()
    # Emit the offsets manifest: chunk id -> global record start_index (non-blank records before
    # this chunk). The renderer passes start_index so `<<rec n=N>>` uses global coordinates, and
    # the grounding gate bounds by [start_index+1, start_index+local_count]. Fixes the
    # global-coordinate fabrication-flag flaw (live-test FLAW-1, 2026-06-20).
    offsets = {f"{i:03d}": nonblank_before.get(s, 0) for i, (s, e) in enumerate(spans)}
    with open(os.path.join(out_dir, "chunk_offsets.json"), "w", encoding="utf-8") as fh:
        json.dump(offsets, fh, indent=2)
    return paths


def main():
    ap = argparse.ArgumentParser(description="Chunk a session JSONL without dropping records.")
    ap.add_argument("transcript")
    ap.add_argument("--out", default=None, help="output dir for chunk_NNN.jsonl files")
    ap.add_argument("--mode", choices=["non-overlap", "overlap"], default="non-overlap")
    ap.add_argument("--budget-tokens", type=int, default=600_000,
                    help="per-chunk token budget (char-estimate; real gate is Phase B)")
    ap.add_argument("--overlap-lines", type=int, default=40,
                    help="lines of backward overlap per chunk in overlap mode")
    ap.add_argument("--stat-only", action="store_true", help="print the chunk plan; don't write")
    args = ap.parse_args()

    if not os.path.isfile(args.transcript):
        print(f"ERROR: not a file: {args.transcript}", file=sys.stderr)
        sys.exit(2)

    spans, line_bytes, boundaries, n_lines = plan_chunks(
        args.transcript, args.budget_tokens, args.overlap_lines, args.mode
    )

    total_bytes = sum(line_bytes)
    print(f"transcript: {args.transcript}")
    print(f"lines: {n_lines:,}  bytes: {total_bytes:,}  est_tokens: {estimate_tokens(total_bytes):,}")
    print(f"compaction boundaries: {len(boundaries)}")
    print(f"mode: {args.mode}  budget_tokens: {args.budget_tokens:,}  chunks: {len(spans)}")
    print()
    print(f"{'chunk':>5} {'startLine':>9} {'endLine':>9} {'lines':>7} {'bytes':>12} {'estTok':>10}")
    print("-" * 60)
    for cid, (s, e) in enumerate(spans):
        cb = sum(line_bytes[s:e])
        print(f"{cid:>5} {s:>9} {e:>9} {e - s:>7} {cb:>12,} {estimate_tokens(cb):>10,}")

    if args.stat_only:
        return
    if not args.out:
        print("\n(no --out given; nothing written. pass --out <dir> to write chunk files)")
        return
    paths = write_chunks(args.transcript, spans, args.out)
    print(f"\nwrote {len(paths)} chunks to {args.out}/")


if __name__ == "__main__":
    main()
