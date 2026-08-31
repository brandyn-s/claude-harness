#!/usr/bin/env python3
"""PostCompact hook: audit the generated compact summary against the ledger.

WHAT PostCompact CAN AND CANNOT DO (verified verbatim, code.claude.com 2026-07-26)
---------------------------------------------------------------------------------
  "Runs after Claude Code completes a compact operation. Use this event to react
   to the new compacted state, for example to log the generated summary or update
   external state."

It has NO decision control and CANNOT inject model context. So this hook does not
and cannot rehydrate anything -- rehydration happens in
`SessionStart(source=compact)`. Treating PostCompact as a rehydration point was
one of the review recommendations the red team correctly retracted; this hook is
the legitimate use: audit + external state.

WHAT IT RECORDS
---------------
Whether each ledger entry still appears in the compact summary, with dropped
REJECTED entries called out separately -- reintroducing an already-rejected option
is the specific documented failure mode. The result is appended to a per-session
audit log for later analysis, never written into the conversation.

The comparison is token containment and is a SIGNAL, not a verdict: an entry that
was paraphrased or stemmed differently reads as missing. See
`session_ledger.audit_against_summary` for the documented limitation.

Fails open and silent: an audit hook must never disrupt a session.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import session_ledger as sl
except Exception:
    sl = None

AUDIT_DIR = Path.home() / ".claude" / "session-ledgers" / "audits"


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    if sl is None:
        sys.exit(0)

    session_id = data.get("session_id") or "unknown"
    # Field name per the hooks reference; tolerate variants rather than assume.
    summary = (
        data.get("compact_summary")
        or data.get("summary")
        or ""
    )

    try:
        ledger = sl.load(session_id)
        if not ledger:
            sys.exit(0)

        report = sl.audit_against_summary(ledger, summary)
        report["session_id"] = ledger.get("session_id")
        report["compaction_count"] = ledger.get("compaction_count", 0)
        report["audited_ts"] = time.time()
        report["trigger"] = data.get("trigger") or data.get("matcher")

        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(report, sort_keys=True)
        with open(
            AUDIT_DIR / f"{ledger.get('session_id')}.jsonl", "a", encoding="utf-8"
        ) as fh:
            fh.write(line + "\n")

        # Surface only the case that matters operationally: a rejection the
        # summary no longer mentions. Everything else stays in the log.
        dropped = report.get("rejected_dropped") or []
        if dropped:
            msg = (
                f"[postcompact-audit] {len(dropped)} explicitly-rejected item(s) "
                "no longer appear in the compact summary; the acceptance ledger is "
                "authoritative for user intent."
            )
            print(json.dumps({"systemMessage": msg}))
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
