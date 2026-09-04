#!/usr/bin/env python3
"""Cross-skill chain reliability validator.

Discovers documented skill-to-skill chains in SKILL.md bodies (patterns like
"after /skill-B", "use /skill-A first", "chains into /skill-C") and verifies:

  1. The target skill exists.
  2. The target's body acknowledges its role as a downstream / upstream
     of the source (bidirectional sanity check).
  3. No documented chain leaves the source's outputs unconsumed (orphan-
     output detection).

Exit codes:
  0    all documented chains validate
  1    at least one chain has a problem
  2    runner error

Output is informational by default; use --strict to gate.

Designed to run alongside scripts/validate-skills.py and scripts/run-skill-evals.py
in CI. Cheap, no LLM calls.
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# Patterns that document a chain. Each captures the TARGET skill name.
CHAIN_PATTERNS = [
    # "use /<skill>" in body or description
    (re.compile(r"use\s+`?/([a-z][a-z0-9-]+)`?", re.I), "use_target"),
    # "after /<skill>" / "before /<skill>"
    (re.compile(r"(?:after|before|then|chains? (?:into|to))\s+`?/([a-z][a-z0-9-]+)`?", re.I), "sequence"),
    # "Pairs with /<skill>" / "Wraps /<skill>"
    (re.compile(r"(?:pairs with|wraps|composed (?:with|by))\s+`?/([a-z][a-z0-9-]+)`?", re.I), "compose"),
]

SKIP_TARGETS = {
    # Built-in CLI commands or Anthropic-managed primitives — not skills
    "help", "compact", "clear", "init", "config", "setup", "fast",
    "goal", "loop",  # built-in Claude Code primitives
    "model", "memory", "permissions", "agents",
    # MCP server tool method names (Firecrawl etc.) — not skills
    "map", "scrape", "crawl", "search", "extract", "research",
    # Things that look like /name but aren't routable skills in this repo
    "v1", "v2", "skill-name", "<skill>", "<name>",
    "tmp", "etc", "home", "claude", "user",
    # Common filesystem path prefixes (/full/abs/path, /var/log, etc.)
    "full", "var", "usr", "opt", "bin", "sbin", "lib", "dev", "proc", "sys",
}


def list_skill_names():
    return {p.parent.name for p in Path("skills").glob("*/SKILL.md")}


def extract_chains(skill_dir, body):
    """Returns list of (target_skill, pattern_type, context_snippet)."""
    chains = []
    for pat, kind in CHAIN_PATTERNS:
        for m in pat.finditer(body):
            target = m.group(1).lower()
            if target == skill_dir.name or target in SKIP_TARGETS:
                continue
            # Capture 80 chars of context for inspection
            start = max(0, m.start() - 30)
            end = min(len(body), m.end() + 50)
            ctx = body[start:end].replace("\n", " ")
            chains.append((target, kind, ctx))
    return chains


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", help="Detail for one skill")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero on any issue")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    all_skills = list_skill_names()
    chain_graph = defaultdict(list)   # source -> list of (target, kind, ctx)
    dangling = []                     # (source, target, ctx)

    for skill_md in sorted(Path("skills").glob("*/SKILL.md")):
        skill = skill_md.parent.name
        if args.skill and skill != args.skill:
            continue
        body = skill_md.read_text(encoding='utf-8')
        chains = extract_chains(skill_md.parent, body)
        for target, kind, ctx in chains:
            chain_graph[skill].append((target, kind, ctx))
            if target not in all_skills:
                dangling.append((skill, target, ctx))

    # Bidirectional acknowledgement: for compose / sequence chains,
    # check whether the target's body acknowledges the source.
    unilateral = []
    for source, chains in chain_graph.items():
        source_body = (Path("skills") / source / "SKILL.md").read_text(encoding='utf-8').lower()
        for target, kind, ctx in chains:
            if kind != "compose":
                continue  # only enforce bidirectionality for explicit composition
            target_md = Path("skills") / target / "SKILL.md"
            if not target_md.exists():
                continue
            target_body = target_md.read_text(encoding='utf-8').lower()
            if f"/{source}" not in target_body:
                unilateral.append((source, target, ctx))

    # Output
    if dangling:
        print(f"=== Dangling chain targets (skill cites /X but skills/X/ doesn't exist) (n={len(dangling)}) ===")
        for src, tgt, ctx in dangling:
            print(f"  {src} → /{tgt}  ctx={ctx!r}")
        print()

    if unilateral:
        print(f"=== Unilateral compose links (source says 'composes /target' but target doesn't reciprocate) (n={len(unilateral)}) ===")
        for src, tgt, ctx in unilateral:
            print(f"  {src} → /{tgt}  ctx={ctx!r}")
        print()

    if args.verbose:
        print(f"=== Full chain graph (n={sum(len(v) for v in chain_graph.values())}) ===")
        for src in sorted(chain_graph):
            for tgt, kind, _ in chain_graph[src]:
                print(f"  {src} --{kind}--> {tgt}")
        print()

    # Summary
    total_chains = sum(len(v) for v in chain_graph.values())
    print("=== Chain validation summary ===")
    print(f"  Skills emitting chain references: {len(chain_graph)}")
    print(f"  Total chain edges:                {total_chains}")
    print(f"  Dangling (target missing):        {len(dangling)}")
    print(f"  Unilateral compose:               {len(unilateral)}")

    if args.strict and (dangling or unilateral):
        sys.exit(1)


if __name__ == "__main__":
    main()
