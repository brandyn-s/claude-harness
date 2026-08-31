# Garden — Worked Examples

Moved from SKILL.md 2026-06-11 (B8c/F2 size split).

**Example 1: Weekly tending with auto-resolutions**
User: `/garden`
Actions:
1. Branch garden/<date> from origin/main
2. Inventory: 126 topics, 4 MoCs, 3 dashboards
3. Auto-fix pass: promote 3 stages, strip 10 broken links, assign 1 orphan
   to strong-fit MoC, fill 5 MoC gaps (3 strong / 2 weak), convert 13 bare
   links. Append 2 entries to canonicalization-candidates.md.
4. Open PR with all fixes, auto-merge
Result: Garden state advances by 32 in-place fixes plus 2 backlog appends,
single PR, no user prompts

**Example 2: Healthy garden**
User: `/garden`
Actions:
1. Branch garden/<date> from origin/main
2. Inventory clean: 0 stage mismatches, 0 orphans, 0 MoC gaps, 0 broken links
3. No fixes applied, no PR
Result: Report-only run, single message back to user

**Example 3: Audit mode before a large run**
User: `/garden audit`
Actions:
1. Branch garden/<date> from origin/main
2. Inventory: 134 topics (8 new since last /garden)
3. Detection pass reports "Would apply: 4 stage promotions, 7 bare-link
   conversions, 1 orphan to weak-fit MoC, 3 candidates appended to
   canonicalization-candidates.md"
4. No edits, no PR
Result: User reviews the preview, then re-runs `/garden` without args to
apply the changes

**Example 4: Memory-search MCP down**
User: `/garden`
Actions:
1. Branch garden/<date> from origin/main
2. Inventory + standard checks (no findings)
3. Merge candidates: first MCP call times out → skip the entire check,
   note "merge candidates skipped — memory-search MCP unavailable"
4. Continue with the other checks; push if anything changed
Result: Garden run completes even when the MCP is degraded
