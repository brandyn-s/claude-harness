# Audit Probe Targets

## MCP Connectivity Ping Tools

Match by substring if exact name differs (e.g., `remote-crowdstrike` matches `crowdstrike` entry). For servers without a known ping tool, attempt ToolSearch to load any tool from that server as a connectivity check.

<!-- BEGIN GENERATED: current-host-servers (gen_probe_targets.py) -->

### Current host servers (0 registered — generated from live `~/.claude.json`; do not hand-edit this block)

No MCP servers are registered on this host (`~/.claude.json` top-level
and project scopes, `~/.mcp.json`). There is nothing to probe: report
R1 connectivity as N/A, and re-run `gen_probe_targets.py --write` after
registering a server.

<!-- END GENERATED: current-host-servers -->

> The sections below predominantly list prior-host (Windows-era) and gateway servers
> not currently registered in this host's `~/.claude.json`. They are retained for
> forward-compat as `*.mcp.example.internal` servers get re-registered — treat a
> no-matching-server entry as N/A, not a failure.

### Security & IT Servers

| Server | Ping tool |
|---|---|
| remote-crowdstrike | `falcon_check_connectivity` |
| remote-tenable | `tenable_server_status` |
| remote-airlock / technological-ivory-cicada | `airlock_test_connectivity` |
| remote-msgraph | `msgraph_get_organization` |
| security-remix | ToolSearch to load any tool — this is the meta-tool and MUST be probed |

### Collaboration & Project Servers

| Server | Ping tool |
|---|---|
| slack-user | `workspace_info` |
| linear-server | `list_teams` (limit 1) |
| remote-lever | `lever_get_stages` (if available, else ToolSearch) |
| remote-confluence | `confluence_list_allowed_spaces` (if available, else ToolSearch) |
| lucid-admin | `get_profile` |
| lucid-mcp | ToolSearch to load any tool (project-scoped) |

### Infrastructure & Utility Servers

| Server | Ping tool |
|---|---|
| remote-tailscale | `get_tailnet_settings` |
| hologram | ToolSearch to load any tool (e.g., `get_current_user`) |
| netcloud | ToolSearch to load any tool (e.g., `list_routers`) |
| tavily | `tavily_search` (query: "test", max_results: 1, search_depth: "basic") |
| exa | `web_search_exa` (query: "test", numResults: 1) |
| context7-docs | `resolve-library-id` (libraryName: "test") |
| fastmcp-docs | `search_fast_mcp` (query: "test") |
| awslabs.terraform-mcp-server | `SearchAwsProviderDocs` (query: "test") |
| awslabs.ccapi-mcp-server | `check_environment_variables` |
| memory-search | `memory_stats` |
| code-graph | ToolSearch to load any tool (e.g., `list_projects`) |
| code-search | ToolSearch to load any tool (e.g., `list_projects`) |
| office-docs | ToolSearch to load any tool (e.g., `list_sheets`) |
| chrome-devtools | ToolSearch to load any tool (e.g., `list_pages`) |

### Research & Documentation Servers

| Server | Ping tool |
|---|---|
| arxiv-mcp-server | ToolSearch to load any tool (e.g., `search_papers`) |
| gitmcp-claude-code | `search_claude_code_documentation` (query: "test") |
| gitmcp-fastmcp | `search_fastmcp_documentation` (query: "test") |
| gitmcp-opa | `search_opa_documentation` (query: "test") |

### Platform & Compliance Servers

| Server | Ping tool |
|---|---|
| claude_platform | ToolSearch to load any tool (e.g., `get_organization`) |
| claude-compliance | ToolSearch to load any tool (e.g., `list_organizations`) |
| aws-athena | ToolSearch to load any tool (e.g., `list_saved_queries`) |

### Security Scanning & Finance Servers

| Server | Ping tool |
|---|---|
| prowler | `prowler_hub_list_providers` |
| ramp | ToolSearch to load any tool (needs OAuth — may return auth error, which still confirms connectivity) |

> **Note**: Use Python `json.load()` for atomic read of `~/.claude.json` when enumerating servers — the running Claude Code process actively writes to this file, and the Edit tool may encounter race conditions. Servers marked "project-scoped" live under `projects[<encoded-project-path>]["mcpServers"]` in `~/.claude.json`, not at the top level. The encoding depends on OS (Windows: `C:/Users/<name>`; Linux: `/home/<name>`; macOS: `/Users/<name>`) — enumerate `projects` keys at runtime rather than hardcoding a path.
