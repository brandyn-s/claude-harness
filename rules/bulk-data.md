# Bulk Data

INVARIANT scripted_bulk_without_authorization_bypass

For >100 results/export/large data: invoke /bulk-api-script; use a reviewed script with pagination, rate limits, bounded retries, progress, and per-item outcomes. Do not iterate MCP calls in-session. At <=100, MCP is acceptable. Ramp SQL is the narrow exception: supported LIMIT/OFFSET or GROUP BY via MCP.

BULK_WRITE:
- Never loop state-changing MCP calls or use a script to bypass OPA/user confirmation.
- Before execution: preview target set + action; define batch bounds/stop conditions; record item results/retry state; establish rollback/compensation. Reconfirm if scope/count/action changes.
- CrowdStrike: never loop falcon_* mutations. Use only a reviewed batch path verified to exist here; do not assume Windows-era cs_hygiene.py exists.
- Microsoft Graph: script @odata.nextLink reads with $select; use a reviewed API client for bulk writes.

On failure, stop, preserve the item ledger, and resume only unresolved items after cause and authorization are revalidated.

Vendor specifics: skills/bulk-api-script/SKILL.md and agent-memory topics.
