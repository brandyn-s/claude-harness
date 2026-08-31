#!/usr/bin/env python3
"""Atomic per-session decision/acceptance ledger.

WHY THIS EXISTS
---------------
The 14-day review found 58 substantive corrective user turns, 35 of them
concentrated in six long sessions. The recurring themes were requirement drift: a
rejected constraint reintroduced later in a long conversation, promised
deliverables reported complete while incomplete, an evidence standard forgotten.

IMPORTANT SCOPING (red-team correction, preserved deliberately): that
concentration is REAL but its CAUSE is NOT established. Long sessions also carry
more exposure, more complex work, and more legitimate iteration. This module does
not assume compaction caused the corrections; it makes the acceptance state
DURABLE so the hypothesis becomes testable and the state survives regardless of
cause.

WHAT REPLACES WHAT
------------------
`hooks/precompact-checkpoint.py` writes a static hint ("Re-read CLAUDE.md, check
git status") plus session id and cwd. It carries no acceptance state, and nothing
reads it: SessionStart never loads it, so there is no rehydration path at all.
This module is the real replacement. The old checkpoint is deliberately left in
place for a dual-run parity window and is NOT removed by this change.

LIFECYCLE (contracts verified verbatim against code.claude.com 2026-07-26)
-------------------------------------------------------------------------
  PreCompact                  -> persist the ledger atomically
  SessionStart(source=compact)-> inject + reconcile the ledger into model context
  PostCompact                 -> AUDIT the compact_summary against the ledger

`PostCompact` deliberately does NOT rehydrate: it "Runs after Claude Code
completes a compact operation. Use this event to react to the new compacted
state, for example to log the generated summary or update external state." It has
no decision control and cannot inject model context. `SessionStart` is the
injection point, and its matcher values are exactly
`startup, resume, clear, compact, fork` -- so `compact` is a real matcher.

FAIL-OPEN IS INTENTIONAL
------------------------
`PreCompact` CAN block (exit 2 / {"decision":"block"}), but this module never
does. `precompact-checkpoint.py` documents why: auto-compaction fires near the
context limit, so blocking it turns a recoverable hiccup (disk full, transient
permission error) into a session-ending failure. A missing ledger is recoverable;
a blocked compaction is not. That prior decision is honoured here -- the ability
to fail closed is a capability, not a licence to use it.

WRITES ARE ATOMIC
-----------------
temp-file + os.replace, which is atomic on POSIX and Windows. A ledger torn
half-way through a write would be worse than an absent one, because a reader
cannot tell a truncated ledger from a complete one.

STORAGE
-------
One file per session under ~/.claude/session-ledgers/<session_id>.json, so
concurrent sessions cannot clobber each other. The audit found a shared tracked
file being read-modify-written on ordinary turn completion, which created the very
contention other guards then had to resolve (M10). Per-session files avoid that
class entirely.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

LEDGER_DIR = Path.home() / ".claude" / "session-ledgers"

SCHEMA = "session-ledger/1"

#: Ledger entry kinds. These are the states a later claim must map back to.
DELIVERABLE = "deliverable"   # something the user asked for
CONSTRAINT = "constraint"     # a requirement on HOW it must be done
REJECTED = "rejected"         # an option the user explicitly ruled out
EVIDENCE = "evidence"         # the evidence standard demanded
DECISION = "decision"         # a settled choice
OPEN_QUESTION = "open_question"

KINDS = (DELIVERABLE, CONSTRAINT, REJECTED, EVIDENCE, DECISION, OPEN_QUESTION)

#: Cap the ledger so it cannot grow into a context problem of its own.
MAX_ENTRIES = 200
MAX_TEXT = 500


def _safe_session_id(session_id) -> str:
    """Filesystem-safe session id.

    A session id reaches us from hook stdin, i.e. it is untrusted input for
    path-construction purposes. Anything outside [A-Za-z0-9._-] is stripped so a
    crafted value cannot traverse out of the ledger directory.
    """
    raw = str(session_id or "unknown")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "", raw)
    cleaned = cleaned.lstrip(".") or "unknown"
    return cleaned[:64]


def ledger_path(session_id, ledger_dir: Path | None = None) -> Path:
    base = Path(ledger_dir) if ledger_dir else LEDGER_DIR
    return base / f"{_safe_session_id(session_id)}.json"


def new_ledger(session_id, cwd: str = "") -> dict:
    return {
        "schema": SCHEMA,
        "session_id": _safe_session_id(session_id),
        "cwd": cwd,
        "created_ts": time.time(),
        "updated_ts": time.time(),
        "compaction_count": 0,
        "entries": [],
    }


def load(session_id, ledger_dir: Path | None = None) -> dict | None:
    """Read a ledger. Returns None when absent or unreadable.

    Unreadable is treated as absent on purpose: a corrupt ledger must degrade to
    "no acceptance state" rather than raising inside a lifecycle hook.
    """
    p = ledger_path(session_id, ledger_dir)
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    if not isinstance(data.get("entries"), list):
        return None
    return data


def save(ledger: dict, ledger_dir: Path | None = None) -> bool:
    """Atomically persist a ledger. Returns True on success, never raises.

    Atomic because a torn ledger is worse than an absent one: a reader cannot
    distinguish a truncated file from a complete one, so a partial write would
    silently present incomplete acceptance state as authoritative.
    """
    p = ledger_path(ledger.get("session_id"), ledger_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        ledger["updated_ts"] = time.time()
        payload = json.dumps(ledger, indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".ledger-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except Exception:
        # Fail OPEN. See the module docstring: blocking compaction is worse than
        # losing one checkpoint.
        return False


def add_entry(ledger: dict, kind: str, text: str, *, source: str = "") -> dict:
    """Append an entry, de-duplicating on (kind, normalized text).

    De-duplication matters because the same constraint restated across turns
    should not consume the entry budget, and a reader counting "how many
    constraints" should not see inflation.
    """
    if kind not in KINDS:
        kind = DECISION
    clean = " ".join(str(text or "").split())[:MAX_TEXT]
    if not clean:
        return ledger
    key = (kind, clean.lower())
    for existing in ledger.get("entries", []):
        if (existing.get("kind"), str(existing.get("text", "")).lower()) == key:
            existing["restated"] = int(existing.get("restated", 0)) + 1
            existing["updated_ts"] = time.time()
            return ledger
    entries = ledger.setdefault("entries", [])
    entries.append({
        "kind": kind,
        "text": clean,
        "source": source,
        "added_ts": time.time(),
        "restated": 0,
        "satisfied": None,   # None = unknown; True/False set explicitly
    })
    # Keep the newest MAX_ENTRIES, but never drop a REJECTED entry to make room:
    # a forgotten rejection is the specific failure this ledger exists to prevent.
    if len(entries) > MAX_ENTRIES:
        rejected = [e for e in entries if e.get("kind") == REJECTED]
        others = [e for e in entries if e.get("kind") != REJECTED]
        keep = others[-(MAX_ENTRIES - len(rejected)):] if len(rejected) < MAX_ENTRIES else []
        ledger["entries"] = rejected + keep
    return ledger


def mark_compaction(ledger: dict) -> dict:
    ledger["compaction_count"] = int(ledger.get("compaction_count", 0)) + 1
    ledger["last_compaction_ts"] = time.time()
    return ledger


def render_for_injection(ledger: dict) -> str:
    """Render the ledger as model-facing context.

    Ordering is deliberate: REJECTED first. The documented failure mode is
    reintroducing an option the user already ruled out, so that section must not
    be the one truncated or skimmed.
    """
    if not ledger:
        return ""
    entries = ledger.get("entries") or []
    if not entries:
        return ""

    order = [REJECTED, CONSTRAINT, DELIVERABLE, EVIDENCE, DECISION, OPEN_QUESTION]
    labels = {
        REJECTED: "EXPLICITLY REJECTED — do not reintroduce",
        CONSTRAINT: "CONSTRAINTS",
        DELIVERABLE: "REQUIRED DELIVERABLES",
        EVIDENCE: "EVIDENCE STANDARD",
        DECISION: "SETTLED DECISIONS",
        OPEN_QUESTION: "OPEN QUESTIONS",
    }

    lines = [
        "## Acceptance ledger (recovered after compaction)",
        "",
        f"Compactions so far: {ledger.get('compaction_count', 0)}. "
        "This is the durable record of what was asked, ruled out, and settled. "
        "Reconcile any completion claim against it; if an item below conflicts "
        "with the compact summary, THIS LEDGER IS AUTHORITATIVE for user intent.",
    ]
    for kind in order:
        group = [e for e in entries if e.get("kind") == kind]
        if not group:
            continue
        lines.append("")
        lines.append(f"### {labels[kind]}")
        for e in group:
            mark = ""
            if e.get("satisfied") is True:
                mark = " [satisfied]"
            elif e.get("satisfied") is False:
                mark = " [NOT satisfied]"
            restated = e.get("restated") or 0
            emphasis = f" (restated {restated}x)" if restated else ""
            lines.append(f"- {e.get('text', '')}{mark}{emphasis}")
    return "\n".join(lines)


def audit_against_summary(ledger: dict, compact_summary: str) -> dict:
    """Compare a compact summary against the ledger. Read-only, no side effects.

    This is what PostCompact can legitimately do: it cannot inject context or
    block, but it CAN observe that the summary dropped a rejected option or an
    open question, which is exactly the drift signal worth recording.

    Matching is TOKEN CONTAINMENT, not contiguous substring: an entry counts as
    present when its significant words all appear somewhere in the summary.

    A contiguous-substring probe does not work here and was a false-positive
    generator when first written (caught 2026-07-26 by
    test_audit_finds_nothing_missing_when_summary_covers_everything). Stripping
    short words from the ENTRY but not the SUMMARY made it search for
    "produce handoff document" inside "produce the handoff document", which fails
    on any intervening stop word -- so nearly every multi-word entry reported as
    dropped, including the `rejected_dropped` alarm. An audit signal that always
    fires trains operators to ignore it, which would bury a real dropped
    rejection. Summarization also reorders and rewords by design, so contiguity
    was the wrong property to test for.

    It remains a SIGNAL, not a verdict -- a genuinely-preserved item can be
    paraphrased past recognition.
    """
    entries = (ledger or {}).get("entries") or []
    hay_tokens = set(re.findall(r"[a-z0-9]+", str(compact_summary or "").lower()))
    missing = []
    for e in entries:
        text = str(e.get("text", ""))
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3]
        probe = words[:4]
        if probe and not set(probe).issubset(hay_tokens):
            missing.append({"kind": e.get("kind"), "text": text})
    return {
        "total_entries": len(entries),
        "not_found_in_summary": missing,
        "rejected_dropped": [m for m in missing if m["kind"] == REJECTED],
        "summary_chars": len(compact_summary or ""),
    }
