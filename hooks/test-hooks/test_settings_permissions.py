"""Regression guards for settings.json permissions.deny invariants.

Several rules rely on permission-layer enforcement at the harness level
(e.g., web-search-preference.md's FORBIDDEN = {WebSearch, WebFetch}).
When those entries vanish silently — as they did in PR #482 (2026-04-01),
collateral damage in an unrelated env-var rewrite — the rule becomes
unenforced and audit-rules surfaces it weeks later as a measurable
violation rate (14.0% session rate, 2026-05-26).

These tests pin the entries so future settings-rewrites surface the loss
at CI time instead of via audit-rules.
"""
import json
from pathlib import Path

CONFIG_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = CONFIG_ROOT / "settings.json"


def _deny_entries():
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        s = json.load(f)
    return s.get("permissions", {}).get("deny", [])


def test_websearch_in_deny():
    """WebSearch must be in permissions.deny.

    Enforces rules/web-search-preference.md INVARIANT FORBIDDEN at the
    harness level. Specialized MCP tools (Tavily/Exa/Firecrawl) provide
    rate-limit hooks, result caps, and structured params that built-in
    WebSearch lacks. Originally added in PR #387; silently removed in
    PR #482; restored 2026-05-26.
    """
    deny = _deny_entries()
    assert "WebSearch" in deny, (
        f"WebSearch must be in permissions.deny. Current deny:\n{deny}"
    )


def test_webfetch_in_deny():
    """WebFetch must be in permissions.deny. Same rationale as WebSearch."""
    deny = _deny_entries()
    assert "WebFetch" in deny, (
        f"WebFetch must be in permissions.deny. Current deny:\n{deny}"
    )


def test_sensitive_paths_in_deny():
    """Sanity check: standard sensitive-path denies still in place.

    Catches accidental settings.json rewrites that drop denies wholesale
    (the failure mode that hit WebSearch/WebFetch in PR #482).
    """
    deny = _deny_entries()
    required = [
        "Read(~/.ssh/**)",
        "Read(~/.aws/**)",
        "Read(**/.env)",
        "Edit(~/.ssh/**)",
    ]
    missing = [r for r in required if r not in deny]
    assert not missing, (
        f"permissions.deny missing required entries: {missing}\n"
        f"Current deny:\n{deny}"
    )
