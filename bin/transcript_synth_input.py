#!/usr/bin/env python3
"""transcript_synth_input.py — extract one bucket's Pass-1 prep findings into a compact list for
a Pass-2 synthesis agent. Keeps the synthesis input small + focused (one bucket at a time) and
INCLUDES the recurring-event clusters (as pre-merged count-bearing items) alongside the distinct
findings, so the synthesis agent sees the full picture for that bucket.

Output is a JSON list of {summary, ground, for, chunk, [count]} — count present only for cluster
representatives. The synthesis agent merges semantic duplicates and returns a deduped bucket.
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep", required=True, help="prep-artifact.json from transcript_reduce.py")
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    a = json.load(open(args.prep, encoding="utf-8"))
    items = []
    for f in a["distinct"]:
        if f.get("bucket") == args.bucket:
            items.append({"summary": f.get("summary"), "ground": f.get("ground"),
                          "for": f.get("for"), "chunk": f.get("_chunk")})
    for c in a["clusters"]:
        if c.get("bucket") == args.bucket:
            items.append({"summary": c.get("representative"), "ground": c.get("first_ground"),
                          "for": c.get("for"), "count": c.get("count"),
                          "signature": c.get("signature")})
    json.dump(items, open(args.out, "w", encoding="utf-8"), indent=2)
    print(f"bucket={args.bucket}: {len(items)} items written to {args.out}")


if __name__ == "__main__":
    main()
