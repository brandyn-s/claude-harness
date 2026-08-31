# MCP Tool Select Catalog

> ON-DEMAND SNAPSHOT — NOT LIVE AUTHORITY.
>
> The base table was regenerated from the macOS host's live session surface on
> 2026-06-12; Tailscale and NetCloud observations were refreshed on 2026-08-01.
> Servers, aliases, authentication, and tool names drift. Exact-probe every
> candidate with select:mcp__server__tool before relying on it. If an exact
> select returns empty, the row is stale or unavailable in this session: use
> the live result and update this snapshot in the same maintenance change.

The deferred-tools listing is a sample. It can suggest a candidate, but only an
exact live select establishes whether that candidate is registered now.

## Naming conventions in this snapshot

- Alias-prefixed names such as mcp__memory-search__memory_search describe locally
  or CLI-registered servers. Everything that was live when this snapshot was
  generated used this form.
- GUID-prefixed names such as mcp__<uuid>__tool describe claude.ai connector
  installs. None were present on the macOS host when this snapshot was generated.
- Linear used mcp__linear-server__* on this host. Older Windows material may
  contain a connector GUID; probe the current session instead.

## Live at snapshot time — by task

| Need | Candidate select query |
|------|------------------------|
| **Web search (Exa)** | select:mcp__exa__web_search_exa — people/company verticals via category in the query |
| **URL fetch (Exa)** | select:mcp__exa__web_fetch_exa |
| **Web search (Firecrawl)** | select:mcp__firecrawl__firecrawl_search — operators, domain filters, and web/news/images sources |
| **Scrape URL (Firecrawl)** | select:mcp__firecrawl__firecrawl_scrape |
| **Site map / crawl (Firecrawl)** | select:mcp__firecrawl__firecrawl_map,mcp__firecrawl__firecrawl_crawl,mcp__firecrawl__firecrawl_check_crawl_status |
| **Structured extract (Firecrawl)** | select:mcp__firecrawl__firecrawl_extract,mcp__firecrawl__firecrawl_parse |
| **Research agent (Firecrawl)** | select:mcp__firecrawl__firecrawl_agent,mcp__firecrawl__firecrawl_agent_status |
| **Browser session (Firecrawl)** | select:mcp__firecrawl__firecrawl_interact,mcp__firecrawl__firecrawl_interact_stop |
| **Page monitors (Firecrawl)** | +mcp__firecrawl__firecrawl_monitor |
| **Web search (Tavily)** | select:mcp__tavily__tavily_search — topic, time_range, search_depth, and chunks_per_source per rules/web-search-preference.md |
| **URL content (Tavily)** | select:mcp__tavily__tavily_extract |
| **Site map / crawl (Tavily)** | select:mcp__tavily__tavily_map,mcp__tavily__tavily_crawl |
| **Deep research (Tavily)** | select:mcp__tavily__tavily_research |
| **Memory search** | select:mcp__memory-search__memory_search,mcp__memory-search__memory_search_batch |
| **Memory dedup / stats / stale / reindex** | select:mcp__memory-search__memory_check_duplicate,mcp__memory-search__memory_stats,mcp__memory-search__memory_stale,mcp__memory-search__memory_reindex |
| **Checkpoints** | select:mcp__memory-search__checkpoint_save,mcp__memory-search__checkpoint_resume,mcp__memory-search__checkpoint_list |
| **Code text search** | select:mcp__codebase-memory-mcp__search_code |
| **Code semantic search** | select:mcp__codebase-memory-mcp__search_code_semantic |
| **Code graph query** | select:mcp__codebase-memory-mcp__query_graph,mcp__codebase-memory-mcp__search_graph,mcp__codebase-memory-mcp__get_graph_schema |
| **Code architecture / tracing** | select:mcp__codebase-memory-mcp__get_architecture,mcp__codebase-memory-mcp__trace_call_path,mcp__codebase-memory-mcp__trace_data_flow,mcp__codebase-memory-mcp__service_map |
| **Code localization / ranking** | select:mcp__codebase-memory-mcp__code_localize,mcp__codebase-memory-mcp__code_localize_agent,mcp__codebase-memory-mcp__rank_by_query |
| **Change context / review** | select:mcp__codebase-memory-mcp__get_relevant_context,mcp__codebase-memory-mcp__get_review_context,mcp__codebase-memory-mcp__get_affected_tests,mcp__codebase-memory-mcp__get_change_coupling,mcp__codebase-memory-mcp__detect_changes,mcp__codebase-memory-mcp__diff_graph |
| **Code quality / structure** | select:mcp__codebase-memory-mcp__degree_filter,mcp__codebase-memory-mcp__detect_cycles,mcp__codebase-memory-mcp__find_similar_functions,mcp__codebase-memory-mcp__explain_symbol,mcp__codebase-memory-mcp__explain_service |
| **Code indexing / projects** | select:mcp__codebase-memory-mcp__index_repository,mcp__codebase-memory-mcp__index_status,mcp__codebase-memory-mcp__index_health,mcp__codebase-memory-mcp__list_projects,mcp__codebase-memory-mcp__delete_project |
| **STIG / security surfaces** | select:mcp__codebase-memory-mcp__query_security_surfaces,mcp__codebase-memory-mcp__query_stig_evidence |
| **ADRs / rationale / reports** | select:mcp__codebase-memory-mcp__manage_adr,mcp__codebase-memory-mcp__find_rationale,mcp__codebase-memory-mcp__generate_report,mcp__codebase-memory-mcp__visualize |
| **Linear issues** | select:mcp__linear-server__list_issues,mcp__linear-server__save_issue,mcp__linear-server__get_issue,mcp__linear-server__get_issue_status,mcp__linear-server__list_issue_statuses,mcp__linear-server__list_issue_labels |
| **Linear projects / initiatives / milestones** | select:mcp__linear-server__list_projects,mcp__linear-server__get_project,mcp__linear-server__save_project,mcp__linear-server__list_initiatives,mcp__linear-server__get_initiative,mcp__linear-server__list_milestones,mcp__linear-server__get_milestone |
| **Linear status updates** | select:mcp__linear-server__save_status_update,mcp__linear-server__get_status_updates |
| **Linear comments / documents** | select:mcp__linear-server__list_comments,mcp__linear-server__save_comment,mcp__linear-server__list_documents,mcp__linear-server__get_document,mcp__linear-server__save_document |
| **Linear teams / users / cycles** | select:mcp__linear-server__list_teams,mcp__linear-server__get_team,mcp__linear-server__list_users,mcp__linear-server__get_user,mcp__linear-server__list_cycles |
| **Linear attachments / diffs / customers** | +mcp__linear-server__attachment / +mcp__linear-server__diff / +mcp__linear-server__customer |
| **Tailscale devices** | select:mcp__tailscale__list_tailnet_devices,mcp__tailscale__ts_get_device,mcp__tailscale__authorize_device,mcp__tailscale__set_device_tags,mcp__tailscale__list_device_routes,mcp__tailscale__expire_device_key |
| **Tailscale users / invites** | select:mcp__tailscale__ts_list_users,mcp__tailscale__ts_get_user,mcp__tailscale__update_user_role,mcp__tailscale__suspend_user,mcp__tailscale__list_user_invites,mcp__tailscale__list_device_invites |
| **Tailscale ACL / policy** | select:mcp__tailscale__get_policy_file,mcp__tailscale__set_policy_file,mcp__tailscale__validate_and_test_policy_file,mcp__tailscale__preview_rule_matches |
| **Tailscale DNS** | select:mcp__tailscale__get_dns_configuration,mcp__tailscale__set_dns_configuration,mcp__tailscale__list_dns_nameservers,mcp__tailscale__get_split_dns,mcp__tailscale__set_split_dns |
| **Tailscale keys / settings / contacts** | select:mcp__tailscale__list_tailnet_keys,mcp__tailscale__create_key,mcp__tailscale__get_tailnet_settings,mcp__tailscale__update_tailnet_settings,mcp__tailscale__get_contacts |
| **Tailscale logging / webhooks / posture / services** | select:mcp__tailscale__list_configuration_audit_logs,mcp__tailscale__list_network_flow_logs,mcp__tailscale__list_webhooks,mcp__tailscale__get_posture_integrations,mcp__tailscale__list_services |
| **Box users / groups admin** | select:mcp__box-admin__box_whoami,mcp__box-admin__list_users,mcp__box-admin__get_user,mcp__box-admin__list_groups,mcp__box-admin__create_user,mcp__box-admin__update_user,mcp__box-admin__delete_user,mcp__box-admin__add_user_to_group |
| **Box governance** | select:mcp__box-admin__list_retention_policies,mcp__box-admin__list_legal_hold_policies,mcp__box-admin__assign_legal_hold,mcp__box-admin__list_shield_barriers,mcp__box-admin__list_storage_policies |
| **Box audit / webhooks / collaborations** | select:mcp__box-admin__get_admin_events,mcp__box-admin__list_webhooks,mcp__box-admin__create_webhook,mcp__box-admin__list_pending_collaborations |
| **Claude platform admin** | select:mcp__claude_platform__get_organization,mcp__claude_platform__list_users,mcp__claude_platform__get_user,mcp__claude_platform__create_invite,mcp__claude_platform__list_invites,mcp__claude_platform__update_user |
| **Claude compliance** | select:mcp__claude-compliance__list_activities,mcp__claude-compliance__list_chats,mcp__claude-compliance__get_chat_messages,mcp__claude-compliance__download_file_content,mcp__claude-compliance__list_projects |
| **Hologram IoT devices** | select:mcp__hologram__list_devices,mcp__hologram__get_device,mcp__hologram__count_connected_devices,mcp__hologram__get_device_locations,mcp__hologram__get_bulk_state_job_status |
| **NetCloud inventory** | select:mcp__netcloud__list_routers,mcp__netcloud__list_accounts,mcp__netcloud__netcloud_list_groups,mcp__netcloud__list_net_devices,mcp__netcloud__netcloud_list_users |
| **NetCloud alerts / logs / audit** | select:mcp__netcloud__list_alerts,mcp__netcloud__list_router_alerts,mcp__netcloud__list_activity_logs,mcp__netcloud__list_router_logs,mcp__netcloud__list_configuration_managers |
| **NetCloud location / signal telemetry** | select:mcp__netcloud__list_locations,mcp__netcloud__list_historical_locations,mcp__netcloud__list_net_device_signal_samples,mcp__netcloud__list_net_device_usage_samples,mcp__netcloud__list_net_device_health |
| **GitHub wrapper** | select:mcp__github__create_pr,mcp__github__list_prs,mcp__github__get_pr,mcp__github__merge_pr,mcp__github__pr_checks,mcp__github__set_branch_protection |
| **Workspace provisioner** | select:mcp__workspace-provisioner__provision_workspace,mcp__workspace-provisioner__create_m365_group,mcp__workspace-provisioner__create_confluence_space,mcp__workspace-provisioner__create_slack_channel |
| **Compliance Access Framework** | select:mcp__compliance-access-framework__assign_group_to_enterprise_app,mcp__compliance-access-framework__create_m365_group,mcp__compliance-access-framework__create_scim_group,mcp__compliance-access-framework__link_channel_to_idp_group,mcp__compliance-access-framework__sync_workspace_members,mcp__compliance-access-framework__create_confluence_space,mcp__compliance-access-framework__create_slack_channel |
| **Office docs** | select:mcp__office-docs__read_xlsx,mcp__office-docs__list_sheets,mcp__office-docs__read_docx,mcp__office-docs__docx_to_text,mcp__office-docs__write_xlsx |
| **Azure Automation** | select:mcp__azure-automation__list_automation_accounts,mcp__azure-automation__list_runbooks,mcp__azure-automation__get_runbook,mcp__azure-automation__list_jobs,mcp__azure-automation__get_job_output,mcp__azure-automation__create_or_update_runbook,mcp__azure-automation__publish_runbook |

## Tailscale and NetCloud constraints

These constraints change interpretation, not just routing, so their concise forms
remain ambient in rules/mcp-tool-names.md. Read the authoritative working notes
before a conclusion or mutation:

- agent-memory/topics/tailscale.md — two-tailnet coverage, direct REST credentials,
  identity reconciliation, API deletion limits, device fields, and HuJSON.
- agent-memory/topics/netcloud.md — 500-row pagination, bodyless fields 409s,
  required group projections, sensitive read fields, and the absence of OPA on
  local-stdio writes.

Snapshot-specific observations retained for diagnosis:

- The Tailscale MCP was bound to EXAMPLE, not CORP. An MCP-only fleet or identity
  answer therefore omitted CORP. User DELETE returned 405 while device DELETE
  remained supported.
- NetCloud list calls required pagination through meta.next. Invalid field names
  returned a bodyless 409, and netcloud_list_groups needed a narrow fields
  projection to avoid an oversized embedded configuration response.

## Registered gateway candidates at snapshot time

These gateway aliases were registered but required shared Entra GCC High OAuth
completion through /mcp at snapshot time: msgraph, crowdstrike, tenable, airlock,
security-remix, confluence, ashby, solarwinds, paloalto, and pa-cdss.

Do not infer current authentication or individual tool names from that list.
Authenticate when authorized, then discover and exact-probe the live tools. Lever
was removed after its 2026-07-24 sunset. Tailscale later authenticated; NetCloud
later became live as local stdio. Slack-user authentication and aliases have also
changed across migrations, so discover them live rather than copying an old GUID.

## Retired or not migrated in this snapshot

Do not route to these without a current live probe proving that the status changed:

- mcp__exa__web_search_advanced_exa, mcp__exa__get_code_context_exa, and
  mcp__exa__crawling_exa. Exa consolidated to web_search_exa and web_fetch_exa;
  domain/operator search moved to Firecrawl.
- mcp__code-search__* and mcp__code-graph__*. Their successor was
  codebase-memory-mcp on this host.
- mcp__arxiv-mcp-server__*. This was a Windows-era local server.
- Slack connector GUID prefixes. Use the currently registered alias discovered
  from the live surface.
- mcp__tailscale__authenticate and
  mcp__tailscale__complete_authentication. These bootstrap names returned an
  empty exact select after Tailscale authenticated.
- Windows-era local servers not migrated at snapshot time: context7-docs,
  aws-athena, lucid-admin, awslabs terraform/ccapi, websets, gitmcp variants,
  mcp-registry, scheduled-tasks, chrome-devtools, and mailbox-mcp.
- xAI mcp__xai__answer_query_websearch returned 410 after Live Search retired.
  Windows-era mcp__xai__x_search and mcp__x-search__* never migrated. The
  working X/web route at snapshot time was bin/x-monitor.py or the direct xAI
  Responses API with x_search/web_search. Exact-probe
  mcp__xai__answer_query_direct before using its no-search answer path.

## Maintenance

Regenerate this catalog when a server is added, removed, renamed, or reauthenticated:

1. Discover candidates from the current session surface.
2. Exact-probe each candidate.
3. Update status and caveats with the verification date.
4. Keep volatile inventory here, not in the unconditional rule.
