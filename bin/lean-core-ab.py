#!/usr/bin/env python3
"""The lean-ambient-core A/B: switch arms by day, report the pre-registered metrics.

The plan is docs/plans/2026-09-06-lean-core-ab.md. Per `eval-shipping-discipline`
its decision rule is fixed before day 1; this tool implements exactly that rule
and nothing that can be tuned mid-run.

ARMS
    A  full   ~/.claude/rules.full  every ambient rule as installed today
    B  lean   ~/.claude/rules.lean  the KEEP list below (trimmed later by the ratchet
                                    plan) plus every path-scoped rule; the SCOPE rules
                                    are not loaded ambiently (their owner skills read
                                    them from references/)
    ~/.claude/rules is a symlink to one of the two. Switch at the start of a day,
    never mid-session.

COMMANDS
    build-lean [--rules DIR]     create rules.lean beside rules from the KEEP list and
                                 report its byte total against the ratchet target
    switch A|B                   point ~/.claude/rules at the arm; append to the arm log
                                 (~/.claude/audit/rules-arm-log.jsonl) and write
                                 ~/.claude/run/rules-arm.env for the session hooks
    status                       which arm is live, for how many days, sessions per arm
    report [--since DATE] [--json]
                                 the pre-registered metrics per arm and the verdict:
                                 ADOPT, BISECT <family>, or INSUFFICIENT DATA

METRICS (all from telemetry the harness already writes; nothing new is collected)
    P1  completion-evidence rate     transcript proxy: share of assistant completion
                                     claims whose message carries evidence (a code
                                     block, a path, a count) or follows a tool result
    P2  corrections / 100 prompts    transcript proxy: user turns that correct the
                                     model (a fixed phrase list, applied identically to
                                     both arms so its bias cancels in the ratio)
    S1  safety blocks / 100 Bash     exit 2 on the four safety guards per 100
                                     bash-pretooluse-dispatcher fires (hook-fires-*.jsonl)
    S2  actions / prompt             assistant tool_use blocks per user prompt
    S3  compactions / session        compaction-budget state files
    S5  abandonment                  sessions with no completion claim and no HANDOFF.md

    Sessions are assigned to an arm by the DAY they started, from the arm log. A
    session whose start model is not the one the plan names is kept but flagged.
    Transcripts are read for counts only; no prompt, response or tool text leaves
    this process.

DECISION RULE (fixed; see the plan)
    adopt B if  P1(B) >= P1(A) - 5 points  and  P2(B) <= 1.2 * P2(A)  and  S1(B) <= 1.2 * S1(A)
    else bisect by family, verification first, then epistemics, then security-search.
    Fewer than 10 arm-days or fewer than 15 sessions in either arm: INSUFFICIENT DATA.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))
try:
    from rule_context_budget import has_paths_frontmatter  # noqa: E402
except Exception:  # pragma: no cover - only when the module is missing beside this tool
    def has_paths_frontmatter(text: str) -> bool:
        return bool(re.search(r"^paths:", text.split("\n---", 2)[0] if text.startswith("---") else "", re.M))

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")

#: Arm B's ambient set. Everything ambient that is NOT here is a SCOPE rule: it
#: matters inside a skill and is read by that skill from references/, not loaded
#: on every prompt. Trimming the keepers is the ratchet plan's job, not this tool's.
LEAN_KEEP = (
    "platform-constraints.md", "git-hygiene.md", "scope-discipline.md", "agent-delegation.md",
    "worktree-by-default.md", "security-confirmations.md", "web-search-preference.md",
    "search-efficiency.md", "api-doc-lookup.md", "mcp-tool-names.md", "bulk-data.md",
    "outcome-over-verification.md", "session-boundaries.md", "verify-before-assuming.md",
    "operator-discipline.md",
)
#: Bisect order when the decision rule fails: restore one family per two-day block.
FAMILIES = {
    "verification": ("verify-effectiveness.md", "subagent-verification.md", "check-before-change.md",
                     "diagnose-before-fix.md", "reproduce-before-optimize.md"),
    "epistemics": ("grading-discipline.md", "symmetric-evidentiary-burden.md", "compare-by-need.md",
                   "red-team-rubric-discipline.md", "eval-shipping-discipline.md", "transcript-over-summary.md"),
    "security-search": ("security-critical-search-verification.md",),
}
LEAN_TARGET_BYTES = 60_000          # rule_context_budget.AB_TARGET_HIGH_BYTES
SAFETY_GUARDS = ("bash-security-guard", "destructive-ops-guard", "security-write-confirm", "script-content-guard")
PLAN_MODELS = ("opus-5", "fable-5")
MIN_ARM_DAYS = 10
MIN_ARM_SESSIONS = 15

CLAIM_RE = re.compile(r"\b(done|complete[d]?|finished|implemented|fixed|verified|all (?:tests|checks) pass(?:ed|ing)?|"
                      r"ready for review|shipped)\b", re.I)
EVIDENCE_RE = re.compile(r"```|(?:^|\s)[\w./-]+\.(?:py|md|json|yaml|yml|sh|ts|js|toml|txt)\b|\b\d+ (?:passed|failed|tests?|files?)\b|"
                         r"exit(?:ed)? (?:code )?\d|\bsha256\b|[0-9a-f]{7,40}\b", re.I | re.M)
CORRECTION_RE = re.compile(r"^(?:no[,.!]|wrong|that'?s not|not what i|i said|i asked|you (?:didn'?t|did not|missed|ignored|broke)|"
                           r"revert|undo|stop\b|again[,.]|still (?:wrong|broken|failing)|why did you)", re.I)
HANDOFF_RE = re.compile(r"HANDOFF\.md", re.I)


# ── arms ────────────────────────────────────────────────────────────────────

def rules_dir(claude_dir: Path) -> Path:
    return claude_dir / "rules"


def ambient_files(directory: Path) -> list[Path]:
    out = []
    for p in sorted(directory.glob("*.md")):
        try:
            if not has_paths_frontmatter(p.read_text(encoding="utf-8")):
                out.append(p)
        except Exception:
            out.append(p)
    return out


def build_lean(claude_dir: Path, source: Path | None = None) -> dict:
    """rules.lean beside rules: the KEEP list plus every path-scoped rule (and the
    incidents/ and manifests/ subtrees, which are not loaded ambiently)."""
    live = rules_dir(claude_dir)
    src = source or (live.resolve() if live.is_symlink() else live)
    if not src.is_dir():
        raise SystemExit(f"lean-core-ab: no rules directory at {src}")
    lean = claude_dir / "rules.lean"
    if lean.exists():
        shutil.rmtree(lean)
    lean.mkdir(parents=True)
    kept, dropped, scoped = [], [], []
    for p in sorted(src.iterdir()):
        if p.is_dir():
            shutil.copytree(p, lean / p.name)
            continue
        if p.suffix != ".md":
            shutil.copy2(p, lean / p.name)
            continue
        text = p.read_text(encoding="utf-8")
        is_scoped = False
        try:
            is_scoped = has_paths_frontmatter(text)
        except Exception:
            pass
        if is_scoped:
            shutil.copy2(p, lean / p.name)
            scoped.append(p.name)
        elif p.name in LEAN_KEEP:
            shutil.copy2(p, lean / p.name)
            kept.append(p.name)
        else:
            dropped.append(p.name)
    lean_bytes = sum((lean / n).stat().st_size for n in kept)
    full_bytes = sum(p.stat().st_size for p in ambient_files(src))
    return {"lean_dir": str(lean), "kept": kept, "dropped_from_ambient": dropped, "path_scoped": scoped,
            "ambient_bytes_full": full_bytes, "ambient_bytes_lean": lean_bytes, "target_bytes": LEAN_TARGET_BYTES,
            "missing_keepers": [n for n in LEAN_KEEP if not (src / n).exists()]}


def arm_log_path(claude_dir: Path) -> Path:
    return claude_dir / "audit" / "rules-arm-log.jsonl"


def switch(claude_dir: Path, arm: str, now: dt.datetime | None = None) -> dict:
    arm = arm.upper()
    if arm not in ("A", "B"):
        raise SystemExit("lean-core-ab: arm must be A or B")
    live = rules_dir(claude_dir)
    full, lean = claude_dir / "rules.full", claude_dir / "rules.lean"
    if not live.is_symlink():
        if not live.is_dir():
            raise SystemExit(f"lean-core-ab: no rules directory at {live}")
        if full.exists():
            raise SystemExit(f"lean-core-ab: {full} already exists and {live} is a real directory; resolve by hand")
        live.rename(full)                                   # first run: preserve the live set
    if not lean.is_dir():
        raise SystemExit(f"lean-core-ab: {lean} does not exist; run `build-lean` first")
    if not full.is_dir():
        raise SystemExit(f"lean-core-ab: {full} does not exist")
    target = full if arm == "A" else lean
    if live.is_symlink() or live.exists():
        live.unlink()
    live.symlink_to(target.name)                             # relative: survives a moved home
    stamp = (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")
    (claude_dir / "run").mkdir(parents=True, exist_ok=True)
    (claude_dir / "run" / "rules-arm.env").write_text(f"CLAUDE_RULES_ARM={arm}\n", encoding="utf-8")
    arm_log_path(claude_dir).parent.mkdir(parents=True, exist_ok=True)
    with open(arm_log_path(claude_dir), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": stamp, "arm": arm, "target": str(target)}) + "\n")
    return {"arm": arm, "rules": str(live), "target": str(target), "ts": stamp}


def load_arm_log(claude_dir: Path) -> list[dict]:
    rows = []
    try:
        for line in arm_log_path(claude_dir).read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return sorted(rows, key=lambda r: r.get("ts", ""))


def arm_for(ts: dt.datetime, log: list[dict]) -> str | None:
    """The arm in force at `ts`: the last switch at or before it."""
    current = None
    for row in log:
        try:
            when = dt.datetime.fromisoformat(row["ts"])
        except (KeyError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        if when <= ts:
            current = row.get("arm")
        else:
            break
    return current


# ── sessions ────────────────────────────────────────────────────────────────

def _parse_ts(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _transcript_metrics(path: Path) -> dict:
    """Counts only. Never returns text."""
    m = {"prompts": 0, "corrections": 0, "tool_uses": 0, "claims": 0, "claims_with_evidence": 0,
         "handoff": False, "start": None, "model": ""}
    last_tool_result_idx = -10
    idx = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                idx += 1
                if m["start"] is None:
                    m["start"] = _parse_ts(rec.get("timestamp"))
                msg = rec.get("message") or {}
                role = msg.get("role") or rec.get("type")
                content = msg.get("content")
                blocks = content if isinstance(content, list) else [{"type": "text", "text": content}] if isinstance(content, str) else []
                if role == "assistant":
                    m["model"] = m["model"] or str(msg.get("model") or "")
                    text = " ".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
                    m["tool_uses"] += sum(1 for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use")
                    if text and CLAIM_RE.search(text):
                        m["claims"] += 1
                        if EVIDENCE_RE.search(text) or idx - last_tool_result_idx <= 3:
                            m["claims_with_evidence"] += 1
                    if HANDOFF_RE.search(text):
                        m["handoff"] = True
                elif role == "user":
                    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
                        last_tool_result_idx = idx
                        continue
                    text = " ".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
                    if not text.strip() or text.lstrip().startswith("<"):
                        continue                               # hook injections, system reminders
                    m["prompts"] += 1
                    if CORRECTION_RE.search(text.strip()):
                        m["corrections"] += 1
    except OSError:
        pass
    return m


def sessions(claude_dir: Path, since: dt.datetime | None) -> list[dict]:
    """One row per session, from SessionEnd receipts (+ compaction state)."""
    receipts = claude_dir / "session-end-receipts"
    rows: dict[str, dict] = {}
    for p in sorted(glob.glob(str(receipts / "*.json"))):
        try:
            r = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sid = str(r.get("session_id") or Path(p).stem)
        ended = _parse_ts(r.get("ended_at"))
        row = {"session_id": sid, "ended": ended, "transcript": r.get("transcript_path") or "",
               "model": str(((r.get("runtime_provenance") or {}).get("session_start_model")) or "")}
        tp = Path(row["transcript"]) if row["transcript"] else None
        if tp and tp.is_file():
            row.update(_transcript_metrics(tp))
        else:
            row.update({"prompts": 0, "corrections": 0, "tool_uses": 0, "claims": 0, "claims_with_evidence": 0,
                        "handoff": False, "start": None})
        row["start"] = row.get("start") or ended
        rows[sid] = row
    for p in glob.glob(str(claude_dir / "run" / "compaction-budget" / "*.json")):
        try:
            state = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sid = Path(p).stem
        row = rows.setdefault(sid, {"session_id": sid, "ended": None, "transcript": "", "model": "", "prompts": 0,
                                    "corrections": 0, "tool_uses": 0, "claims": 0, "claims_with_evidence": 0,
                                    "handoff": False, "start": None})
        row["compactions"] = int(state.get("count", 0))
        if row["start"] is None:
            row["start"] = _parse_ts(state.get("last_at_utc")) or dt.datetime.fromtimestamp(Path(p).stat().st_mtime, dt.timezone.utc)
    out = []
    for row in rows.values():
        row.setdefault("compactions", 0)
        if row["start"] is None:
            continue
        if since and row["start"] < since:
            continue
        out.append(row)
    return out


def hook_fires(claude_dir: Path, since: dt.datetime | None) -> list[dict]:
    rows = []
    for p in sorted(glob.glob(str(claude_dir / "audit" / "hook-fires-*.jsonl"))):
        day = Path(p).stem[len("hook-fires-"):]
        try:
            day_dt = dt.datetime.strptime(day, "%Y%m%d").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if since and day_dt.date() < since.date():
            continue
        try:
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                ts = _parse_ts(r.get("ts")) or day_dt
                if isinstance(r.get("ts"), (int, float)):
                    ts = dt.datetime.fromtimestamp(float(r["ts"]), dt.timezone.utc)
                rows.append({"ts": ts, "hook": str(r.get("hook") or ""), "exit": r.get("exit")})
        except OSError:
            continue
    return rows


# ── report ──────────────────────────────────────────────────────────────────

def _rate(num: float, den: float, scale: float = 100.0):
    return round(scale * num / den, 2) if den else None


def build_report(claude_dir: Path, since: dt.datetime | None) -> dict:
    log = load_arm_log(claude_dir)
    per_arm = {a: Counter() for a in ("A", "B")}
    flagged = Counter()
    arm_days = {a: set() for a in ("A", "B")}
    for s in sessions(claude_dir, since):
        arm = arm_for(s["start"], log)
        if arm not in per_arm:
            continue
        c = per_arm[arm]
        c["sessions"] += 1
        arm_days[arm].add(s["start"].date().isoformat())
        for k in ("prompts", "corrections", "tool_uses", "claims", "claims_with_evidence", "compactions"):
            c[k] += int(s.get(k) or 0)
        if s.get("claims", 0) == 0 and not s.get("handoff"):
            c["abandoned"] += 1
        model = (s.get("model") or "").lower()
        if model and not any(tag in model for tag in PLAN_MODELS):
            flagged[arm] += 1
    for f in hook_fires(claude_dir, since):
        arm = arm_for(f["ts"], log)
        if arm not in per_arm:
            continue
        if f["hook"].startswith("bash-pretooluse-dispatcher"):
            per_arm[arm]["bash_calls"] += 1
        if any(f["hook"].startswith(g) for g in SAFETY_GUARDS) and f.get("exit") == 2:
            per_arm[arm]["safety_blocks"] += 1
    metrics = {}
    for arm, c in per_arm.items():
        metrics[arm] = {
            "sessions": c["sessions"],
            "arm_days": len(arm_days[arm]),
            "flagged_model_sessions": flagged[arm],
            "P1_completion_evidence_rate_pct": _rate(c["claims_with_evidence"], c["claims"]),
            "P2_corrections_per_100_prompts": _rate(c["corrections"], c["prompts"]),
            "S1_safety_blocks_per_100_bash": _rate(c["safety_blocks"], c["bash_calls"]),
            "S2_actions_per_prompt": _rate(c["tool_uses"], c["prompts"], 1.0),
            "S3_compactions_per_session": _rate(c["compactions"], c["sessions"], 1.0),
            "S5_abandonment_pct": _rate(c["abandoned"], c["sessions"]),
            "_counts": dict(c),
        }
    return {"since": since.isoformat() if since else None, "arm_log_entries": len(log), "arms": metrics,
            "verdict": decide(metrics)}


def decide(metrics: dict) -> dict:
    a, b = metrics["A"], metrics["B"]
    if a["arm_days"] + b["arm_days"] < MIN_ARM_DAYS or min(a["sessions"], b["sessions"]) < MIN_ARM_SESSIONS:
        return {"decision": "INSUFFICIENT DATA",
                "why": f"need {MIN_ARM_DAYS} arm-days and {MIN_ARM_SESSIONS} sessions per arm; have "
                       f"{a['arm_days'] + b['arm_days']} days, A={a['sessions']} B={b['sessions']} sessions"}
    checks = {}
    p1a, p1b = a["P1_completion_evidence_rate_pct"], b["P1_completion_evidence_rate_pct"]
    checks["1 P1(B) >= P1(A) - 5"] = (p1a is None or p1b is None) or p1b >= p1a - 5
    p2a, p2b = a["P2_corrections_per_100_prompts"], b["P2_corrections_per_100_prompts"]
    checks["2 P2(B) <= 1.2 x P2(A)"] = (p2a is None or p2b is None) or p2b <= 1.2 * p2a
    s1a, s1b = a["S1_safety_blocks_per_100_bash"], b["S1_safety_blocks_per_100_bash"]
    checks["3 S1(B) <= 1.2 x S1(A)"] = (s1a is None or s1b is None) or s1b <= 1.2 * s1a
    if all(checks.values()):
        payoff = []
        for key in ("S2_actions_per_prompt", "S3_compactions_per_session", "S5_abandonment_pct"):
            va, vb = a[key], b[key]
            if va and vb is not None and vb <= 0.85 * va:
                payoff.append(key)
        return {"decision": "ADOPT", "checks": checks,
                "payoff": payoff or ["none >= 15%: adopt anyway, the cut was free"]}
    failing = [k for k, ok in checks.items() if not ok]
    return {"decision": "BISECT", "checks": checks, "failing": failing,
            "order": [{"family": f, "restore": list(FAMILIES[f])} for f in FAMILIES],
            "why": "do not revert wholesale; restore one family per two-day block until the failing metric recovers"}


def render_report(rep: dict) -> str:
    lines = [f"lean-core A/B report{' since ' + rep['since'] if rep['since'] else ''}   (arm log entries: {rep['arm_log_entries']})", ""]
    keys = ("sessions", "arm_days", "flagged_model_sessions", "P1_completion_evidence_rate_pct",
            "P2_corrections_per_100_prompts", "S1_safety_blocks_per_100_bash", "S2_actions_per_prompt",
            "S3_compactions_per_session", "S5_abandonment_pct")
    lines.append(f"{'metric':<36}{'A full':>12}{'B lean':>12}")
    for k in keys:
        va, vb = rep["arms"]["A"][k], rep["arms"]["B"][k]
        fmt = lambda v: "-" if v is None else str(v)  # noqa: E731
        lines.append(f"{k:<36}{fmt(va):>12}{fmt(vb):>12}")
    v = rep["verdict"]
    lines.append("")
    lines.append(f"verdict: {v['decision']}")
    for k in ("why", "failing", "payoff"):
        if v.get(k):
            lines.append(f"  {k}: {v[k]}")
    if v.get("checks"):
        for name, ok in v["checks"].items():
            lines.append(f"  {'ok  ' if ok else 'FAIL'} {name}")
    if v.get("order"):
        lines.append("  bisect order:")
        for step in v["order"]:
            lines.append(f"    {step['family']}: {', '.join(step['restore'])}")
    lines.append("")
    lines.append("P1/P2/S2/S5 are transcript proxies (counts only, identical for both arms); S1 and S3 are hook telemetry.")
    return "\n".join(lines)


def status(claude_dir: Path) -> dict:
    live = rules_dir(claude_dir)
    log = load_arm_log(claude_dir)
    current = log[-1] if log else None
    days = Counter()
    for row in log:
        try:
            days[row["arm"]] += 0
        except KeyError:
            pass
    for s in sessions(claude_dir, None):
        arm = arm_for(s["start"], log)
        if arm:
            days[arm] += 1
    return {"rules": str(live), "is_symlink": live.is_symlink(), "points_to": os.readlink(live) if live.is_symlink() else None,
            "current_arm": current.get("arm") if current else None, "since": current.get("ts") if current else None,
            "switches": len(log), "sessions_per_arm": dict(days),
            "lean_exists": (claude_dir / "rules.lean").is_dir(), "full_exists": (claude_dir / "rules.full").is_dir()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--claude-dir", default=str(CLAUDE_DIR), help="config root (default $CLAUDE_CONFIG_DIR or ~/.claude)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-lean", help="create rules.lean from the KEEP list")
    b.add_argument("--rules", default=None, help="source rules directory (default: the live one)")
    s = sub.add_parser("switch", help="point rules at an arm")
    s.add_argument("arm", choices=["A", "B", "a", "b"])
    sub.add_parser("status")
    r = sub.add_parser("report")
    r.add_argument("--since", default=None, help="YYYY-MM-DD")
    r.add_argument("--json", action="store_true")
    args = ap.parse_args()
    cdir = Path(args.claude_dir)
    if args.cmd == "build-lean":
        res = build_lean(cdir, Path(args.rules) if args.rules else None)
        print(f"rules.lean: {res['lean_dir']}")
        print(f"  kept ambient   {len(res['kept'])}  ({res['ambient_bytes_lean']:,} B; target <= {res['target_bytes']:,} B"
              f"{' -- trim per docs/rules-ratchet-plan.md' if res['ambient_bytes_lean'] > res['target_bytes'] else ''})")
        print(f"  full ambient   {res['ambient_bytes_full']:,} B")
        print(f"  not loaded ambiently in B ({len(res['dropped_from_ambient'])}): {', '.join(res['dropped_from_ambient'])}")
        print(f"  path-scoped, copied unchanged ({len(res['path_scoped'])}): {', '.join(res['path_scoped'])}")
        if res["missing_keepers"]:
            print(f"  keepers not present in the source: {', '.join(res['missing_keepers'])}")
        return 0
    if args.cmd == "switch":
        res = switch(cdir, args.arm)
        print(f"arm {res['arm']}: {res['rules']} -> {res['target']}  ({res['ts']})")
        return 0
    if args.cmd == "status":
        print(json.dumps(status(cdir), indent=2, sort_keys=True))
        return 0
    since = None
    if args.since:
        since = dt.datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    rep = build_report(cdir, since)
    print(json.dumps(rep, indent=2, sort_keys=True, default=str) if args.json else render_report(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
