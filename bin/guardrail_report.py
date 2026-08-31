#!/usr/bin/env python3
"""
guardrail_report.py — turn the guardrail corpus into four operational artifacts.

Reads guardrail-corpus.jsonl (produced by guardrail_corpus.py) and emits, on demand:

  cvp-evidence  Block rate + distribution pack for the Cyber Use Case Form
                (markdown narrative + attachable CSV, request IDs included).
  drift         Daily/weekly block-count time series with baseline + spike/drop
                flags — an Anthropic-side classifier-change signal.
  workaround    Descriptive analysis of the conditions blocks occur under
                (model, sticky sessions, context accumulation) mapped to the
                mitigation each supports, with confidence labels.
  fp-report     Per-block, appeal-ready false-positive reports keyed by request
                ID, plus a combined multi-ID block for the false-positive form.
  all           Run all four.

Scope note: cvp-evidence / drift / fp-report operate on the model_safeguard tier
only (Anthropic's cyber/bio safeguards — the appealable, drift-relevant ones).
workaround also considers the auto_mode_classifier tier. Local hook_guardrail
events are ours, not Anthropic's, so they are excluded from these four.

EGRESS SAFETY (cvp-evidence + fp-report are submitted to an external Anthropic
form): by default these artifacts DENY free-text prompt bodies and emit only a
whitelist (timestamp, request_id, category, model, session_id). Pass
--include-context to add best-effort-redacted prompt bodies — which are NOT
guaranteed clean (regex redaction can't catch names/codenames) and are labeled
for mandatory human review. Use --redact "<literal>" (repeatable) to scrub
specific names/codenames when including context.

Usage:
  python3 guardrail_report.py all
  python3 guardrail_report.py cvp-evidence --since 2026-06-01
  python3 guardrail_report.py fp-report --org-id <uuid> --include-context --redact "Acme Corp"
"""
import argparse
import csv
import json
import os
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
DEFAULT_OUT = os.path.join(HOME, "Documents", "reports", "guardrails")
DEFAULT_CORPUS = os.path.join(DEFAULT_OUT, "guardrail-corpus.jsonl")

# ---- denylist: defense-in-depth for the --include-context path (A'1) ----
# NOTE: this is NOT the primary control. The primary control is deny-by-default
# (bodies omitted unless --include-context). A denylist cannot catch names,
# org codenames, or internal project names — never treat a denylist pass as
# "safe to submit". Redaction is best-effort; human review is mandatory.
_SANITIZERS = [
    (re.compile(r"/Users/[^/\s]+/"), "~/"),
    (re.compile(r"\bA(?:KIA|SIA|IDA|ROA|GPA|NPA)[0-9A-Z]{12,}\b"), "[AWS_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[GITHUB_TOKEN]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[SLACK_TOKEN]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\b"), "[JWT]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"), "Bearer [TOKEN]"),
    (re.compile(r"\bsk-[A-Za-z0-9-]{20,}\b"), "[API_KEY]"),
    (re.compile(r"(?i)\b(password|secret|token|api[_-]?key|access[_-]?key)\b\s*[=:]\s*\S+"),
     r"\1=[REDACTED]"),
    (re.compile(r"\b[\w.-]+\.example\.com\b"), "[HOSTNAME]"),
    (re.compile(r"\b(?:10|127)(?:\.\d{1,3}){3}\b"), "[IP]"),
    (re.compile(r"\b192\.168(?:\.\d{1,3}){2}\b"), "[IP]"),
    (re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}\b"), "[IP]"),
    (re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2}\b"), "[IP]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b\d{12}\b"), "[ACCOUNT_ID]"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "[HEX]"),
]


def sanitize(text, extra_literals=None):
    """Best-effort redaction for the --include-context path. NOT a guarantee."""
    if not text:
        return text
    for lit in (extra_literals or []):
        if lit:
            text = re.sub(re.escape(lit), "[REDACTED]", text, flags=re.IGNORECASE)
    for rx, repl in _SANITIZERS:
        text = rx.sub(repl, text)
    return text


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def load_corpus(path, since_dt=None):
    ev, seen = [], set()
    try:
        fh = open(path, encoding='utf-8')
    except FileNotFoundError:
        # missing corpus is not a crash — reports emit empty + freshness_warning
        # surfaces "no corpus". (roundtable finding E)
        return []
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)          # X1: one bad line must not crash all reports
            except json.JSONDecodeError:
                continue
            # dedup by (session, uuid) — the real-time capture hook appends to
            # the same corpus, so a full rebuild + live appends can overlap.
            key = (e.get("session_id"), e.get("uuid"))
            if key in seen:
                continue
            seen.add(key)
            if since_dt:
                ts = parse_ts(e.get("timestamp"))
                # exclude BOTH pre-window AND undated events from a dated pack —
                # `if ts and ts < since_dt` alone leaked null-timestamp rows
                # into a --since evidence pack (roundtable finding C).
                if ts is None or ts < since_dt:
                    continue
            ev.append(e)
    # A1/consuming-side safety: collapse model_safeguard to one row per
    # request_id (the hook-append path may add both the fallback-row and the
    # stop_reason-row for one block; scanner collapses per file, this covers
    # cross-file / cross-append overlap).
    by_req, out = {}, []
    for e in ev:
        if e.get("tier") == "model_safeguard" and e.get("request_id"):
            r = e["request_id"]
            if r in by_req:
                keep = by_req[r]
                if keep.get("category") == "unspecified" and e.get("category") != "unspecified":
                    keep["category"] = e["category"]
                keep["fallback_model"] = keep.get("fallback_model") or e.get("fallback_model")
                continue
            by_req[r] = e
        out.append(e)
    return out


def freshness_warning(corpus_path, max_age_days=2):
    """Warn when the explicitly generated offline corpus is missing or stale."""

    try:
        corpus_mtime = os.path.getmtime(corpus_path)
    except OSError:
        return ("⚠️ offline guardrail corpus scan has NEVER run. Run "
                "guardrail_corpus.py before trusting these reports.")
    age_days = (datetime.now(timezone.utc).timestamp() - corpus_mtime) / 86400
    if age_days > max_age_days:
        return (f"⚠️ offline guardrail corpus is STALE — last scan {age_days:.1f} "
                f"days ago. Run guardrail_corpus.py before trusting these reports.")
    return None


def day_of(e):
    ts = parse_ts(e.get("timestamp"))
    return ts.date().isoformat() if ts else "unknown"


def span(events):
    ds = sorted(d for d in (parse_ts(e.get("timestamp")) for e in events) if d)
    return (ds[0], ds[-1]) if ds else (None, None)


# ---------------------------------------------------------------- cvp-evidence
def cvp_evidence(events, out_dir, org_id, include_context, redactions):
    ms = [e for e in events if e["tier"] == "model_safeguard"]
    auto = [e for e in events if e["tier"] == "auto_mode_classifier"]
    lo, hi = span(ms)
    active_days = len({day_of(e) for e in ms if day_of(e) != "unknown"})
    days_total = ((hi - lo).days + 1) if lo and hi else 0
    by_cat = Counter(e["category"] for e in ms)
    by_model = Counter((e.get("active_model") or "unknown") for e in ms)
    req_ids = sorted({e["request_id"] for e in ms if e.get("request_id")})
    sessions = {e["session_id"] for e in ms}
    cal_rate = round(len(ms) / days_total, 2) if days_total else 0
    burst_rate = round(len(ms) / active_days, 2) if active_days else 0

    L = ["# CVP evidence pack — Claude cyber/bio safeguard blocks", ""]
    L.append(f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} from local "
             f"Claude Code session transcripts._")
    if not include_context:
        L.append("\n> **Egress mode: whitelist-only.** Free-text prompt bodies are "
                 "omitted from this artifact. Re-run with `--include-context` to add "
                 "best-effort-redacted prompts (which require manual review before "
                 "submission).")
    else:
        L.append("\n> ⚠️ **--include-context is ON.** Prompt bodies below are "
                 "**best-effort redacted only** — regex cannot catch names, org "
                 "codenames, or internal project names. **Review every line before "
                 "submitting to Anthropic.**")
    if org_id:
        L.append(f"\n**Organization ID:** `{org_id}`")
    L += ["", "## Summary", ""]
    L.append(f"- **Window:** {lo:%Y-%m-%d} → {hi:%Y-%m-%d} ({days_total} calendar days)"
             if lo else "- Window: n/a")
    L.append(f"- **Total Anthropic safeguard blocks:** {len(ms)} "
             f"(+{len(auto)} local auto-mode Bash-classifier events, context only — not appealable)")
    L.append(f"- **Blocks per calendar day:** {cal_rate}  "
             f"(_burst intensity, active days only: {burst_rate} across {active_days} days_)")
    L.append(f"- **Distinct sessions affected:** {len(sessions)}")
    L.append(f"- **Unique appealable request IDs (server-side lookup-able):** {len(req_ids)}")
    L += ["", "### By category", ""]
    for c, n in by_cat.most_common():
        L.append(f"- **{c}**: {n}")
    L += ["", "### By model in use when blocked", ""]
    for m, n in by_model.most_common():
        L.append(f"- {m}: {n}")

    if include_context:
        # A'3: sample deterministically (evenly spaced by time), NOT by security-
        # vocab density (which surfaces the least-typical, highest-leak prompts).
        by_time = sorted(ms, key=lambda e: e.get("timestamp") or "")
        k = min(12, len(by_time))
        picks = [by_time[round(i * (len(by_time) - 1) / max(k - 1, 1))] for i in range(k)] if k else []
        L += ["", "## Sample blocked requests (chronological sample; best-effort redacted)", ""]
        for e in picks:
            p = sanitize(e.get("prompt_context") or "(continuation / tool turn)", redactions)
            L.append(f"- `{e.get('request_id') or 'no-req-id'}` · {day_of(e)} · "
                     f"{e.get('active_model')} · {e['category']} — {p}")

    L += ["", "## Request IDs (paste-ready)", "", "```", " ".join(req_ids), "```"]

    md = os.path.join(out_dir, "cvp-evidence.md")
    with open(md, "w", encoding='utf-8') as fh:
        fh.write("\n".join(L))

    csv_path = os.path.join(out_dir, "cvp-evidence.csv")
    with open(csv_path, "w", newline="", encoding='utf-8') as fh:
        w = csv.writer(fh)
        cols = ["timestamp", "request_id", "category", "model_in_use",
                "fallback_model", "session_id", "turn_index", "minutes_into_session"]
        if include_context:
            cols.append("redacted_prompt_context")
        w.writerow(cols)
        for e in sorted(ms, key=lambda e: e.get("timestamp") or ""):
            row = [e.get("timestamp"), e.get("request_id"), e["category"],
                   e.get("active_model"), e.get("fallback_model"), e["session_id"],
                   e.get("turn_index"), e.get("minutes_into_session")]
            if include_context:
                row.append(sanitize(e.get("prompt_context") or "", redactions))
            w.writerow(row)
    return [md, csv_path]


# ----------------------------------------------------------------------- drift
def drift(events, out_dir):
    ms = [e for e in events if e["tier"] == "model_safeguard"]
    lo, hi = span(ms)
    L = ["# Classifier-drift signal — daily Anthropic safeguard block counts", ""]
    L.append(f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}. "
             f"n={len(ms)} blocks — LOW sample; treat flags as candidates, not proof. "
             f"A durable signal needs the real-time hook feeding this daily._")
    if not (lo and hi):
        L.append("\nNo model_safeguard events to analyze.")
        md = os.path.join(out_dir, "drift.md")
        open(md, "w", encoding='utf-8').write("\n".join(L))
        return [md]

    counts = Counter(day_of(e) for e in ms)
    series = []
    d = lo.date()
    while d <= hi.date():
        series.append((d.isoformat(), counts.get(d.isoformat(), 0)))
        d += timedelta(days=1)
    vals = [c for _, c in series]
    mean = round(statistics.mean(vals), 2)
    sd = round(statistics.pstdev(vals), 2) if len(vals) > 1 else 0
    spike_thr = mean + 2 * sd

    L += ["", f"- Daily mean: {mean} · population stdev: {sd} · "
          f"spike threshold (mean+2σ): {round(spike_thr, 2)}", "",
          "## Daily series", "", "| date | blocks | flag |", "|---|---|---|"]
    for day, c in series:
        flag = ""
        if c and c >= spike_thr and c >= 3:
            flag = "⬆ SPIKE"
        elif c == 0:
            flag = "·"
        L.append(f"| {day} | {c} | {flag} |")

    # Weekly rollup carries the DROP flag: a drop is the actionable direction
    # (Anthropic LOOSENED the classifier) and is only robust at weekly
    # granularity on this zero-inflated data — daily drop-flagging would fire on
    # every quiet day. (roundtable convergent finding #2: drop was advertised
    # but unimplemented.)
    weekly = defaultdict(int)
    for day, c in series:
        wk = datetime.fromisoformat(day).isocalendar()
        weekly[f"{wk[0]}-W{wk[1]:02d}"] += c
    L += ["", "## Weekly rollup", "", "| iso-week | blocks | flag |", "|---|---|---|"]
    wk_keys = sorted(weekly)
    for i, wk in enumerate(wk_keys):
        c, flag = weekly[wk], ""
        if i > 0:
            prev = weekly[wk_keys[i - 1]]
            if prev >= 3 and c <= 0.2 * prev:
                flag = "⬇ DROP (possible loosening)"
            elif c >= 3 and prev >= 1 and c >= 2 * prev:
                flag = "⬆ SPIKE (possible tightening)"
        L.append(f"| {wk} | {c} | {flag} |")

    L += ["", "## How to read this", "",
          "- A daily **⬆ SPIKE** or a weekly **⬇ DROP / ⬆ SPIKE** that does not "
          "match a change in *your* workload points to an Anthropic-side classifier "
          "update. A DROP (loosening) is the more actionable signal.",
          "- Counts are zero-inflated and overdispersed; the thresholds are rough "
          "guides, NOT significance tests, and there is no per-usage denominator "
          "(a drop can also mean you simply did less security work that week). "
          "Prefer a sustained multi-week step, and re-run after the real-time hook "
          "has accumulated ≥4 weeks of counts."]
    md = os.path.join(out_dir, "drift.md")
    open(md, "w", encoding='utf-8').write("\n".join(L))
    return [md]


# ------------------------------------------------------------------ workaround
def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def workaround(events, out_dir):
    ms = [e for e in events if e["tier"] in ("model_safeguard", "auto_mode_classifier")]
    safeguard = [e for e in ms if e["tier"] == "model_safeguard"]
    by_model = Counter((e.get("active_model") or "unknown") for e in safeguard)

    per_session = defaultdict(list)
    for e in safeguard:
        per_session[e["session_id"]].append(e)
    multi = {s: v for s, v in per_session.items() if len(v) > 1}
    max_run = max((len(v) for v in per_session.values()), default=0)
    poisoned_rate = round(100 * len(multi) / len(per_session), 0) if per_session else 0

    med_turn = _med([e.get("turn_index") for e in safeguard])
    med_min = _med([e.get("minutes_into_session") for e in safeguard])
    med_chars = _med([e.get("accumulated_prompt_chars") for e in safeguard])
    deep = [e for e in safeguard if (e.get("turn_index") or 0) > 3]

    L = ["# Workaround selection — conditions under which blocks occur", ""]
    L.append(f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}. "
             f"DESCRIPTIVE analysis of {len(safeguard)} Anthropic safeguard blocks "
             f"(+{len(ms)-len(safeguard)} auto-mode). Blocks-only: there is no "
             f"non-block control, so these are associations, not proven causes._")
    L.append("\n> **These are block COUNTS, not RATES.** The corpus records blocks "
             "but has no per-model / per-session USAGE denominator, so a model or "
             "session shape with more blocks may simply have been used more. Read "
             "every number below as directional, not as a measured rate. (roundtable "
             "finding: model-attribution overclaim.)")

    L += ["", "## 1. Model attribution (count-based; no exposure denominator)", "",
          "| model in use | safeguard blocks |", "|---|---|"]
    for m, n in by_model.most_common():
        L.append(f"| {m} | {n} |")
    sonnet = sum(n for m, n in by_model.items() if "sonnet" in m.lower())
    L.append(f"\n**Signal (directional):** {sonnet} of {len(safeguard)} safeguard "
             f"blocks occurred on a Sonnet model. A near-zero Sonnet count is "
             f"consistent with pinning Sonnet/Opus over Fable 5 helping — but this "
             f"is NOT rate-adjusted: it is only decisive if Sonnet had comparable "
             f"usage, which this corpus cannot confirm.")

    L += ["", "## 2. Sticky sessions (supports: fresh session to clear a block)", "",
          f"- Sessions with >1 safeguard block (\"poisoned\"): "
          f"{len(multi)}/{len(per_session)} ({poisoned_rate:.0f}%)",
          f"- Longest consecutive run in one session: {max_run}",
          "",
          "**Signal:** once a session takes a block, the classifier's accumulated-"
          "context state makes further blocks likely. When you take a block mid-task, "
          "start a fresh session rather than re-prompting the poisoned one."]

    L += ["", "## 3. Context accumulation (supports: don't stack security context)", "",
          f"- Median turn index at block: {med_turn}",
          f"- Median minutes into session at block: {med_min}",
          f"- Median accumulated prompt size at block: {med_chars} chars",
          f"- Blocks that fired deeper than turn 3: {len(deep)}/{len(safeguard)}",
          "",
          "**Signal:** blocks cluster deep in sessions, after context has "
          "accumulated, not on turn 1. (Note: this corpus can only measure your "
          "*user prompts*, not the git history / CLAUDE.md / tool output the "
          "classifier also scores — so accumulated security-shaped context is "
          "under-measured here, not over.) Keep security tasks short and split; "
          "tell the agent to ignore git/CLAUDE.md when not needed."]

    # Confidence is capped at MEDIUM for every row: all rest on block COUNTS with
    # no usage denominator (see the caveat above), so none earns HIGH regardless
    # of n. (roundtable: a HIGH label on a raw count claims more than the data holds.)
    L += ["", "## Mitigation table", "",
          "_All rows are count-based associations without an exposure denominator; "
          "confidence is capped at MEDIUM. To earn HIGH, recompute as block RATES "
          "per model/session (needs total-usage data this corpus does not hold)._", "",
          "| mitigation | evidence in your data (counts, not rates) | confidence |",
          "|---|---|---|",
          f"| Pin Sonnet/Opus over Fable 5 | {by_model.most_common(1)[0][1] if by_model else 0} "
          f"of {len(safeguard)} blocks on the top model; {sonnet} on Sonnet — not rate-adjusted | MEDIUM |",
          f"| Fresh session after a block | {poisoned_rate:.0f}% of blocked sessions "
          f"took >1 block (no retry-success control) | MEDIUM |",
          f"| Split / shorten security tasks | median block at turn {med_turn} "
          f"({med_min} min in), {len(deep)}/{len(safeguard)} past turn 3 | MEDIUM |",
          "| Strip git/CLAUDE.md from context | classifier scores whole context "
          "(community-confirmed); not directly measured here | LOW-MEDIUM |"]
    md = os.path.join(out_dir, "workaround.md")
    open(md, "w", encoding='utf-8').write("\n".join(L))
    return [md]


# ------------------------------------------------------------------- fp-report
def fp_report(events, out_dir, org_id, include_context, redactions, categories):
    ms = [e for e in events if e["tier"] == "model_safeguard" and e.get("request_id")]
    excluded = sorted({e["category"] for e in ms if e["category"] not in categories})
    ms = [e for e in ms if e["category"] in categories]
    ms.sort(key=lambda e: e.get("timestamp") or "")
    seen, deduped = set(), []
    for e in ms:
        if e["request_id"] in seen:
            continue
        seen.add(e["request_id"])
        deduped.append(e)
    ms = deduped

    L = ["# False-positive reports — appeal-ready, keyed by request ID", ""]
    L.append(f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}. "
             f"{len(ms)} blocks in categories {sorted(categories)}. File at "
             f"https://claude.com/form/cyber-block-false-positive-report-cvp-rejection-appeal_")
    L.append("\n> ⚠️ **Do not submit the canned justification.** Anthropic verifies "
             "each request ID server-side; a blanket claim that mismatches the actual "
             "request undermines the whole batch. Fill in the per-block justification "
             "for each entry, and drop any entry that was not in-scope defensive work.")
    if excluded:
        L.append(f"\n> Excluded {excluded} category blocks by default (CVP is cyber-scoped; "
                 f"bio is a separate track). Add with `--categories cyber,unspecified,bio`.")
    if not include_context:
        L.append("\n> Prompt bodies omitted (whitelist-only). Re-run with "
                 "`--include-context` to add best-effort-redacted bodies for review.")
    if org_id:
        L.append(f"\n**Organization ID:** `{org_id}`")
    L += ["", "## Combined request-ID list (for a single batched appeal)", "", "```",
          " ".join(e["request_id"] for e in ms), "```", "", "## Individual reports", ""]
    for i, e in enumerate(ms, 1):
        fb = f" → {e['fallback_model']}" if e.get("fallback_model") else ""
        L.append(f"### Report {i} — request `{e['request_id']}`\n")
        L.append(f"- **Timestamp:** {e.get('timestamp')}")
        L.append(f"- **Model in use:** {e.get('active_model')}{fb}")
        L.append(f"- **Category:** {e['category']}")
        L.append("- **Surface:** Claude Code (CLI)")
        if include_context:
            L.append(f"- **What I was doing (best-effort redacted — REVIEW):** "
                     f"{sanitize(e.get('prompt_context') or '(continuation / tool-result turn)', redactions)}")
        L.append("- **Why this is a legitimate false positive:** "
                 "`[FILL IN: why THIS specific request was authorized, in-scope "
                 "defensive work — do not submit until completed]`\n")
    md = os.path.join(out_dir, "fp-reports.md")
    open(md, "w", encoding='utf-8').write("\n".join(L))
    return [md]


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["cvp-evidence", "drift", "workaround",
                                     "fp-report", "all"])
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--since", help="YYYY-MM-DD; only events on/after this date")
    ap.add_argument("--org-id", default="", help="your CVP org UUID, embedded in outputs")
    ap.add_argument("--include-context", action="store_true",
                    help="include best-effort-redacted prompt bodies in the external "
                         "artifacts (default OFF — bodies are omitted for egress safety)")
    ap.add_argument("--redact", action="append", default=[],
                    help="literal string to scrub when --include-context (repeatable): "
                         "your name, org, internal codenames")
    ap.add_argument("--categories", default="cyber,unspecified",
                    help="fp-report categories to include (default cyber,unspecified)")
    args = ap.parse_args()

    since_dt = (datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
                if args.since else None)
    events = load_corpus(args.corpus, since_dt)
    os.makedirs(args.out, exist_ok=True)
    cats = {c.strip() for c in args.categories.split(",") if c.strip()}
    stale = freshness_warning(args.corpus)

    written = []
    if args.mode in ("cvp-evidence", "all"):
        written += cvp_evidence(events, args.out, args.org_id, args.include_context, args.redact)
    if args.mode in ("drift", "all"):
        written += drift(events, args.out)
    if args.mode in ("workaround", "all"):
        written += workaround(events, args.out)
    if args.mode in ("fp-report", "all"):
        written += fp_report(events, args.out, args.org_id, args.include_context, args.redact, cats)

    print(f"loaded {len(events)} corpus events from {args.corpus.replace(HOME, '~')}")
    print(f"egress mode: {'INCLUDE-CONTEXT (review before submit)' if args.include_context else 'whitelist-only (bodies omitted)'}")
    if stale:
        print(stale)
    for w in written:
        print(f"wrote {w.replace(HOME, '~')}")


if __name__ == "__main__":
    main()
