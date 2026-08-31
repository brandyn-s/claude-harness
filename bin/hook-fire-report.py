#!/usr/bin/env python3
"""Aggregate hook fire-rate telemetry written by hooks/run-hook.

run-hook appends one JSONL line per invocation to
  ~/.claude/audit/hook-fires-YYYYMMDD.jsonl   {"ts","hook","exit","ms"}

This tool rolls those up per hook so you can answer the obsolescence question
with data instead of guesses:

  - invocations : how often the matcher actually fires the hook
  - blocks      : exit 2 (a PreToolUse hook that hard-blocked)
  - auto-fixes  : exit 0 + updated_input (a guard that REWROTE the call instead
                  of blocking). Exit codes can't distinguish an auto-rewrite
                  from a plain allow, so this count comes from the per-guard
                  decision logs (audit/<prefix>-YYYY-MM-DD.jsonl), not hook-fires.
  - crashes     : exit not in (0, 2) — a hook erroring out
  - p50/p95 ms  : latency; flags hooks creeping toward their timeout

Triage hints:
  - A blocking guard with invocations >> 0 but blocks == 0 AND auto_fixes == 0
    over a long window is a prune/test candidate (it never catches anything).
    A guard that AUTO-FIXES is earning its keep even with blocks == 0 — it is
    NOT a prune candidate (this is why auto_fixes is read here: the 2026-06-13
    block->auto-rewrite conversion of bash-tail-buffering-guard /
    inline-python-guard would otherwise look like a guard that "stopped
    blocking" and get falsely flagged).
  - A hook that is never invoked has a dead/over-narrow matcher.
  - WARN-ONLY hooks (exit 0 + systemMessage, e.g. security-write-confirm,
    loop-detector) do NOT show up as "blocks"
    or "auto_fixes"; their fire-rate is in manifest_metrics' advisory log.

Usage:
  python bin/hook-fire-report.py                 # all logs under ~/.claude/audit
  python bin/hook-fire-report.py --days 7        # only the last 7 days of files
  python bin/hook-fire-report.py --dir /path     # custom audit dir
  python bin/hook-fire-report.py --json          # machine-readable
"""
import argparse
import datetime as dt
import glob
import json
import os
from pathlib import Path

# Blocking PreToolUse hooks: invocations with zero blocks AND zero auto-fixes
# over a long window are prune/test candidates. (Warn-only hooks excluded.)
BLOCKING_HOOKS = {
    "bash-security-guard.py", "search-path-guard.py", "block-partial-read.py",
    "config-guard.py", "memory-write-guard.py", "destructive-ops-guard.py",
    "git-empty-push-guard.py", "bash-tail-buffering-guard.py",
    "promise-checker.py",
}

# Guards that emit a per-decision audit log ({"action": "auto-fixed"|"blocked"}).
# Maps hook script name -> audit-log filename prefix (audit/<prefix>-YYYY-MM-DD.jsonl).
# This is the only place the auto-fix signal is recoverable — run-hook's
# hook-fires log records exit code only, and an auto-rewrite exits 0.
AUTOFIX_LOGS = {
    "bash-security-guard.py": "bash-security",
    "bash-tail-buffering-guard.py": "bash-tail-buffering",
}


def _default_dir() -> Path:
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or str(Path.home())
    return Path(home) / ".claude" / "audit"


def _percentile(values, pct):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100) * (len(s) - 1)))))
    return s[k]


def load(audit_dir: Path, days: int | None):
    cutoff = None
    if days:
        cutoff = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y%m%d")
    rows = []
    for f in sorted(glob.glob(str(audit_dir / "hook-fires-*.jsonl"))):
        if cutoff:
            stamp = Path(f).stem.replace("hook-fires-", "")
            if stamp.isdigit() and stamp < cutoff:
                continue
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue
    return rows


def load_autofix_counts(audit_dir: Path, days: int | None):
    """Per-hook auto-fix / logged-block counts from the per-guard decision logs.

    Returns {hook_name: {"auto_fixes": n, "logged_blocks": n}}. The block count
    here is from the guard's own log (a cross-check on hook-fires' exit-2 count);
    the auto_fixes count is the signal hook-fires structurally cannot capture.
    """
    cutoff = None
    if days:
        cutoff = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    counts = {}
    for hook, prefix in AUTOFIX_LOGS.items():
        c = counts.setdefault(hook, {"auto_fixes": 0, "logged_blocks": 0})
        for f in glob.glob(str(audit_dir / f"{prefix}-*.jsonl")):
            stamp = Path(f).stem[len(prefix) + 1:]  # YYYY-MM-DD
            if cutoff and stamp < cutoff:
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            action = json.loads(line).get("action")
                        except (json.JSONDecodeError, ValueError):
                            continue
                        if action == "auto-fixed":
                            c["auto_fixes"] += 1
                        elif action == "blocked":
                            c["logged_blocks"] += 1
            except OSError:
                continue
    return counts


def aggregate(rows):
    agg = {}
    for r in rows:
        hook = r.get("hook", "?")
        a = agg.setdefault(hook, {"invocations": 0, "blocks": 0, "crashes": 0, "ms": []})
        a["invocations"] += 1
        code = r.get("exit")
        if code == 2:
            a["blocks"] += 1
        elif code not in (0, 2, None):
            a["crashes"] += 1
        ms = r.get("ms")
        if isinstance(ms, (int, float)):
            a["ms"].append(ms)
    return agg


def main():
    ap = argparse.ArgumentParser(description="Aggregate hook fire-rate telemetry.")
    ap.add_argument("--dir", type=Path, default=None)
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    audit_dir = args.dir or _default_dir()
    rows = load(audit_dir, args.days)
    if not rows:
        print(f"No telemetry found in {audit_dir} "
              f"(hook-fires-*.jsonl). run-hook writes it as hooks fire.")
        return
    agg = aggregate(rows)
    autofix = load_autofix_counts(audit_dir, args.days)

    window = f" (last {args.days}d)" if args.days else ""
    rolled = []
    for hook, a in agg.items():
        rolled.append({
            "hook": hook,
            "invocations": a["invocations"],
            "blocks": a["blocks"],
            "auto_fixes": autofix.get(hook, {}).get("auto_fixes", 0),
            "crashes": a["crashes"],
            "p50_ms": _percentile(a["ms"], 50),
            "p95_ms": _percentile(a["ms"], 95),
        })
    rolled.sort(key=lambda x: x["invocations"], reverse=True)

    if args.json:
        print(json.dumps({"window_days": args.days, "dir": str(audit_dir), "hooks": rolled}, indent=2))
        return

    print(f"Hook fire-rate report{window} — {len(rows)} invocations across "
          f"{len(agg)} hooks  [{audit_dir}]")
    print(f"{'HOOK':<38} {'INVOKES':>8} {'BLOCKS':>7} {'AUTOFIX':>8} {'CRASH':>6} {'p50ms':>6} {'p95ms':>6}")
    print("-" * 86)
    for r in rolled:
        p50 = "" if r["p50_ms"] is None else r["p50_ms"]
        p95 = "" if r["p95_ms"] is None else r["p95_ms"]
        af = r["auto_fixes"] or ""
        print(f"{r['hook']:<38} {r['invocations']:>8} {r['blocks']:>7} {af:>8} "
              f"{r['crashes']:>6} {p50:>6} {p95:>6}")

    # Friction summary: auto-fixes are the correction-turns the guards saved by
    # rewriting instead of blocking (each block costs the model a re-attempt turn).
    total_autofix = sum(r["auto_fixes"] for r in rolled)
    total_blocks = sum(r["blocks"] for r in rolled)
    print()
    print(f"FRICTION: {total_autofix} auto-fixes (~correction-turns saved) vs "
          f"{total_blocks} hard blocks (~turns spent re-attempting).")

    # Obsolescence / health flags
    never_block = [r["hook"] for r in rolled
                   if r["hook"] in BLOCKING_HOOKS and r["blocks"] == 0
                   and r["auto_fixes"] == 0]
    crashy = [r["hook"] for r in rolled if r["crashes"] > 0]
    slow = [(r["hook"], r["p95_ms"]) for r in rolled
            if isinstance(r["p95_ms"], (int, float)) and r["p95_ms"] >= 2500]

    print()
    if never_block:
        print("PRUNE/TEST CANDIDATES — blocking guards that neither blocked nor "
              "auto-fixed in this window:")
        for h in never_block:
            print(f"  - {h}")
    if crashy:
        print("CRASHING — non-0/2 exits (investigate):")
        for h in crashy:
            print(f"  - {h}")
    if slow:
        print("SLOW — p95 near the 3s hook timeout:")
        for h, p in slow:
            print(f"  - {h} ({p}ms)")
    if not (never_block or crashy or slow):
        print("No prune/crash/latency flags in this window.")
    print("\nNote: warn-only hooks (exit 0 + systemMessage) don't appear as BLOCKS "
          "or AUTOFIX; see manifest_metrics advisory log for their fire-rate.")


if __name__ == "__main__":
    main()
