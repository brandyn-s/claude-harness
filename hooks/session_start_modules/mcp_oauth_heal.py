"""Self-heal orphaned MCP OAuth client registrations at SessionStart.

Background (2026-07-14): the *.mcp.example.internal FastMCP gateways stored OAuth
Dynamic Client Registration (DCR) records in Redis, and a startup safety-net
(`_flush_cimd_clients`) wiped ALL of them on every redeploy until mcp-infra
PR #562 enabled CIMD fleet-wide (2026-06-30). Every client registered before
that fix holds a UUID-style client_id the server no longer recognizes,
producing the FastMCP "Client Not Registered" browser error on every auth
attempt — and the auth can never succeed until the stale local registration
is cleared so the client re-registers via CIMD (URL-based client ID, no
server-side registry to lose).

This module detects those orphaned registrations in the Claude Code keychain
credential store and purges them so the next /mcp authentication succeeds on
the first try. Detection rule (conservative):

  - serverUrl host is under GATEWAY_DOMAIN (our FastMCP fleet), AND
  - clientId is a bare UUID (pre-CIMD DCR registration; post-fix
    registrations use the https://claude.ai/... CIMD metadata URL), AND
  - the entry holds no live access token (empty accessToken, or expiresAt
    in the past). An entry with a live token is left alone and warned about
    instead — purging it would break a working connection.

The previous blob is backed up to a sibling keychain entry (BACKUP_SERVICE)
before every mutation. Purged entries are dead by construction, so the
backup exists only for forensics.

INTERRUPTION: safe — the keychain write is a single atomic `security
add-generic-password -U` replace; interruption before it leaves the original
blob untouched, interruption after it leaves a fully-written new blob. A
concurrent session completing an auth flow between our read and write could
be overwritten (read-modify-write race), which costs one re-auth and
converges at the next SessionStart.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time

GATEWAY_DOMAIN = ".mcp.example.internal"
SERVICE = "Claude Code-credentials"
BACKUP_SERVICE = "Claude Code-credentials-prepurge"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _classify(mcp_oauth: dict, now_ms: float) -> tuple[list[str], list[str]]:
    """Split mcpOAuth entries into (purge_keys, warn_keys).

    purge: gateway host + UUID clientId + no live token → orphaned pre-CIMD
    registration, safe to delete.
    warn: gateway host + UUID clientId but a token that still looks live —
    anomalous (should not exist post-CIMD); surfaced, never auto-deleted.
    """
    purge: list[str] = []
    warn: list[str] = []
    for key, entry in mcp_oauth.items():
        if not isinstance(entry, dict):
            continue
        url = entry.get("serverUrl", "")
        host = url.split("//", 1)[-1].split("/", 1)[0]
        if not host.endswith(GATEWAY_DOMAIN):
            continue
        if not UUID_RE.match(entry.get("clientId", "")):
            continue  # CIMD (URL) client IDs are the healthy end state
        expires = entry.get("expiresAt") or 0
        token_live = bool(entry.get("accessToken")) and expires > now_ms
        (warn if token_live else purge).append(key)
    return purge, warn


def _security(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["security", *args], capture_output=True, timeout=10
    )


def _read_blob() -> tuple[str, str] | None:
    """Return (raw_json, account) for the credentials entry, or None."""
    attrs = _security("find-generic-password", "-s", SERVICE)
    if attrs.returncode != 0:
        return None
    m = re.search(r'"acct"<blob>="([^"]*)"', attrs.stdout.decode(errors="replace"))
    account = m.group(1) if m else ""
    raw = _security("find-generic-password", "-s", SERVICE, "-w")
    if raw.returncode != 0:
        return None
    return raw.stdout.decode(errors="replace").strip(), account


def heal_mcp_oauth_clients() -> list[str]:
    """SessionStart entry point. Returns banner messages (empty when healthy)."""
    if sys.platform != "darwin":
        return []
    try:
        blob = _read_blob()
        if blob is None:
            return []
        raw, account = blob
        data = json.loads(raw)
        mcp_oauth = data.get("mcpOAuth")
        if not isinstance(mcp_oauth, dict):
            return []

        purge, warn = _classify(mcp_oauth, time.time() * 1000)
        messages: list[str] = []

        if purge:
            backup = _security(
                "add-generic-password", "-U", "-a", account,
                "-s", BACKUP_SERVICE, "-w", raw,
            )
            if backup.returncode != 0:
                return [
                    "MCP OAuth self-heal: found "
                    f"{len(purge)} orphaned pre-CIMD client registration(s) "
                    "but the keychain backup step failed — not purging. "
                    "Run hooks/session_start_modules/mcp_oauth_heal.py manually."
                ]
            names = sorted(k.split("|", 1)[0] for k in purge)
            for key in purge:
                del mcp_oauth[key]
            write = _security(
                "add-generic-password", "-U", "-a", account,
                "-s", SERVICE, "-w", json.dumps(data),
            )
            if write.returncode == 0:
                messages.append(
                    "MCP OAuth self-heal: purged "
                    f"{len(purge)} orphaned pre-CIMD client registration(s) "
                    f"({', '.join(names)}). These would have failed with "
                    "'Client Not Registered'. Run /mcp once to re-authenticate "
                    "each server via CIMD."
                )
            else:
                messages.append(
                    "MCP OAuth self-heal: keychain write failed after backup; "
                    "registrations unchanged. Investigate `security "
                    "add-generic-password` permissions."
                )

        if warn:
            names = sorted(k.split("|", 1)[0] for k in warn)
            messages.append(
                "MCP OAuth self-heal: gateway server(s) with a legacy UUID "
                f"client ID but a live token ({', '.join(names)}) — left "
                "untouched. If auth errors appear, re-authenticate via /mcp."
            )
        return messages
    except Exception:
        return []  # never break session start


if __name__ == "__main__":
    for line in heal_mcp_oauth_clients() or ["MCP OAuth self-heal: nothing to do."]:
        print(line)
