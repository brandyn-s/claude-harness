---
name: true-fixture
description: A fixture containing 15 known-true bugs the calibration set targets. Use when testing the oracle's TPR. Do NOT use for any other purpose — this is calibration infrastructure.
argument-hint: "[X]"
allowed-tools: Read mcp__code-graph__index_status mcp__unused-tool__never_called
---

## true-fixture

This fixture contains bugs the oracle should detect. Each labeled
finding in `findings.yaml` targets one or more of these.

Bad citation: `references/missing-ref.md` — file doesn't exist.
Phantom MCP tool: `mcp__code-graph__index_status` — known-phantom.
{baseDir} placeholder rendered literally in this prose.
<your-claude-project> appears here outside backticks.

```bash
python /usr/bin/nonexistent-script.py "$1"
echo "writing to /tmp/calibration-output"
python ${CLAUDE_SKILL_DIR}/scripts/run.py
```

Scripts that don't exist are also a bug class.
