#!/usr/bin/env python3
"""transcript_cluster_from_assign.py — build the B4 clusters.json from a flat key->cluster assignment.

Rationale (flaw #8, 2026-06-20): a single clustering agent stalled trying to emit a nested
{clusters:[{members:[...]}]} structure over 472 lessons in one StructuredOutput, but it DID produce
a complete, correct FLAT assignment {key: cluster_name} (firstpass.json: 472/472 assigned, 0
unassigned, 27 clusters). The flat mapping is the easy-to-emit shape; this deterministic converter
inverts it to the cluster shape the B5 gate validates, and synthesizes each cluster's metadata
(pattern/root_cause/proposed_fix/tier_hint) from its MEMBER LESSONS — the most common kind + the
representative lessons — so no second LLM call is needed. Deterministic; the gate then recomputes
breadth and verifies coverage/no-fabrication.

Input : --assign firstpass.json ({assign:{key:name}}) + --lessons cluster_input.json
Output: clusters.json ({clusters:[{name, pattern, root_cause, proposed_fix, tier_hint, members}]})

Usage:
  python3 transcript_cluster_from_assign.py --assign firstpass.json --lessons cluster_input.json \
        --out clusters.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict


def build(assign, lessons_by_key):
    groups = defaultdict(list)
    for key, name in assign.items():
        groups[name].append(key)

    clusters = []
    for name, keys in groups.items():
        members = [lessons_by_key[k] for k in keys if k in lessons_by_key]
        # representative metadata: most common tier_hint + kind; longest root_cause/fix as exemplar
        tiers = Counter(m.get("tier_hint", "none") for m in members if m.get("tier_hint"))
        kinds = Counter(m.get("kind", "") for m in members if m.get("kind"))
        # pick the longest non-empty root_cause / proposed_fix as the cluster exemplar (most detailed)
        root = max((m.get("root_cause", "") for m in members), key=lambda s: len(s or ""), default="")
        fix = max((m.get("proposed_fix", "") for m in members), key=lambda s: len(s or ""), default="")
        dominant_kind = kinds.most_common(1)[0][0] if kinds else ""
        clusters.append({
            "name": name,
            "pattern": f"Cross-session recurring {dominant_kind or 'pattern'}: {name} "
                       f"(spans {len(set(k.split('::')[0] for k in keys))} sessions, {len(keys)} lessons)",
            "root_cause": root,
            "proposed_fix": fix,
            "tier_hint": tiers.most_common(1)[0][0] if tiers else "none",
            "members": keys,
        })
    clusters.sort(key=lambda c: -len(c["members"]))
    return {"clusters": clusters}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assign", required=True)
    ap.add_argument("--lessons", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    fp = json.load(open(args.assign, encoding="utf-8"))
    assign = fp.get("assign", fp)
    lessons = json.load(open(args.lessons, encoding="utf-8"))["lessons"]
    by_key = {le["key"]: le for le in lessons}

    result = build(assign, by_key)
    json.dump(result, open(args.out, "w", encoding="utf-8"), indent=2)
    print(f"built {len(result['clusters'])} clusters from {len(assign)} assignments -> {args.out}")
    for c in result["clusters"][:15]:
        n_sessions = len(set(k.split("::")[0] for k in c["members"]))
        print(f"  {n_sessions:>3} sessions  {len(c['members']):>4} lessons  {c['name']}")


if __name__ == "__main__":
    main()
