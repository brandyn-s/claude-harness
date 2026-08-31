#!/usr/bin/env python3
"""transcript_synth_shard.py — split one bucket's Pass-1 items into size-bounded shards for the
Pass-2 LLM synthesis, so synthesis works at ANY bucket size (FLAW-5: a 552-item bucket exceeds one
agent's careful-merge capacity → it skims into a shallow summary).

WHY hierarchical sharding (not a single agent, not embedding-clustering): this env has no local
embedding client (voyageai/sentence-transformers not importable), so semantic grouping is the
LLM's job, same as everywhere else in mega-retro. The deterministic structural pre-clustering
(transcript_reduce.py, signature-based) already collapsed the high-FREQUENCY recurring events; what
remains is the semantic residue. We shard that residue, synthesize each shard, then a cross-shard
merge pass catches duplicates that landed in different shards.

To MINIMIZE cross-shard duplicates (which the merge pass must then catch), shards are built so
similar items tend to co-locate: items are sorted by a coarse lexical key (first 4 significant
words of the summary) before chunking into shards. This is a cheap deterministic proxy for
"group similar together" — it does not REPLACE the cross-shard merge (which is the correctness
guarantee), it just reduces its load.

Usage:
  python3 transcript_synth_shard.py --in <synth_in_BUCKET.json> --shard-size 60 --out-dir <dir>
Emits shard_000.json .. shard_NNN.json + a shards-manifest.json. Single-shard buckets (<= shard
size) emit one shard and set "needs_cross_shard_merge": false.
"""
import argparse
import json
import os
import re

_STOP = {"the", "a", "an", "to", "of", "in", "for", "and", "was", "is", "by", "on", "with",
         "that", "it", "as", "at", "from", "this", "be", "not", "but", "claude"}


def lex_key(summary):
    words = re.findall(r"[a-z0-9]+", (summary or "").lower())
    sig = [w for w in words if w not in _STOP and len(w) > 2]
    return " ".join(sig[:4])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--shard-size", type=int, default=60,
                    help="max items per shard (kept small enough for careful per-item merge)")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    items = json.load(open(args.inp, encoding="utf-8"))
    os.makedirs(args.out_dir, exist_ok=True)

    # sort by coarse lexical key so similar summaries co-shard (reduces cross-shard dupes)
    items_sorted = sorted(items, key=lambda f: lex_key(f.get("summary")))

    shards = [items_sorted[i:i + args.shard_size]
              for i in range(0, len(items_sorted), args.shard_size)] or [[]]
    for i, sh in enumerate(shards):
        with open(os.path.join(args.out_dir, f"shard_{i:03d}.json"), "w", encoding="utf-8") as fh:
            json.dump(sh, fh, indent=2)

    manifest = {
        "bucket_items": len(items),
        "shard_size": args.shard_size,
        "n_shards": len(shards),
        "needs_cross_shard_merge": len(shards) > 1,
        "shard_sizes": [len(s) for s in shards],
    }
    with open(os.path.join(args.out_dir, "shards-manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
