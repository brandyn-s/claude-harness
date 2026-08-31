#!/usr/bin/env python3
"""Compare advisory hook signal against invocation cost from offline audit logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MIN_SAMPLE = 100
MAX_KEEP_SIGNAL_RATE = 0.005


def _rows(paths):
    for path in paths:
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(row, dict):
                    yield row


def compare(audit_dir: Path) -> dict:
    fires = list(_rows(sorted(audit_dir.glob("hook-fires-*.jsonl"))))
    compliance = list(
        _rows(sorted(audit_dir.glob("manifest-compliance-*.jsonl")))
    )

    verify_invokes = sum(
        row.get("hook") == "verify-before-assuming.py" for row in fires
    )
    verify_records = [
        row for row in compliance if row.get("hook") == "verify-before-assuming"
    ]
    verify_test = sum(str(row.get("session", "")).startswith("pytest") for row in verify_records)
    verify_real = len(verify_records) - verify_test

    alias_rows = [row for row in fires if row.get("hook") == "skill-alias.py"]
    alias_real = sum(row.get("exit") == 2 for row in alias_rows)

    def result(invokes: int, real: int, tests: int = 0) -> dict:
        rate = real / invokes if invokes else 0.0
        remove = invokes >= MIN_SAMPLE and rate <= MAX_KEEP_SIGNAL_RATE
        return {
            "invocations": invokes,
            "real_signals": real,
            "test_records": tests,
            "signal_rate": rate,
            "decision": "remove" if remove else "retain",
        }

    return {
        "verify-before-assuming": result(verify_invokes, verify_real, verify_test),
        "skill-alias": result(len(alias_rows), alias_real),
        "policy": {
            "minimum_sample": MIN_SAMPLE,
            "maximum_remove_signal_rate": MAX_KEEP_SIGNAL_RATE,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = compare(args.audit_dir)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for name in ("verify-before-assuming", "skill-alias"):
            row = report[name]
            print(
                f"{name}: {row['real_signals']}/{row['invocations']} "
                f"({row['signal_rate']:.3%}) -> {row['decision']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
