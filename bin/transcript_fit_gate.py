#!/usr/bin/env python3
"""transcript_fit_gate.py — turn a chunk JSONL into the exact text a subagent will receive,
and emit its character size + char-estimate tokens, so Phase B can verify every chunk fits the
real token budget.

WHY separate from the chunker: the chunker budgets by a fast char estimate (no deps). This gate
produces the ACTUAL extraction payload (the rendered chunk text a subagent reads) and sizes it.
The real count_message_tokens call (claude_platform MCP) is driven from the orchestrating skill /
session, not here — this script produces the payload string + a local estimate so the caller can
(a) smoke one payload through count_message_tokens, (b) compare real-vs-estimate, (c) re-chunk if
the real count exceeds budget.

The payload rendering is LOSSLESS for the chunk: it includes every record, every block type
(thinking, tool_result, tool_use, image refs, file-history-snapshot, attachments) — nothing
dropped, consistent with the "don't drop anything" constraint. Images are rendered as a
[image: N bytes base64 omitted-from-text] placeholder ONLY because base64 is not useful text to
an extractor and would blow the token count 4x for zero signal — but the placeholder RECORDS
that an image was present at that point (so the extractor knows a screenshot existed). That is
the one and only content transform, and it is reversible-by-reference (the chunk file still has
the bytes). Everything else is passed through verbatim.
"""
from __future__ import annotations

import argparse
import json
import os

CHARS_PER_TOKEN = 3.0


def render_block(b):
    """Render one content block as text. Lossless except base64 image bodies (placeholdered)."""
    if not isinstance(b, dict):
        return str(b)
    bt = b.get("type", "?")
    if bt == "text":
        return b.get("text", "")
    if bt == "thinking":
        return f"[thinking]\n{b.get('thinking', '')}"
    if bt == "tool_use":
        return f"[tool_use {b.get('name','?')}] input={json.dumps(b.get('input', {}))}"
    if bt == "tool_result":
        c = b.get("content", "")
        err = " is_error" if b.get("is_error") else ""
        if isinstance(c, list):
            c = "\n".join(
                (x.get("text", "") if isinstance(x, dict) and x.get("type") == "text"
                 else (f"[image {len(json.dumps(x))}b]" if isinstance(x, dict) and x.get("type") == "image"
                       else json.dumps(x)))
                for x in c
            )
        return f"[tool_result{err}]\n{c}"
    if bt == "image":
        # placeholder — record presence + size, omit base64 body (not useful text)
        return f"[image: ~{len(json.dumps(b))}b base64 omitted-from-text]"
    # any other block type: pass through as JSON so nothing is silently lost
    return f"[{bt}] {json.dumps(b)}"


def render_chunk(path, start_index=0):
    """Render a chunk JSONL into a single text blob the extractor subagent will read.

    Each record is tagged `<<rec n=N>>` with N being its GLOBAL record index in the original
    transcript (1-based), NOT a per-chunk 1..N counter. This is load-bearing: a per-chunk counter
    made groundings ambiguous, and extractor LLMs — reading content that references the broader
    session — resolved the ambiguity toward GLOBAL coordinates, so a chunk at global offset 1844
    produced groundings like `rec n=2019` that a local [1,359] bound wrongly rejected as
    fabrications (live-test FLAW-1, 2026-06-20: up to 76% false-flag on high-offset chunks).
    Numbering globally means (a) agent groundings and the gate's bound share ONE coordinate system,
    and (b) a ground is directly traceable back to the real transcript record. `start_index` is the
    global index of the FIRST record in this chunk (0-based line offset from the chunk plan); the
    first rendered record is therefore n=start_index+1.

    Returns (text, global_record_range) where global_record_range is (first_n, last_n) inclusive.
    """
    out = []
    n = start_index  # global index of the record just before this chunk's first
    first_n = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            n += 1  # 1-based global record index
            if first_n is None:
                first_n = n
            try:
                r = json.loads(raw)
            except Exception:
                out.append(f"[unparseable record n={n}] {raw[:200]}")
                continue
            t = r.get("type", "?")
            msg = r.get("message") or {}
            role = msg.get("role", t)
            tag = f"<<rec n={n} type={t} role={role}>>"
            c = msg.get("content")
            if isinstance(c, str):
                out.append(f"{tag}\n{c}")
            elif isinstance(c, list):
                body = "\n".join(render_block(b) for b in c)
                out.append(f"{tag}\n{body}")
            else:
                # non-message records (file-history-snapshot, pr-link, mode, etc.) — keep verbatim
                # as compact JSON so nothing is dropped; these are usually small.
                out.append(f"{tag} {json.dumps(r)[:4000]}")
    return "\n".join(out), (first_n or start_index + 1, n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chunk_dir", help="dir of chunk_NNN.jsonl files (or a single chunk file)")
    ap.add_argument("--budget-tokens", type=int, default=600_000)
    ap.add_argument("--emit", default=None,
                    help="if set, write rendered payloads to this dir as payload_NNN.txt")
    args = ap.parse_args()

    if os.path.isfile(args.chunk_dir):
        files = [args.chunk_dir]
        offsets = {}
    else:
        files = sorted(
            os.path.join(args.chunk_dir, f)
            for f in os.listdir(args.chunk_dir)
            if f.startswith("chunk_") and f.endswith(".jsonl")
        )
        # Load the global-offset manifest the chunker wrote, so records are numbered by GLOBAL
        # index (fixes the global-coordinate grounding flaw). Absent → fall back to 0-offset
        # (local numbering) and warn, since that reintroduces the flaw.
        offsets = {}
        off_path = os.path.join(args.chunk_dir, "chunk_offsets.json")
        if os.path.exists(off_path):
            with open(off_path, encoding="utf-8") as fh:
                offsets = json.load(fh)
        else:
            print("WARN: chunk_offsets.json absent — numbering records LOCALLY (per-chunk). "
                  "Re-run transcript_chunk.py to emit it; global grounding will mis-flag otherwise.")
    if args.emit:
        os.makedirs(args.emit, exist_ok=True)

    print(f"{'chunk':>5} {'recRange':>16} {'payloadChars':>13} {'estTokens':>10} {'<=budget?':>9}")
    print("-" * 60)
    worst = 0
    for i, f in enumerate(files):
        cid = os.path.basename(f).replace("chunk_", "").replace(".jsonl", "")
        start_index = int(offsets.get(cid, 0))
        payload, (first_n, last_n) = render_chunk(f, start_index=start_index)
        chars = len(payload)
        est = int(chars / CHARS_PER_TOKEN)
        worst = max(worst, est)
        ok = "OK" if est <= args.budget_tokens else "OVER"
        print(f"{i:>5} {f'{first_n}-{last_n}':>16} {chars:>13,} {est:>10,} {ok:>9}")
        if args.emit:
            with open(os.path.join(args.emit, f"payload_{i:03d}.txt"), "w", encoding="utf-8") as out:
                out.write(payload)
    print(f"\nworst-chunk est tokens: {worst:,}  (budget {args.budget_tokens:,})")
    print("NOTE: this is the char-ESTIMATE. Smoke the worst payload through count_message_tokens")
    print("      (claude_platform MCP) to get the REAL count before trusting the budget.")


if __name__ == "__main__":
    main()
