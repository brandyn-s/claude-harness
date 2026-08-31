#!/usr/bin/env python3
"""tool-receipt-scan.py — retrospective forged/injected tool-RESULT scan over local transcripts.

The decision-gate companion to bin/tool-receipt-verify.py and hooks/staged/tool-receipt-log.spec.md.
The verifier needs a receipt LOG (only exists once the hook is enabled), so it cannot measure
HISTORICAL transcripts. This script computes the receipt-equivalent: had the hook been running,
every issued tool_use would have a receipt, so the issued-id set == the receipt set. An orphan
(a consumed tool_result whose tool_use_id was never issued) is the #64095/#68332 injected-result
signature — measurable directly from the transcript, no receipts needed.

Parsing mirrors verify() in tool-receipt-verify.py exactly. Reports orphans two ways:
  per-file  — returned id with no issued match in the SAME file
  global    — returned id with no issued match in the UNION of all files (conservative; immune
              to cross-file/sidechain id splitting). The global rate is the decision-gate number.

COVERAGE (honest): the transcript-visible injected-RESULT-BLOCK class only. The pure
in-extended-thinking #68332 (fake tool_use never enters the transcript as a real block) needs a
content-claim matcher over the narrative — the documented follow-on, not this scan.

Run: python3 bin/tool-receipt-scan.py            # scans ~/.claude/projects/*/*.jsonl
     python3 bin/tool-receipt-scan.py <dir>      # scans <dir>/*.jsonl
"""
import glob
import json
import os
import sys


def parse_file(path):
    """Return (issued_ids set, returned_ids list). Mirrors verify()'s parse."""
    issued, returned = set(), []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            msg = r.get("message") or {}
            t = r.get("type")
            if t == "assistant":
                for b in (msg.get("content") or []):
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id"):
                        issued.add(b["id"])
            elif t == "user":
                c = msg.get("content")
                if isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id"):
                            returned.append(b["tool_use_id"])
    return issued, returned


def main():
    if len(sys.argv) == 2:
        files = sorted(glob.glob(os.path.join(sys.argv[1], "*.jsonl")))
    else:
        files = sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")))
    if not files:
        print("no transcripts found")
        return 2

    parsed = {}
    global_issued = set()
    total_issued = total_returned = 0
    for p in files:
        issued, returned = parse_file(p)
        parsed[p] = (issued, returned)
        global_issued |= issued
        total_issued += len(issued)
        total_returned += len(returned)

    perfile_orphans = 0
    global_orphans = []
    for p, (issued, returned) in parsed.items():
        perfile_orphans += sum(1 for t in returned if t not in issued)
        for t in returned:
            if t not in global_issued:
                global_orphans.append((os.path.basename(p), t))

    g_rate = (len(global_orphans) / total_returned * 100) if total_returned else 0.0
    pf_rate = (perfile_orphans / total_returned * 100) if total_returned else 0.0
    print(f"transcripts={len(files)}  issued={total_issued}  consumed_results={total_returned}  unique_issued={len(global_issued)}")
    print(f"PER-FILE orphans : {perfile_orphans} ({pf_rate:.3f}%)")
    print(f"GLOBAL  orphans  : {len(global_orphans)} ({g_rate:.4f}%)   <-- decision-gate number")
    if global_orphans:
        print("GLOBAL orphans (consumed result, tool_use_id never issued anywhere):")
        for fn, tid in global_orphans[:40]:
            print(f"   {fn}  {tid}")
        if len(global_orphans) > 40:
            print(f"   ... +{len(global_orphans) - 40} more")
        print(f"\nforged-result warn-rate = {g_rate:.4f}%  -> evaluate per-tool-call overhead vs this rate.")
        return 1
    print("GLOBAL orphans: NONE — every consumed tool_result traces to a real issued call.")
    print("forged-result warn-rate = 0.0000% -> ~0 -> hook STAYS STAGED (spec gate).")
    return 0


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>"); sys.exit(0)
    sys.exit(main())
