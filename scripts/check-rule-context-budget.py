#!/usr/bin/env python3
"""Fail when the always-loaded rule corpus exceeds its aggregate budget."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "hooks"))
from rule_context_budget import (  # noqa: E402
    AB_TARGET_HIGH_BYTES,
    AB_TARGET_LOW_BYTES,
    HARD_CAP_BYTES,
    RuleContextBudgetError,
    WARN_BYTES,
    scan_unconditional_rules,
)

# Bytes-per-token: 2.72, MEASURED 2026-08-31 against Anthropic's
# /v1/messages/count_tokens on this repository's own ambient corpus
# (206,488 B -> 75,420 tokens, claude-sonnet-5, corpus in the `system`
# field because that is how ambient rules actually load).
#
# It was 4.0 (a bytes/4 estimate), which understated the corpus by 47% --
# this advisory reported ~51,607 tokens against a 50,000-60,000 target band
# while the true figure was 75,413, i.e. 25% ABOVE the band's ceiling. A
# self-measurement that flatters the thing it measures is worse than none.
#
# Re-derive rather than trust this constant if the corpus changes character:
# prose with dense code blocks and DSL markers tokenizes very differently
# from ordinary English, and 2.72 is specific to THIS corpus.
BYTES_PER_TOKEN = 2.72


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rules-dir",
        type=Path,
        default=REPO / "rules",
        help="rules directory to measure (default: repository rules/)",
    )
    args = parser.parse_args(argv)

    rules_dir = args.rules_dir.expanduser().resolve()
    if not rules_dir.is_dir():
        print(f"FAIL: rules directory does not exist: {rules_dir}", file=sys.stderr)
        return 2

    try:
        snapshot = scan_unconditional_rules(rules_dir)
    except RuleContextBudgetError as exc:
        print(f"ERROR: ambient rule context is unmeasurable: {exc}", file=sys.stderr)
        return 2

    size = snapshot.total_bytes
    tokens = int(size / BYTES_PER_TOKEN)
    summary = (
        f"ambient rule context: {len(snapshot.files)} files, {size:,} bytes, "
        f"~{tokens:,} tokens (A/B target {AB_TARGET_LOW_BYTES:,}-"
        f"{AB_TARGET_HIGH_BYTES:,}; warn {WARN_BYTES:,}; hard cap {HARD_CAP_BYTES:,})"
    )
    if size > HARD_CAP_BYTES:
        print(f"FAIL: {summary}", file=sys.stderr)
        print(
            "Compact or path-scope rules; move detailed rationale and incidents "
            "to on-demand references.",
            file=sys.stderr,
        )
        return 1
    if size > WARN_BYTES:
        print(f"WARN: {summary}")
        return 0
    if size > AB_TARGET_HIGH_BYTES:
        print(f"ADVISORY: {summary}")
        return 0
    print(f"OK: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
