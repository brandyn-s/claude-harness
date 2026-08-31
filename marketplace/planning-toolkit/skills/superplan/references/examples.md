# Superplan — Examples

## Example 1: Cross-domain security automation

User says: "Build a runbook that pulls CrowdStrike detections and creates Linear issues for each"

Actions:
1. Phase 1 detects Security (primary) + Project Management + Automation (supplementary)
2. Phase 2 loads security.md and crowdstrike.md topic files fully, linear.md and msgraph.md as supplementary
3. Phase 3 identifies: CrowdStrike MCP (OPA-gated writes), Linear MCP (read-write), PowerShell execution path
4. Phase 4 produces plan with sequential pipeline: worker reads detections → worker creates issues
5. Dependency summary: 1 → 2 → 3 → [4 | 5] → 6

Result: Structured plan with domain-specific gotchas, parallelizable steps identified, and execution path recommendation.

## Example 2: Single-domain finance task

User says: "Plan how to analyze our top 10 vendors by spend this quarter"

Actions:
1. Phase 1 detects Finance (primary, only domain)
2. Phase 2 loads ramp.md topic file, ramp-patterns.md deep reference
3. Phase 3 identifies: Ramp MCP with SQL queries, notes ~100-row limit
4. Phase 4 produces plan: MCP direct path via worker agent with GROUP BY aggregation

Result: Plan delegates to worker agent with specific SQL query pattern and known Ramp constraints noted.

## Example 3: MCP development task

User says: "Build a new MCP server for the Tailscale API"

Actions:
1. Phase 1 detects MCP Development (primary)
2. Phase 2 loads mcp-development-patterns.md, api-research-patterns.md
3. Phase 2c finds knowledge base topics: mcp-server-generation.md (11 entries)
4. Phase 3 identifies: superpowers chain execution path
5. Phase 4 produces phased plan: Phase A (API analysis) → Phase B (server generation) → Phase C (audit + deploy)

Result: Plan with full MCP development context, including prior generation lessons from KB.
