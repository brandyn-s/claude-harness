#!/usr/bin/env python3
"""
guardrail_corpus.py — build an on-demand corpus of safeguard / guardrail hits
from local Claude Code session transcripts.

Scans ~/.claude/projects/**/*.jsonl and extracts every event where a safeguard
or guardrail fired, with the model that was in use, the triggering prompt/context,
timestamp, category, and the block message. Three tiers are captured:

  Tier 1  model_safeguard    Anthropic's API-level cyber/bio safeguards
                             (subtype=model_refusal_fallback / _no_fallback,
                              apiRefusalCategory + apiRefusalExplanation).
                             Carries originalModel + fallbackModel verbatim.
  Tier 2  auto_mode_classifier  The harness Bash safety classifier
                             ("... temporarily unavailable, auto mode cannot
                              determine safety of Bash").
  Tier 3  hook_guardrail     Local PreToolUse hook denials (bash-security-guard,
                             worktree-enforcement, etc.). Best-effort match; the
                             raw snippet is kept so every hit is auditable.

Outputs (durable, under ~/Documents/reports/guardrails/):
  guardrail-corpus.jsonl        one JSON row per event (full fields)
  guardrail-corpus-report.md    human-readable summary + timeline

Usage:
  python3 guardrail_corpus.py                 # all transcripts, all tiers
  python3 guardrail_corpus.py --since 2026-07-01
  python3 guardrail_corpus.py --tier model_safeguard
  python3 guardrail_corpus.py --projects-dir ~/.claude/projects --out ~/Documents/reports/guardrails
"""
import argparse
import glob
import json
import os
import re
from datetime import datetime, timezone

try:
    import fcntl  # Unix-only. These tools run on the macOS host; Windows CI only
except ImportError:  # imports the module for tests, where advisory locking no-ops
    fcntl = None

HOME = os.path.expanduser("~")
DEFAULT_PROJECTS = os.path.join(HOME, ".claude", "projects")
DEFAULT_OUT = os.path.join(HOME, "Documents", "reports", "guardrails")

MODEL_SAFEGUARD_SUBTYPES = {"model_refusal_fallback", "model_refusal_no_fallback"}

# Tier 2 — auto-mode Bash safety classifier
CLASSIFIER_RE = re.compile(
    r"(auto mode cannot determine safety|cannot determine safety of|"
    r"temporarily unavailable, auto mode)", re.IGNORECASE)

# Tier 3 — local hook denials. Match the harness's structured block SHAPES only
# (H1): the "PreToolUse:X hook error: … BLOCKED" envelope, or "blocked by … hook",
# or "Permission denied by … hook". A bare matcher-name substring like
# "PreToolUse:Bash" or "bash-security-guard" appears in settings/logs/docs with
# no block occurring — matching it produced ~48% false positives.
HOOK_RE = re.compile(
    r"(?:Pre|Post)ToolUse:\S+\s+hook error:[^\n]*?BLOCKED"
    r"|blocked by (?:the |a |deployed )?[\w\-.]+ hook"
    r"|Permission denied by [\w\-.]+ hook", re.IGNORECASE)
_HOOK_MATCHER_RE = re.compile(r"(?:Pre|Post)ToolUse:\S+", re.IGNORECASE)
# Exclude rows that are clearly documentation/source, not a live block. The
# source/rule markers (re.compile, *_RE, topic filenames) also keep the auto-mode
# CLASSIFIER phrase from matching rule files and this scanner's own source (H2).
HOOK_DOC_EXCLUDE = re.compile(r"(GUARD pattern=|@rule |SKILL\.md|FORBIDDEN:|"
                              r"# WHY|manifest\.yaml|re\.compile|CLASSIFIER_RE|"
                              r"HOOK_RE|platform-constraints|diagnose-before-fix)", re.IGNORECASE)

# Security vocabulary the cyber classifier is reported to key on (community
# issue tracker: #61646, #66449, #64230, HN 48752030). Used to estimate how
# "security-shaped" the accumulated session context was at block time — a proxy
# for the context-accumulation trigger, NOT a claim of causation.
SEC_VOCAB = [
    "exploit", "vulnerabilit", "cve", "malware", "payload", "exfiltrat",
    "ransomware", "reverse-engineer", "reverse engineer", "offensive", "pentest",
    "penetration test", "credential", "backdoor", "rootkit", "shellcode",
    "privilege escalation", "decrypt", "bypass", "injection", "firmware",
    "gdb", "ps aux", "debugger", "profiler", "threat model", "attack", "c2",
    "beacon", "keylog", "brute force", "port scan", "nmap", "metasploit",
    "vfio", "kernel", "hardcoded", "secret", "token", "api key", "leak",
]
SEC_VOCAB_RE = re.compile("|".join(re.escape(w) for w in SEC_VOCAB), re.IGNORECASE)


def load_rows(path):
    out = []
    try:
        with open(path, "r", errors="replace", encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return out


def text_of(row):
    """Best-effort plain text of a transcript row's message content."""
    msg = row.get("message") or {}
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for x in c:
            if isinstance(x, dict):
                if x.get("type") == "text" and x.get("text"):
                    parts.append(x["text"])
                elif x.get("type") == "tool_result":
                    tc = x.get("content")
                    if isinstance(tc, str):
                        parts.append(tc)
                    elif isinstance(tc, list):
                        parts.extend(p.get("text", "") for p in tc
                                     if isinstance(p, dict))
        return " ".join(p for p in parts if p)
    return ""


def is_tool_result(row):
    msg = row.get("message") or {}
    c = msg.get("content")
    if isinstance(c, list):
        return any(isinstance(x, dict) and x.get("type") == "tool_result"
                   for x in c)
    return False


def is_real_user_prompt(row):
    """A human-authored user turn (not a tool_result, not a skill preamble)."""
    if row.get("type") != "user":
        return False
    if is_tool_result(row):
        return False
    t = text_of(row)
    if not t:
        return False
    # skill invocations arrive as user rows; skip their boilerplate preamble
    if t.startswith("Base directory for this skill:") or t.startswith("<task-notification>"):
        return False
    # slash-command plumbing (/retro, /ship, …) and the local-command wrappers
    # are harness-injected, not human prompts — they misattribute the block's
    # narrative and pollute the accumulation signals (A2).
    if t.lstrip().startswith(("<command-message>", "<command-name>",
                              "<local-command-stdout>", "<local-command-caveat>")):
        return False
    # compaction-continuation rows re-embed a whole prior-session summary
    # (~150KB) as if it were one user turn — never a real prompt.
    if "This session is being continued from a previous conversation" in t[:200]:
        return False
    return True


def nearest_prompt(rows, i):
    for j in range(i - 1, -1, -1):
        if is_real_user_prompt(rows[j]):
            return text_of(rows[j]).strip()
    return None


def nearest_active_model(rows, i, self_model=None):
    if self_model and self_model != "<synthetic>":
        return self_model
    for j in range(i, -1, -1):
        m = (rows[j].get("message") or {}).get("model")
        if m and m != "<synthetic>":  # injected rows aren't a served model
            return m
    return None


def parse_ts(row):
    ts = row.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def session_id_from(path):
    return os.path.basename(path).replace(".jsonl", "")


def scan_file(path, since_dt, tiers):
    rows = load_rows(path)
    sid = session_id_from(path)
    events = []

    # Running per-session state for the context-accumulation signals (cap 3).
    session_start_ts = None
    for r in rows:
        session_start_ts = parse_ts(r)
        if session_start_ts:
            break
    prompts_seen = []      # every real user prompt, in order
    accumulated_chars = 0  # running size of accumulated prompt context

    for i, r in enumerate(rows):
        if is_real_user_prompt(r):
            t = text_of(r).strip()
            prompts_seen.append(t)
            accumulated_chars += len(t)

        tier = category = None
        original_model = fallback_model = explanation = trigger = req = None
        subtype = r.get("subtype")
        msg = r.get("message") or {}
        stop_details = msg.get("stop_details") or {}
        # A1: the canonical API refusal shape is an assistant row with
        # message.stop_reason == "refusal" (+ stop_details.category), which
        # carries NO top-level subtype/apiRefusalCategory — so the old
        # subtype/apiRefusalCategory-only test missed it (notably subagent
        # refusals and refusals with no model fallback). Dedup by request_id
        # below collapses the fallback-row + stop_reason-row for one block.
        is_refusal_stop = (msg.get("stop_reason") == "refusal"
                           or stop_details.get("type") == "refusal")

        # Tier 1 — Anthropic model safeguard
        if subtype in MODEL_SAFEGUARD_SUBTYPES or r.get("apiRefusalCategory") or is_refusal_stop:
            tier = "model_safeguard"
            category = (r.get("apiRefusalCategory") or stop_details.get("category")
                        or "unspecified")
            _sm = msg.get("model") if is_refusal_stop else None
            original_model = r.get("originalModel") or (_sm if _sm != "<synthetic>" else None)
            fallback_model = r.get("fallbackModel")
            explanation = (r.get("apiRefusalExplanation") or stop_details.get("explanation")
                           or r.get("content"))
            trigger = r.get("trigger") or ("refusal" if is_refusal_stop else None)
            # ONLY a top-level requestId (req_...) is an appealable, globally-unique
            # server id. The old `or msg.get("id")` fallback stored a message id
            # (msg_..., session-local) as request_id — which would (a) enter appeals
            # as a non-lookup-able id and (b) key the request_id collapse, risking a
            # merge of two distinct blocks. Drop it: no requestId => request_id=None
            # (event still captured; just not batchable into an appeal). (roundtable B)
            req = r.get("requestId")
        else:
            blob = text_of(r) or (r.get("content") if isinstance(r.get("content"), str) else "")
            doc = HOOK_DOC_EXCLUDE.search(blob) if blob else None
            if blob and not doc and CLASSIFIER_RE.search(blob):
                tier = "auto_mode_classifier"
                category = "bash_safety_classifier"
                explanation = blob[:500]
            elif blob and not doc and (hook_m := HOOK_RE.search(blob)):
                tier = "hook_guardrail"
                # category = the tool matcher (PreToolUse:Bash) when present, else
                # the block phrase — group(1) no longer exists in the new HOOK_RE.
                mm = _HOOK_MATCHER_RE.search(hook_m.group(0))
                category = (mm.group(0) if mm else hook_m.group(0)[:40]).strip().lower()
                explanation = blob[:500]

        if not tier or tier not in tiers:
            continue

        ts = parse_ts(r)
        # under --since, exclude pre-window AND undated rows (an undated row must
        # not leak into a dated window). (roundtable finding C)
        if since_dt and (ts is None or ts < since_dt):
            continue

        active_model = nearest_active_model(rows, i, self_model=original_model)
        prompt = prompts_seen[-1] if prompts_seen else None

        # Context-accumulation signals at block time (cap 3: workaround selection)
        minutes_into_session = None
        if ts and session_start_ts:
            minutes_into_session = round((ts - session_start_ts).total_seconds() / 60, 1)
        acc_context = " ".join(prompts_seen)
        sec_vocab_hits = len({m.group(0).lower()
                                 for m in SEC_VOCAB_RE.finditer(acc_context)})

        events.append({
            "session_id": sid,
            "session_file": path.replace(HOME, "~"),
            "timestamp": r.get("timestamp"),
            "tier": tier,
            "category": category,
            "subtype": subtype,
            "active_model": active_model,
            "original_model": original_model,
            "fallback_model": fallback_model,
            "trigger": trigger,
            "request_id": req,
            "uuid": r.get("uuid"),
            "turn_index": len(prompts_seen),
            "minutes_into_session": minutes_into_session,
            "accumulated_prompt_chars": accumulated_chars,
            "sec_vocab_distinct": sec_vocab_hits,
            "prompt_context": (prompt[:600] + " …") if prompt and len(prompt) > 600 else prompt,
            "explanation": (explanation[:600] if isinstance(explanation, str) else explanation),
        })
    # A1: collapse the fallback-row + stop_reason-row for one block (same
    # request_id within this session) so neither the full scan nor the live
    # Stop-capture path double-counts an appealable request ID.
    return _collapse_safeguard_by_request(events)


def dedup(events):
    seen, out = set(), []
    for e in events:
        key = (e["session_id"], e.get("uuid") or e.get("request_id"),
               e["tier"], e.get("timestamp"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    # global collapse catches the same block saved across two session files
    return _collapse_safeguard_by_request(out)


def _collapse_safeguard_by_request(events):
    """A1: one Anthropic block can appear as BOTH a model_refusal_fallback
    system row and an assistant stop_reason=='refusal' row (different uuids,
    SAME requestId). Collapse those to one model_safeguard event per
    request_id, preferring a named category and a known fallback model."""
    by_req, order, out = {}, [], []
    for e in events:
        if e["tier"] != "model_safeguard" or not e.get("request_id"):
            out.append(e)
            continue
        # request_id is globally unique to one API call, so key on it ALONE —
        # this also merges the same block saved under two session-file IDs
        # (a resumed/forked session), which a session-scoped key would miss.
        rid = e["request_id"]
        if rid not in by_req:
            by_req[rid] = e
            order.append(rid)
        else:
            keep = by_req[rid]
            # prefer a real category over "unspecified"
            if keep.get("category") == "unspecified" and e.get("category") != "unspecified":
                keep["category"] = e["category"]
            # keep whichever fallback/explanation is populated
            keep["fallback_model"] = keep.get("fallback_model") or e.get("fallback_model")
            keep["original_model"] = keep.get("original_model") or e.get("original_model")
            keep["explanation"] = keep.get("explanation") or e.get("explanation")
    return out + [by_req[r] for r in order]


def write_report(events, out_dir):
    from collections import Counter
    ev = sorted(events, key=lambda e: e["timestamp"] or "")
    by_tier = Counter(e["tier"] for e in ev)
    by_cat = Counter(f'{e["tier"]}/{e["category"]}' for e in ev)
    by_model = Counter(e["active_model"] or "unknown" for e in ev)
    fallbacks = Counter(
        f'{e["original_model"]} → {e["fallback_model"]}'
        for e in ev if e["tier"] == "model_safeguard" and e["fallback_model"])

    lines = ["# Guardrail / Safeguard Corpus", ""]
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"_Generated {gen} · {len(ev)} events across "
                 f"{len({e['session_id'] for e in ev})} sessions._")
    if ev:
        lines.append(f"_Span: {ev[0]['timestamp']} → {ev[-1]['timestamp']}_")
    lines += ["", "## Counts by tier", ""]
    for t, n in by_tier.most_common():
        lines.append(f"- **{t}**: {n}")
    lines += ["", "## Counts by category", ""]
    for c, n in by_cat.most_common():
        lines.append(f"- {c}: {n}")
    lines += ["", "## Model in use when triggered", ""]
    for m, n in by_model.most_common():
        lines.append(f"- {m}: {n}")
    if fallbacks:
        lines += ["", "## Model-safeguard fallbacks (original → fallback)", ""]
        for f, n in fallbacks.most_common():
            lines.append(f"- {f}: {n}")
    lines += ["", "## Events (chronological)", ""]
    for e in ev:
        head = f"### {e['timestamp']}  ·  {e['tier']} / {e['category']}"
        lines.append(head)
        model_line = e["active_model"] or "unknown"
        if e["tier"] == "model_safeguard" and e["fallback_model"]:
            model_line = f"{e['original_model']} → {e['fallback_model']}"
        lines.append(f"- **model**: {model_line}")
        lines.append(f"- **session**: `{e['session_id']}`")
        if e["prompt_context"]:
            pc = e["prompt_context"].replace("\n", " ")
            lines.append(f"- **prompt/context**: {pc}")
        if e["explanation"]:
            ex = str(e["explanation"]).replace("\n", " ")[:300]
            lines.append(f"- **block message**: {ex}")
        lines.append("")

    os.makedirs(out_dir, exist_ok=True)
    md = os.path.join(out_dir, "guardrail-corpus-report.md")
    with open(md, "w", encoding='utf-8') as fh:
        fh.write("\n".join(lines))
    return md


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projects-dir", default=DEFAULT_PROJECTS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--since", help="YYYY-MM-DD; only events on/after this date")
    ap.add_argument("--tier", action="append",
                    choices=["model_safeguard", "auto_mode_classifier", "hook_guardrail"],
                    help="restrict to tier(s); repeatable. default: all")
    args = ap.parse_args()

    since_dt = None
    if args.since:
        since_dt = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    tiers = set(args.tier) if args.tier else {
        "model_safeguard", "auto_mode_classifier", "hook_guardrail"}

    files = glob.glob(os.path.join(args.projects_dir, "**", "*.jsonl"),
                      recursive=True)
    files = [f for f in files if "/tool-results/" not in f]

    all_events = []
    for f in files:
        all_events.extend(scan_file(f, since_dt, tiers))
    all_events = dedup(all_events)

    os.makedirs(args.out, exist_ok=True)
    jsonl = os.path.join(args.out, "guardrail-corpus.jsonl")
    # B1 + atomicity fix (roundtable finding D): hold the SHARED corpus lock file
    # (also taken by the Stop-hook's append + existing-keys read), write a temp
    # file, then os.replace() it in ATOMICALLY. A crash mid-write leaves the old
    # corpus intact — never the empty/truncated window the old in-place truncate
    # left. The lock serializes rescan vs. concurrent append.
    lockpath = jsonl + ".lock"
    tmp = jsonl + ".tmp"
    with open(lockpath, "w", encoding='utf-8') as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(tmp, "w", encoding='utf-8') as fh:
                fh.writelines(json.dumps(e) + "\n" for e in sorted(all_events, key=lambda e: e["timestamp"] or ""))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, jsonl)  # atomic rename (atomic on POSIX + Windows)
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)
    md = write_report(all_events, args.out)

    # stdout summary
    from collections import Counter
    by_tier = Counter(e["tier"] for e in all_events)
    by_model = Counter(e["active_model"] or "unknown" for e in all_events
                       if e["tier"] == "model_safeguard")
    print(f"scanned {len(files)} transcripts")
    print(f"corpus: {len(all_events)} guardrail/safeguard events")
    for t, n in by_tier.most_common():
        print(f"  {t}: {n}")
    if by_model:
        print("model_safeguard by model-in-use:")
        for m, n in by_model.most_common():
            print(f"  {m}: {n}")
    print(f"wrote {jsonl.replace(HOME, '~')}")
    print(f"wrote {md.replace(HOME, '~')}")


if __name__ == "__main__":
    main()
