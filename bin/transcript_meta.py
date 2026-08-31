#!/usr/bin/env python3
"""transcript_meta.py — mega-retro META-ANALYSIS pass (the distill-grade reduce stage).

WHY this exists: mega-retro's per-chunk extractors are context-ISOLATED — each subagent sees only
its ~60-record chunk, with no view of the rule corpus, prior sessions, or the other chunks. So they
structurally CANNOT produce distill's signature META findings (measured 2026-06-21: 1 rule-gap and
0 why-was-I-wrong across 976 findings). distill produces those by LOOKING UP the session's events
against the rest of the architecture (grep rules/*.md, memory_search prior sessions, cross-cutting
sibling-repo grep). That lookup can only happen at REDUCE time, where full context + repo access
exist. This is that stage.

Two parts:
  PART 1 (this script, deterministic): the recurrence signal is ALREADY computed by
    transcript_reduce.py's structural clustering — a cluster with count>=N means an event fired N
    times. distill normally has to INFER recurrence from memory; we hand it the count. Elevate every
    recurring cluster to a META candidate: "X fired Nx -> the guard/habit/rule must change, not just
    be noted." Also emit the rule-gap cross-reference WORKLIST: the synthesized errors_failures
    findings that a meta agent should grep the rule corpus against.
  PART 2 (the skill's meta agent, separate): take this worklist, grep rules/*.md +
    agent-memory/topics/*.md + memory_search prior sessions per finding, and answer distill's
    question: "was there a rule that should have caught this (T1 update)? has this failed before
    (cross-session)? does it correct a skill (SKILL-routed)?" That agent has repo + memory access;
    the chunk-extractors did not.

Usage:
  python3 transcript_meta.py --prep <prep-artifact.json> --final <FINAL-findings-artifact.json> \
      --recur-threshold 3 --out <meta-worklist.json>
"""
from __future__ import annotations

import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prep", required=True, help="prep-artifact.json (has structural clusters + counts)")
    ap.add_argument("--final", required=True, help="FINAL synthesized findings artifact")
    ap.add_argument("--recur-threshold", type=int, default=3,
                    help="cluster count >= this is elevated as a recurrence meta-finding")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    prep = json.load(open(args.prep, encoding="utf-8"))
    final = json.load(open(args.final, encoding="utf-8"))
    findings = final["findings"] if isinstance(final, dict) and "findings" in final else final

    # PART 1a — elevate recurring clusters to META findings. The structural clustering already
    # counted them; a recurrence IS the lesson (distill: "the recurrence itself means the guard or
    # habit must change"). These are the highest-confidence meta-findings and cost zero LLM.
    recurrence_meta = []
    for c in prep.get("clusters", []):
        if c.get("count", 0) >= args.recur_threshold:
            recurrence_meta.append({
                "kind": "recurrence",
                "signature": c["signature"],
                "bucket": c["bucket"],
                "count": c["count"],
                "representative": c["representative"],
                "first_ground": c.get("first_ground"),
                "meta_question": (
                    f"This event fired {c['count']}x in one session. A one-off is friction; "
                    f"{c['count']}x means the guard/habit/rule should CHANGE (re-tune the guard, "
                    f"add a rule, or fix the recurring habit) — not just be noted per-occurrence."
                ),
            })
    recurrence_meta.sort(key=lambda m: -m["count"])

    # PART 1b — build the rule-gap cross-reference worklist: the synthesized error/abandoned
    # findings a meta agent must grep the rule corpus against. We pass them through with their
    # remediation fields (root_cause/proposed_fix/tier_hint/target_hint) when present, plus a
    # distilled set of grep-able keywords so the agent's corpus search is targeted.
    rulegap_worklist = []
    for f in findings:
        if f.get("_bucket") not in ("errors_failures", "abandoned_approaches"):
            continue
        if f.get("for") not in ("distill", "both"):
            continue
        rulegap_worklist.append({
            "summary": f.get("summary"),
            "ground": f.get("ground"),
            "root_cause": f.get("root_cause"),
            "proposed_fix": f.get("proposed_fix"),
            "tier_hint": f.get("tier_hint"),
            "target_hint": f.get("target_hint"),
        })

    out = {
        "session": final.get("summary", {}).get("session") if isinstance(final, dict) else "",
        "recurrence_threshold": args.recur_threshold,
        "recurrence_meta_findings": recurrence_meta,
        "rulegap_worklist_size": len(rulegap_worklist),
        "rulegap_worklist": rulegap_worklist,
    }
    json.dump(out, open(args.out, "w", encoding="utf-8"), indent=2)

    print(f"recurrence meta-findings (count >= {args.recur_threshold}): {len(recurrence_meta)}")
    for m in recurrence_meta:
        print(f"  {m['count']:>3}x [{m['bucket']}] {m['signature']} -> guard/rule should change")
    print(f"\nrule-gap cross-reference worklist (for the meta agent): {len(rulegap_worklist)} findings")
    print(f"meta worklist -> {args.out}")


if __name__ == "__main__":
    main()
