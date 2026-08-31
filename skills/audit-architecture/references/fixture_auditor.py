#!/usr/bin/env python3
"""Deterministic fixture auditor for audit-architecture corpus live check.

Usage:
    python fixture_auditor.py <fixture_dir>

Checks a fixture directory for 6 architecture bug patterns and outputs
JSON to stdout:
    {"codes": ["R3", "D5", ...], "fixture": "<name>"}

Exit 0 always. Errors go to stderr.

Detection logic:
  R3: any *settings*.json fails json.loads()
  R2: any mcp.json mcpServers entry has an "args" list containing an
      absolute path (starts with "/") that does not exist on disk
  D3: mcp.json has N servers but ARCHITECTURE.md claims M (via regex
      `(\\d+) MCP server`), and M != N
  D4: server name appears in ARCHITECTURE.md's markdown table but NOT
      in mcp.json's mcpServers keys (phantom docs entry)
  D5: mcp.json mcpServers key NOT mentioned anywhere in ARCHITECTURE.md text
  C2: mcp.json mcpServers key NOT mentioned in routing-rules.json text
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _parse_arch_server_table(arch_text: str) -> list[str]:
    """Extract server names from the markdown pipe-table after
    '## MCP Servers' header. Stop at the next '## ' section.

    Returns a list of server names (first cell of each data row)."""
    servers: list[str] = []
    in_section = False
    for line in arch_text.splitlines():
        if re.match(r"^##\s+MCP Servers", line):
            in_section = True
            continue
        if in_section and re.match(r"^##\s+", line):
            break
        if in_section:
            # Match a pipe-table data row: | name | ... |
            # Skip header separator rows (|---|...|)
            m = re.match(r"^\|\s*([^|\-][^|]*?)\s*\|", line)
            if m:
                name = m.group(1).strip()
                # Skip the header row (contains "Server" or similar)
                if name and not re.match(r"^-+$", name) and name.lower() != "server":
                    servers.append(name)
    return servers


def audit_fixture(fixture_dir: Path) -> list[str]:
    """Run all 6 checks against fixture_dir. Return list of triggered codes."""
    codes: list[str] = []

    # ── R3: any *settings*.json fails json.loads() ─────────────────────────
    for settings_file in fixture_dir.glob("*settings*.json"):
        try:
            json.loads(settings_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            codes.append("R3")
            break

    # ── Load mcp.json if present ────────────────────────────────────────────
    mcp_path = fixture_dir / "mcp.json"
    mcp_servers: dict[str, dict] = {}
    if mcp_path.is_file():
        try:
            mcp_data = json.loads(mcp_path.read_text(encoding="utf-8"))
            mcp_servers = mcp_data.get("mcpServers", {})
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"WARNING: could not parse mcp.json: {e}", file=sys.stderr)

    # ── R2: mcp.json entry has args with absolute path that doesn't exist ──
    for _server, cfg in mcp_servers.items():
        args = cfg.get("args", [])
        for arg in args:
            if isinstance(arg, str) and arg.startswith("/") and not Path(arg).exists():
                codes.append("R2")
                break
        else:
            continue
        break

    # ── Load ARCHITECTURE.md if present ─────────────────────────────────────
    arch_path = fixture_dir / "ARCHITECTURE.md"
    arch_text = ""
    arch_table_servers: list[str] = []
    arch_claimed_count: int | None = None
    if arch_path.is_file():
        arch_text = arch_path.read_text(encoding="utf-8")
        arch_table_servers = _parse_arch_server_table(arch_text)
        m = re.search(r"(\d+)\s+MCP\s+server", arch_text)
        if m:
            arch_claimed_count = int(m.group(1))

    # ── D3: mcp.json has N servers; ARCHITECTURE.md claims M (M != N) ──────
    if mcp_path.is_file() and arch_path.is_file() and arch_claimed_count is not None:
        n = len(mcp_servers)
        if arch_claimed_count != n:
            codes.append("D3")

    # ── D4: server in ARCHITECTURE.md table but NOT in mcp.json ─────────────
    if mcp_path.is_file() and arch_path.is_file():
        mcp_keys = set(mcp_servers.keys())
        phantom_docs = [s for s in arch_table_servers if s not in mcp_keys]
        if phantom_docs:
            codes.append("D4")

    # ── D5: mcp.json server key NOT mentioned anywhere in ARCHITECTURE.md ───
    if mcp_path.is_file() and arch_path.is_file():
        for server_name in mcp_servers:
            if server_name not in arch_text:
                codes.append("D5")
                break

    # ── C2: mcp.json server key NOT mentioned in routing-rules.json ─────────
    routing_path = fixture_dir / "routing-rules.json"
    if mcp_path.is_file() and routing_path.is_file():
        routing_text = routing_path.read_text(encoding="utf-8")
        for server_name in mcp_servers:
            if server_name not in routing_text:
                codes.append("C2")
                break

    return list(dict.fromkeys(codes))  # deduplicate, preserve order


def main() -> None:
    if len(sys.argv) != 2:
        print(
            f"Usage: {sys.argv[0]} <fixture_dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    fixture_dir = Path(sys.argv[1])
    if not fixture_dir.is_dir():
        print(
            f"ERROR: fixture_dir does not exist or is not a directory: {fixture_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        codes = audit_fixture(fixture_dir)
    except Exception as e:
        print(f"ERROR: unhandled exception during audit: {e}", file=sys.stderr)
        codes = []

    result = {
        "codes": codes,
        "fixture": fixture_dir.name,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>"); sys.exit(0)
    main()
