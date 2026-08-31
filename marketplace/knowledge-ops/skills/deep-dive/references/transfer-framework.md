# Transfer Difficulty Assessment

Shared framework for assessing how difficult it is to transfer external findings (community patterns or research insights) into this Claude Code architecture. Referenced by gather-intel, gather-research, and deep-dive.

## Difficulty Levels

| Level | Definition | Examples | Typical effort |
|-------|-----------|----------|---------------|
| **Drop-in** | Direct application - change a prompt, config, or parameter | "Add this line to CLAUDE.md" / "Set this hook parameter to X" / "Research shows explicit step numbering improves tool-use accuracy" | Single session |
| **Pattern adoption** | Adopt a structural pattern that maps to existing components | "Use this hook pattern for auto-formatting" / "Add this agent routing rule" / "ReAct-style reasoning loops in agent prompts" | 1-2 sessions with testing |
| **Skill/hook creation** | Build a new skill or hook to implement the pattern | "Create a PreToolUse hook that validates X" / "Build a skill for Y workflow" / "Self-reflection after tool failures" | Planned implementation |
| **Architecture evolution** | Modify the architecture's structure (new agents, new routing, new memory patterns) | "Restructure agent delegation from keyword to semantic" / "Hierarchical planning with sub-goal decomposition" | Project-level planning via superplan |
| **Infrastructure addition** | Requires new external infrastructure (MCP server, embedding model, database) | "Add vector-indexed memory" / "Build a custom MCP server for X" | Significant project |

**Opt-out for general research:** The deep-dive skill is general-purpose research, not architecture-focused intelligence. Transfer difficulty assessment is optional for deep-dive reports. Include it only when a finding implies a specific architectural change to this system. For pure knowledge reports (vendor comparisons, technology surveys, compliance framework analysis), omit transfer difficulty.

## How to Apply

When scoring a finding in Phase C of any research/intelligence skill:

1. Identify the recommended action
2. Determine which architecture component it touches
3. Match to the difficulty level above
4. Include in the finding format as `Transfer difficulty: [level]`

Drop-in and Pattern adoption findings are immediately actionable. Skill/hook creation needs a planning session. Architecture evolution and Infrastructure addition need superplan.

## Experiment Design Template

For findings tagged `[experiment]` or classified as "TEST" / "UNTESTED":

```
## Experiment: [Name]
- **Hypothesis**: [What the finding predicts will improve - be specific about direction and magnitude]
- **Control**: [Current architecture behavior - baseline measurement method and expected baseline value]
- **Treatment**: [Specific change to test - exact files, configs, or prompts to modify]
- **Success criteria**: [What improvement magnitude justifies permanent adoption? e.g., ">20% reduction in tool-call errors" or "measurable context savings with no quality loss"]
- **Metrics**: [How to measure improvement - success rate, error reduction, task completion time, context usage. Include HOW to collect each metric.]
- **Confounders**: [What else could explain the result? e.g., different task types, model version changes, time-of-day effects. How will you control for them?]
- **Sample size**: [Minimum number of sessions/tasks before evaluating. For behavioral changes, minimum 10 sessions. For prompt changes, minimum 5 diverse tasks.]
- **Duration**: [Calendar time to run the experiment - typically 1-2 weeks for behavioral patterns]
- **Rollback plan**: [How to revert if the change is net negative - specific git revert or config change]
```
