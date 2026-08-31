#!/usr/bin/env python3
"""Historical activation metric for legacy routing-hint logs.

Sibling instrument to the per-skill efficacy harnesses (run_live.py / grade.py):
those measure whether a skill, *once invoked*, produces a good answer. This
measures the upstream question — when the routing hint SUGGESTS a skill, does
that skill actually FIRE? A skill can be perfectly accurate yet useless if it is
never activated.

Data source
-----------
`~/.claude/skill-usage.jsonl` was appended by the now-retired keyword-routing
hook. Existing records remain useful as historical hint telemetry; new native
skill discovery does not append to this file. Legacy records have these fields:

    {"ts": <iso8601>, "skill": <name|null>, "agent": <name|null>,
     "matched": <regex-matched substring>}

That record is a *hint* event. Whether the skill was then actually invoked is a
separate signal. Two optional, forward-compatible fields are honored if present:

  * "event":   "hint" (default when absent) or "invoked"
  * "invoked": truthy boolean on a hint record meaning the skill fired

When NEITHER signal is present anywhere in the log, activation cannot be derived
from hint-only data; the harness still reports per-skill hint counts and emits
`METRIC activation_median=NA` rather than fabricating a rate. The deliverable is
the instrument — point it at an environment that carries invocation data.

Metrics (per skill)
-------------------
  * count            -- number of hint events for the skill
  * activation_rate  -- of hinted prompts, fraction where the skill was invoked
                        (NA when no invocation signal exists)
  * false_positive_rate -- 1 - activation_rate (NA likewise); the rate at which a
                        hint did NOT lead to invocation

Pure stdlib. Read-only. Never crashes on missing/garbled data.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

USAGE_FILE = Path(os.path.expanduser("~")) / ".claude" / "skill-usage.jsonl"
RULES_FILE = Path(__file__).resolve().parent.parent.parent.parent / "hooks" / "skill-rules.json"


def load_must_activate() -> set:
    """Return the set of skill names tagged must_activate in skill-rules.json.

    Fail-open: any error -> empty set (no skills treated as must_activate).
    """
    try:
        with open(RULES_FILE, encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return set()
    out = set()
    for rule in config.get("rules", []):
        if rule.get("must_activate") and rule.get("skill"):
            out.add(rule["skill"])
    return out


def load_events(path: Path) -> list:
    """Parse the jsonl usage log into a list of dicts. Skips malformed lines."""
    events = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    events.append(rec)
    except OSError:
        return []
    return events


def _is_invoked(rec: dict) -> bool:
    """Best-effort: did this record represent an actual invocation?"""
    if rec.get("event") == "invoked":
        return True
    if rec.get("invoked"):
        return True
    return False


def _has_invocation_signal(events: list) -> bool:
    """True if ANY record carries an event-type / invoked signal at all."""
    for rec in events:
        if "event" in rec or "invoked" in rec:
            return True
    return False


def compute_per_skill(events: list) -> dict:
    """Aggregate per-skill counts and (when derivable) activation/FP rates.

    Returns {skill: {"count", "invoked", "activation_rate", "false_positive_rate"}}.
    Rates are None when no invocation signal exists in the data.
    """
    have_signal = _has_invocation_signal(events)
    stats: dict = {}
    for rec in events:
        skill = rec.get("skill")
        if not skill:
            continue  # agent-only routes have no skill to activate
        entry = stats.setdefault(skill, {"count": 0, "invoked": 0})
        entry["count"] += 1
        if _is_invoked(rec):
            entry["invoked"] += 1

    for skill, entry in stats.items():
        if have_signal and entry["count"] > 0:
            rate = entry["invoked"] / entry["count"]
            entry["activation_rate"] = rate
            entry["false_positive_rate"] = 1.0 - rate
        else:
            entry["activation_rate"] = None
            entry["false_positive_rate"] = None
    return stats


def _fmt_rate(v) -> str:
    return "NA" if v is None else f"{v:.3f}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--usage-file",
        default=str(USAGE_FILE),
        help="Path to skill-usage.jsonl (default: ~/.claude/skill-usage.jsonl)",
    )
    parser.add_argument(
        "--must-activate-only",
        action="store_true",
        help="Restrict the report to skills tagged must_activate in skill-rules.json",
    )
    args = parser.parse_args(argv)

    usage_path = Path(args.usage_file)
    if not usage_path.exists():
        print(
            "no activation history found at "
            f"{usage_path}; run in an environment with usage data "
            "(the legacy producer is retired; provide an archived or explicit usage log)."
        )
        print("METRIC activation_median=NA")
        return 0

    events = load_events(usage_path)
    if not events:
        print(
            f"activation history at {usage_path} is empty or unparseable; "
            "no skills to report."
        )
        print("METRIC activation_median=NA")
        return 0

    must_activate = load_must_activate()
    stats = compute_per_skill(events)

    if args.must_activate_only:
        stats = {k: v for k, v in stats.items() if k in must_activate}
        if not stats:
            print(
                "no must_activate skills present in the activation history "
                "(tagged skills: "
                + (", ".join(sorted(must_activate)) if must_activate else "none")
                + ")."
            )
            print("METRIC activation_median=NA")
            return 0

    have_signal = _has_invocation_signal(events)

    # Per-skill table
    name_w = max([len("skill")] + [len(k) for k in stats]) if stats else len("skill")
    header = f"{'skill':<{name_w}}  {'count':>6}  {'invoked':>7}  {'activation':>10}  {'false_pos':>9}  must_activate"
    print(header)
    print("-" * len(header))
    rates = []
    for skill in sorted(stats):
        e = stats[skill]
        ar = e["activation_rate"]
        if ar is not None:
            rates.append(ar)
        flag = "yes" if skill in must_activate else ""
        print(
            f"{skill:<{name_w}}  {e['count']:>6}  {e['invoked']:>7}  "
            f"{_fmt_rate(ar):>10}  {_fmt_rate(e['false_positive_rate']):>9}  {flag}"
        )

    if not have_signal:
        print()
        print(
            "note: no invocation signal in the data (records carry hint events "
            "only). Activation/false-positive rates require an 'event':'invoked' "
            "or 'invoked':true field. Reporting hint counts only."
        )

    if rates:
        median = statistics.median(rates)
        print(f"METRIC activation_median={median:.3f}")
    else:
        print("METRIC activation_median=NA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
