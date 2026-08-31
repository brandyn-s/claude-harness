---
name: clean-skill
description: A minimal skill fixture that exists only to test audit-skill against well-formed input. Use when verifying audit-skill's H1/H2/D3*/M*/T1/C*/B1/P1/Q* checks all let well-formed input pass. Do NOT use for any production purpose — this is test infrastructure only.
argument-hint: "<target>"
allowed-tools: Bash Read
---

## clean-skill

This fixture exists only to exercise audit-skill against well-formed input.
See `references/details.md` for the procedure.

## Procedure

```bash
python ~/.claude/skills/clean-skill/scripts/run.py "$1"
```

## Success Criteria

- Exit code 0 on the happy path
