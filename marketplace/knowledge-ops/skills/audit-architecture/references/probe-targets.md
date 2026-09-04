# Audit Probe Targets

## MCP Connectivity Ping Tools

The server list below is GENERATED from this machine's live config by `gen_probe_targets.py` (`--check` detects drift, `--write` regenerates); the repo ships no server inventory of its own. A registered server appears in the verified-cheap table only when its exact name matches a catalog key in `gen_probe_targets.py`; every other server uses the generic check described after the block.

<!-- BEGIN GENERATED: current-host-servers (gen_probe_targets.py) -->

### Current host servers (0 registered — generated from live `~/.claude.json`; do not hand-edit this block)

No MCP servers are registered on this host (`~/.claude.json` top-level
and project scopes, `~/.mcp.json`). There is nothing to probe: report
R1 connectivity as N/A, and re-run `gen_probe_targets.py --write` after
registering a server.

<!-- END GENERATED: current-host-servers -->

### Servers outside the generated block

Any server without a verified cheap ping — including one registered after the last `--write` (Phase 2c's `--check` catches that) — gets the generic check: ToolSearch one read-only list/get tool from that server and call it with the smallest limit it accepts. A server whose full toolset was registered in the session's deferred-tools list already connected at session start; that registration is sufficient connectivity evidence and needs no live call. Never probe billing-metered search, crawl, or extraction tools unless a failure is suspected. A server that exposes only `authenticate`/bootstrap tools is AUTH-PENDING (registered, not probed), not a failure — probing it starts an OAuth flow.

> **Note**: Use Python `json.load()` for atomic read of `~/.claude.json` when enumerating servers — the running Claude Code process actively writes to this file, and the Edit tool may encounter race conditions. Servers marked "project-scoped" live under `projects[<encoded-project-path>]["mcpServers"]` in `~/.claude.json`, not at the top level. The encoding depends on OS (Windows: `C:/Users/<name>`; Linux: `/home/<name>`; macOS: `/Users/<name>`) — enumerate `projects` keys at runtime rather than hardcoding a path.
