#!/usr/bin/env python3
"""classifier-fallback-audit.py — measure WHAT triggers Fable 5 -> Opus 4.8 fallback.

Context: the 2026-06-14 transcript mine measured 46.5% of agent turns running on
Opus 4.8 (the reasoning-amplified fallback). This audits the *trigger* of each
Fable->Opus transition: a security/cyber-keyword prompt implicates the Fable
cyber-safety classifier (#67107/#66641/#67006); no keyword + mid-task implicates
a capacity fallback (#66822).

PROXY/LIMITATION: the classifier scores the full message-in-flight (prompt + tool
results + history), but this script keys only on the most-recent USER prompt text.
So "security-keyword present" is a LOWER BOUND on classifier-driven fallback
(tool-result-content triggers, e.g. a Grep returning CVE text, are not counted).

Usage: python3 bin/classifier-fallback-audit.py [days] [project_dir]
"""
import glob
import json
import os
import re
import sys
import time
from collections import Counter

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
PROJ = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser(
    "~/.claude/projects/-Users-you")
CUTOFF = time.time() - DAYS * 86400

SEC = re.compile(
    r"\b(cve|stig|srg|exploit|vulnerab\w*|malware|payload|attack(er)?|threat|adversar\w+|"
    r"\bc2\b|ransomware|backdoor|rootkit|crowdstrike|tenable|airlock|semgrep|codeql|"
    r"pentest|red[ -]?team|offensive|shellcode|reverse shell|privilege escalation|"
    r"lateral movement|\bioc\b|yara|sigma rule|mitre|att&ck|exfil\w*|\bsbom\b|owasp|"
    r"injection|\bxss\b|\bsqli\b|\brce\b|\bcsrf\b|\bssrf\b|cwe-\d+|threat model|"
    r"prompt injection|jailbreak|decrypt|cyber)\b", re.IGNORECASE)


def user_text(content):
    out = []
    if isinstance(content, str):
        out.append(content)
    elif isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                out.append(b.get("text", ""))
    return " ".join(out)


files = sorted(
    [f for f in glob.glob(PROJ + "/*.jsonl")
     if os.path.getmtime(f) >= CUTOFF and os.path.getsize(f) < 80_000_000],
    key=os.path.getmtime, reverse=True)

transitions = []   # (session, trigger_snippet, sec_hit)
whole_opus = mixed = whole_fable = 0
for f in files:
    sid = os.path.basename(f)[:8]
    last_user = ""
    prev = None
    seen = set()
    try:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:  # noqa: S112, BLE001 -- best-effort probe: skip unparseable JSONL lines
                    continue  # skip unparseable line
                t = r.get("type")
                msg = r.get("message") or {}
                if t == "user":
                    c = msg.get("content")
                    is_tr = isinstance(c, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
                    if not is_tr:
                        tx = user_text(c)
                        if tx and not tx.startswith(
                                ("<system-reminder", "<command-", "Caveat:", "[Request")):
                            last_user = tx
                elif t == "assistant":
                    m = msg.get("model")
                    if not m:
                        continue
                    seen.add(m)
                    if prev == "claude-fable-5" and m == "claude-opus-4-8":
                        transitions.append(
                            (sid, last_user[:160].replace("\n", " "), bool(SEC.search(last_user))))
                    prev = m
    except Exception:  # noqa: S112, BLE001 -- best-effort probe: skip unreadable transcripts
        continue  # skip unreadable transcript
    nonsynth = {x for x in seen if not x.startswith("<")}
    if nonsynth == {"claude-opus-4-8"}:
        whole_opus += 1
    elif "claude-fable-5" in nonsynth and "claude-opus-4-8" in nonsynth:
        mixed += 1
    elif nonsynth and "claude-opus-4-8" not in nonsynth:
        whole_fable += 1

n = len(transitions)
sec = sum(1 for _, _, s in transitions if s)
print(f"window={DAYS}d  files={len(files)}  fable->opus transitions={n}")
print(f"  trigger prompt has security/cyber keyword (classifier-implicated): {sec} ({100*sec/max(n,1):.0f}%)  [LOWER BOUND]")
print(f"  no security keyword in trigger prompt (capacity-fallback candidate): {n-sec} ({100*(n-sec)/max(n,1):.0f}%)")
print(f"session model composition: whole-opus-4.8={whole_opus}  mixed={mixed}  whole-fable(no opus)={whole_fable}")

kw = Counter()
for _, snip, _ in transitions:
    for mm in SEC.finditer(snip):
        kw[mm.group(0).lower()] += 1
print("\ntop trigger keywords:")
for k, c in kw.most_common(12):
    print(f"  {k}: {c}")

print("\nsample security-triggered transitions:")
for sid, snip, s in [t for t in transitions if t[2]][:8]:
    print(f"  [{sid}] {snip}")
print("\nsample non-security transitions (capacity-fallback candidates):")
for sid, snip, s in [t for t in transitions if not t[2]][:8]:
    print(f"  [{sid}] {snip}")
