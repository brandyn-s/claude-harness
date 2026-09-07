#!/usr/bin/env python3
"""Roll up the acceptance-ledger audits written at PostCompact.

compaction-budget.py appends one JSONL row per compaction to
  ~/.claude/audit/ledger-audit-YYYYMMDD.jsonl
    {"ts","date","session_id","cwd","trigger","compaction_count","total_entries",
     "not_found_count","rejected_dropped_count","not_found":[{kind,text}],"summary_chars"}

hooks/session_ledger.py exists on a hypothesis it deliberately does not assume:
that compaction drops acceptance state and the corrective turns follow. These
rows are the measurement. The report answers, per day and per session:

  - compactions audited, and how many had a ledger at all (a compaction with no
    ledger is a session that never framed its work -- the /frame gap, not a
    compaction problem)
  - entries the summary did not mention, and the REJECTED subset -- the specific
    failure the ledger exists to prevent
  - which rejections were dropped, verbatim, so a recurring one can become a
    precompact-priorities.py line or a rule

The audit is TOKEN CONTAINMENT (session_ledger.audit_against_summary): an entry
counts as present when its first four significant words all appear in the
summary. Paraphrase past recognition reads as dropped, so a non-zero drop rate
is a signal to read the summaries, not a verdict. A REJECTED drop rate near zero
over weeks is what would retire the hypothesis.

Usage:
  python3 bin/ledger-audit-report.py                 # all rows under ~/.claude/audit
  python3 bin/ledger-audit-report.py --days 14       # only the last 14 days of files
  python3 bin/ledger-audit-report.py --dir /path     # custom audit dir
  python3 bin/ledger-audit-report.py --json          # machine-readable
  python3 bin/ledger-audit-report.py --dropped       # list every dropped entry with its session
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_DIR = Path.home() / ".claude" / "audit"


def _files(audit_dir: Path, days: int | None) -> list[str]:
    paths = sorted(glob.glob(str(audit_dir / "ledger-audit-*.jsonl")))
    if days is None:
        return paths
    cutoff = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")
    return [p for p in paths if os.path.basename(p)[len("ledger-audit-"):-len(".jsonl")] >= cutoff]


def load_rows(audit_dir: Path, days: int | None = None) -> list[dict]:
    rows = []
    for path in _files(audit_dir, days):
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        rows.append(row)
        except OSError:
            continue
    return rows


def summarize(rows: list[dict]) -> dict:
    per_day: dict[str, Counter] = defaultdict(Counter)
    per_session: dict[str, dict] = {}
    dropped: list[dict] = []
    totals = Counter()
    for r in rows:
        day = str(r.get("date") or "unknown")
        sid = str(r.get("session_id") or "unknown")
        entries = int(r.get("total_entries") or 0)
        nf = int(r.get("not_found_count") or 0)
        rd = int(r.get("rejected_dropped_count") or 0)
        for bucket in (per_day[day], totals):
            bucket["compactions"] += 1
            bucket["with_ledger"] += 1 if entries else 0
            bucket["entries"] += entries
            bucket["not_found"] += nf
            bucket["rejected_dropped"] += rd
            bucket["compactions_dropping_a_rejection"] += 1 if rd else 0
        s = per_session.setdefault(sid, {"session_id": sid, "cwd": r.get("cwd", ""), "compactions": 0,
                                         "entries": 0, "not_found": 0, "rejected_dropped": 0,
                                         "triggers": Counter()})
        s["compactions"] += 1
        s["entries"] = max(s["entries"], entries)
        s["not_found"] += nf
        s["rejected_dropped"] += rd
        s["triggers"][str(r.get("trigger") or "unknown")] += 1
        for m in r.get("not_found") or []:
            if isinstance(m, dict):
                dropped.append({"date": day, "session_id": sid, "kind": m.get("kind"),
                                "text": str(m.get("text", ""))[:200]})
    for s in per_session.values():
        s["triggers"] = dict(s["triggers"])
    worst = sorted(per_session.values(), key=lambda s: (-s["rejected_dropped"], -s["not_found"], -s["compactions"]))
    recurring = Counter((d["kind"], d["text"].lower()) for d in dropped if d["kind"] == "rejected")
    return {
        "rows": len(rows),
        "totals": dict(totals),
        "rejected_drop_rate_pct": (round(100.0 * totals["compactions_dropping_a_rejection"] / totals["compactions"], 1)
                                   if totals["compactions"] else None),
        "per_day": {d: dict(c) for d, c in sorted(per_day.items())},
        "worst_sessions": worst[:10],
        "dropped": dropped,
        "recurring_dropped_rejections": [{"text": t, "times": n} for (k, t), n in recurring.most_common(10) if n > 1],
    }


def render(summary: dict, show_dropped: bool) -> str:
    t = summary["totals"]
    out = []
    if not summary["rows"]:
        out.append("ledger-audit-report: no rows (no compaction has audited a ledger yet — "
                   "rows appear once compaction-budget.py runs on PostCompact with a session ledger present)")
        return "\n".join(out)
    out.append(f"compactions audited        {t.get('compactions', 0)}   with a ledger: {t.get('with_ledger', 0)}")
    out.append(f"ledger entries (sum)       {t.get('entries', 0)}")
    out.append(f"not mentioned by summary   {t.get('not_found', 0)}   of which REJECTED: {t.get('rejected_dropped', 0)}")
    out.append(f"compactions dropping a rejection   {t.get('compactions_dropping_a_rejection', 0)}"
               f"  ->  {summary['rejected_drop_rate_pct']}%")
    out.append("")
    out.append(f"{'day':<12}{'compactions':>12}{'w/ledger':>10}{'entries':>9}{'dropped':>9}{'rejected':>10}")
    for day, c in summary["per_day"].items():
        out.append(f"{day:<12}{c.get('compactions', 0):>12}{c.get('with_ledger', 0):>10}{c.get('entries', 0):>9}"
                   f"{c.get('not_found', 0):>9}{c.get('rejected_dropped', 0):>10}")
    if summary["worst_sessions"]:
        out.append("")
        out.append("sessions by dropped rejections:")
        for s in summary["worst_sessions"][:5]:
            out.append(f"  {s['session_id'][:24]:<26} compactions {s['compactions']:>2}  entries {s['entries']:>3}  "
                       f"dropped {s['not_found']:>3}  rejected {s['rejected_dropped']:>2}  {s['cwd']}")
    if summary["recurring_dropped_rejections"]:
        out.append("")
        out.append("rejections dropped more than once (candidates for precompact-priorities.py or a rule):")
        for r in summary["recurring_dropped_rejections"]:
            out.append(f"  {r['times']}x  {r['text']}")
    if show_dropped and summary["dropped"]:
        out.append("")
        out.append("every dropped entry:")
        for d in summary["dropped"]:
            out.append(f"  {d['date']}  {d['session_id'][:20]:<20}  [{d['kind']}] {d['text']}")
    out.append("")
    out.append("Token-containment signal, not a verdict: a paraphrased entry reads as dropped. "
               "Read the summaries behind a non-zero REJECTED count before concluding anything.")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="audit directory (default ~/.claude/audit)")
    ap.add_argument("--days", type=int, default=None, help="only files from the last N days")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--dropped", action="store_true", help="list every dropped entry")
    args = ap.parse_args()
    summary = summarize(load_rows(Path(args.dir), args.days))
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(render(summary, args.dropped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
