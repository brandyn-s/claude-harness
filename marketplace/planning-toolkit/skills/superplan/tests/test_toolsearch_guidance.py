"""Regression tests for superplan's active MCP discovery guidance."""

from pathlib import Path


REFERENCE = Path(__file__).resolve().parents[1] / "references" / "phase-2-and-3-detail.md"


def test_superplan_uses_native_exact_toolsearch_instead_of_stale_failure_claim():
    body = REFERENCE.read_text(encoding="utf-8")

    assert "do NOT use ToolSearch" not in body
    assert "ToolSearch returns empty 70%" not in body
    assert "exact `select:`" in body
    assert "Do not assume" in body
