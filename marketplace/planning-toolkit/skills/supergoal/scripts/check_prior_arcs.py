#!/usr/bin/env python3
"""Check prior terminal-docs for the plan's metric names. Revised semantics
per academic research on Reflexion-style failure history:

- 0 prior arcs: silent
- 1-2 prior arcs: soft-warn (emit ledger; proceed) — failure history in
  context helps the next attempt (Reflexion's empirical lift)
- 3+ prior arcs: hard-refuse unless --force-rerun. This is the
  structural-ceiling signal — past 3 attempts, max_recoverable_lift must
  be demonstrated before re-attempting (superplan Phase 3.6 field 3)

Always writes a ≤200-token ledger snippet to state.prior_arc_ledger so
the hook re-emits it each turn (skill content evaporates after compaction;
the ledger must travel through state.json, not SKILL.md).

Usage:
    check_prior_arcs.py <state-dir-or-state-json>

Exit codes (matched against references/headless.md table):
    0  - clean, soft-warn, or --force-rerun accepted
    21 - prior-arcs-exist: 3+ prior arcs and --force-rerun not set; ledger emitted; refused
    1  - other error (state file missing/corrupt)
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from state_io import locked_state, CorruptStateError


HARD_REFUSE_THRESHOLD = 3

# Setup-time exit code — must match references/headless.md "Exit codes" table.
EXIT_PRIOR_ARCS_EXIST = 21


USAGE = (
    "usage: check_prior_arcs.py <state-dir-or-state-json>\n"
    "  Surface prior-arc fingerprints relevant to the current supergoal state.\n"
    "  -h, --help  show this help message and exit"
)


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(USAGE)
        sys.exit(0)
    if len(sys.argv) != 2:
        sys.exit(USAGE)
    arg = Path(sys.argv[1]).expanduser()
    state_path = arg if arg.suffix == ".json" else arg / "state.json"
    if not state_path.exists():
        sys.exit(f"state file not found: {state_path}")

    plans_dir = Path.home() / "Documents" / "knowledge-base" / "plans"
    if not plans_dir.exists():
        print("PRIOR-ARC: skipped (no ~/Documents/knowledge-base/plans/)")
        return 0

    try:
        with locked_state(state_path) as state:
            metric_names = state.get("metric_names", [])
            force_rerun = state.get("force_rerun", False)
            own_slug = state.get("plan_slug", "")
    except CorruptStateError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not metric_names:
        print("PRIOR-ARC: skipped (no metric_names extracted). Declare the plan's "
              "metrics as `METRIC <name>=<target>` lines (any case) so the prior-arc "
              "guard can match them against past terminal docs.")
        return 0

    hits = []
    for term in plans_dir.glob("*-terminal.md"):
        if own_slug and term.stem.startswith(own_slug):
            continue
        text = term.read_text(encoding="utf-8")
        matched = [m for m in metric_names if re.search(rf"\b{re.escape(m)}\b", text)]
        if not matched:
            continue
        hits.append({
            "file": str(term),
            "date": _date_from_name(term.name),
            "matched_metrics": matched,
            "exit_reason": _extract(r"(?im)^\s*\*{0,2}Exit reason\*{0,2}:\s*(.+?)\s*$", text) or "?",
            "retired_hypothesis": _first_line(_extract(r"(?ims)^##+\s*Retired hypothesis\s*\n(.+?)(?=^##\s|\Z)", text)),
        })

    hits.sort(key=lambda h: h["date"] or "")

    ledger_md = _format_ledger(hits)
    with locked_state(state_path) as state:
        state["prior_arc_ledger"] = ledger_md
        state["prior_arc_count"] = len(hits)
        if hits and (force_rerun or len(hits) < HARD_REFUSE_THRESHOLD):
            state["lineage"] = [h["file"] for h in hits]

    if not hits:
        print(f"PRIOR-ARC: clean ({len(metric_names)} metric(s) not seen)")
        return 0

    print(ledger_md)
    print()

    if len(hits) < HARD_REFUSE_THRESHOLD:
        print(f"SOFT-WARN: {len(hits)} prior arc(s) exist; proceeding with ledger attached to context.")
        print("           Per-turn hook will re-emit this ledger so retired hypotheses stay visible.")
        return 0

    if force_rerun:
        print(f"FORCE-RERUN: {len(hits)} prior arcs (>= {HARD_REFUSE_THRESHOLD}); proceeding under explicit override.")
        print("           Terminal doc will carry full lineage chain.")
        return 0

    print(f"REFUSED: {len(hits)} prior arcs (>= {HARD_REFUSE_THRESHOLD} threshold).")
    print("         Structural-ceiling signal — past 3 attempts, superplan Phase 3.6")
    print("         requires demonstrating max_recoverable_lift before re-attempting.")
    print("         Override with --force-rerun if max-lift analysis is in the new plan.")
    return EXIT_PRIOR_ARCS_EXIST


def _format_ledger(hits):
    if not hits:
        return ""
    lines = [f"PRIOR-ARC LEDGER ({len(hits)} arc(s) targeting these metrics):"]
    for h in hits:
        lines.append(
            f"  {h['date'] or '?'} [{h['exit_reason'][:25]}] "
            f"metrics={','.join(h['matched_metrics'])} "
            f"retired=\"{(h['retired_hypothesis'] or '')[:50]}\""
        )
    return "\n".join(lines)


def _extract(pattern, text):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def _first_line(s):
    if not s:
        return None
    lines = s.strip().splitlines()
    return lines[0] if lines else None


def _date_from_name(name):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", name)
    return m.group(1) if m else None


if __name__ == "__main__":
    sys.exit(main())
