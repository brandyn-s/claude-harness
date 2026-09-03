#!/usr/bin/env python3
"""Generate skills/README.md from each skill's SKILL.md frontmatter.

The index header has claimed to be generated since the initial export, but no
generator shipped and one row went stale (review 2026-09-03). This is the
generator; bin/test_build_skills_index.py pins the committed file to its output.

Usage:
    python3 bin/build-skills-index.py            # rewrite skills/README.md
    python3 bin/build-skills-index.py --check    # exit 1 if the file is stale
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DESCRIPTION_LIMIT = 162
SUBDIRS = ("references", "scripts", "tests")

HEADER = """# Skills index

{count} skills. **Generated from each `SKILL.md` frontmatter -- do not
hand-edit; regenerate instead.**

A skill is a procedure Claude invokes by matching your request against the
`description` in its frontmatter, so that description *is* the routing logic.
Bigger skills push detail into `references/` and deterministic helpers into
`scripts/`, so `SKILL.md` stays scannable.

| Skill | What it does | Has |
|---|---|---|
"""

FOOTER = """
## Note on cross-references

This is a curated subset of a larger private configuration. Some skills and
incident write-ups reference a skill that is not included here (it operated a
specific internal system). The lesson in those write-ups stands on its own;
the `/name` cross-reference will not resolve.
"""


def _frontmatter(text: str) -> str:
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    return match.group(1) if match else ""


def _description(frontmatter: str) -> str:
    """The `description:` scalar, unquoted; block scalars are joined with spaces."""
    match = re.search(r"^description:[ \t]*(.*)$", frontmatter, re.MULTILINE)
    if not match:
        return ""
    value = match.group(1).strip()
    if value in (">", "|", ">-", "|-"):
        lines = []
        for line in frontmatter[match.end():].splitlines()[1:]:
            if line.startswith((" ", "\t")):
                lines.append(line.strip())
            else:
                break
        return " ".join(lines)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
        if match.group(0).startswith("description: '"):
            value = value.replace("''", "'")
    return value


def _first_sentence(text: str) -> str:
    """The index shows one sentence per skill: up to the first `. ` boundary."""
    cut = text.find(". ")
    return text[: cut + 1] if cut != -1 else text


def _truncate(text: str) -> str:
    text = _first_sentence(text)
    if len(text) <= DESCRIPTION_LIMIT:
        return text
    return text[:DESCRIPTION_LIMIT].rstrip() + "..."


def render(root: Path) -> str:
    skills_dir = root / "skills"
    rows = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        name = skill_md.parent.name
        if name == "_shared":
            continue
        description = _truncate(_description(_frontmatter(skill_md.read_text(encoding="utf-8"))))
        has = [sub for sub in SUBDIRS if (skill_md.parent / sub).is_dir()]
        rows.append(f"| [`{name}`](./{name}/SKILL.md) | {description} | {', '.join(has) or '-'} |")
    return HEADER.format(count=len(rows)) + "\n".join(rows) + "\n" + FOOTER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if skills/README.md is stale")
    args = parser.parse_args(argv)
    target = REPO / "skills" / "README.md"
    expected = render(REPO)
    if args.check:
        if target.read_text(encoding="utf-8") != expected:
            print("skills/README.md is stale; run bin/build-skills-index.py", file=sys.stderr)
            return 1
        print("skills/README.md is current")
        return 0
    target.write_text(expected, encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
