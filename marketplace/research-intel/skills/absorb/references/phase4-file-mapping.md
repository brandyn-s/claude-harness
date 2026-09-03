# Phase 4 — Pattern-Domain → Architecture File Mapping

Use this table when executing Phase 4 Step 1 (Identify the relevant architecture files). Map the pattern's domain to specific files — don't read everything.

| Pattern domain | Read these files |
|---------------|-----------------|
| Coding style & practices | `CLAUDE.md` (platform constraints, output generation), relevant source files in your repos for comparison |
| Architecture & design | `CLAUDE.md`, `rules/search-efficiency.md`, relevant skill/hook source |
| Commit/git workflow | `rules/git-hygiene.md` |
| PR/review process | `rules/git-hygiene.md`, `rules/security-review-before-pr.md` |
| Agent/subagent practices | `rules/agent-delegation.md`, `rules/subagent-verification.md` |
| Hook/scaffolding philosophy | `settings.json` hooks, `rules/verify-effectiveness.md` |
| Skill design & triggers | The actual skill SKILL.md in `${CLAUDE_PLUGIN_ROOT}/skills/<matching-skill>/`. Compare **capability-to-capability**, not skill-to-skill — their one skill may map to your 3 skills, or vice versa. Ask "what capability does this provide?" then find how your architecture delivers that capability (may be a skill, a hook, a rule, or a workflow across multiple tools). |
| Hook architecture & coverage | `settings.json` hooks section, actual hook scripts in `~/.claude/hooks/`. Map their event coverage against yours. |
| Agent configuration | Agent definitions in `~/.claude/agents/`, `rules/agent-delegation.md` routing table |
| CLAUDE.md philosophy | Your `CLAUDE.md`, compare structure and prioritization choices |
| Prompt engineering | The actual text of matching skills/agents — compare instruction structure, constraint style, ambiguity handling |
| Code style/architecture | `CLAUDE.md`, relevant skill files |
| Search/research workflow | `rules/search-efficiency.md`, plus `rules/web-search-preference.md` |
| Testing/validation | `rules/tdd-quality.md` |
| Decision-making process | `rules/check-before-change.md`, `rules/diagnose-before-fix.md` |
| Memory/knowledge practices | `knowledge-base/topics/` via `memory_search`, `agent-memory/topics/` |
| MCP tool usage | `CLAUDE.md` (delegation rules), relevant `agent-memory/topics/` files |
| Engineering discipline | `rules/tdd-quality.md`, `rules/check-before-change.md` |
| Dependencies & CI | Repo `.github/workflows/`, `CLAUDE.md` CI section, `rules/security-review-before-pr.md` |
| Documentation & communication | `rules/git-hygiene.md` (commit WHY), skill templates |
| Other / uncategorized | Grep `rules/` for the pattern's keywords; fallback to `memory_search` |

**Fallback:** If a mapped file doesn't exist (renamed or reorganized since this table was written), grep `rules/` and `skills/` for keywords from the pattern domain before concluding "no existing coverage." A missing file is not evidence of a gap — it may have been consolidated into another rule.
