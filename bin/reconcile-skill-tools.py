#!/usr/bin/env python3
"""Reconcile tool declarations between SKILL.md body, frontmatter
`allowed-tools`, and `manifest.yaml:requires_tools`.

Root cause: every skill has THREE places that state which tools the
skill uses (SKILL.md body invocations, frontmatter declarations,
manifest contract). Edits to one don't propagate to the others, so
the harness blocks tool calls at runtime that the body asks for.

This script scans the body for tool invocations, then either reports
drift or auto-fixes the frontmatter + manifest.

Detection rules — a "tool invocation" is:
    - `mcp__<server>__<tool>(...)` or bare `mcp__<server>__<tool>` token
    - Inline-code `mcp__<server>__<tool>(` or `mcp__<server>__<tool>(...)`
    - Built-in Claude tools mentioned with capitalized convention in
      prose: `Read`, `Write`, `Edit`, `Bash`, `Grep`, `Glob`, `Agent`,
      `AskUserQuestion`, `Skill`, `WebFetch`, `WebSearch`, `Task`,
      `TaskCreate`, `TaskUpdate`, `ExitPlanMode`, `NotebookEdit`,
      `Monitor`, `SendUserFile`, `ToolSearch`
    - `Bash` is implied if any fenced ```bash block exists
    - `Read`/`Grep`/`Glob` are implied if the skill is procedural
      (the heuristic is conservative; only adds when actually
      referenced in prose)

Usage:
    bin/reconcile-skill-tools.py <skill>      # check one
    bin/reconcile-skill-tools.py --all         # check all
    bin/reconcile-skill-tools.py --all --apply # apply fixes

Exit codes:
    0   no drift
    1   drift found (--check) OR fixes applied (--apply)
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"

# Built-in Claude Code tools (capitalized convention).
BUILTIN_TOOLS = {
    "Read", "Write", "Edit", "Bash", "Grep", "Glob", "Agent",
    "AskUserQuestion", "Skill", "WebFetch", "WebSearch",
    "Task", "TaskCreate", "TaskUpdate", "ExitPlanMode",
    "NotebookEdit", "Monitor", "SendUserFile", "ToolSearch",
}

# Regex helpers
MCP_TOOL_PAT = re.compile(r"mcp__[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+")
BACKTICK_TOOL_PAT = re.compile(r"`(mcp__[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+)\b")
BUILTIN_INVOKE_PAT = re.compile(
    r"(?:^|[^\w])("
    + "|".join(sorted(BUILTIN_TOOLS, key=len, reverse=True))
    + r")(?=\s+|\(|`|$)"
)
BASH_FENCE_PAT = re.compile(r"```(?:bash|sh|shell)\s*$", re.MULTILINE)


def parse_frontmatter(md_text):
    """Return (frontmatter_dict, body_text, allowed_tools_line_index).
    Frontmatter is a thin YAML-ish parser tuned for skill files."""
    lines = md_text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, md_text, None
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}, md_text, None
    fm_lines = lines[1:end]
    fm = {}
    allowed_idx = None
    for i, line in enumerate(fm_lines, start=1):
        m = re.match(r"^([a-zA-Z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            fm[key] = val
            if key == "allowed-tools":
                allowed_idx = i
    body = "\n".join(lines[end + 1:])
    return fm, body, allowed_idx


def detect_tools_in_body(body_text):
    """Return set of tool names the body references. Conservative —
    only counts a tool as "used" when the reference is unambiguous.

    For MCP tools: any mcp__*__* token is unambiguous (no English word
    looks like that), so we count any occurrence.

    For built-in tools: bare capitalized words like "Read" and "Write"
    occur as English verbs in skill prose ("Read the section",
    "Write a report") and false-positive constantly. We only count
    built-ins when they appear as backticked code (`Read`), or in
    explicit tool-context phrases (`using the Write tool`, `call
    AskUserQuestion`, `Agent(` / `Agent tool`)."""
    used = set()

    # MCP tools — anywhere in text, high signal
    for m in MCP_TOOL_PAT.finditer(body_text):
        used.add(m.group(0))

    # Built-in tools: only count strong-signal references.
    # 1) Backticked: `Read`, `Write`, `AskUserQuestion`, ...
    backtick_builtin = re.compile(
        r"`(" + "|".join(sorted(BUILTIN_TOOLS, key=len, reverse=True)) + r")`"
    )
    for m in backtick_builtin.finditer(body_text):
        used.add(m.group(1))

    # 2) Explicit "using X" / "via X" / "X tool" / "the X tool" / call X(
    for tool in BUILTIN_TOOLS:
        explicit_patterns = [
            rf"\busing (?:the )?{tool}\b",
            rf"\bvia (?:the )?{tool}\b",
            rf"\bcall (?:the )?{tool}\b",
            rf"\binvoke (?:the )?{tool}\b",
            rf"\bdispatch (?:via |with |using )?{tool}\b",
            rf"\b(?:the )?{tool} tool\b",
            rf"\b{tool}\(",  # function-call shape
        ]
        for pat in explicit_patterns:
            if re.search(pat, body_text):
                used.add(tool)
                break

    # 3) ToolSearch / Bash fenced blocks
    if BASH_FENCE_PAT.search(body_text):
        used.add("Bash")

    return used


def parse_allowed_tools_line(fm):
    """Allowed-tools value can be space-separated or list-shaped.
    Return list of declared tools."""
    val = fm.get("allowed-tools", "")
    if val.startswith("["):
        # JSON-shaped list
        inner = val.strip("[]")
        return [t.strip().strip("'\"") for t in inner.split(",") if t.strip()]
    return [t.strip() for t in val.split() if t.strip()]


def parse_prose_only_tools(manifest_path):
    """Read manifest.yaml's optional `prose_only_tools:` list — tools the
    SKILL.md body MENTIONS but deliberately does not use (negated usage
    like "do NOT call X from this skill", matcher-pattern examples,
    descriptions of a downstream orchestrator's capability). The scanner
    subtracts these from detected usage so a deliberate non-grant is not
    re-reported (or worse, re-applied) as drift. Each entry should carry
    a YAML comment saying why the mention is prose-only (B9/F4)."""
    if not manifest_path.exists():
        return set()
    tools = set()
    in_block = False
    for line in manifest_path.read_text(encoding="utf-8").split("\n"):
        if re.match(r"^prose_only_tools\s*:", line):
            in_block = True
            inline = line.split(":", 1)[1].split("#", 1)[0].strip()
            if inline.startswith("["):
                for t in inline.strip("[]").split(","):
                    t = t.strip().strip("'\"")
                    if t:
                        tools.add(t)
                break
            continue
        if in_block:
            stripped = line.strip()
            if stripped.startswith("-"):
                tool = stripped[1:].split("#", 1)[0].strip().strip("'\"")
                if tool:
                    tools.add(tool)
            elif stripped and not stripped.startswith("#"):
                break
    return tools


def parse_manifest_tools(manifest_path):
    """Read manifest.yaml's requires_tools entries (best-effort YAML parse)."""
    if not manifest_path.exists():
        return None, None
    text = manifest_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    in_block = False
    block_start = None
    block_end = None
    tools = []
    for i, line in enumerate(lines):
        if re.match(r"^requires_tools\s*:", line):
            in_block = True
            block_start = i
            inline = line.split(":", 1)[1].strip()
            if inline.startswith("["):
                inner = inline.strip("[]")
                tools = [t.strip().strip("'\"") for t in inner.split(",") if t.strip()]
                block_end = i
                break
            continue
        if in_block:
            stripped = line.strip()
            if stripped.startswith("-"):
                tool = stripped[1:].strip().strip("'\"")
                if tool:
                    tools.append(tool)
                block_end = i
            elif stripped and not stripped.startswith("#"):
                # End of block — line starts a new top-level key
                break
            elif not stripped:
                continue
    return tools, (block_start, block_end)


def compute_drift(skill_dir):
    """Return dict describing what needs to change for this skill."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    fm, body, _ = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    used = detect_tools_in_body(body)
    used -= parse_prose_only_tools(skill_dir / "manifest.yaml")
    declared = set(parse_allowed_tools_line(fm))

    # Cargo-cult tools to flag: ones declared but never used
    unused = declared - used

    def _covered(tool, declared_set):
        """A declared `mcp__<server>__*` wildcard covers every exact tool
        on that server — same normalization compile.py adopted after the
        2026-05-23 40-of-53 false-positive incident."""
        if tool in declared_set:
            return True
        if tool.startswith("mcp__"):
            return tool.rsplit("__", 1)[0] + "__*" in declared_set
        return False

    # Tools used in body but not declared in frontmatter
    missing_frontmatter = {t for t in used if not _covered(t, declared)}

    manifest_path = skill_dir / "manifest.yaml"
    manifest_tools, manifest_block = parse_manifest_tools(manifest_path)
    if manifest_tools is None:
        missing_manifest = set()
    else:
        missing_manifest = {t for t in used
                            if not _covered(t, set(manifest_tools))}

    return {
        "skill": skill_dir.name,
        "skill_md": skill_md,
        "manifest_path": manifest_path,
        "manifest_block": manifest_block,
        "manifest_tools": manifest_tools,
        "used": used,
        "declared_frontmatter": declared,
        "declared_manifest": set(manifest_tools) if manifest_tools else None,
        "missing_frontmatter": missing_frontmatter,
        "missing_manifest": missing_manifest,
        "unused": unused,
    }


def fix_frontmatter(skill_md, missing_tools, unused_to_drop=None):
    """Add `missing_tools` to allowed-tools line; optionally drop unused."""
    text = skill_md.read_text(encoding="utf-8")
    fm, _body, _ = parse_frontmatter(text)
    declared = parse_allowed_tools_line(fm)
    if unused_to_drop:
        declared = [t for t in declared if t not in unused_to_drop]
    for t in sorted(missing_tools):
        if t not in declared:
            declared.append(t)
    # Sort: builtins first (alphabetically), then mcp tools (alphabetically)
    builtins = sorted([t for t in declared if t in BUILTIN_TOOLS])
    mcps = sorted([t for t in declared if t.startswith("mcp__")])
    other = sorted([t for t in declared
                    if t not in BUILTIN_TOOLS and not t.startswith("mcp__")])
    new_value = " ".join(builtins + other + mcps)
    new_text = re.sub(
        r"^(allowed-tools\s*:\s*).*$",
        rf"\g<1>{new_value}",
        text, count=1, flags=re.MULTILINE,
    )
    skill_md.write_text(new_text, encoding="utf-8")


def fix_manifest(manifest_path, missing_tools, manifest_block):
    """Add `missing_tools` to manifest.yaml `requires_tools` list-block.
    If the block uses inline `[...]` form, rewrite to list form for clarity."""
    if not manifest_path.exists() or manifest_block is None:
        return
    text = manifest_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    start, end = manifest_block
    # Detect current form
    header_line = lines[start]
    if "[" in header_line and "]" in header_line:
        # Inline list — rewrite to block list
        existing_inline = header_line.split(":", 1)[1].strip()
        existing = [t.strip().strip("'\"") for t in existing_inline.strip("[]").split(",") if t.strip()]
        all_tools = sorted(set(existing) | set(missing_tools))
        new_lines = ["requires_tools:"] + [f"  - {t}" for t in all_tools]
        lines = lines[:start] + new_lines + lines[end + 1:]
    else:
        # Block list — append entries before block_end
        existing = []
        for i in range(start + 1, end + 1):
            stripped = lines[i].strip()
            if stripped.startswith("-"):
                existing.append(stripped[1:].strip().strip("'\""))
        all_tools = sorted(set(existing) | set(missing_tools))
        new_lines = ["requires_tools:"] + [f"  - {t}" for t in all_tools]
        lines = lines[:start] + new_lines + lines[end + 1:]
    manifest_path.write_text("\n".join(lines), encoding="utf-8")


def report(drift):
    if not drift:
        return False
    has_drift = bool(drift["missing_frontmatter"] or drift["missing_manifest"])
    if not has_drift:
        print(f"OK   {drift['skill']}")
        return False
    print(f"FAIL {drift['skill']}")
    if drift["missing_frontmatter"]:
        print("  missing from allowed-tools:")
        for t in sorted(drift["missing_frontmatter"]):
            print(f"    + {t}")
    if drift["missing_manifest"]:
        print("  missing from manifest.yaml requires_tools:")
        for t in sorted(drift["missing_manifest"]):
            print(f"    + {t}")
    return True


def main(argv):
    args = argv[1:]
    apply_mode = "--apply" in args
    if apply_mode:
        args.remove("--apply")
    if not args:
        sys.exit("usage: reconcile-skill-tools.py {<skill>|--all} [--apply]")

    if args[0] == "--all":
        skill_names = sorted(
            p.name for p in SKILLS.iterdir()
            if p.is_dir() and (p / "SKILL.md").exists()
        )
    else:
        skill_names = args

    total_drift = 0
    for name in skill_names:
        skill_dir = SKILLS / name
        drift = compute_drift(skill_dir)
        if drift is None:
            continue
        if drift["missing_frontmatter"] or drift["missing_manifest"]:
            total_drift += 1
            if apply_mode:
                fix_frontmatter(drift["skill_md"], drift["missing_frontmatter"])
                if drift["manifest_path"].exists() and drift["missing_manifest"]:
                    fix_manifest(
                        drift["manifest_path"],
                        drift["missing_manifest"],
                        drift["manifest_block"],
                    )
                print(f"FIXED {name}: +{len(drift['missing_frontmatter'])} frontmatter, "
                      f"+{len(drift['missing_manifest'])} manifest")
            else:
                report(drift)
        else:
            print(f"OK   {name}")

    if total_drift:
        if apply_mode:
            print(f"\nApplied fixes to {total_drift} skill(s). Verify with git diff, then commit.")
        else:
            print(f"\n{total_drift} skill(s) have tool-declaration drift. "
                  f"Run with --apply to fix.")
        return 1
    return 0


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>"); sys.exit(0)
    sys.exit(main(sys.argv))
