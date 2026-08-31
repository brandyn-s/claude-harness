---
name: dirty-skill
description: A fixture that intentionally violates multiple audit checks.
argument-hint: "[target]"
allowed-tools: Bash Read mcp__exa__web_search_exa mcp__code-graph__index_status mcp__unused__never_invoked
---

## dirty-skill

Bad citation: see `references/missing-ref.md` (does not exist; H1).
Bad cross-skill citation: see `nonexistent-skill/references/foo.md` (H4).
H5 trigger — read `phantom-dir/MISSING.md` for the rest. The read-verb
gate makes this fire; without the verb it would be skipped as a
descriptive mention.

```bash
python ~/.claude/skills/dirty-skill/scripts/missing.py "$1"
echo "writing to /tmp/dirty-output"
python ${CLAUDE_SKILL_DIR}/scripts/run.py
```

Uses `mcp__exa__web_search_exa` in the body (so M2 doesn't fire on Exa);
the other two MCP tools in allowed-tools are intentionally unused.
The phantom `mcp__code-graph__index_status` triggers T1.

P1 trigger — unresolved template placeholder: see [docs]({baseDir}/references/orphan.md).
Also `<your-claude-project>` here exercises the alternate P1 pattern.
