"""Generate/verify the current-host section of probe-targets.md from live config.

The "Current macOS host servers" section of probe-targets.md went stale once
per architecture generation when hand-maintained (S1 findings 2026-06-12 and
2026-08-22). This script makes it generated content: the server LIST comes
from live `~/.claude.json`; the curated knowledge (which ping tool is cheap,
which servers are AUTH-PENDING) lives in the dicts below, where updating it
is a one-line diff instead of a table rewrite.

Usage:
  python3 gen_probe_targets.py --check   # exit 1 if the block drifted from live config
  python3 gen_probe_targets.py --write   # rewrite the block in place (idempotent)

Run --check from /audit-architecture Phase 2c (self-audit); run --write after
registering or retiring an MCP server. The block is delimited by the
BEGIN/END GENERATED markers in probe-targets.md — never hand-edit inside them.
"""
import argparse
import difflib
import json
import os
import sys

DOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'probe-targets.md')
BEGIN = '<!-- BEGIN GENERATED: current-host-servers (gen_probe_targets.py) -->'
END = '<!-- END GENERATED: current-host-servers -->'

# Curated knowledge — update these dicts, then run --write.
# Only list a ping here after actually exercising it (cheap, read-only).
PING_TOOLS = {
    'memory-search': '`memory_stats`',
    'jamf': '`jamf_ping`',
    'crowdstrike': '`falcon_check_connectivity`',
    'slack-user': '`connection_status`',
    'box-admin': '`box_whoami`',
    'linear-server': '`list_teams` (limit: 1)',
    'tailscale': '`get_tailnet_settings`',
}
AUTH_PENDING = {
    'confluence': ('exposes only `authenticate`/`complete_authentication`; '
                   'probing starts an OAuth flow'),
}
BILLING_NOTE = (
    'Billing-metered probes (only when a failure is suspected): tavily '
    '`tavily_search` (max_results: 1, ultra-fast), exa `web_search_exa` '
    '(numResults: 1), firecrawl `firecrawl_map` (example.com, limit: 1).'
)


def live_servers():
    path = os.path.expanduser('~/.claude.json')
    with open(path, encoding='utf-8') as f:
        cj = json.load(f)
    names = set((cj.get('mcpServers') or {}).keys())
    for pcfg in (cj.get('projects') or {}).values():
        if isinstance(pcfg, dict):
            names.update((pcfg.get('mcpServers') or {}).keys())
    mcp_json = os.path.expanduser('~/.mcp.json')
    if os.path.exists(mcp_json):
        with open(mcp_json, encoding='utf-8') as f:
            names.update((json.load(f).get('mcpServers') or {}).keys())
    return sorted(names)


def render(servers):
    pinged = [s for s in servers if s in PING_TOOLS]
    pending = [s for s in servers if s in AUTH_PENDING]
    rest = [s for s in servers if s not in PING_TOOLS and s not in AUTH_PENDING]
    stale_pings = sorted(set(PING_TOOLS) - set(servers))
    lines = [BEGIN, '']
    lines.append(f'### Current host servers ({len(servers)} registered — '
                 'generated from live `~/.claude.json`; do not hand-edit this block)')
    lines.append('')
    lines.append('Connectivity shortcut: a server whose full toolset is registered in the')
    lines.append("session's deferred-tools list connected successfully at session start —")
    lines.append('that registration IS the connectivity evidence. Reserve live ping calls')
    lines.append('for the verified-cheap table; never probe billing-metered search tools')
    lines.append('unless a failure is suspected.')
    lines.append('')
    lines.append('**Verified cheap pings:**')
    lines.append('')
    lines.append('| Server | Ping tool |')
    lines.append('|---|---|')
    for s in pinged:
        lines.append(f'| {s} | {PING_TOOLS[s]} |')
    lines.append('')
    lines.append('**AUTH-PENDING class (do NOT probe — only auth-bootstrap tools exposed):**')
    lines.append('')
    lines.append('| Server | Note |')
    lines.append('|---|---|')
    for s in pending:
        lines.append(f'| {s} | {AUTH_PENDING[s]} |')
    lines.append('')
    lines.append('**Remaining registered servers** (session tool-registration = connectivity')
    lines.append('evidence; if a live probe is needed, ToolSearch any read-only list/get tool):')
    lines.append(', '.join(rest) + '.')
    lines.append('')
    lines.append(BILLING_NOTE)
    if stale_pings:
        lines.append('')
        lines.append(f'> WARNING: PING_TOOLS entries with no live server: {", ".join(stale_pings)}'
                     ' — remove them from gen_probe_targets.py.')
    lines.append('')
    lines.append(END)
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description='Generate/verify probe-targets current-host block')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write', action='store_true')
    args = ap.parse_args()

    doc = open(DOC, encoding='utf-8').read()
    if BEGIN not in doc or END not in doc:
        print(f'ERROR: markers not found in {DOC}', file=sys.stderr)
        return 2
    head, rest = doc.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    current = BEGIN + rest.split(END, 1)[0] + END
    generated = render(live_servers())

    if args.write:
        if current == generated:
            print('probe-targets.md: already current')
            return 0
        open(DOC, 'w', encoding='utf-8').write(head + generated + tail)
        print('probe-targets.md: current-host block regenerated')
        return 0

    if current == generated:
        print('probe-targets.md: current-host block matches live config')
        return 0
    print('probe-targets.md: DRIFT — current-host block does not match live config',
          file=sys.stderr)
    for line in difflib.unified_diff(current.splitlines(), generated.splitlines(),
                                     'probe-targets.md', 'live-config', lineterm='', n=1):
        print(line, file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
