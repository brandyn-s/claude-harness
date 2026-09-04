#!/usr/bin/env python3
"""Plan a MULTI-WAY file-level decomposition of an over-cap topic file.

Not a chunk reshaper. `size_sweep.py` finds files whose shape is wrong; garden's
soft-chunk pass reshapes a file's INTERNALS into `###` subsections. This does the
third thing neither does: turn ONE 119 KB topic into N real sibling topics.

WHY THIS EXISTS — a measurement I got wrong first. Asked "does ONE split reach
the 8 KB cap?", a six-way split of claude-monitoring.md left 5 of 6 siblings over,
and github.md looked "unsplittable" because 3 of its 6 `##` sections each exceeded
the cap alone. Both conclusions were artifacts of the question. Packing into AS
MANY bins as needed, and descending to `###` for over-cap sections, lands every
sibling under cap on 5 of 6 worst files — github.md included (56 units -> 11
siblings). Taking "a little off the top" was never the remedy; decomposition is.

WHAT THIS OUTPUTS: a PLAN, never a write. Files are the unit of navigation, so a
sibling's name must predict its contents — that is authorial, and a size-packer
cannot do it. So this proposes a taxonomy from the content, reports the packing
feasibility, and names what a human must decide. Apply with review.

USAGE
    split_plan.py <file> [--cap BYTES] [--json]
    split_plan.py ~/.claude/agent-memory/topics/claude-monitoring.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_CAP = 8_192

# Stopwords for keyword extraction — generic to this corpus, so they carry no
# signal about WHICH subdomain a section belongs to.
STOP = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "on", "at", "for", "with", "by", "from", "as", "it", "its",
    "this", "that", "these", "those", "not", "no", "so", "if", "then", "than",
    "when", "which", "what", "why", "how", "all", "any", "one", "two", "per",
    "via", "use", "used", "uses", "using", "we", "our", "you", "your", "can",
    "will", "would", "should", "must", "may", "might", "has", "have", "had",
    "does", "did", "do", "get", "gets", "got", "new", "old", "only", "also",
    "more", "most", "less", "other", "same", "still", "just", "now", "added",
    "observed", "confirmed", "verified", "resolved", "open", "gotcha", "gotchas",
}
WORD = re.compile(r"[a-z][a-z0-9_-]{2,}")


def parse_units(text: str, cap: int) -> tuple[str, list[dict]]:
    """Split into packable units. A `##` section over cap descends to `###`.

    Returns (preamble, units). Each unit records whether it is a whole section
    or a fragment, because a plan that silently fragments sections is misleading
    — a reader needs to know their parent will be broken up.
    """
    parts = re.split(r"(?m)^(## .*)$", text)
    preamble = parts[0]
    units: list[dict] = []
    for i in range(1, len(parts) - 1, 2):
        hdr, body = parts[i], parts[i + 1]
        size = len(hdr) + len(body)
        if size <= cap:
            units.append({"label": hdr.strip(), "size": size, "kind": "section",
                          "parent": None, "text": hdr + body})
            continue
        sub = re.split(r"(?m)^(### .*)$", body)
        if len(sub) == 1:
            units.append({"label": hdr.strip(), "size": size,
                          "kind": "indivisible", "parent": None,
                          "text": hdr + body})
            continue
        pre = sub[0]
        if pre.strip():
            units.append({"label": f"{hdr.strip()} (intro)", "size": len(hdr) + len(pre),
                          "kind": "fragment", "parent": hdr.strip(),
                          "text": hdr + pre})
        for j in range(1, len(sub) - 1, 2):
            shdr, sbody = sub[j], sub[j + 1]
            units.append({"label": shdr.strip(), "size": len(shdr) + len(sbody),
                          "kind": "fragment", "parent": hdr.strip(),
                          "text": shdr + sbody})
    return preamble, units


def keywords(unit: dict, top: int = 4) -> list[str]:
    """Distinctive terms, weighted toward the header — a section's own title is
    the best available statement of its subject."""
    hdr = unit["label"].lower()
    body = unit["text"][:900].lower()
    c = Counter()
    for w in WORD.findall(hdr):
        if w not in STOP:
            c[w] += 3
    for w in WORD.findall(body):
        if w not in STOP:
            c[w] += 1
    return [w for w, _ in c.most_common(top)]


def cluster(units: list[dict], cap: int) -> list[dict]:
    """Group by SHARED VOCABULARY, then size-bound each group.

    Deliberately not pure bin-packing: packing by size alone produces siblings
    grouped by nothing a reader recognizes, which defeats the point of a topic
    file. Vocabulary is a weak proxy for subject, so the output is a STARTING
    taxonomy for a human to rename and re-bucket — never a final answer.
    """
    kw = {i: set(keywords(u, 6)) for i, u in enumerate(units)}
    groups: list[dict] = []
    for i, u in enumerate(units):
        best, best_score = None, 0
        for g in groups:
            if g["size"] + u["size"] > cap:
                continue
            score = len(kw[i] & g["kw"])
            if score > best_score:
                best, best_score = g, score
        if best is not None and best_score >= 2:
            best["units"].append(u)
            best["size"] += u["size"]
            best["kw"] |= kw[i]
        else:
            groups.append({"units": [u], "size": u["size"], "kw": set(kw[i])})

    # Second pass: CONSOLIDATE AGGRESSIVELY. The v1 threshold (cap//4) only
    # merged groups under ~2 KB, so a 3.8 KB singleton survived as its own file
    # and the plan proposed 30 siblings for claude-monitoring.md. That is worse
    # for navigation than the monolith it replaces — the reader now has to guess
    # which of 30 files holds the thing, and ~15 of them were named after
    # co-occurring noise ("-control-while", "-metric-whose").
    #
    # The corpus's own precedent bounds this: the widest existing sibling family
    # is aws-infra at 4 (core + -misc/-s3/-waf), and nothing exceeds ~6. So merge
    # any group below MERGE_FLOOR (3/4 of cap) into a compatible neighbour,
    # preferring the one it shares the most vocabulary with — keeping the split
    # semantic rather than reverting to size-packing.
    MERGE_FLOOR = cap * 3 // 4
    groups.sort(key=lambda g: g["size"])
    merged: list[dict] = []
    for g in groups:
        placed = False
        if g["size"] < MERGE_FLOOR:
            candidates = [h for h in merged if h["size"] + g["size"] <= cap]
            if candidates:
                # Best vocabulary overlap wins; size is the tiebreak, not the rule.
                best = max(candidates,
                           key=lambda h: (len(h["kw"] & g["kw"]), -h["size"]))
                best["units"] += g["units"]
                best["size"] += g["size"]
                best["kw"] |= g["kw"]
                placed = True
        if not placed:
            merged.append(g)
    for g in merged:
        c = Counter()
        for u in g["units"]:
            for w in keywords(u, 4):
                c[w] += 1
        g["name_hint"] = "-".join(w for w, _ in c.most_common(2)) or "misc"
    merged.sort(key=lambda g: -g["size"])
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    path = Path(args.file).expanduser()
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    preamble, units = parse_units(text, args.cap)
    if not units:
        print(f"{path.name}: no `##` sections — nothing to decompose", file=sys.stderr)
        return 1
    groups = cluster(units, args.cap)

    stem = path.stem
    plan = {
        "file": str(path),
        "bytes": len(text),
        "cap": args.cap,
        "units": len(units),
        "fragments": sum(1 for u in units if u["kind"] == "fragment"),
        "indivisible": [
            {"label": u["label"], "size": u["size"]}
            for u in units if u["kind"] == "indivisible"
        ],
        "siblings": [
            {
                "proposed": f"{stem}-{g['name_hint']}.md",
                "bytes": g["size"],
                "over_cap": g["size"] > args.cap,
                "sections": [u["label"][:78] for u in g["units"]],
            }
            for g in groups
        ],
    }
    plan["feasible"] = not any(s["over_cap"] for s in plan["siblings"])

    if args.json:
        print(json.dumps(plan, indent=2))
        return 0

    print(f"DECOMPOSITION PLAN — {path.name}  ({plan['bytes']:,}B, cap {args.cap:,})")
    print(f"  {plan['units']} packable units "
          f"({plan['fragments']} are ### fragments of over-cap sections)")
    print(f"  -> {len(plan['siblings'])} proposed siblings   "
          f"feasible: {plan['feasible']}\n")
    for s in plan["siblings"]:
        flag = "  OVER CAP" if s["over_cap"] else ""
        print(f"  {s['bytes']:>7,}B  {s['proposed']}{flag}")
        for sec in s["sections"][:5]:
            print(f"            - {sec}")
        if len(s["sections"]) > 5:
            print(f"            … {len(s['sections']) - 5} more")
        print()
    if plan["indivisible"]:
        print("  TRUE INDIVISIBLE (over cap, no ### seam — needs authorial editing):")
        for u in plan["indivisible"]:
            print(f"    {u['size']:>7,}B  {u['label'][:70]}")
        print()
    print("NEXT — the plan proves FEASIBILITY, not the taxonomy:")
    print("  1. RENAME every sibling. `name_hint` is co-occurring vocabulary, not")
    print("     a subject a reader would recognize. A topic's name must predict")
    print("     its contents or the split makes retrieval worse, not better.")
    print("  2. Re-bucket anything obviously misfiled — vocabulary overlap is a")
    print("     weak proxy for subject.")
    print("  3. Leave a hub pointer block in the core file naming each sibling.")
    print("  4. Add the new siblings to KNOWN_ARCHIVE_EXCEPTIONS in size_sweep.py,")
    print("     or the next sweep re-flags the products of this split as findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
