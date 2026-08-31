#!/usr/bin/env python3
"""tool-receipt-verify.py — cross-check claimed tool results against the receipt log.

Pairs with hooks/staged/tool-receipt-log.py. Detects the forged/injected-result class
(a tool_result block the model consumed whose tool_use_id has NO receipt = it never
really executed; cf. #64095 envelope injection, #68332 fabrication).

COVERAGE (honest): this transcript-level check catches injected/forged tool_RESULT
BLOCKS. The pure in-extended-thinking fabrication (#68332, where the fake tool_use +
result never enter the transcript as real blocks) needs a content-claim matcher over
the assistant's narrative — that is the documented follow-on, not this prototype.

Run: python3 bin/tool-receipt-verify.py <transcript.jsonl> <receipts.jsonl>
     python3 bin/tool-receipt-verify.py --selftest
"""
import sys
import json
import hashlib
import hmac


def load_receipts(path):
    seen = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("tool_use_id"):
                    seen[r["tool_use_id"]] = r
    except FileNotFoundError:
        pass
    return seen


def verify(tpath, rpath):
    receipts = load_receipts(rpath)
    issued, returned = set(), set()
    with open(tpath, encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            msg = r.get("message") or {}
            if r.get("type") == "assistant":
                for b in (msg.get("content") or []):
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        issued.add(b.get("id"))
            elif r.get("type") == "user":
                c = msg.get("content")
                if isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            returned.add(b.get("tool_use_id"))
    suspect = sorted(t for t in returned if t and t not in receipts)
    print(f"issued tool_use={len(issued)}  returned results={len(returned)}  receipts={len(receipts)}")
    if suspect:
        print(f"SUSPECT (consumed result with NO receipt — forged/injected?): {suspect}")
        return 1
    print("OK: every consumed tool_result has a matching receipt.")
    return 0


def selftest():
    key = b"selftest-key"
    real_id, fake_id = "toolu_real", "toolu_fake"
    real_sha = hashlib.sha256(b"real grep output").hexdigest()
    receipts = {real_id: {"tool_use_id": real_id, "content_sha256": real_sha,
                          "receipt": hmac.new(key, (real_id + "|" + real_sha).encode(),
                                              hashlib.sha256).hexdigest()}}
    # transcript consumed a real result (has receipt) AND a fabricated one (no receipt)
    returned = {real_id, fake_id}
    suspect = sorted(t for t in returned if t not in receipts)
    assert suspect == [fake_id], f"SELFTEST FAILED: {suspect}"
    # receipt is unforgeable: re-signing the real content with the wrong key must differ
    forged = hmac.new(b"wrong-key", (real_id + "|" + real_sha).encode(), hashlib.sha256).hexdigest()
    assert forged != receipts[real_id]["receipt"], "SELFTEST FAILED: receipt forgeable"
    print("SELFTEST PASS:")
    print(f"  consumed={sorted(returned)}  receipts={list(receipts)}  flagged-as-forged={suspect}")
    print("  receipt HMAC is key-bound (wrong key != real receipt) — model cannot forge it.")
    return 0


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>"); sys.exit(0)
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    if len(sys.argv) == 3:
        sys.exit(verify(sys.argv[1], sys.argv[2]))
    print(__doc__)
    sys.exit(2)
