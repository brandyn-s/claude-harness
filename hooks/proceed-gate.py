#!/usr/bin/env python3
"""UserPromptSubmit hook: keep the frame in force when the prompt is shorter than it.

THE PROBLEM
    A third of this week's prompts were bare continuations -- `proceed`,
    `continue`, `Do it all`, `fix 1, 2 and 4`. Each hands the model a decision the
    human never stated: what "it" is, what is out of scope, and what would show it
    worked. The 14-day ledger review found corrections concentrating in long
    sessions with "a rejected constraint reintroduced later"; without a written
    frame there is nothing to check a continuation against. `session_ledger.py`
    exists to hold that frame -- session-start.py rehydrates it after every
    compaction -- but until this hook nothing in the tree wrote to it (the
    precompact-ledger / postcompact-audit producers named in consistency.py are
    not in this repository).

WHAT IT DOES (three cheap behaviours; every path exits 0)
    1. Bare continuation      -> inject a restatement contract: before executing,
                                 state DO / NOT / CHECK, then proceed.
    2. First substantive ask  -> if the working directory has no INTENT.md, nudge
                                 /frame ONCE per session. Questions never trigger it.
    3. INTENT.md present      -> ingest its Done-when / Non-goals / Constraints
                                 bullets into the session ledger (kinds deliverable /
                                 rejected / constraint) once per content hash, so the
                                 ledger that SessionStart already rehydrates after a
                                 compaction finally has a producer.

CONTRACT
    exit 0 always. On UserPromptSubmit a non-zero exit ERASES the user's prompt,
    so every path is guarded. Plain-text stdout on this event becomes context the
    model can see and act on (same mechanism as compaction-continuity.py).

STATE
    One JSON file per session under ~/.claude/run/proceed-gate/, written with
    os.replace. Losing it costs one repeated nudge, never a prompt.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "run" / "proceed-gate"
HOOKS_DIR = Path(__file__).resolve().parent
MAX_CONTINUATION_CHARS = 60

# "proceed", "ok go ahead", "Do it all", "fix 1, 2 and 4", "1,2,3", "yes, continue."
_LEAD = r"(?:(?:ok(?:ay)?|yes|y|yep|yeah|sure|please|pls|go|alright|great|good|fine|sounds good|lgtm)[\s,.!]*)*"
_VERBS = (
    r"proceed|continue|go ahead|go on|carry on|keep going|do it|do (?:it |them |that )?all|"
    r"do all of (?:it|them|those)|fix (?:it|them|those|all|everything|all of (?:it|them|those))|"
    r"implement (?:it|them|all|those|everything)|apply (?:it|them|all|those)|all of (?:it|them|those)|"
    r"next|ship it|make it so|finish (?:it|them|up)|"
    r"(?:do|fix|implement|apply|address|handle)\s+(?:#?\d+(?:\s*(?:,|and|&|-|to|\+)\s*#?\d+)*)"
)
CONTINUATION_RX = re.compile(rf"^\s*{_LEAD}(?:{_VERBS})[\s.!]*$", re.IGNORECASE)
NUMBERS_ONLY_RX = re.compile(r"^\s*#?\d+(?:\s*(?:,|and|&|-|to|\+)\s*#?\d+)*[\s.!]*$")

IMPERATIVE_RX = re.compile(
    r"\b(build|implement|create|add|refactor|migrate|write|design|set up|setup|fix|make|"
    r"convert|integrate|deploy|port|replace|rewrite|wire|ship|extend|automate|generate)\b",
    re.IGNORECASE,
)
META_RX = re.compile(
    r"^\s*(explain|help me understand|what (is|are|does)|why |how (does|do|is)|tell me about|"
    r"summari[sz]e|describe|compare|review|assess|analy[sz]e)",
    re.IGNORECASE,
)

# INTENT.md section -> ledger kind. Matched case-insensitively on heading text.
SECTION_KINDS = (
    (re.compile(r"done[\s-]*when|done[\s-]*criteria|acceptance", re.I), "deliverable"),
    (re.compile(r"non[\s-]*goals?|not doing|out of scope|we will not", re.I), "rejected"),
    (re.compile(r"constraints?|must|requirements?", re.I), "constraint"),
    (re.compile(r"stays? human|human owns|human decides", re.I), "constraint"),
    (re.compile(r"riskiest|assumption|open question", re.I), "open_question"),
)
BULLET_RX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?(.+?)\s*$")
HEADING_RX = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")


def _state_path(session_id) -> Path:
    safe = "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_") or "unknown"
    return STATE_DIR / f"{safe}.json"


def _load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:  # state is advisory; never let it cost a prompt
        print(f"proceed-gate: state write failed: {exc}", file=sys.stderr)


def is_bare_continuation(prompt: str) -> bool:
    p = (prompt or "").strip()
    if not p or len(p) > MAX_CONTINUATION_CHARS or p.startswith("/"):
        return False
    return bool(CONTINUATION_RX.match(p) or NUMBERS_ONLY_RX.match(p))


def is_substantive_ask(prompt: str) -> bool:
    """An imperative request for work, as opposed to a question, a slash command,
    a meta question about the harness, or a continuation."""
    p = (prompt or "").strip()
    if not p or p.startswith("/") or p.endswith("?") or META_RX.match(p):
        return False
    if is_bare_continuation(p):
        return False
    return len(p) >= 60 or bool(IMPERATIVE_RX.search(p))


def parse_intent(text: str) -> list[tuple[str, str]]:
    """Return (kind, text) pairs from INTENT.md bullets under known headings."""
    out: list[tuple[str, str]] = []
    kind = None
    for line in text.splitlines():
        h = HEADING_RX.match(line)
        if h:
            kind = None
            for rx, k in SECTION_KINDS:
                if rx.search(h.group(1)):
                    kind = k
                    break
            continue
        if kind is None:
            continue
        b = BULLET_RX.match(line)
        if b:
            item = b.group(1).strip()
            if item and not item.lower().startswith(("tbd", "todo", "…", "...")):
                out.append((kind, item))
    return out


def ingest_intent(cwd: str, session_id: str, state: dict) -> int:
    """Feed INTENT.md into the session ledger once per content hash. Returns count."""
    intent = Path(cwd or ".") / "INTENT.md"
    try:
        text = intent.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    if state.get("intent_sha") == digest:
        return 0
    entries = parse_intent(text)
    state["intent_sha"] = digest
    if not entries:
        return 0
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import session_ledger as sl  # type: ignore
    except Exception:
        return 0
    try:
        ledger = sl.load(session_id) or sl.new_ledger(session_id, cwd)
        before = len(ledger.get("entries", []))
        for kind, item in entries[:40]:
            sl.add_entry(ledger, kind, item, source="INTENT.md")
        if not sl.save(ledger):
            return 0
        return len(ledger.get("entries", [])) - before
    except Exception as exc:
        print(f"proceed-gate: ledger ingest skipped: {exc}", file=sys.stderr)
        return 0


RESTATE = (
    "<proceed-gate>\n"
    "This prompt is a bare continuation ({shown}). It delegates a decision the user did "
    "not state. Before executing, restate in at most six lines:\n"
    "  DO    - what you will do now, as the concrete outcome, not the activity.\n"
    "  NOT   - what you will not do (non-goals; nearby fixes you are leaving alone).\n"
    "  CHECK - the command or observation that shows each DO item is done.\n"
    "Then execute without waiting. Ask one question only if the restatement exposes two "
    "readings of the request. If INTENT.md exists, DO and NOT must agree with its "
    "Done-when and Non-goals; if the ledger holds a REJECTED entry the plan touches, say so.\n"
    "</proceed-gate>"
)

FRAME_NUDGE = (
    "<frame-nudge>\n"
    "No INTENT.md in {cwd}. For work with more than one slice, run /frame first: problem, "
    "checkable done-when, non-goals, riskiest assumption, what stays human. It takes two "
    "minutes and gives every later `proceed` something to be checked against. For a single "
    "small change, skip this. (Shown once per session.)\n"
    "</frame-nudge>"
)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if payload.get("hook_event_name") not in (None, "UserPromptSubmit"):
        return 0
    prompt = str(payload.get("prompt") or "")
    cwd = str(payload.get("cwd") or os.getcwd())
    sid = str(payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "unknown")

    path = _state_path(sid)
    state = _load_state(path)
    state["prompts"] = int(state.get("prompts", 0)) + 1
    out: list[str] = []

    if is_bare_continuation(prompt):
        shown = prompt.strip()
        shown = f'"{shown[:24]}…"' if len(shown) > 25 else f'"{shown}"'
        out.append(RESTATE.format(shown=shown))

    has_intent = (Path(cwd) / "INTENT.md").is_file()
    if not has_intent and not state.get("frame_nudged") and is_substantive_ask(prompt):
        state["frame_nudged"] = True
        out.append(FRAME_NUDGE.format(cwd=cwd))

    if has_intent:
        n = ingest_intent(cwd, sid, state)
        if n:
            out.append(f"<proceed-gate>Ledger: {n} INTENT.md item(s) recorded as acceptance state.</proceed-gate>")

    _save_state(path, state)
    if out:
        print("\n".join(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never let this hook erase a prompt
        print(f"proceed-gate: {exc}", file=sys.stderr)
        sys.exit(0)
