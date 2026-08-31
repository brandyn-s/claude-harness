"""Unit tests for the MCP OAuth self-heal module.

Targets the pure classifier (_classify) — the safety-critical part: a wrong
classification either leaves clients broken (missed purge) or deletes a live
registration (over-purge). No real keychain access.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import mcp_oauth_heal as mod  # noqa: E402

NOW_MS = time.time() * 1000
CIMD_ID = "https://claude.ai/oauth/claude-code-client-metadata"
UUID_ID = "11111111-1111-1111-1111-111111111111"


def _entry(url: str, client_id: str, token: str = "", expires: int = 0) -> dict:
    return {
        "serverUrl": url,
        "clientId": client_id,
        "accessToken": token,
        "expiresAt": expires,
    }


def test_orphaned_uuid_gateway_client_is_purged():
    """Dead pre-CIMD registration (no token) on a gateway host → purge."""
    mcp = {"airlock|x": _entry("https://service.mcp.example.internal/mcp", UUID_ID)}
    purge, warn = mod._classify(mcp, NOW_MS)
    assert purge == ["airlock|x"]
    assert warn == []


def test_expired_token_uuid_gateway_client_is_purged():
    """UUID client with an EXPIRED token is dead → purge."""
    mcp = {
        "tenable|x": _entry(
            "https://service.mcp.example.internal/mcp", UUID_ID,
            token="tok", expires=int(NOW_MS - 60_000),
        )
    }
    purge, warn = mod._classify(mcp, NOW_MS)
    assert purge == ["tenable|x"]
    assert warn == []


def test_cimd_client_is_never_touched():
    """URL-based CIMD client IDs are the healthy end state."""
    mcp = {"tailscale|x": _entry("https://service.mcp.example.internal/mcp", CIMD_ID)}
    purge, warn = mod._classify(mcp, NOW_MS)
    assert purge == [] and warn == []


def test_non_gateway_host_is_never_touched():
    """UUID DCR clients on external servers (e.g. Linear) are legitimate."""
    mcp = {"linear|x": _entry("https://mcp.linear.app/mcp", UUID_ID)}
    purge, warn = mod._classify(mcp, NOW_MS)
    assert purge == [] and warn == []


def test_live_token_uuid_gateway_client_warns_not_purges():
    """The over-purge guard: a live token is surfaced, never deleted."""
    mcp = {
        "msgraph|x": _entry(
            "https://service.mcp.example.internal/mcp", UUID_ID,
            token="tok", expires=int(NOW_MS + 3_600_000),
        )
    }
    purge, warn = mod._classify(mcp, NOW_MS)
    assert purge == []
    assert warn == ["msgraph|x"]


def test_lookalike_domain_is_not_matched():
    """evil-mcp.example.internal.attacker.io must not match the gateway suffix."""
    mcp = {"x|y": _entry("https://service.mcp.example.internal.evil.io/mcp", UUID_ID)}
    purge, warn = mod._classify(mcp, NOW_MS)
    assert purge == [] and warn == []


def test_malformed_entries_are_skipped():
    try:
        purge, warn = mod._classify({"bad|1": "not-a-dict", "bad|2": {}}, NOW_MS)
    except Exception as e:  # pragma: no cover
        raise AssertionError(f"classifier must not raise on malformed input: {e}")
    assert purge == [] and warn == []


def test_non_darwin_returns_empty():
    """heal_mcp_oauth_clients is a no-op off macOS."""
    orig = mod.sys.platform
    try:
        mod.sys.platform = "linux"
        assert mod.heal_mcp_oauth_clients() == []
    finally:
        mod.sys.platform = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"{len(fns)} tests passed")
