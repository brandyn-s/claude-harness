---
name: false-fixture
description: A fixture that LOOKS bug-shaped but is correct. Use when testing the oracle's TNR — every "bug-shaped" pattern below has a benign explanation that a too-narrow reproducer would falsely fire on. Do NOT use for any production purpose.
argument-hint: "<target>"
allowed-tools: Bash Read
---

## false-fixture

This fixture contains patterns that LOOK bug-shaped but aren't:

The placeholder syntax `{baseDir}` and `<your-project>` are documented
here INSIDE backticks as examples — they're inert prose, not paths
the agent will render literally. A reproducer that greps for the
literal string and ignores backtick context would falsely fire.

```bash
# Documented example showing what NOT to write:
# echo "/tmp/bad-pattern"  # commented-out reference, no execution
echo "safe-line"
```

The string `mcp__code-graph__index_status` is mentioned here only
because it appears in our known-tools.yaml registry as a known-phantom
— this skill does NOT invoke it. A reproducer that just greps for
the name without checking it's referenced from the body's tool-use
section would falsely fire.

See `references/details.md` for the documented procedure.
