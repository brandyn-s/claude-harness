#!/usr/bin/env python3
"""Compare a batch Layer-A reverify against expectations (audit-fix Step 5).

Expectation model:
  - every APPLIED finding (apply-state `applied`, plus any extra indices
    passed via --also-fixed for orchestrator-applied cross-cutting fixes,
    plus `skip_updated_reps` indices — skipped-as-already-fixed findings
    whose corrected predicate can now see the fixed tree)
    must adjudicate STALE (its reproducer no longer fires)
  - every other finding must NOT be STALE (an unfixed finding going
    quiet means either parallel work resolved it — fine, verify — or
    the reproducer broke; both deserve eyes)
  - --expect-fires indices are exempt from the first rule (e.g. a
    FALSE_POSITIVE the batch deliberately did not fix)

Exit 0 when there are zero unexpected outcomes; exit 1 otherwise, with
every deviation listed. The campaign-11 batches used exactly this gate
to catch a header-matching over-broad reproducer and three deployed-path
probes before they shipped as "fixed".

Usage:
  batch_verdicts.py <reverify.json> <patched-worklist.yaml> <apply-state.json>
      [--also-fixed 0,9,13] [--expect-fires 20]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: PyYAML required (python3 -m pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


def _indices(spec: str | None) -> set[int]:
    if not spec:
        return set()
    return {int(x) for x in spec.split(",") if x.strip()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reverify", type=Path, help="reverify --json output")
    ap.add_argument("worklist", type=Path, help="the patched worklist that was reverified")
    ap.add_argument("state", type=Path, help="apply-state JSON from apply_fixes.py")
    ap.add_argument("--also-fixed", help="comma-separated extra indices fixed by the orchestrator")
    ap.add_argument("--expect-fires", help="comma-separated indices expected to STILL-FIRE (e.g. FALSE_POSITIVEs)")
    args = ap.parse_args(argv)

    for p in (args.reverify, args.worklist, args.state):
        if not p.exists():
            print(f"error: not found: {p}", file=sys.stderr)
            return 2
    try:
        rows = json.loads(args.reverify.read_text(encoding="utf-8"))
        state = json.loads(args.state.read_text(encoding="utf-8"))
        wl = yaml.safe_load(args.worklist.read_text(encoding="utf-8"))["findings"]
    except (json.JSONDecodeError, yaml.YAMLError, KeyError, TypeError) as e:
        print(f"error: malformed input: {e}", file=sys.stderr)
        return 2
    if len(rows) != len(wl):
        print(f"error: reverify has {len(rows)} rows but worklist has "
              f"{len(wl)} findings — mismatched inputs", file=sys.stderr)
        return 2

    applied = {int(k) for k in (state.get("applied") or {})}
    applied |= _indices(args.also_fixed)
    # Skipped findings that carry a corrected reproducer are expected to
    # adjudicate STALE too: the agent verified the fix already exists in
    # the tree and supplied an honest predicate that can see it.
    skip_reps = {int(k) for k in (state.get("skip_updated_reps") or {})}
    applied |= skip_reps
    expect_fires = _indices(args.expect_fires)

    print("verdicts:", dict(Counter(r["status"] for r in rows)))
    unexpected = []
    for i, r in enumerate(rows):
        if i in expect_fires:
            if r["status"] == "STALE":
                unexpected.append((i, "expected STILL-FIRES (exempt) but STALE",
                                   r["skill"] + "/" + r["code"], ""))
            continue
        if i in applied and r["status"] != "STALE":
            unexpected.append((i, f"expected STALE, got {r['status']}",
                               r["skill"] + "/" + r["code"],
                               str(r.get("evidence", ""))[:110]))
        if i not in applied and r["status"] == "STALE":
            unexpected.append((i, "unfixed but STALE (parallel work or broken reproducer?)",
                               r["skill"] + "/" + r["code"], ""))

    print(f"expected-fixed: {len(applied)} "
          f"(incl. {len(skip_reps)} skip-side corrected predicates), "
          f"exempt: {len(expect_fires)}")
    print(f"unexpected outcomes: {len(unexpected)}")
    for u in unexpected:
        print("  ", u)
    return 0 if not unexpected else 1


if __name__ == "__main__":
    sys.exit(main())
