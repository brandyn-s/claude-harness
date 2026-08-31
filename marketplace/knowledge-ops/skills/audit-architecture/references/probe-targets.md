# Audit Probe Targets

## MCP Connectivity Ping Tools

Match by substring if exact name differs (e.g., `remote-crowdstrike` matches `crowdstrike` entry). For servers without a known ping tool, attempt ToolSearch to load any tool from that server as a connectivity check.

<!-- BEGIN GENERATED: current-host-servers (gen_probe_targets.py) -->

### Current host servers (34 registered — generated from live `~/.claude.json`; do not hand-edit this block)

Connectivity shortcut: a server whose full toolset is registered in the
session's deferred-tools list connected successfully at session start —
that registration IS the connectivity evidence. Reserve live ping calls
for the verified-cheap table; never probe billing-metered search tools
unless a failure is suspected.

**Verified cheap pings:**

| Server | Ping tool |
|---|---|
| box-admin | `box_whoami` |
| crowdstrike | `falcon_check_connectivity` |
| jamf | `jamf_ping` |
| linear-server | `list_teams` (limit: 1) |
| memory-search | `memory_stats` |
| slack-user | `connection_status` |
| tailscale | `get_tailnet_settings` |

**AUTH-PENDING class (do NOT probe — only auth-bootstrap tools exposed):**

| Server | Note |
|---|---|
| confluence | exposes only `authenticate`/`complete_authentication`; probing starts an OAuth flow |

**Remaining registered servers** (session tool-registration = connectivity
evidence; if a live probe is needed, ToolSearch any read-only list/get tool):
airlock, ashby, azure-automation, claude-compliance, claude_platform, compliance-access-framework, confluence-gov, exa, firecrawl, github, hologram, knowbe4, msgraph, netcloud, office-docs, pa-cdss, palantir-mcp, paloalto, pryzm, sec-automations-query, security-remix, solarwinds, tavily, tenable, workspace-provisioner, xai.

Billing-metered probes (only when a failure is suspected): tavily `tavily_search` (max_results: 1, ultra-fast), exa `web_search_exa` (numResults: 1), firecrawl `firecrawl_map` (example.com, limit: 1).

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
