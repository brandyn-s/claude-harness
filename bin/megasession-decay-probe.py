#!/usr/bin/env python3
"""megasession-decay-probe.py — does self-inflicted error-rate rise with context-fill?

First-pass measurement for the unmeasured ~70% autocompact threshold (E13). Frontier
basis: the Entropy Principle (arXiv:2606.08162, S(t)=S0*e^(a*t)) + Context Rot predict
degradation rising with context length. This buckets every assistant turn in a
megasession by its context size (input + cache tokens at that turn) and reports the
error-rate per bucket. Rising error-rate in high-context buckets supports compacting
EARLIER than 70%; a flat curve says the threshold is fine.

CAVEAT: "error" here = a following tool_result with is_error (dominated by hook-blocks
and read-before-edit). That is a self-inflicted-FRICTION proxy, not pure model decay;
but if it rises with context-fill it is still a decay signal worth acting on. This is
E13 step 1 (observational); the full ACON-vs-fixed-threshold A/B is the follow-on.

Usage: python3 bin/megasession-decay-probe.py [days] [min_turns]
"""
import glob
import json
import os
import sys
import time

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
MINTURNS = int(sys.argv[2]) if len(sys.argv) > 2 else 300
PROJ = os.path.expanduser("~/.claude/projects/-Users-you")
CUTOFF = time.time() - DAYS * 86400
BUCKETS = [(0, 100_000), (100_000, 200_000), (200_000, 400_000),
           (400_000, 700_000), (700_000, 1_000_000), (1_000_000, 10_000_000)]
LABELS = ["<100k", "100-200k", "200-400k", "400-700k", "700k-1M", ">1M"]


def bidx(ctx):
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= ctx < hi:
            return i
    return len(BUCKETS) - 1


files = sorted(
    [f for f in glob.glob(PROJ + "/*.jsonl")
     if os.path.getmtime(f) >= CUTOFF and os.path.getsize(f) < 80_000_000],
    key=os.path.getmtime, reverse=True)

turns = [0] * len(BUCKETS)
errs = [0] * len(BUCKETS)
mega = 0
for f in files:
    rows = []
    last = None
    aturns = 0
    try:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:  # noqa: S112, BLE001 -- best-effort probe: skip unparseable JSONL lines
                    continue  # skip unparseable line
                t = r.get("type")
                msg = r.get("message") or {}
                if t == "assistant":
                    if not msg.get("model"):
                        continue
                    aturns += 1
                    u = msg.get("usage") or {}
                    ctx = ((u.get("input_tokens") or 0)
                           + (u.get("cache_read_input_tokens") or 0)
                           + (u.get("cache_creation_input_tokens") or 0))
                    rows.append([bidx(ctx), False])
                    last = len(rows) - 1
                elif t == "user" and last is not None:
                    c = msg.get("content")
                    if isinstance(c, list):
                        for b in c:
                            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                                rows[last][1] = True
    except Exception:  # noqa: S112, BLE001 -- best-effort probe: skip unreadable transcripts
        continue  # skip unreadable transcript
    if aturns >= MINTURNS:
        mega += 1
        for bk, err in rows:
            turns[bk] += 1
            if err:
                errs[bk] += 1

print(f"megasessions (>= {MINTURNS} assistant turns): {mega}  (window {DAYS}d)")
print(f"{'ctx-fill bucket':>16} | {'turns':>7} | {'err-turns':>9} | {'err-rate':>8}")
print("-" * 50)
for i in range(len(BUCKETS)):
    tc, ec = turns[i], errs[i]
    rate = f"{100*ec/tc:.1f}%" if tc else "n/a"
    print(f"{LABELS[i]:>16} | {tc:>7} | {ec:>9} | {rate:>8}")
lo = (errs[0] / turns[0] * 100) if turns[0] else 0
hi_idx = max((i for i in range(len(BUCKETS)) if turns[i]), default=0)
hi = (errs[hi_idx] / turns[hi_idx] * 100) if turns[hi_idx] else 0
print(f"\nlow-context err-rate={lo:.1f}%  highest-populated-bucket({LABELS[hi_idx]}) err-rate={hi:.1f}%")
print("decay signal" if hi > lo * 1.5 else "no strong decay-with-context signal (threshold likely OK)")
