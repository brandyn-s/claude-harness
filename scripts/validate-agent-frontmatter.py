#!/usr/bin/env python3
"""Validate agent frontmatter against the documented subagent field set.

WHY THIS EXISTS
---------------
Two audit findings, both silent:

1. `agents/worker.md` carried `allowedAgentTypes: worker` — NOT a documented
   subagent field. It read like a delegation restriction and did nothing. Nothing
   in the repo validated agent frontmatter, so an unsupported field could sit there
   indefinitely looking like enforcement (and `agents/TEMPLATE.md` taught it to
   every new agent).

2. Omitting `tools:` is not a neutral default — the subagents reference states it
   "Inherits every tool available to subagents". A denylist can remove named tools,
   but only a non-empty positive `tools:` allowlist bounds the complete tool and MCP
   surface against future additions.

This validator is a lint, not a security boundary: it checks what the files
DECLARE. Actual enforcement is the platform's.

FIELD SET (verified verbatim, https://code.claude.com/docs/en/sub-agents, 2026-07-26)
------------------------------------------------------------------------------------
name, description, tools, disallowedTools, model, permissionMode, maxTurns,
skills, mcpServers, hooks, memory, background, effort, isolation, color.

Exit codes:
  0 = all agents valid
  1 = at least one agent declares an unsupported field
  2 = could not read the agents directory (UNKNOWN, not a pass and not a failure)
"""

from __future__ import annotations

import argparse
import os
import re
import sys

#: Documented subagent frontmatter fields. Anything else is unsupported and
#: silently ignored by the platform.
SUPPORTED = frozenset(
    {
        "name",
        "description",
        "tools",
        "disallowedTools",
        "model",
        "permissionMode",
        "maxTurns",
        "skills",
        "mcpServers",
        "hooks",
        "memory",
        "background",
        "effort",
        "isolation",
        "color",
    }
)

#: Known-unsupported fields we have actually seen, with the correct lever.
KNOWN_BAD = {
    "allowedAgentTypes": (
        "not a documented field; it silently does nothing. To stop an agent from "
        "dispatching subagents use `disallowedTools: [Agent]`; to restrict tools "
        "use a positive `tools:` list."
    ),
}

FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
#: Top-level YAML keys only (no leading whitespace), tolerating comments.
TOP_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:", re.MULTILINE)


def parse_top_level_keys(text: str) -> list[str]:
    m = FRONTMATTER.search(text)
    if not m:
        return []
    block = m.group(1)
    # Strip full-line comments so a documented "# allowedAgentTypes is NOT
    # supported" note is not mistaken for a declaration.
    lines = [ln for ln in block.splitlines() if not ln.lstrip().startswith("#")]
    return TOP_KEY.findall("\n".join(lines))


def parse_frontmatter_values(text: str, field: str) -> list[str]:
    """Return scalar, flow-list, or block-list values for one top-level field."""
    match = FRONTMATTER.search(text)
    if not match:
        return []

    lines = match.group(1).splitlines()
    field_line = re.compile(rf"^{re.escape(field)}\s*:(.*)$")
    for index, line in enumerate(lines):
        found = field_line.match(line)
        if not found:
            continue

        inline = found.group(1).strip()
        if inline:
            if inline == "[]":
                return []
            raw = inline.strip("[]")
            return [
                item.strip().strip("\"'")
                for item in raw.split(",")
                if item.strip().strip("\"'")
            ]

        values: list[str] = []
        for following in lines[index + 1 :]:
            if TOP_KEY.match(following):
                break
            item = re.match(r"^\s+-\s*(.+?)\s*$", following)
            if item:
                values.append(item.group(1).strip().strip("\"'"))
        return values

    return []


def is_intentional_inherited_tools_exception(filename: str, text: str) -> bool:
    """Recognize the one reviewed agent that intentionally inherits tools."""
    return (
        filename == "worker.md"
        and parse_frontmatter_values(text, "name") == ["worker"]
        and not parse_frontmatter_values(text, "tools")
        and parse_frontmatter_values(text, "disallowedTools") == ["Agent"]
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dir",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents"),
        help="agents directory (default: <repo>/agents)",
    )
    ap.add_argument(
        "--warn-unbounded",
        action="store_true",
        help="also report agents without a non-empty positive tools allowlist",
    )
    args = ap.parse_args(argv)

    if not os.path.isdir(args.dir):
        print(f"validate-agent-frontmatter: cannot read {args.dir}", file=sys.stderr)
        return 2

    problems: list[str] = []
    warnings: list[str] = []
    checked = 0

    for name in sorted(os.listdir(args.dir)):
        if not name.endswith(".md"):
            continue
        # README/TEMPLATE are documentation, not live agent definitions.
        if name in {"README.md", "TEMPLATE.md"}:
            continue
        path = os.path.join(args.dir, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            problems.append(f"{name}: unreadable ({type(exc).__name__})")
            continue

        keys = parse_top_level_keys(text)
        if not keys:
            warnings.append(f"{name}: no YAML frontmatter found")
            continue
        checked += 1

        for key in keys:
            if key in SUPPORTED:
                continue
            hint = KNOWN_BAD.get(key, "not a documented subagent frontmatter field")
            problems.append(f"{name}: unsupported field `{key}` — {hint}")

        if args.warn_unbounded and not parse_frontmatter_values(text, "tools"):
            if is_intentional_inherited_tools_exception(name, text):
                warnings.append(
                    f"{name}: intentional inherited-tool exception — MCP-unbounded "
                    "by design; `Agent` remains denied"
                )
            else:
                denied = parse_frontmatter_values(text, "disallowedTools")
                inherited = "every other tool" if denied else "every tool"
                warnings.append(
                    f"{name}: no non-empty positive `tools:` allowlist — omitting "
                    f"`tools` INHERITS {inherited} available to subagents"
                )

    print(f"validate-agent-frontmatter: checked {checked} agent definition(s)")
    for w in warnings:
        print(f"  warn: {w}")
    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("  all declared fields are documented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
