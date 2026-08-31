---
name: shell-only-skill
description: A fixture that ships only .sh scripts. Use when verifying C3 fires on bash-only skills. Do NOT use this for any real purpose — it's test infrastructure.
argument-hint: "<arg>"
allowed-tools: Bash
---

## shell-only-skill

```bash
bash ~/.claude/skills/shell-only-skill/scripts/run.sh "$1"
```
