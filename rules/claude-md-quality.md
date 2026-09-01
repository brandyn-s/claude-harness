---
paths:
  - "**/CLAUDE.md"
---

# Keep CLAUDE.md small and operational

`CLAUDE.md` is always loaded, so include only instructions that apply to nearly
every task in that repository.

Before adding a line, ask what failure it prevents. If the answer is tied to a
specific workflow, language, directory, or occasional task, route it elsewhere:

- path-specific guidance → `.claude/rules/` with `paths` frontmatter
- occasional procedure → a skill
- deterministic action that must always happen → a hook
- external capability → MCP configuration
- background explanation or history → ordinary documentation

Write instructions as short, testable actions. Prefer a command, decision rule,
or file pointer over narrative. Avoid duplicating a rule already enforced by a
hook or permission setting.

Keep the file under 200 lines. When it grows, delete stale instructions first,
then move lower-frequency material to scoped rules or skills. Validate that a
new contributor can answer these questions quickly:

1. What is this repository?
2. Where are the main components?
3. What commands build and test it?
4. Which boundaries must not be crossed?
5. Where does specialized guidance live?

Do not add incident timelines, generic coding advice, personal machine paths,
credentials, organization-only systems, or instructions that depend on tools a
public user cannot access.
