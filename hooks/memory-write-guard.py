#!/usr/bin/env python3
"""ASI06: Memory and Context Poisoning guard.

PreToolUse hook for Write|Edit that intercepts writes to memory files
(topic files, MEMORY.md, *-patterns.md) and blocks:
- Prompt injection patterns embedded in memory entries
- Oversized entries (memory inflation attacks)

Non-memory files pass through immediately (exit 0).
"""

import json
import re
import sys
from pathlib import Path

# Memory file locations
MEMORY_PATHS = [
    Path.home() / ".claude" / "agent-memory",
    Path.home() / ".claude" / "projects",
]
MEMORY_SUFFIXES = {".md"}
MAX_ENTRY_LENGTH = 2500  # Calibrated 2026-03-28: P50=1513, P75=2064, P90=2756 across 580 KB entries

# Injection patterns that should NEVER appear in memory entries.
# These detect attempts to embed instructions in what should be data.
INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?previous\s+instructions",
    r"(?i)you\s+are\s+now\s+in\s+\w+\s+mode",
    r"(?i)<system[^>]*>",
    r"(?i)OVERRIDE:\s*\S",
    r"(?i)system:\s*(you|ignore|override|forget)",
    r"(?i)disregard\s+(all\s+)?(previous|prior|above)",
]

# Pattern for "IMPORTANT:" followed by a directive verb - blocks injection
# but allows "IMPORTANT note about X" (no directive verb after colon)
IMPORTANT_DIRECTIVE = (
    r"(?i)IMPORTANT:\s*(ignore|override|forget|disregard|disable|delete|remove)"
)


def is_memory_file(file_path: str) -> bool:
    """Check if the target file is a memory/topic file."""
    p = Path(file_path)
    if p.suffix not in MEMORY_SUFFIXES:
        return False
    for mem_path in MEMORY_PATHS:
        try:
            p.relative_to(mem_path)
            return True
        except ValueError:
            continue
    if "-patterns.md" in p.name:
        return True
    return False


def check_injection(content: str) -> str | None:
    """Scan content for prompt injection patterns."""
    for pattern in INJECTION_PATTERNS:
        match = re.search(pattern, content)
        if match:
            return f"Injection pattern: '{match.group()[:60]}'"

    match = re.search(IMPORTANT_DIRECTIVE, content)
    if match:
        return f"Directive injection: '{match.group()[:60]}'"

    return None


def check(hook_input):
    """Returns (exit_code, stderr_payload, stdout_payload).
    exit_code: 0=allow, 2=block. Payloads are strings or None.
    """
    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Content comes from "content" (Write), "new_string" (Edit), or each
    # edits[].new_string (MultiEdit). MultiEdit was previously unscanned, so a
    # poisoned entry written via MultiEdit bypassed the ASI06 guard entirely.
    content = tool_input.get("content", "") or tool_input.get("new_string", "")
    if not content and isinstance(tool_input.get("edits"), list):
        content = "\n".join(
            e.get("new_string", "")
            for e in tool_input["edits"]
            if isinstance(e, dict)
        )

    if not is_memory_file(file_path):
        return (0, None, None)

    # Check injection patterns
    injection = check_injection(content)
    if injection:
        reason = f"ASI06 Memory Poisoning blocked: {injection}"
        return (2, json.dumps({"decision": "block", "reason": reason}), None)

    # Check entry size — EXCEPT for a shrinking MEMORY.md rewrite.
    #
    # MEMORY.md is an INDEX, not an entry: MAX_ENTRY_LENGTH was calibrated
    # 2026-03-28 against ENTRY files (P50=1513, P75=2064, P90=2756) while a
    # healthy compacted index is ~14-15 KB. The memory-index-size PostToolUse
    # hook MANDATES compacting it when it nears the 24.4 KB read limit, and that
    # compaction is necessarily a full-file rewrite far above 2,500 chars — so
    # the per-entry cap made the mandated maintenance impossible through the
    # file-write tools, and the documented Bash `cp`/python reroute was hit a
    # 3rd time on 2026-07-05.
    #
    # A SHRINKING full-file rewrite is definitionally not memory inflation, so
    # only that case is exempt. Growth writes to MEMORY.md (>= current size) and
    # every entry-file write keep the cap unchanged. The injection scan above
    # already ran on this content, so the poisoning half of ASI06 keeps full
    # coverage either way. (Staged spec: hooks/staged/memory-index-compaction-exemption.spec.md)
    target = Path(file_path)
    inflation_exempt = False
    if target.name == "MEMORY.md":
        try:
            if target.exists() and len(content) < target.stat().st_size:
                inflation_exempt = True
        except OSError:
            inflation_exempt = False  # can't stat -> keep the cap (fail closed)

    if not inflation_exempt and len(content) > MAX_ENTRY_LENGTH:
        reason = f"ASI06 Memory inflation blocked: {len(content)} chars exceeds {MAX_ENTRY_LENGTH} limit. Break into smaller entries."
        return (2, json.dumps({"decision": "block", "reason": reason}), None)

    # Batch-warn: advisory for sequential ~/.claude/ edits
    claude_dir = Path.home() / ".claude"
    safe_files = {"settings.json", "settings.local.json"}
    p = Path(file_path)
    try:
        p.relative_to(claude_dir)
        if p.name not in safe_files:
            warning = (
                "Sequential Write/Edit calls on ~/.claude/ files get reverted by "
                "PostToolUse hooks. If editing multiple files, batch ALL changes into "
                "a single Python script and execute via Bash."
            )
            return (0, None, json.dumps({"additionalContext": warning}))
    except ValueError:
        pass

    return (0, None, None)


def main():
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    code, stderr_msg, stdout_msg = check(hook_input)
    if stderr_msg:
        print(stderr_msg, file=sys.stderr)
    if stdout_msg:
        print(stdout_msg)
    sys.exit(code)


if __name__ == "__main__":
    main()
