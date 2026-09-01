#!/usr/bin/env python3
"""Read the shadow-mode completion-claim log and print its distribution.

This report refuses to recommend a gate until the sample can support one. The
whole reason the observer exists is that the original proposal rested on a count
with no denominator; a report that turned 3 rows into a recommendation would
reproduce that error with better formatting.
"""
import argparse
import json
import os
import sys

LOG = os.path.expanduser("~/.claude/state/completion-claims.jsonl")
MIN_SAMPLE = 100      # below this, report the distribution and decline to advise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", default=LOG)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.log):
        print(f"no log at {args.log} -- the observer has not run yet.\n"
              f"Wire hooks/completion-claim-observer.py to the Stop event, then "
              f"work normally for a while.")
        return 1

    rows, malformed = [], 0
    with open(args.log, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                malformed += 1          # counted, never silently skipped

    n = len(rows)
    unread = sum(1 for r in rows if not r.get("transcript_read"))
    readable = [r for r in rows if r.get("transcript_read")]
    claims = [r for r in readable if r.get("claimed_done")]
    with_ev = [r for r in claims if r.get("evidence_in_tool_output")]
    prose_only = [r for r in claims if r.get("evidence_in_prose_only")]
    bare = [r for r in claims if not r.get("evidence_in_tool_output")
            and not r.get("evidence_in_prose_only")]

    if args.json:
        print(json.dumps({
            "turns": n, "malformed_lines": malformed,
            "readable_turns": len(readable),
            "turns_with_unreadable_transcript": unread,
            "completion_claims": len(claims),
            "claims_with_tool_evidence": len(with_ev),
            "claims_with_prose_evidence_only": len(prose_only),
            "claims_with_no_evidence": len(bare),
            "sample_sufficient": len(readable) >= MIN_SAMPLE and bool(claims),
        }, indent=2))
        return 0

    print(f"turns observed              : {n:,}")
    if malformed:
        print(f"  malformed log lines       : {malformed} (reported, not skipped)")
    if unread:
        print(f"  turns w/ unreadable tail  : {unread} "
              f"({100*unread/max(1,n):.0f}%) -- these cannot support a verdict")
    print(f"completion claims           : {len(claims):,}"
          f"  ({100*len(claims)/max(1,n):.0f}% of turns)")
    if claims:
        print(f"  with tool-output evidence : {len(with_ev):,} "
              f"({100*len(with_ev)/len(claims):.0f}%)")
        print(f"  prose evidence only       : {len(prose_only):,} "
              f"({100*len(prose_only)/len(claims):.0f}%)")
        print(f"  NO evidence in the turn   : {len(bare):,} "
              f"({100*len(bare)/len(claims):.0f}%)")

    print()
    if len(readable) < MIN_SAMPLE or not claims:
        reason = (
            f"{len(readable)} readable < {MIN_SAMPLE}"
            if len(readable) < MIN_SAMPLE
            else "no completion claims detected"
        )
        print(f"SAMPLE NOT USABLE ({reason}). No recommendation.")
        print("This is the point of the observer: the proposal it exists to test")
        print("was rejected for resting on a count with no denominator. Reporting")
        print("a rate from a handful of turns would repeat that error.")
        return 0
    rate = len(bare) / len(claims) if claims else 0.0
    print(f"unverified-claim rate: {rate:.1%} over {len(readable):,} readable turns")
    print("Interpretation is the operator's: this tool measures, it does not gate.")
    print("A low rate is evidence the ambient verification rules are working and")
    print("no gate is warranted. A high rate is the first real basis for one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
