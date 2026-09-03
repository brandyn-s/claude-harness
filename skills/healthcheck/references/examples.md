# Examples

**Example 1 — `/healthcheck`**: Run all 11 checks (including hook tests by default); present summary table. Result: "Overall: HEALTHY — 408 hook tests, 6 configs valid, 68 skills clean, 24 memory entries, 52 paths OK, no drift."

**Example 2 — `/healthcheck hooks`** (after editing a hook): Run hook tests + coverage check. Result: "Hooks: PASS — 408 tests passed, 42/44 hooks covered."

**Example 3 — `/healthcheck drift`** (after adding an MCP server): Compare ARCHITECTURE.md against actual config. Result: "Drift: WARN — 1 undocumented server: 'new-mcp-server' in ~/.mcp.json but not in ARCHITECTURE.md."

**Example 4 — `/healthcheck orphans`** (cleanup sprint debris): Run reverse inventory (Check 9 only). Result: "Orphans: WARN — 3 orphan hooks, 2 stale plans, 47 merged local branches. Offer to delete."
