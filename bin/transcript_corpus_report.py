#!/usr/bin/env python3
"""transcript_corpus_report.py — mega-distill corpus-mode Phase C1+C4: merge layers + ranked report.

Merges the two layers into ONE breadth-ranked cross-session report:
  Layer 1 (friction spine, transcript_recurrence.py output): deterministic signature breadth over the
    FULL corpus (1209 sessions).
  Layer 2 (semantic clusters, B5-verified clusters): LLM-derived prose-pattern breadth over the >1MB
    cohort (97 sessions).

Each row is LABELED with its cohort + denominator so breadth is never misread across layers
(grading-discipline: don't collapse incomparable axes). The report also classifies each pattern for
the ship step (C2/C3): does an existing rule already cover it? (the skill's ship step greps rules/).

Emits corpus_report.md (human) + corpus_report.json (machine). The coverage line is mandatory.

Usage:
  python3 transcript_corpus_report.py --friction friction_recurrence.json \
      --clusters clusters_verified.json --friction-cohort 1209 --semantic-cohort 97 \
      --out-md corpus_report.md --out-json corpus_report.json
"""
from __future__ import annotations

import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--friction", required=True)
    ap.add_argument("--clusters", required=True)
    ap.add_argument("--friction-cohort", type=int, required=True)
    ap.add_argument("--semantic-cohort", type=int, required=True)
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    friction = json.load(open(args.friction, encoding="utf-8"))
    clusters = json.load(open(args.clusters, encoding="utf-8"))
    fc = friction.get("clusters", [])
    sc = clusters.get("clusters", [])

    # Layer 1 rows (deterministic signature breadth, full corpus)
    frows = [{
        "layer": "friction", "name": c["signature"], "breadth": c["breadth"],
        "cohort": args.friction_cohort, "pct": round(100.0 * c["breadth"] / args.friction_cohort, 1),
        "total": c["total"],
    } for c in fc]

    # Layer 2 rows (semantic clusters, >1MB cohort) — skip the honest 'None' catch-all from headline
    srows = []
    for c in sc:
        breadth = c.get("breadth", len(set(m.split("::")[0] for m in c.get("members", []))))
        name = c.get("name") or "uncategorized"   # the agent's catch-all cluster has a null name
        srows.append({
            "layer": "semantic", "name": name, "breadth": breadth,
            "cohort": args.semantic_cohort, "pct": round(100.0 * breadth / args.semantic_cohort, 1),
            "lessons": len(c.get("members", [])),
            "root_cause": c.get("root_cause", ""), "proposed_fix": c.get("proposed_fix", ""),
            "tier_hint": c.get("tier_hint", "none"),
            "is_uncategorized": name.lower() in ("none", "null", "uncategorized", ""),
        })

    frows.sort(key=lambda r: -r["pct"])
    srows.sort(key=lambda r: -r["pct"])

    report = {
        "friction_cohort": args.friction_cohort,
        "semantic_cohort": args.semantic_cohort,
        "coverage": (f"Friction spine: {args.friction_cohort}/{args.friction_cohort} (100%). "
                     f"Semantic layer: {args.semantic_cohort}/{args.friction_cohort} (>1MB cohort); "
                     f"{args.friction_cohort - args.semantic_cohort} smaller sessions covered by "
                     f"friction spine only."),
        "friction_rows": frows,
        "semantic_rows": srows,
    }
    json.dump(report, open(args.out_json, "w", encoding="utf-8"), indent=2)

    lines = []
    lines.append("# mega-distill corpus-mode — cross-session recurrence report\n")
    lines.append(f"> {report['coverage']}\n")
    lines.append("\n## Layer 1 — Friction spine (deterministic, full corpus)\n")
    lines.append("Signature breadth across ALL sessions (no LLM). Breadth = distinct sessions.\n")
    lines.append("\n| breadth | %corpus | total | signature |")
    lines.append("|---:|---:|---:|---|")
    for r in frows:
        lines.append(f"| {r['breadth']}/{r['cohort']} | {r['pct']}% | {r['total']} | `{r['name']}` |")
    lines.append("\n## Layer 2 — Semantic patterns (LLM, >1MB cohort, gated)\n")
    lines.append("Prose meta-patterns the signature spine cannot see. Breadth = distinct sessions in the >1MB cohort.\n")
    lines.append("\n| breadth | %cohort | lessons | pattern | tier |")
    lines.append("|---:|---:|---:|---|---|")
    for r in srows:
        tag = " _(uncategorized)_" if r["is_uncategorized"] else ""
        lines.append(f"| {r['breadth']}/{r['cohort']} | {r['pct']}% | {r['lessons']} | "
                     f"{r['name']}{tag} | {r['tier_hint']} |")
    with open(args.out_md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(report["coverage"])
    print(f"\nLayer 1 (friction): {len(frows)} signatures; top = {frows[0]['name']} "
          f"({frows[0]['breadth']}/{frows[0]['cohort']})" if frows else "no friction rows")
    print(f"Layer 2 (semantic): {len(srows)} clusters; top = {srows[0]['name']} "
          f"({srows[0]['breadth']}/{srows[0]['cohort']})" if srows else "no semantic rows")
    print(f"\nreport: {args.out_md} + {args.out_json}")


if __name__ == "__main__":
    main()
