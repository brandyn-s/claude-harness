#!/usr/bin/env python3
"""The always-loaded rule corpus must fit the derived ambient ceiling.

hooks/rule-size-guard.py evaluates the ledger only as an in-session nudge and
says hard enforcement lives in this file. Measured 2026-09-03: this file did not
exist, the corpus stood at 207,630 B against a derived ceiling of 206,506 B, and
nothing was red. A gate that runs nowhere is bookkeeping.

The ceiling is DERIVED (baseline + ledger deltas); see manifests/ambient-budget.json.
A missing or malformed ledger raises rather than passing, so deleting the ledger
cannot green this test.

Run: pytest scripts/test_context_policy_contracts.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "hooks"))

from rule_context_budget import (  # noqa: E402
    BUDGET_LEDGER_RELPATH,
    load_ambient_budget,
    unconditional_rule_bytes,
)


def test_unconditional_corpus_within_derived_ceiling():
    budget = load_ambient_budget(REPO / BUDGET_LEDGER_RELPATH)
    actual = unconditional_rule_bytes(REPO / "rules")
    assert actual <= budget.allowed_bytes, (
        f"always-loaded rule corpus is {actual:,} B against a derived ceiling of "
        f"{budget.allowed_bytes:,} B ({actual - budget.allowed_bytes:+,}). Relocate bytes "
        f"out of ambient or append a justified entry to {BUDGET_LEDGER_RELPATH}."
    )


def test_ceiling_check_fires_on_an_over_budget_fixture(tmp_path):
    """Known-positive control for the assertion above."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "a.md").write_text("x" * 100, encoding="utf-8")
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"baseline_unconditional_bytes": 50, "ledger": []}),
                      encoding="utf-8")
    budget = load_ambient_budget(ledger)
    assert unconditional_rule_bytes(rules) > budget.allowed_bytes
