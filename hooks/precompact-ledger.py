#!/usr/bin/env python3
"""PreCompact hook: persist the acceptance ledger before compaction.

DUAL-RUN, NOT A REPLACEMENT
---------------------------
This runs ALONGSIDE `precompact-checkpoint.py` for a parity window. The old
checkpoint writes a static hint with no acceptance state and has no consumer;
this writes the durable ledger that `session-start.py` rehydrates on
`source=compact`. Nothing is removed until the new path is proven in practice --
per the remediation plan, remove old hooks only after measured parity.

FAILS OPEN, ALWAYS
------------------
`PreCompact` can block (exit 2 / {"decision":"block"}), and this hook never uses
that. Auto-compaction fires near the context limit, so blocking it converts a
recoverable hiccup (disk full, transient permission error) into a session-ending
failure -- the rationale already documented in `precompact-checkpoint.py`. A
missing ledger is recoverable; a blocked compaction is not.

WHAT IT CAN AND CANNOT CAPTURE
------------------------------
A PreCompact hook receives session metadata, not the conversation. It therefore
CANNOT infer deliverables or rejected options on its own. Its job is to:

  * ensure a ledger file exists for this session,
  * stamp the compaction event and count,
  * preserve whatever entries were recorded during the session.

Entries are written by whatever records acceptance state during the session (a
skill, an explicit tool call, or a future UserPromptSubmit-side recorder). This
hook is the DURABILITY half, not the extraction half -- claiming otherwise would
be the "heuristic-as-telemetry" anti-pattern the review named.
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


def _session_id_fallback() -> tuple[str, str]:
    """Recover (session_id, cwd) when this hook's stdin arrived EMPTY.

    WHY THIS IS NEEDED — the stdin-drain race (proven 2026-07-29):
    two hooks are registered on PreCompact and run SERIALLY over ONE shared
    stdin pipe:

        [0] precompact-checkpoint.py   -> does sys.stdin.read()
        [1] precompact-ledger.py       -> this file

    `.read()` consumes the WHOLE stream, so the second hook sees EOF and
    `json.load` raises -> `data = {}`. Measured consequence: 113 of 113 audit
    records and the sole ledger file all carried `session_id="unknown"`, with
    `trigger=null` and `summary_chars=0` — every session collapsing into one
    shared `unknown.json` with a merged `compaction_count` of 114, destroying
    the per-session isolation the ledger exists to provide.

    Reproduced directly:
        echo '{"session_id":"X"}' | { python3 a.py; python3 b.py; }
        a.py -> len=57      b.py -> len=0

    `hooks/run-hook` cannot help: it passes the inherited fd straight through
    (`"$@"`) with no buffering or replay. Registration order is also not ours
    to rely on, so this hook must tolerate an empty payload rather than assume
    it is first.

    The sibling checkpoint hook writes the SAME two fields it just consumed to
    `~/.claude/.precompact-state.json`, so when our stdin is empty we read them
    back from there. Freshness-gated: a stale checkpoint from a previous
    compaction would mislabel this one, which is worse than "unknown".
    """
    state = Path.home() / ".claude" / ".precompact-state.json"
    try:
        st = json.loads(state.read_text(encoding="utf-8"))
    except Exception:
        return "unknown", ""
    ts = st.get("timestamp")
    if not isinstance(ts, (int, float)) or (time.time() - ts) > 120:
        # Not from this compaction event — do not attribute to it.
        return "unknown", ""
    return (str(st.get("session_id") or "unknown"), str(st.get("cwd") or ""))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}

    if sl is None:
        sys.exit(0)

    session_id = data.get("session_id") or "unknown"
    cwd = data.get("cwd") or ""

    # Our stdin may have been drained by an earlier hook on this same event
    # (see _session_id_fallback). Recover rather than write "unknown".
    if session_id == "unknown":
        session_id, fb_cwd = _session_id_fallback()
        cwd = cwd or fb_cwd

    try:
        ledger = sl.load(session_id)
        if ledger is None:
            ledger = sl.new_ledger(session_id, cwd=cwd)
        sl.mark_compaction(ledger)
        ok = sl.save(ledger)
        if not ok:
            print(
                "[precompact-ledger] WARN: ledger write failed; compaction proceeds "
                "(fail-open by design)",
                file=sys.stderr,
            )
    except Exception as exc:  # never block compaction
        try:
            print(f"[precompact-ledger] WARN: {type(exc).__name__}", file=sys.stderr)
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
