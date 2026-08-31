#!/usr/bin/env python3
"""Check 4: Memory consistency — single source of truth.

Delegates to doc_accuracy_audit.py's `audit_memory_md`, which correctly
resolves MEMORY.md links that point OUTSIDE the memory dir (e.g.
`~/Documents/knowledge-base/topics/*.md`) and treats intentionally-local
gitignored entries as non-orphans. An earlier inline implementation in
SKILL.md re-globbed only the memory dir and produced false "missing"
findings for every KB-topic link (observed 2026-06-16: 3 phantom misses).

Exit 0 = PASS, 1 = WARN (orphans/missing refs), 2 = could not run audit.
"""
import os
import sys
import json
import subprocess

AUDIT = os.path.expanduser(
    "~/.claude/skills/audit-architecture/references/doc_accuracy_audit.py"
)


def main():
    if not os.path.exists(AUDIT):
        print(f"Memory: WARN — audit scanner not found at {AUDIT}")
        return 2
    try:
        r = subprocess.run(
            ["python3", AUDIT], capture_output=True, text=True, timeout=120
        )
        data = json.loads(r.stdout)
    except (json.JSONDecodeError, subprocess.SubprocessError, OSError) as e:
        print(f"Memory: WARN — could not parse audit output ({e})")
        return 2

    mem = data.get("memory_md", {})
    issues = mem.get("issues", 0)
    lines = mem.get("lines", "?")
    links = mem.get("links", "?")
    findings = mem.get("findings", [])

    if not issues:
        print(f"Memory: PASS — {links} links resolve, {lines} lines, 0 issues")
        return 0

    print(f"Memory: WARN — {issues} issue(s), {links} links, {lines} lines")
    for f in findings:
        print(f"    {f}")
    if isinstance(lines, int) and lines > 180:
        print(f"    WARN: MEMORY.md approaching 200 lines ({lines})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
