# Response Shape Guards

Defensive parsing patterns for MCP tool responses. Check the relevant topic file for tool-specific details.

## General Guards

| Response | Meaning | Guard |
|----------|---------|-------|
| Normal JSON result | Successful query | Parse as expected per topic file |
| Empty list `[]` | No matches | Report "none found", continue |
| `None` / null | Some tools return None instead of empty | Treat as empty, continue |
| Error object `{"error": ...}` | Tool/API error | Log error, check auth/params, skip tool |
| 401/403 | Auth expired | Log "auth expired", skip tool |
| 429 | Rate limited | Wait Retry-After, retry once, then skip |
| Timeout | Connection issue | Retry once, then skip |

## Tool-Specific Shapes

Consult the corresponding topic file (`~/.claude/agent-memory/topics/*.md`) for:
- Expected response format and field names
- Known quirks (e.g., Airlock returns None not [], Graph returns error with 200 status)
- Filter syntax (FQL, OData, SQL WHERE)
- Response size warnings and filtering requirements

**Never fail the triage because one tool returns an unexpected shape.** Log the anomaly, skip that tool, continue.
