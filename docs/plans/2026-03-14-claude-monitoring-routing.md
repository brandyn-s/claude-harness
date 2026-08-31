# Claude Monitoring Routing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a topic file and skill that let Claude intelligently route monitoring/admin questions to the correct data source (claude-compliance MCP, claude_platform MCP, or AWS Athena OTel) without manual tool selection.

**Architecture:** A topic file provides always-in-context routing knowledge (cached IDs, tool selection rules, parameter gotchas). A skill provides structured multi-step query workflows for complex cross-system questions. Athena saved queries provide reusable SQL for OTel data once telemetry is deployed.

**Tech Stack:** Claude agent-memory topic files (.md), Claude skills (SKILL.md), AWS Athena saved queries (SQL), existing MCP servers (no new infrastructure).

---

### Task 1: Create the topic file

**Files:**
- Create: `~/.claude/agent-memory/topics/claude-monitoring.md`

**Step 1: Write the topic file with routing table and cached IDs**

```markdown
# Claude Monitoring & Administration

## Quick Reference IDs

- **Compliance org (newer, active for Chat)**: org_id=`org_01SVVHxXdvjcuNW23h8M7bLm`, uuid=`11111111-1111-1111-1111-111111111111`
- **Compliance org (older, active for Code)**: uuid=`11111111-1111-1111-1111-111111111111`
- **Admin API org**: id=`11111111-1111-1111-1111-111111111111`
- **you user_id**: `user_01KVW1Na7cHoPBCUrzxZ28Lr`
- **Athena database**: `mcp_compliance`
- **Athena OTel table**: `cowork_otel` (nested `resourcelogs` column, partitioned by year/month/day/hour)

## Three Data Sources

| Source | MCP Server | Covers | Does NOT cover |
|---|---|---|---|
| **Compliance API** | `claude-compliance` | Chat transcripts, activities, projects, files, user audit trail (IP, user_agent) | Claude Code sessions, Cowork, cost, token usage |
| **Admin API** | `claude_platform` | Cost reports, Claude Code usage metrics, org/user/workspace/API key management, models, skills, files, batches | Chat transcripts, message content, Cowork |
| **OTel via Athena** | `aws-athena` | Claude Code user prompts (if OTEL_LOG_USER_PROMPTS=1), tool execution, bash commands, cost per request, API errors | Chat sessions, Cowork, Claude responses |

## Routing Table

### Content & Transcripts (claude-compliance)
| Question | Tool | Required params | Gotchas |
|---|---|---|---|
| "What did user X say in Chat" | `list_chats` → `get_chat_messages` | `user_ids` (REQUIRED), date filters | Sorts oldest-first. Get user_id from `list_organization_users` first. |
| "Show me chat transcript" | `get_chat_messages` | `claude_chat_id` | Returns full message history with content blocks and artifacts. |
| "Who was active today (Chat)" | `list_activities` | `organization_ids`, `activity_types=["claude_chat_created"]`, date filters | Does NOT require user_ids. Use org_id `org_01SVVHxXdvjcuNW23h8M7bLm`. |
| "All activity today" | `list_activities` | `organization_ids`, date filters, `limit` up to 5000 | Newest first. Activity types: claude_chat_created, claude_chat_deleted, claude_chat_viewed, claude_project_viewed. |
| "List projects" | `list_projects` | Optional: org/user/date filters | Returns metadata only. Use `get_project` for details. |
| "Project attachments" | `list_project_attachments` → `get_project_document` | `claude_proj_id` | |
| "Download file from chat" | `download_file_content` | `claude_file_id` | Returns base64 for binary, text for text files. |
| "Delete chat (eDiscovery)" | `delete_chat` | `claude_chat_id` | IRREVERSIBLE. Confirm with user first. |
| "List all users (with names)" | `list_organization_users` | `org_uuid` (NOT org_id) | Use uuid `11111111-1111-1111-1111-111111111111`. Paginate with `page` token. |
| "List orgs" | `list_organizations` | None | Returns both Example orgs (older + newer). |

### Cost, Usage & Admin (claude_platform)
| Question | Tool | Required params | Gotchas |
|---|---|---|---|
| "How much did we spend" | `get_cost_report` | `start_date` (RFC 3339), `granularity` ("day" only) | `end_date` MUST be > start_date (use next day). `group_by` options: "description", "workspace_id" (NOT "workspace"). Amounts in USD cents. |
| "Claude Code usage by user" | `get_claude_code_usage_report` | `date` (YYYY-MM-DD) | Returns per-user: sessions, LOC, commits, PRs, tool actions, model breakdown with cost. Paginate with `page`. |
| "Messages API usage" | `get_messages_usage_report` | `start_date`, `granularity` ("minute"/"hour"/"day") | Returns empty if no direct API calls (all usage via Chat/Code). `group_by`: "model", "api_key", "workspace", "context_window", "inference_geo", "service_tier". |
| "List users (admin)" | `list_users` | Optional: `email` filter | Returns user_id, email, name, role. Different from compliance list_organization_users. |
| "Invite user" | `create_invite` | `email`, `role` | SSO orgs fail with 400: "SSO configuration automatically manages members". Roles: user, developer, billing, claude_code_user, managed. |
| "List workspaces" | `list_workspaces` | Optional: `include_archived` | |
| "List API keys" | `list_api_keys` | Optional: `status`, `workspace_id`, `created_by_user_id` | |
| "Available models" | `list_models` | | Most recent first. |
| "List skills" | `list_skills` | | Org-level skills. |
| "Update user role" | `update_user` | `user_id` + role | Cannot set admin via API. |
| "Remove user" | `remove_user` | `user_id` | IRREVERSIBLE. Confirm first. |

### Code Telemetry (aws-athena)
| Question | Tool | Required params | Gotchas |
|---|---|---|---|
| "What did user X prompt in Code" | `run_query` | `database`="mcp_compliance", SQL against `cowork_otel` | Requires OTEL_LOG_USER_PROMPTS=1 on device. Table uses nested `resourcelogs` JSON. |
| "Code tool execution patterns" | `run_query` | Same | Parse tool_result events from resourcelogs. |
| "Code cost by user" | `run_query` | Same | Parse api_request events for cost_usd field. |
| "Code errors today" | `run_query` | Same | Parse api_error events. |

**NOTE**: `cowork_otel` table is currently empty - OTel env vars not yet deployed via Intune. Once deployed, data flows into year/month/day/hour partitions.

### Coverage Gaps (no tool can answer)
| Question | Why | Workaround |
|---|---|---|
| "What did user do in Cowork" | Explicitly excluded from Compliance API, audit logs, data exports | None. Contact Anthropic for roadmap. |
| "What did Claude respond in Code" | OTel logs user prompts only, not LLM responses (GitHub #2090) | Infer from tool_result events (what Claude did, not what Claude said). |
| "Chat cost breakdown per user" | Cost report aggregates all products, no per-user Chat cost | Subtract Code costs (from Code report) from total to approximate. |

## Parameter Reference

### Date formats
- Compliance API: RFC 3339 (`2026-03-14T00:00:00Z`)
- Admin cost/usage reports: RFC 3339 (`2026-03-14T00:00:00Z`)
- Admin Code usage: `YYYY-MM-DD` (`2026-03-14`)
- Athena partitions: `year=2026 AND month=3 AND day=14`

### Pagination patterns
- Compliance `list_chats`: `after_id`/`before_id` from response `first_id`/`last_id`
- Compliance `list_activities`: same
- Compliance `list_organization_users`: `page` token from response
- Admin API: `after_id`/`before_id` cursor pagination on all list endpoints
- Athena: `maxRows` param (default 1000, max 10000)
```

**Step 2: Verify the topic file loads correctly**

Run: Read the file back and confirm no syntax issues.

**Step 3: Commit**

```bash
cd ~/.claude
git add agent-memory/topics/claude-monitoring.md
git commit -m "feat: add claude-monitoring topic file with routing table"
```

---

### Task 2: Create the skill

**Files:**
- Create: `~/.claude/skills/claude-monitor/SKILL.md`

**Step 1: Write the skill file**

```markdown
---
name: claude-monitor
description: Route Claude monitoring and admin queries to the correct data source (Compliance API, Admin API, or OTel via Athena). Use when asked about user activity, spend, transcripts, Claude Code usage, or admin tasks like invites and workspace management. Trigger phrases - "who used Claude", "how much did we spend", "show me transcripts", "active users", "Claude Code usage", "invite user", "list workspaces", "user prompts in Code". Do NOT use for general Claude conversations or code generation tasks.
---

# Claude Monitor

Route monitoring and administration queries across three data sources.

## Before any query

1. Load topic file: `~/.claude/agent-memory/topics/claude-monitoring.md`
2. Identify query category from routing table
3. Use cached IDs from topic file (never look up org UUIDs mid-query)

## Query Categories

### Category 1: "What did someone say/do in Chat?"
**Source**: claude-compliance MCP

1. If user_id unknown: `list_organization_users` with org_uuid `11111111-1111-1111-1111-111111111111` to find user_id by email
2. For chat list: `list_chats` with `user_ids=[user_id]` + date filters
3. For transcript: `get_chat_messages` with `claude_chat_id`
4. For activity audit: `list_activities` with `organization_ids=["org_01SVVHxXdvjcuNW23h8M7bLm"]` + date filters

### Category 2: "How much did we spend / who's using Code?"
**Source**: claude_platform MCP

1. For cost: `get_cost_report` with `start_date`, `end_date` = next day, `granularity="day"`, `group_by=["description"]`
2. For Code usage: `get_claude_code_usage_report` with `date` in YYYY-MM-DD format
3. For API usage: `get_messages_usage_report` with `start_date`, `granularity`

### Category 3: "What did someone prompt/execute in Code CLI/Desktop?"
**Source**: aws-athena MCP

1. Run SQL against `mcp_compliance.cowork_otel` table
2. Always include partition filter: `WHERE year=YYYY AND month=M AND day=D`
3. Parse nested `resourcelogs` JSON for event data
4. If table is empty: inform user OTel not yet deployed, reference Intune scripts at `~/Desktop/Scripts/intune-otel-*.ps1`

### Category 4: Admin actions
**Source**: claude_platform MCP

- Invite: `create_invite` (will fail on SSO orgs - explain JIT provisioning instead)
- Users: `list_users`, `get_user`, `update_user`, `remove_user`
- Workspaces: `list_workspaces`, `create_workspace`, etc.
- API keys: `list_api_keys`, `get_api_key`, `update_api_key`
- Models: `list_models`

### Category 5: Cross-system queries
**"What did user X do today across all products?"**

Run in parallel:
1. `list_activities` (compliance) - Chat activity with IP, user_agent
2. `get_claude_code_usage_report` (platform) - Code sessions, LOC, cost
3. Athena query (aws-athena) - Code prompts and tool execution (if OTel deployed)

Merge results into a unified timeline by timestamp.

## Coverage gap warnings

Always inform the user when a query hits a known gap:
- **Cowork**: "Cowork activity is excluded from all monitoring APIs. No visibility available."
- **Code responses**: "OTel captures user prompts and tool execution but not Claude's text responses."
- **Chat per-user cost**: "Cost reports aggregate all products. Approximate Chat cost = total minus Code cost."

## Examples

- "Show me you's last 5 chats" → Category 1 (use cached user_id `user_01KVW1Na7cHoPBCUrzxZ28Lr`)
- "How much did we spend yesterday?" → Category 2 (cost report)
- "Who's the heaviest Code user this week?" → Category 2 (Code usage report, multiple days)
- "What bash commands did user X run in Code today?" → Category 3 (Athena)
- "Invite security@example.com" → Category 4 (will fail with SSO message)
- "Full activity report for user X today" → Category 5 (parallel across all three)

## Success Criteria

- Correct tool selected on first attempt (no trial-and-error)
- Required parameters provided without extra lookup calls
- Coverage gaps communicated proactively
- Cross-system queries run in parallel where possible
```

**Step 2: Verify skill frontmatter and structure**

Run: Read the file back. Confirm:
- `name:` matches folder name (`claude-monitor`)
- `description:` under 1024 characters
- No XML angle brackets in frontmatter
- No `claude` or `anthropic` in the skill name (NOTE: "claude-monitor" contains "claude" - rename to `monitor-claude-platform` or abbreviate to `cc-monitor`)

**IMPORTANT**: Skill naming rule says no `claude` in skill names. Rename folder and name field to `cc-monitor`.

- Create: `~/.claude/a separate skill (not included in this export) (not `claude-monitor`)
- Set `name: cc-monitor` in frontmatter

**Step 3: Commit**

```bash
cd ~/.claude
git add a separate skill (not included in this export)
git commit -m "feat: add cc-monitor skill for Claude monitoring query routing"
```

---

### Task 3: Update agent-delegation routing table

**Files:**
- Modify: `~/.claude/rules/agent-delegation.md`

**Step 1: Add claude monitoring keywords to the routing table**

Add this row to the delegation table:

```markdown
| spend, cost, transcript, chat history, active users, Claude Code usage, invite, workspace, compliance, audit, monitoring, who used, OTel | `claude-monitoring.md` | Single read op, <5KB, no cross-tool correlation |
```

**Step 2: Commit**

```bash
cd ~/.claude
git add rules/agent-delegation.md
git commit -m "feat: add claude monitoring keywords to agent delegation routing"
```

---

### Task 4: Verify routing correctness

Test each routing category by running the actual query and confirming correct tool selection and parameter usage.

**Step 1: Test Category 1 - Chat content (compliance)**

Query: "List you's chats from today"
Expected tool: `mcp__claude-compliance__list_chats`
Expected params: `user_ids=["user_01KVW1Na7cHoPBCUrzxZ28Lr"]`, `created_at_gte="2026-03-14T00:00:00Z"`, `limit=10`
Verify: Returns chat metadata with names and timestamps.

**Step 2: Test Category 1 - Activity audit (compliance)**

Query: "How many unique users had Chat sessions today?"
Expected tool: `mcp__claude-compliance__list_activities`
Expected params: `organization_ids=["org_01SVVHxXdvjcuNW23h8M7bLm"]`, `activity_types=["claude_chat_created"]`, `created_at_gte="2026-03-14T00:00:00Z"`, `limit=5000`
Verify: Returns activity records. Count unique `actor.user_id` values.

**Step 3: Test Category 2 - Cost report (platform)**

Query: "How much did we spend yesterday?"
Expected tool: `mcp__claude_platform__get_cost_report`
Expected params: `start_date="2026-03-13T00:00:00Z"`, `end_date="2026-03-14T00:00:00Z"`, `granularity="day"`, `group_by=["description"]`
Verify: Returns cost line items in USD cents. No 400 error.

**Step 4: Test Category 2 - Code usage (platform)**

Query: "Who used Claude Code yesterday?"
Expected tool: `mcp__claude_platform__get_claude_code_usage_report`
Expected params: `date="2026-03-13"`
Verify: Returns per-user/per-key rows with sessions, LOC, cost breakdown.

**Step 5: Test Category 3 - OTel (Athena)**

Query: "Any OTel data in Athena?"
Expected tool: `mcp__aws-athena__run_query`
Expected params: `database="mcp_compliance"`, `query="SELECT COUNT(*) FROM cowork_otel WHERE year=2026 AND month=3 AND day=14"`
Verify: Returns 0 (OTel not yet deployed). Confirm no query error.

**Step 6: Test Category 4 - Admin action (platform)**

Query: "List current workspaces"
Expected tool: `mcp__claude_platform__list_workspaces`
Verify: Returns workspace list with names and status.

**Step 7: Test coverage gap warning**

Query: "What did user X do in Cowork today?"
Expected behavior: No tool called. Claude responds with coverage gap warning about Cowork exclusion.

**Step 8: Commit verification results**

Document any parameter corrections needed. Update topic file if any gotchas were discovered.

```bash
cd ~/.claude
git add -A
git commit -m "feat: verify routing correctness, update any parameter fixes"
```

---

### Task 5: Create Athena saved queries (for when OTel data flows)

**Files:**
- These are created via `aws-athena` MCP or AWS console

**Step 1: Create saved query - active Code users today**

```sql
-- Name: otel_active_code_users_today
-- Description: Unique Claude Code users with sessions today
SELECT DISTINCT
  json_extract_scalar(log_record, '$.attributes.user\\.account_uuid') AS account_uuid,
  json_extract_scalar(log_record, '$.attributes.user\\.email') AS email,
  COUNT(*) AS event_count
FROM cowork_otel
CROSS JOIN UNNEST(
  cast(json_extract(resourcelogs, '$[*].scopeLogs[*].logRecords[*]') AS array(json))
) AS t(log_record)
WHERE year = year(current_date)
  AND month = month(current_date)
  AND day = day(current_date)
  AND json_extract_scalar(log_record, '$.attributes.event\\.name') = 'user_prompt'
GROUP BY 1, 2
ORDER BY event_count DESC
```

**NOTE**: The exact JSON path structure depends on how the OTel collector serializes data to S3/Athena. This query is a starting template - it MUST be validated against actual data once OTel is deployed. Mark as BLOCKED until Intune deployment populates the table.

**Step 2: Create saved query - user prompts by user**

```sql
-- Name: otel_user_prompts
-- Description: User prompt content for a specific user (requires OTEL_LOG_USER_PROMPTS=1)
-- Parameters: Replace ACCOUNT_UUID and DATE values
SELECT
  json_extract_scalar(log_record, '$.timeUnixNano') AS timestamp,
  json_extract_scalar(log_record, '$.attributes.prompt') AS prompt_text,
  json_extract_scalar(log_record, '$.attributes.prompt_length') AS prompt_length
FROM cowork_otel
CROSS JOIN UNNEST(
  cast(json_extract(resourcelogs, '$[*].scopeLogs[*].logRecords[*]') AS array(json))
) AS t(log_record)
WHERE year = 2026 AND month = 3 AND day = 14
  AND json_extract_scalar(log_record, '$.attributes.event\\.name') = 'user_prompt'
  AND json_extract_scalar(log_record, '$.attributes.user\\.account_uuid') = 'ACCOUNT_UUID'
ORDER BY timestamp DESC
LIMIT 50
```

**Step 3: Create saved query - tool execution trail**

```sql
-- Name: otel_tool_execution
-- Description: Tool execution events with bash commands and success/failure
SELECT
  json_extract_scalar(log_record, '$.timeUnixNano') AS timestamp,
  json_extract_scalar(log_record, '$.attributes.tool_name') AS tool_name,
  json_extract_scalar(log_record, '$.attributes.success') AS success,
  json_extract_scalar(log_record, '$.attributes.duration_ms') AS duration_ms,
  json_extract_scalar(log_record, '$.attributes.tool_parameters') AS tool_params
FROM cowork_otel
CROSS JOIN UNNEST(
  cast(json_extract(resourcelogs, '$[*].scopeLogs[*].logRecords[*]') AS array(json))
) AS t(log_record)
WHERE year = 2026 AND month = 3 AND day = 14
  AND json_extract_scalar(log_record, '$.attributes.event\\.name') = 'tool_result'
ORDER BY timestamp DESC
LIMIT 100
```

**Step 4: Note in topic file that saved queries exist but are BLOCKED**

Add to the Athena section of the topic file:
```
Saved queries: otel_active_code_users_today, otel_user_prompts, otel_tool_execution
Status: BLOCKED - queries are templates only. Validate JSON paths against actual data after Intune OTel deployment.
```

**Step 5: Commit**

```bash
cd ~/.claude
git add agent-memory/topics/claude-monitoring.md
git commit -m "feat: add Athena saved query templates for OTel, mark BLOCKED"
```

---

Plan complete and saved to `~/.claude/docs/plans/2026-03-14-claude-monitoring-routing.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?
