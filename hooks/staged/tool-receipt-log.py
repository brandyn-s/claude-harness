#!/usr/bin/env python3
"""tool-receipt-log.py — PostToolUse hook: HMAC-signed receipts of REAL tool results.

STAGED PROTOTYPE — NOT wired into settings.json. Defense against the live Opus-4.8
tool-result fabrication class (#68332, ~46.5% of turns on the fabrication-amplified
fallback model per 2026-06-14). The model can fabricate a tool RESULT, but it cannot
forge an HMAC receipt of a real execution. `tool-receipt-verify.py` cross-checks claimed
results against this log: a consumed tool_result with no receipt = forged/injected.

Inspired by NabaOS (arXiv:2603.10060, signed tool-execution receipts, 94.2% catch @ <15ms).
Advisory only — never blocks (exit 0). Set CLAUDE_TOOL_RECEIPT_KEY to a secret the model
never sees (hook env, NOT context) for a real deployment; otherwise a session-derived dev
key is used (forgeable — prototype only).
"""
import sys
import json
import os
import hashlib
import hmac
import time


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tuid = data.get("tool_use_id") or data.get("toolUseId") or ""
    resp = data.get("tool_response", data.get("tool_result", ""))
    if not isinstance(resp, (str, bytes)):
        resp = json.dumps(resp, sort_keys=True, ensure_ascii=False, default=str)
    if isinstance(resp, str):
        resp = resp.encode("utf-8", "replace")
    content_sha = hashlib.sha256(resp).hexdigest()
    sid = data.get("session_id", "unknown")
    env_key = os.environ.get("CLAUDE_TOOL_RECEIPT_KEY", "").encode()
    key = env_key or hashlib.sha256((sid + "|receipt-proto-dev-key").encode()).digest()
    receipt = hmac.new(key, (tuid + "|" + content_sha).encode(), hashlib.sha256).hexdigest()
    logdir = os.path.expanduser("~/.claude/logs")
    try:
        os.makedirs(logdir, exist_ok=True)
        rec = {"ts": time.time(), "session_id": sid, "tool_use_id": tuid,
               "tool_name": data.get("tool_name", ""), "content_sha256": content_sha,
               "receipt": receipt, "keyed": bool(env_key)}
        with open(os.path.join(logdir, f"tool-receipts-{sid}.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
