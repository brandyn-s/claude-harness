#!/usr/bin/env python3
"""Install updated reproducers into a worklist YAML (audit-fix Step 4.5).

Agents supply `updated_reproducer` (on fixes AND on skipped findings —
see apply_fixes.py) when a finding's original reproducer cannot
adjudicate the fix:
  - doc-decoupled probes (run the broken pattern against the SHELL/host
    directly — fixing the doc can't flip them; 40 instances in the
    campaign-11 A1 batch)
  - deployed-path probes (~/.claude refs that test the deployed tree,
    not the tree under test)
  - stateful probes (append to a persistent file; stale lines keep the
    predicate firing after the fix)

This script swaps those reproducers in by finding index and re-emits the
worklist in the loader-safe literal-block form (multi-line commands as
`command: |` blocks; no width folding). PyYAML required.

Usage:
  patch_worklist.py <worklist.yaml> <apply-state.json> --out <patched.yaml>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: PyYAML required (python3 -m pip install pyyaml)", file=sys.stderr)
    sys.exit(2)


class IndentDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


class LiteralStr(str):
    pass


def _lit(dumper, s):
    return dumper.represent_scalar("tag:yaml.org,2002:str", s, style="|")


IndentDumper.add_representer(LiteralStr, _lit)


def emit(data, dest: Path):
    """Loader-safe emission: block-literal commands, no width folding."""
    for f in data["findings"]:
        rep = f.get("reproducer") or {}
        if rep.get("command"):
            c = str(rep["command"])
            rep["command"] = LiteralStr(c if c.endswith("\n") else c + "\n")
        for k, v in list(f.items()):
            if isinstance(v, str) and "\n" in v and not isinstance(v, LiteralStr):
                f[k] = LiteralStr(v if v.endswith("\n") else v + "\n")
    with dest.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, Dumper=IndentDumper, sort_keys=False,
                  allow_unicode=True, width=10**9)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("worklist", type=Path)
    ap.add_argument("state", type=Path, help="apply-state JSON from apply_fixes.py")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    for p in (args.worklist, args.state):
        if not p.exists():
            print(f"error: not found: {p}", file=sys.stderr)
            return 2
    try:
        data = yaml.safe_load(args.worklist.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"error: {args.worklist} is not valid YAML: {e}", file=sys.stderr)
        return 2
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        print(f"error: {args.worklist} is not a findings worklist", file=sys.stderr)
        return 2
    try:
        state = json.loads(args.state.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: {args.state} is not valid JSON: {e}", file=sys.stderr)
        return 2

    rows = data["findings"]
    updated = {int(k): v for k, v in (state.get("updated_reps") or {}).items()}
    # Skip-side corrected predicates (see apply_fixes.py docstring) are
    # installed identically — the finding wasn't edited, but its tracker
    # reproducer was decoupled/over-broad and the agent supplied the
    # honest one.
    updated.update(
        {int(k): v for k, v in (state.get("skip_updated_reps") or {}).items()})
    out_of_range = [i for i in updated if i >= len(rows)]
    if out_of_range:
        print(f"error: updated_reps indices {out_of_range} exceed worklist "
              f"size {len(rows)} — wrong state file for this worklist?",
              file=sys.stderr)
        return 2

    for idx, rep in updated.items():
        new_rep = {"type": rep["type"], "command": rep["command"]}
        if rep.get("expected_exit") not in (None, ""):
            new_rep["expected_exit"] = rep["expected_exit"]
        rows[idx]["reproducer"] = new_rep

    emit(data, args.out)
    print(f"patched {len(updated)} reproducers -> {args.out} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
