---
paths:
  - "**/CLAUDE.md"
---

# CLAUDE.md Quality — Writing Instructions Agents Follow

CLAUDE.md loads every turn. Every line costs context budget. Poorly
structured instructions get skipped under cognitive load.

## Content Routing Decision Tree

Before adding content to CLAUDE.md, route it:

```
Platform/shell constraint affecting tool execution?
  → CLAUDE.md (Platform section)

Routing decision (which skill/agent/tool)?
  → CLAUDE.md (Delegation section)

Enforcement rule with incident citations?
  → rules/<topic>.md

Workflow-specific (only matters during one skill)?
  → that skill's SKILL.md or references/

API gotcha or tool-specific pattern?
  → memory/*-patterns.md or agent-memory/topics/

Strategic decision or lesson learned?
  → knowledge-base/topics/

None of the above?
  → probably doesn't need to be written down
```

### CLAUDE.md is the right place for

- Platform constraints affecting every Bash/Python/PowerShell call
- Delegation routing tables (skill triggers, agent dispatch)
- Brief "don't forget" pointers to rules that get violated despite
  being in `rules/` files — but as pointers, not restatements

### CLAUDE.md is NOT the right place for

- Enforcement rules with incident history → `rules/`
- Skill-specific workflows → skill's SKILL.md
- API gotchas → pattern files
- Anything >5 lines for a single concern → extract to `rules/`

## Formatting Principles

- **Order by invocation frequency**: platform (every Bash call) →
  delegation (every message) → behavioral (periodic) → output (rare)
- **Decision trees, not prose**: `Failed? → Same error? → Modify.
  2 retries? → Report.` beats `"reformulate and retry immediately"`
- **One claim per bullet**: dense prose loses claims on rewrite
- **Pointers, not restatements**: if `rules/X.md` covers it, write
  `See rules/X.md` — don't duplicate the content
- **No meta-sentences**: don't explain why a section exists
- **Qualifier preservation**: "always" means no exceptions, "never"
  means no workarounds — don't drop qualifiers during edits

## Budget

- Total: ≤120 lines
- Per section: ≤20 lines (delegation table exempt)
- Over 20: extract to `rules/` or `references/`, keep a pointer

Selectively adapted from JoernStoehler/xrisk-pause-game meta-claudemd
(2026-03-31, gather-repos run 21).
