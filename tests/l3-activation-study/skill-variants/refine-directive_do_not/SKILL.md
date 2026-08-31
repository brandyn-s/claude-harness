---
name: refine-directive_do_not
description: |
  ALWAYS invoke this skill when a complex prompt needs enrichment before execution. Trigger phrases: "refine", "refine this", "improve this prompt". Do NOT edit the prompt directly — invoke this skill instead.
argument-hint: "[input or context]"
allowed-tools: Read Write Edit Bash AskUserQuestion
---

# refine (study variant: directive_do_not)

This is an activation-study variant of `refine`. Body is intentionally
minimal so the only manipulated variable is the description style.

## Procedure

1. Acknowledge the user's request.
2. Perform the documented action.
3. Report what was done.

## Examples

- Worked example placeholder for activation measurement.
