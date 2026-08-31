#!/usr/bin/env python3
"""transcript_friction.py — mega-distill corpus-mode Phase A1: deterministic friction extractor.

The cheap, fabrication-proof half of corpus-mode. Streams ONE session transcript and extracts
FRICTION EVENTS — the recurring failures, blocks, corrections, and stalls that show "what I keep
getting stuck on" — into NORMALIZED SIGNATURES, emitting a per-session histogram. No LLM: every
signature is a deterministic regex match, so a corpus-wide aggregation of these counts cannot
fabricate (the recurrence ranking it feeds is auditable down to the session id).

WHY signatures, not raw bodies (FLAW-3 lesson from transcript_reduce.py): a recurring friction
EVENT carries a unique body each time — `bash-security-guard blocked <different command>` 37×, each
naming a different command. Exact-body counting scatters one recurring class into 37 singletons.
The signature captures the EVENT CLASS (which guard / hook / error / correction), stripping the
volatile instance detail, so the 37 collapse to one count of 37 — which is the actual signal.

Friction sources (grounded in real transcript bodies, eff98a2f sample 2026-06-20):
  - tool_result with is_error  -> classify the error body (hook block, read-before-edit, EPERM,
    timeout, classifier-denied, command-failed, mcp-hook-block, ...)
  - user messages that are CORRECTIONS (short rebukes / "no" / "that's wrong" / "I'm tired of") —
    the highest-value friction, since a correction means I did the wrong thing
  - compaction boundaries (context-loss events; counted, not a "failure" but a session-shape signal)

Emits ONE JSON record for this session: {session, path, mtime, events_total, signatures: {sig:count},
plus a few example bodies per signature for auditability}. transcript_recurrence.py (Phase A2)
aggregates these across the corpus into the breadth-ranked table.

Usage:
  python3 transcript_friction.py <transcript.jsonl> [--examples 2]
    -> prints one JSON object to stdout (one session's friction record)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# ── Signature taxonomy ─────────────────────────────────────────────────────────────────────────
# Each (regex, signature) pair maps an error/correction body to a coarse EVENT CLASS. Order matters:
# first match wins, so put specific patterns before general ones. Seeded from transcript_reduce.py's
# _SIGNATURES and grounded in real eff98a2f error bodies (top classes: bash-security-guard 37x,
# tail-buffering 19x, read-before-edit 15x, timeout 20x). Anything unmatched falls to a generic
# bucket keyed by a normalized prefix, so the long tail is still counted (never silently dropped).

_ERROR_SIGNATURES = [
    # Hook/guard blocks (PreToolUse) — the body names the hook script.
    (re.compile(r"bash-security-guard", re.I),            "guard:bash-security"),
    (re.compile(r"bash-tail-buffering|\|\s*(tail|head|grep)\b", re.I), "guard:tail-buffering"),
    (re.compile(r"inline[- ]python|python -c", re.I),     "guard:inline-python"),
    (re.compile(r"encoding[- ]?guard|cp1252|encoding=.{0,3}utf", re.I), "guard:encoding"),
    (re.compile(r"staged-additions-guard", re.I),         "guard:staged-additions"),
    (re.compile(r"write-edit-dispatche|Agent.*protected|targets protected repo", re.I), "guard:agent-dispatch"),
    (re.compile(r"worktree-enforcement", re.I),           "guard:worktree-enforcement"),
    (re.compile(r"commit-guard|commit to main|never_commit", re.I), "guard:commit-to-main"),
    (re.compile(r"exfiltration[- ]?guard", re.I),         "guard:exfiltration"),
    (re.compile(r"credential[- ]?guard|curl.*verbose", re.I), "guard:credential"),
    (re.compile(r"PreToolUse:.*hook error", re.I),        "guard:other-pretooluse-hook"),
    # Read-before-edit / write gate (harness-level, not a hook).
    (re.compile(r"has not been read yet|modified since|read it first", re.I), "gate:read-before-edit"),
    # Permission / classifier denials.
    (re.compile(r"auto mode classifier|safety classifier|vets bash", re.I), "deny:bash-classifier"),
    (re.compile(r"doesn'?t want to proceed|tool use was rejected|user (denied|rejected)", re.I), "deny:user-rejected-tool"),
    (re.compile(r"Permission.*denied by", re.I),          "deny:permission"),
    # Filesystem / OS errors.
    (re.compile(r"EPERM|operation not permitted", re.I),  "fs:eperm"),
    (re.compile(r"File does not exist|no such file|not a file", re.I), "fs:file-not-found"),
    (re.compile(r"ENOENT|EACCES|EEXIST", re.I),           "fs:other-errno"),
    # Process control.
    (re.compile(r"timed out|timeout|Exit code 143", re.I), "proc:timeout"),
    (re.compile(r"Exit code [1-9]", re.I),                "proc:nonzero-exit"),
    # MCP / network.
    (re.compile(r"No such tool available|tool not found", re.I), "mcp:tool-unavailable"),
    (re.compile(r"Connection error|ECONNREFUSED|connection refused|disconnect", re.I), "net:connection"),
    (re.compile(r"rate limit|429|throttl", re.I),         "net:rate-limit"),
]

# User-correction detection. A correction is a SHORT user turn that rebukes / redirects. We keep this
# conservative: long user turns are usually new instructions, not corrections. The phrase set is
# grounded in this corpus's real corrections ("I'm tired of going back and forth", "that's wrong",
# "no, ...", "stop"). A correction is the highest-value friction because it means I did the wrong
# thing and the user had to intervene.
_CORRECTION_PHRASES = re.compile(
    r"\b(that'?s (wrong|incorrect|not right)|you'?re wrong|no,? (that|this|don'?t|stop|it'?s)|"
    r"that is not what|not what i (asked|meant|wanted)|i'?m tired of|going back and forth|"
    r"stop (doing|that)|why (did|would) you|you (keep|already|just|still)|"
    r"i (already )?(told|said|asked) you|read (it|the|my)|you didn'?t|you failed to|"
    r"that'?s not|do it (again|right|properly)|undo|revert that|wrong (repo|file|branch|approach))",
    re.I,
)
# A user turn longer than this many chars is treated as a fresh instruction, not a correction,
# even if it contains a rebuke phrase (it's carrying too much new content to be a pure correction).
_CORRECTION_MAX_CHARS = 600


def _strip_volatile(s):
    """Remove instance-specific substrings so signature grouping is stable across occurrences:
    absolute paths, hex ids, PIDs, line:col, timestamps, quoted commands."""
    s = re.sub(r"/[^\s'\"]+", "<path>", s)                  # absolute/relative paths
    s = re.sub(r"\b[0-9a-f]{7,40}\b", "<hex>", s)           # sha / hex ids
    s = re.sub(r"\b\d{2,}\b", "<n>", s)                     # multi-digit numbers (pids, line nos)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def classify_error(body):
    """Map an error tool_result body to a signature. Falls through to a normalized-prefix bucket so
    the long tail is counted (never dropped)."""
    for rx, sig in _ERROR_SIGNATURES:
        if rx.search(body):
            return sig
    # Unmatched: bucket by a stripped, lowercased 6-word prefix so similar uncategorized errors group.
    prefix = " ".join(_strip_volatile(body).lower().split()[:6])
    return f"error:other:{prefix}" if prefix else "error:other:empty"


def _text_blocks(content):
    """Yield text strings from a message 'content' field (str or list-of-blocks)."""
    if isinstance(content, str):
        if content.strip():
            yield content
        return
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text") or ""
                if t.strip():
                    yield t


def _error_bodies(content):
    """Yield error tool_result bodies from a message 'content' list."""
    if not isinstance(content, list):
        return
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
            body = b.get("content", "")
            if isinstance(body, list):
                body = " ".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in body)
            yield str(body)


def extract(path, n_examples=2):
    """Stream one transcript; return its friction record."""
    sigs = {}            # signature -> count
    examples = {}        # signature -> [example bodies] (capped at n_examples)
    counts = {"error": 0, "correction": 0, "compaction": 0}

    def bump(sig, body):
        sigs[sig] = sigs.get(sig, 0) + 1
        if len(examples.setdefault(sig, [])) < n_examples:
            examples[sig].append(_strip_volatile(body)[:200])

    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                r = json.loads(raw)
            except Exception:
                continue
            if r.get("isCompactSummary"):
                counts["compaction"] += 1
                bump("session:compaction-boundary", "[compaction]")
                continue
            t = r.get("type")
            msg = r.get("message") or {}
            content = msg.get("content")
            # Error tool_results (can appear on user-type records, since results are user-role).
            for body in _error_bodies(content):
                counts["error"] += 1
                bump(classify_error(body), body)
            # User corrections.
            if t == "user":
                for txt in _text_blocks(content):
                    if len(txt) <= _CORRECTION_MAX_CHARS and _CORRECTION_PHRASES.search(txt):
                        counts["correction"] += 1
                        bump("correction:user-rebuke", txt)
                        break  # one correction per turn

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    session = os.path.basename(path).replace(".jsonl", "")
    events_total = sum(sigs.values())
    return {
        "session": session,
        "path": path,
        "mtime": mtime,
        "events_total": events_total,
        "counts": counts,
        "signatures": dict(sorted(sigs.items(), key=lambda kv: -kv[1])),
        "examples": examples,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--examples", type=int, default=2,
                    help="example bodies to retain per signature (for auditability)")
    args = ap.parse_args()
    if not os.path.isfile(args.transcript):
        print(f"not a file: {args.transcript}", file=sys.stderr)
        sys.exit(2)
    rec = extract(args.transcript, args.examples)
    print(json.dumps(rec))


if __name__ == "__main__":
    main()
