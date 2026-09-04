"""Analyze manifest layer metrics from hook audit logs.

Reads:
  ~/.claude/audit/manifest-queries-*.jsonl  — hook usage patterns
  ~/.claude/audit/manifest-compliance-*.jsonl — advisory effectiveness

Usage:
  python analyze_metrics.py              # analyze all available data
  python analyze_metrics.py --days 7     # last 7 days only
  python analyze_metrics.py --hook X     # filter to specific hook
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

AUDIT_DIR = Path.home() / ".claude" / "audit"


def load_jsonl(pattern, days=None):
    """Load JSONL entries matching a glob pattern, optionally filtered by age."""
    entries = []
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for f in sorted(AUDIT_DIR.glob(pattern)):
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if cutoff:
                        ts = entry.get("ts", "")
                        if ts and ts < cutoff.isoformat():
                            continue
                    entries.append(entry)
        except Exception:
            pass
    return entries


def analyze_queries(entries):
    """Analyze manifest query usage patterns."""
    by_hook = defaultdict(lambda: {"total": 0, "fallback": 0})

    for e in entries:
        hook = e.get("hook", "unknown")
        by_hook[hook]["total"] += 1
        if e.get("used_fallback"):
            by_hook[hook]["fallback"] += 1

    return dict(by_hook)


def analyze_compliance(entries):
    """Analyze advisory hook compliance rates."""
    by_hook = defaultdict(lambda: {"warned": 0, "passed": 0})

    for e in entries:
        hook = e.get("hook", "unknown")
        if e.get("warned"):
            by_hook[hook]["warned"] += 1
        else:
            by_hook[hook]["passed"] += 1

    return dict(by_hook)


def main():
    args = sys.argv[1:]
    days = 7  # default
    hook_filter = None

    for i, arg in enumerate(args):
        if arg == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
        elif arg == "--hook" and i + 1 < len(args):
            hook_filter = args[i + 1]

    # Load data
    query_entries = load_jsonl("manifest-queries-*.jsonl", days)
    compliance_entries = load_jsonl("manifest-compliance-*.jsonl", days)

    if hook_filter:
        query_entries = [e for e in query_entries if e.get("hook") == hook_filter]
        compliance_entries = [e for e in compliance_entries if e.get("hook") == hook_filter]

    print(f"MANIFEST METRICS — last {days} days")
    print(f"  Query log entries: {len(query_entries)}")
    print(f"  Compliance log entries: {len(compliance_entries)}")

    # Hook usage
    if query_entries:
        print("\nHook usage:")
        query_stats = analyze_queries(query_entries)
        for hook, stats in sorted(query_stats.items()):
            total = stats["total"]
            fallback = stats["fallback"]
            manifest_pct = 100 * (total - fallback) / total if total else 0
            print(f"  {hook:<30} {total:>4} fires, {total - fallback} manifest-first ({manifest_pct:.0f}%), {fallback} fallback ({100-manifest_pct:.0f}%)")
    else:
        print("\nNo manifest query data yet.")

    # Advisory compliance
    if compliance_entries:
        print("\nAdvisory compliance:")
        comp_stats = analyze_compliance(compliance_entries)
        for hook, stats in sorted(comp_stats.items()):
            warned = stats["warned"]
            passed = stats["passed"]
            total = warned + passed
            print(f"  {hook:<30} {total:>4} checks: {warned} write-warnings, {passed} read-passthroughs")

            if warned > 0:
                # Compliance rate would require tracking whether the agent
                # confirmed after the warning — that needs transcript analysis.
                # For now, we report warning count as the base metric.
                print(f"    -> {warned} warnings issued. Check transcripts for compliance rate.")
                if warned >= 3:
                    print("    WARNING: HIGH WARNING COUNT — consider upgrading to exit 2 (hard block)")
    else:
        print("\nNo advisory compliance data yet.")

    # Session distribution
    sessions = set()
    for e in query_entries + compliance_entries:
        sid = e.get("session", "")
        if sid:
            sessions.add(sid)
    print(f"\nSessions with manifest hook activity: {len(sessions)}")

    # Recommendations
    print("\nRECOMMENDATIONS:")
    query_stats = analyze_queries(query_entries) if query_entries else {}
    comp_stats = analyze_compliance(compliance_entries) if compliance_entries else {}

    recommendations = []

    # Check fallback rates
    for hook, stats in query_stats.items():
        if stats["total"] > 5 and stats["fallback"] / stats["total"] > 0.5:
            recommendations.append(
                f"  {hook}: >50% fallback rate — manifests may be incomplete or prompts don't reference skill names"
            )

    # Check advisory warning counts
    for hook, stats in comp_stats.items():
        if stats["warned"] >= 5:
            recommendations.append(
                f"  {hook}: {stats['warned']} warnings — upgrade to exit 2 if transcript analysis shows <70% compliance"
            )

    # Check for dead features
    for hook in ["subagent-start-context"]:
        if hook in query_stats:
            fallback_fires = sum(1 for e in query_entries
                                 if e.get("hook") == hook and e.get("query_type") == "topic_fallback")
            if query_stats[hook]["total"] > 10 and fallback_fires < 2:
                recommendations.append(
                    f"  {hook}: manifest fallback fired {fallback_fires}/{query_stats[hook]['total']} times — consider removing (dead code)"
                )

    if recommendations:
        for r in recommendations:
            print(r)
    else:
        print("  No actionable recommendations yet. Collect more data.")


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>"); sys.exit(0)
    main()
