# Subagent Dispatch Template

When dispatching `/absorb` via Agent tool, include this summary in the prompt — subagents
do NOT load SKILL.md automatically:

```
ABSORB SKILL SUMMARY (include in agent prompt):
- 3 evidence tiers: Code (50%), Automation Artifacts (20%), Workflow (30%)
  - Adapt split to target: CC config authors → boost Tier 2 to 40%+; pure coders → skip Tier 2
- Tier 2 reads: skills, hooks, agents, CLAUDE.md, settings.json, prompt text
  - Do NOT compare against your architecture during evidence collection (Phase 2)
  - Comparison happens in Phase 4 against actual skill/hook/agent implementations
- 3 language tags: [universal], [principle-transferable] (extract principle), [language-specific]
- Gate 3-alt: patterns passing gates 1-2 but lacking incidents → persist as latent gaps
- Cross-developer aggregation: search absorb-*.md for recurring patterns, tag [cross-validated: N]
  - Only count developers who are independent sources (not forking each other's configs)
- Budget: 30 gh + 7 Exa (Exa file reads exempt from gh count)
- Output: profile → knowledge-base/topics/absorb-<username>.md with rejected patterns,
  latent gaps, and recommendations (with revert triggers)
- Frontmatter MUST include description: (a retrieval synopsis) — CI hard-requires it; a
  profile without it turns the KB main red (the 2026-06-07 16-profile batch did exactly this)
- COMPILE before done (or the PR fails CI and blocks all KB PRs): run
  `python3 ~/Documents/knowledge-base/tools/kb.py build` (the canonical compiler —
  regenerates the catalog, graph, evidence ledger, health report, README, and Home — or run
  /garden as an alternative), then confirm the same script with `check` exits 0.
  A bare .md is incomplete.
- Effectiveness: include ## What Shipped tracking section
```
