#!/usr/bin/env python3
"""PoC / staleness gate for SARIF findings (semgrep, codeql, any SARIF tool).

Dedups, then drops findings whose flagged code is no longer present at the
cited location (STALE), keeping PRESENT / INCONCLUSIVE / ERROR. Reports at the
layer that fired. PRESENT means "still there", NOT "exploitable" — fp-check and
a human decide true-positive/severity.

Usage:
  sarif_poc_gate.py <results.sarif> --root <scanned-tree> [--json] [--no-dedup]

Exit codes: 0 always on a successful run (this filters + reports; it is not a
pass/fail gate), 2 on a SARIF load error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sarif_helpers import (  # noqa: E402
    SarifLoadError, load_sarif, extract_findings, gate_findings,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PoC/staleness gate for SARIF findings")
    ap.add_argument("sarif", help="path to a SARIF results file")
    ap.add_argument("--root", default=".", help="scanned source tree the findings cite")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a text report")
    ap.add_argument("--no-dedup", action="store_true", help="skip fingerprint dedup")
    args = ap.parse_args(argv)

    try:
        sarif = load_sarif(args.sarif)
    except SarifLoadError:
        return 2
    findings = extract_findings(sarif)
    res = gate_findings(findings, args.root, dedup=not args.no_dedup)
    s = res["summary"]
    if args.json:
        print(json.dumps({
            "summary": s,
            "kept": [{"rule_id": f.rule_id, "file": f.file_path,
                      "line": f.start_line, "verdict": getattr(f, "gate_verdict", "")}
                     for f in res["kept"]],
            "dropped": [{"rule_id": f.rule_id, "file": f.file_path, "line": f.start_line}
                        for f in res["dropped"]],
        }, indent=2))
    else:
        print(f"SARIF PoC gate: {s['raw']} raw -> {s['deduped']} deduped -> "
              f"kept {s['kept']} (dropped {s['dropped_stale']} stale)")
        print(f"  verdicts: {s['by_verdict']}")
        print(f"  {s['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
