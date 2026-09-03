#!/usr/bin/env python3
"""SessionStart module: inject the acceptance ledger after a compaction.

THE MISSING CONSUMER
--------------------
The former `precompact-checkpoint.py` (deleted 2026-09-03, never wired) wrote
`~/.claude/.precompact-state.json` for a long time, and NOTHING ever read it:
SessionStart had no reader, so there was no rehydration path at all. That
checkpoint's own docstring said "the instructions
re-injected by the echo command reference this file", but no such consumer exists
in the tree. This module is that consumer, for the real ledger.

WHY SessionStart AND NOT PostCompact
------------------------------------
`PostCompact` cannot inject model context (verified verbatim: it is for reacting
to the compacted state, e.g. logging the summary or updating external state).
`SessionStart` is the injection point, and its documented matcher values are
exactly `startup, resume, clear, compact, fork` -- so a compaction genuinely
re-enters through SessionStart with `source == "compact"`.

SCOPED TO source == "compact" (and "resume"/"fork")
--------------------------------------------------
Injecting acceptance state into a brand-new `startup` session would be wrong: the
ledger belongs to a different conversation and would read as this session's
requirements. Compaction, resume and fork all continue an existing session, so the
ledger is in-scope there.

Returns ("", "") when there is nothing to inject, so the caller can skip cleanly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import session_ledger as sl
except Exception:  # pragma: no cover - module must never break session start
    sl = None

#: Sources that CONTINUE an existing conversation. `startup` and `clear` start a
#: fresh one, so a prior ledger must not be presented as its requirements.
CONTINUATION_SOURCES = frozenset({"compact", "resume", "fork"})


def run_ledger_rehydrate(session_id, source: str = "") -> tuple[str, str]:
    """Return (additional_context, banner_summary).

    Never raises: a failure here must not prevent a session from starting.
    """
    if sl is None:
        return "", ""
    if str(source or "").lower() not in CONTINUATION_SOURCES:
        return "", ""
    try:
        ledger = sl.load(session_id)
        if not ledger:
            return "", ""
        rendered = sl.render_for_injection(ledger)
        if not rendered:
            return "", ""
        entries = ledger.get("entries") or []
        rejected = sum(1 for e in entries if e.get("kind") == sl.REJECTED)
        summary = (
            f"Acceptance ledger restored ({len(entries)} item(s)"
            + (f", {rejected} explicitly rejected" if rejected else "")
            + f") after {ledger.get('compaction_count', 0)} compaction(s)."
        )
        return rendered, summary
    except Exception:
        return "", ""
