# Research-to-Practice Transfer Analysis Template

## Implementation Verification Gate

Before filling the **Current Approach** and **Gap** columns, read the actual
implementation files for each architecture component in the table -- not just
ARCHITECTURE.md summaries. If a skill, hook, or shared reference already
implements what the research recommends (even partially), note "Partially
covered by [file]" in the Gap column and adjust Transfer Difficulty downward.
Unverified gap claims waste user time on problems that don't exist.

## Gap Analysis Table

Cross-reference research findings with current architecture:

| Architecture Component | Current Approach | Research State-of-the-Art | Gap | Transfer Difficulty | Priority |
|---|---|---|---|---|---|
| Agent routing | Keyword-based delegation table | Semantic intent classification + learned routing | Moderate — current approach works but is brittle | Medium (needs embedding model) | MEDIUM |
| Memory management | File-based MEMORY.md per agent | Vector-indexed episodic memory with decay | Large — current approach doesn't scale | High (needs infrastructure) | LOW (current scale is fine) |

## Transfer Difficulty Ratings

- **Low**: Configuration change, prompt edit, or skill modification. Can do in one session.
- **Medium**: New skill, new hook, or agent prompt restructure. Requires planning + testing.
- **High**: New infrastructure (MCP server, external service, embedding model). Requires project-level effort.
- **Experimental**: Research is promising but unproven in this context. Needs controlled experiment first.

## Architecture Components to Map Against

- **Agent system** (agent definitions, delegation, routing)
- **Memory & persistence** (agent memory, topic files, checkpoints)
- **Tool integration** (MCP servers, hooks, skill routing)
- **Context management** (compaction, summarization, token budgets)
- **Prompt engineering** (CLAUDE.md, agent prompts, skill instructions)
- **Evaluation & feedback** (self-improvement loops, quality metrics)
- **Security & compliance** (guardrails, confirmation patterns, audit trails)
- **Orchestration** (parallel dispatch, sequential pipelines, error recovery)
