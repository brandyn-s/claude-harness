# MCP Tool Discovery

INVARIANT live_surface_over_static_catalog

- Exact-probe select:mcp__server__tool; never guess. A deferred-tools list is only a sample. An empty exact select means unavailable now.
- skills/_shared/mcp-tool-select-catalog.md is an on-demand snapshot for candidates, never authority. Live wins; update a stale row with the maintenance change.

## Scope-changing caveats

TAILSCALE:
- The MCP covers EXAMPLE only, not CORP. Fleet/person claims require both tailnets (CORP via direct REST/Keychain) and identity reconciliation.
- User DELETE is unsupported (405/admin console only); API revocation is suspend_user + expire_device_key. Device DELETE works. Policy is HuJSON.
- Read agent-memory/topics/tailscale.md before conclusions or writes.

NETCLOUD:
- limit maxes at 500; follow meta.next. Invalid fields return bodyless 409: retry without fields, inspect names, then narrow. Groups require fields to avoid oversized configuration.
- Reads can expose ICCID/IMSI/IMEI/phone numbers; minimize fields. Local-stdio writes have an advisory but no OPA: name target + verb and confirm.
- Read agent-memory/topics/netcloud.md before conclusions or writes.
