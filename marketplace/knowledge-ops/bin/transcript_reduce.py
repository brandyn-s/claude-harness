#!/usr/bin/env python3
"""transcript_reduce.py — mega-retro reduce step, deterministic prep half.

Two-pass reduce (per knowledge-base/topics/retrospective-analysis.md "the extractor prepares
data, the model provides judgment"):
  PASS 1 (this script, deterministic, no LLM): gate every chunk's findings against its GLOBAL
    record range, collect the valid ones, and STRUCTURALLY cluster near-duplicate findings so the
    recurring-event noise is collapsed before the model ever sees it. Emits a prep artifact:
    distinct findings + cluster groups (recurring events with a count + representative + members).
  PASS 2 (the skill's LLM synthesis step, separate): the model reads the prep artifact and merges
    the SEMANTIC duplicates structural clustering can't catch (paraphrases, same lesson in
    different words), producing the final synthesized findings artifact.

WHY structural clustering here (FLAW-3, live-test 2026-06-20): a naive exact-string dedup removed
0 of 1,241 findings because recurring EVENTS have unique summaries — `inline-python-guard blocked`
appeared 19x, each naming a different command. Exact-string equality is too strict; full semantic
dedup is the model's job. This middle layer collapses the obvious recurring-event class cheaply and
deterministically (by an event SIGNATURE extracted from the summary), leaving the model a much
smaller, pre-grouped input. It does NOT discard anything — every member is retained inside its
cluster, so PASS 2 (and a human) can still see all of them.

Usage:
  python3 transcript_reduce.py --findings-dir <dir> --chunks-dir <dir> --out <artifact.json>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "transcript_ground_check.py")

# Event-signature patterns: when a finding's summary matches one of these, findings sharing the
# same (bucket, signature) are clustered as one recurring event. The signature is intentionally
# coarse — it captures the EVENT CLASS (which guard/hook/error), not the specific instance, so 19
# distinct "inline-python-guard blocked <different command>" findings collapse to one cluster.
# Extend this list as new recurring event classes appear; anything unmatched stays a distinct
# finding (clustering is opt-in per pattern, never a catch-all that could over-merge).
_SIGNATURES = [
    (re.compile(r"inline[- ]python[- ]?guard|inline `?python -c", re.I), "guard:inline-python"),
    (re.compile(r"tail[- ]buffering|\|\s*(tail|head|grep)\b.*block", re.I), "guard:tail-buffering"),
    (re.compile(r"post[- ]write[- ]edit", re.I), "hook:post-write-edit"),
    (re.compile(r"read[- ]before[- ]edit|has not been read|modified since", re.I), "guard:read-before-edit"),
    (re.compile(r"encoding[- ]guard|encoding=.?utf-?8|cp1252", re.I), "guard:encoding"),
    (re.compile(r"exfiltration[- ]guard", re.I), "guard:exfiltration"),
    (re.compile(r"credential[- ]guard", re.I), "guard:credential"),
    (re.compile(r"wasted (call|read)|file unchanged", re.I), "friction:wasted-read"),
    (re.compile(r"dirty repos? (detected|at session)", re.I), "friction:dirty-repo-warning"),
    (re.compile(r"memory[_-]search latency|latency_ms", re.I), "perf:memory-search-latency"),
]


def signature(bucket, summary):
    """Return a cluster key (bucket, sig) if the summary matches a known recurring-event pattern,
    else None (the finding stays distinct)."""
    for rx, sig in _SIGNATURES:
        if rx.search(summary or ""):
            return (bucket, sig)
    return None


def gnum(f):
    m = re.search(r"rec n=(\d+)", f.get("ground", ""))
    return int(m.group(1)) if m else 10**9


def gate_chunk(findings_path, chunk_path):
    r = subprocess.run(["python3", GATE, "--findings", findings_path, "--chunk", chunk_path],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings-dir", required=True)
    ap.add_argument("--chunks-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--session", default="")
    ap.add_argument("--allow-partial", action="store_true",
                    help="proceed even if some chunks have no findings file (default: FAIL loud). "
                         "Use only for a deliberately partial run; never as the silent default.")
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(args.findings_dir)
                   if f.startswith("findings_") and f.endswith(".json"))

    # COMPLETENESS GUARD (FLAW-7, 2026-06-21): the map step's contract is "write a findings file
    # per chunk AND return". Those two diverge — a map workflow reported 79/79 ok while only 72
    # findings files landed on disk (7 silent write-misses). reduce consumes the DISK, so without
    # this check it silently distills a PARTIAL session (72 of 79) and every downstream count is an
    # undercount with no signal. Disk truth, not the workflow's return value, is authoritative
    # (subagent-verification). Compare findings-file IDs to chunk-file IDs; FAIL loud on any missing
    # chunk unless --allow-partial is explicitly set.
    chunk_ids = {f.replace("chunk_", "").replace(".jsonl", "")
                 for f in os.listdir(args.chunks_dir)
                 if f.startswith("chunk_") and f.endswith(".jsonl")}
    findings_ids = {f.replace("findings_", "").replace(".json", "") for f in files}
    missing = sorted(chunk_ids - findings_ids)
    if missing:
        msg = (f"COMPLETENESS GUARD: {len(missing)} of {len(chunk_ids)} chunks have NO findings file "
               f"(missing chunk ids: {', '.join(missing)}). The map step under-delivered — re-extract "
               f"the missing chunks before reducing, or pass --allow-partial to distill the partial "
               f"set deliberately. Reducing now would silently undercount the session.")
        if not args.allow_partial:
            print(msg, file=sys.stderr)
            sys.exit(3)
        print("WARN (--allow-partial): " + msg, file=sys.stderr)

    valid, flagged, per_chunk = [], [], []
    for ff in files:
        cid = ff.replace("findings_", "").replace(".json", "")
        cpath = os.path.join(args.chunks_dir, f"chunk_{cid}.jsonl")
        if not os.path.exists(cpath):
            per_chunk.append({"id": cid, "error": "chunk missing"})
            continue
        d = gate_chunk(os.path.join(args.findings_dir, ff), cpath)
        if d is None:
            per_chunk.append({"id": cid, "error": "gate unparseable"})
            continue
        for v in d["valid"]:
            v["_chunk"] = cid
        valid.extend(d["valid"])
        flagged.extend(d["flagged"])
        per_chunk.append({"id": cid, "range": d.get("valid_range"),
                          "valid": d["n_valid"], "flagged": d["n_flagged"]})

    # Structural clustering: group recurring-event findings by (bucket, signature).
    clusters = {}      # key -> {signature, bucket, members:[...]}
    distinct = []      # findings with no recurring-event signature
    for f in valid:
        key = signature(f.get("bucket"), f.get("summary"))
        if key is None:
            distinct.append(f)
        else:
            c = clusters.setdefault(key, {"bucket": key[0], "signature": key[1], "members": []})
            c["members"].append(f)

    # A cluster with only 1 member is not actually recurring — treat as distinct.
    cluster_list = []
    for key, c in clusters.items():
        if len(c["members"]) == 1:
            distinct.append(c["members"][0])
            continue
        members = sorted(c["members"], key=gnum)
        cluster_list.append({
            "bucket": c["bucket"],
            "signature": c["signature"],
            "count": len(members),
            "representative": members[0]["summary"],
            "first_ground": members[0].get("ground"),
            "for": _merge_for(members),
            "member_grounds": [m.get("ground") for m in members],
            "members": members,
        })
    cluster_list.sort(key=lambda c: -c["count"])

    # The PASS-2 input = distinct findings + one representative per cluster. This is what shrinks
    # the model's job: 1,241 raw -> (distinct + n_clusters) items to semantically merge.
    pass2_items = len(distinct) + len(cluster_list)
    collapsed = sum(c["count"] for c in cluster_list) - len(cluster_list)

    artifact = {
        "session": args.session,
        "chunks_processed": len(files),
        "raw_valid_findings": len(valid),
        "flagged_findings": len(flagged),
        "distinct_findings": len(distinct),
        "recurring_clusters": len(cluster_list),
        "findings_collapsed_into_clusters": collapsed,
        "pass2_input_size": pass2_items,
        "bucket_distribution": _buckets(valid),
        "clusters": cluster_list,
        "distinct": distinct,
        "per_chunk": per_chunk,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2)

    print(f"chunks processed: {len(files)}")
    print(f"raw valid findings: {len(valid)}  flagged: {len(flagged)}")
    print(f"recurring-event clusters: {len(cluster_list)} "
          f"(collapsed {collapsed} duplicate findings)")
    print(f"distinct findings: {len(distinct)}")
    print(f"PASS-2 (LLM synthesis) input size: {pass2_items} items "
          f"(down from {len(valid)} raw — structural prep did {100*collapsed/max(1,len(valid)):.0f}% reduction)")
    print("top clusters:")
    for c in cluster_list[:6]:
        print(f"  {c['count']:>3}x [{c['bucket']}] {c['signature']}")
    print(f"prep artifact: {args.out}")


def _merge_for(members):
    fors = {m.get("for") for m in members}
    if fors == {"distill"}:
        return "distill"
    if fors == {"capture"}:
        return "capture"
    return "both"


def _buckets(findings):
    out = {}
    for f in findings:
        out[f.get("bucket", "?")] = out.get(f.get("bucket", "?"), 0) + 1
    return out


if __name__ == "__main__":
    main()
