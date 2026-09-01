#!/usr/bin/env python3
"""Shadow-mode observer: does a completion claim carry verification evidence?

MEASURES, NEVER BLOCKS. This hook exists to produce a denominator, because the
argument it would eventually support cannot be made without one.

Background: the ambient corpus spends more on "verify before claiming done" than
on any other concern, and none of it has mechanical backing. The tempting move is
a Stop hook that blocks an unverified completion claim. The evidence for that move
was a count of hook BLOCKS with no denominator -- survivorship logic, rejected by
an adversarial review. This hook supplies what was missing:

    per Stop event: claimed_done? verification_evidence_in_same_turn?

Read the resulting distribution with bin/completion-claim-report.py. If claims
without evidence turn out to be rare, no gate is warranted and the ambient spend
is doing its job. If they are common, there is now a measured basis for one.

Design constraints, deliberately narrow:
  * exit 0 unconditionally; no `decision` key; nothing is ever blocked
  * append-only JSONL under the operator's own state dir; no network
  * a parse failure is silent (a broken observer must not break a session)
  * transcript read is bounded to the tail; a long session must not stall Stop
"""
import json
import os
import re
import sys

STATE = os.path.expanduser("~/.claude/state")
LOG = os.path.join(STATE, "completion-claims.jsonl")
TAIL_BYTES = 256 * 1024          # bounded read: Stop must stay fast

# Negation and hedge cues. A completion phrase inside one of these is NOT a
# claim -- it is the opposite. Qualification measured this: "I would need to run
# the suite before saying anything is fixed" matched `is fixed` and was recorded
# as a claim, an error that inflates the unverified-claim rate and so flatters
# the hypothesis this observer exists to test. A literal list, not a cleverness,
# so a reader can see what is excluded.
NEGATION = re.compile(
    r"\b(?:not|n't|never|no|without|before|until|unless|cannot|can't|"
    r"would\s+need|need\s+to|should|must|todo|unverified|unconfirmed|"
    r"claim(?:s|ing|ed)?\s+that|assume|assuming|if\s+it|once\s+it|"
    r"haven'?t|hasn'?t|isn'?t|aren'?t|don'?t|doesn'?t|didn'?t)\b", re.I)
NEG_WINDOW = 90        # chars of preceding clause to inspect


def _is_negated(text, start):
    """Is the clause leading up to `start` negating or hedging the claim?"""
    left = text[max(0, start - NEG_WINDOW):start]
    # Only the CURRENT clause matters -- a negation two sentences back does not
    # negate this one. Cut at the nearest sentence or clause boundary.
    for sep in (". ", "! ", "? ", "\n", "; ", " -- ", " — "):
        idx = left.rfind(sep)
        if idx != -1:
            left = left[idx + len(sep):]
    return bool(NEGATION.search(left))


# A completion claim in the assistant's own voice. Deliberately narrow: these are
# the phrasings that assert a finished outcome, not ones that describe a plan.
CLAIM = re.compile(
    r"\b(?:"
    r"(?:it|that|this|everything)\s+(?:now\s+)?works\b"
    r"|all\s+(?:tests|checks)\s+pass(?:ing|ed)?\b"
    r"|(?:is|are)\s+(?:now\s+)?(?:fixed|working|complete|done|shipped|deployed)\b"
    r"|(?:successfully|fully)\s+(?:fixed|implemented|deployed|verified)\b"
    r"|verified\s+(?:working|complete|clean)\b"
    r")", re.I)

# Evidence that something was actually exercised in the same turn. Tool-result
# shapes and command names, not prose about verification.
EVIDENCE = re.compile(
    r"\b(?:"
    r"\d+\s+passed\b|\d+\s+failed\b|exit(?:ed)?\s+(?:code\s+)?0\b|rc=0\b"
    r"|pytest\b|npm\s+test\b|go\s+test\b|cargo\s+test\b"
    r"|curl\s+-|HTTP/\d|status(?:Code)?[\"']?\s*[:=]\s*2\d\d"
    r"|git\s+log\b|git\s+status\b|--check\b"
    r")", re.I)


def read_tail(path):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()          # discard a partial line
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def last_turn_text(raw):
    """Assistant text plus tool results since the last user message."""
    assistant, tools = [], []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        message = rec.get("message") or {}
        role = message.get("role") or rec.get("type")
        content = message.get("content")
        if role == "user":
            # Claude transcripts encode tool results as user-role messages.
            # Those are continuations of the current human turn, not new turns.
            result_blocks = [
                blk for blk in content
                if isinstance(content, list)
                and isinstance(blk, dict)
                and blk.get("type") == "tool_result"
            ] if isinstance(content, list) else []
            if result_blocks:
                for blk in result_blocks:
                    value = blk.get("content")
                    tools.append(
                        value if isinstance(value, str) else json.dumps(value)[:4000]
                    )
            else:
                assistant, tools = [], []  # a new human turn began
            continue
        if isinstance(content, str):
            assistant.append(content)
        elif isinstance(content, list):
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "text":
                    assistant.append(blk.get("text") or "")
    return "\n".join(assistant), "\n".join(tools)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0                          # a broken observer stays silent

    transcript = payload.get("transcript_path") or ""
    raw = read_tail(transcript) if transcript and os.path.exists(transcript) else ""
    said, tool_out = last_turn_text(raw)

    # A match only counts when its own clause is not negating or hedging it.
    claimed = any(not _is_negated(said, m.start()) for m in CLAIM.finditer(said))
    # Evidence counts from tool OUTPUT primarily; prose mentioning "pytest" is
    # not evidence that pytest ran. Assistant text is checked only as a weaker
    # secondary signal and recorded separately so the two never merge.
    ev_tool = bool(EVIDENCE.search(tool_out))
    ev_prose = bool(EVIDENCE.search(said))

    row = {
        "session": payload.get("session_id"),
        "claimed_done": claimed,
        "evidence_in_tool_output": ev_tool,
        "evidence_in_prose_only": (ev_prose and not ev_tool),
        "turn_chars": len(said),
        "tool_output_chars": len(tool_out),
        "transcript_read": bool(raw),
    }
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass
    return 0                              # NEVER blocks


if __name__ == "__main__":
    sys.exit(main())
