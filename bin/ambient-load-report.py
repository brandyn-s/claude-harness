#!/usr/bin/env python3
"""Report the REAL per-session ambient rule load, not just the budgeted subset.

Why this exists
---------------
`hooks/rule_context_budget.py` gates on UNCONDITIONAL bytes and treats any rule
carrying `paths:` frontmatter as scoped, therefore free. That is the right idea --
a rule that only loads when you touch a Terraform file should not cost a Python
session anything.

But the exemption is granted on the PRESENCE of `paths:`, never on its BREADTH. A
rule scoped to 27 patterns covering `**/*.py`, `**/*.js`, `**/*.ts`, `**/*.go`,
`**/*.rs`, `**/*.yaml`, `**/*.json` and `**/tests/**` matches essentially every
source file in every language: it leaves the budget without leaving the session.

So the budget can read comfortably while the real context cost is materially
higher. This script prints both numbers and the split between them. It does NOT
change any gate -- where to draw "too broad" is a policy call for the maintainer,
and a measurement that quietly re-gates is worse than one that just tells you.

Usage
-----
    python3 bin/ambient-load-report.py [--root .] [--json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "hooks"))
from rule_context_budget import estimate_tokens

# Extensions common enough that scoping to them is not scoping. Deliberately a
# LIST rather than a cleverness: a maintainer can see exactly what is counted and
# argue with it.
MAINSTREAM_EXT = {
    "py", "pyi", "js", "jsx", "ts", "tsx", "go", "rs", "java", "kt", "cs", "rb",
    "php", "swift", "sh", "ps1", "yaml", "yml", "json", "toml", "tf", "hcl", "sql",
    "c", "cc", "cpp", "h", "hpp", "m", "mm", "scala", "ex", "exs", "lua", "pl",
}
# Directory patterns that appear in nearly every repository.
UBIQUITOUS_DIR = {"tests", "test", "spec", "__tests__", "src", "lib", "docs"}

FM = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def read_paths(path: str) -> list[str] | None:
    """Return the rule's `paths:` list, or None when it has no frontmatter scope."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None
    m = FM.match(text)
    if not m:
        return None
    body = m.group(1)
    # Deliberately not a YAML parse: these files are read by several tools and a
    # hard dependency here would be a new failure mode for a reporting script.
    block = re.search(r"^paths:\s*(.*?)(?=^[A-Za-z@][A-Za-z0-9_-]*:|\Z)",
                      body, re.DOTALL | re.MULTILINE)
    if not block:
        return None
    raw = block.group(1)
    inline = re.findall(r"['\"]?([^'\",\[\]\s][^'\",\[\]]*)['\"]?", raw.replace("\n", " "))
    return [p.strip() for p in inline if p.strip() and not p.strip().startswith("#")]


def is_universal(patterns: list[str]) -> tuple[bool, str]:
    """Is this scope broad enough that it loads in most sessions?"""
    exts, dirs = set(), set()
    for p in patterns:
        m = re.search(r"\*\.([A-Za-z0-9]+)$", p)
        if m:
            exts.add(m.group(1).lower())
        for d in re.findall(r"\*\*/([A-Za-z0-9_\-]+)/\*\*", p):
            dirs.add(d.lower())
    hit_ext = exts & MAINSTREAM_EXT
    hit_dir = dirs & UBIQUITOUS_DIR
    if len(hit_ext) >= 3:
        return True, f"matches {len(hit_ext)} mainstream source extensions"
    if hit_dir:
        return True, f"matches ubiquitous directory pattern(s): {sorted(hit_dir)}"
    return False, "scope is genuinely narrow"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rules_dir = os.path.join(args.root, "rules")
    if not os.path.isdir(rules_dir):
        return int(bool(sys.stderr.write(f"no rules/ under {args.root}\n")) or 1)

    unconditional, universal, narrow = [], [], []
    for f in sorted(glob.glob(os.path.join(rules_dir, "*.md"))):
        size = os.path.getsize(f)
        paths = read_paths(f)
        if not paths:
            unconditional.append((size, os.path.basename(f), ""))
            continue
        broad, why = is_universal(paths)
        (universal if broad else narrow).append((size, os.path.basename(f), why))

    u = sum(s for s, _, _ in unconditional)
    v = sum(s for s, _, _ in universal)
    n = sum(s for s, _, _ in narrow)

    if args.json:
        print(json.dumps({
            "unconditional_bytes": u, "universal_scoped_bytes": v,
            "narrow_scoped_bytes": n,
            "budgeted_bytes": u, "effective_coding_session_bytes": u + v,
            "understatement_pct": round(100 * v / (u + v), 1) if u + v else 0,
            "universal_scoped_files": [f for _, f, _ in sorted(universal, reverse=True)],
        }, indent=2))
        return 0

    def band(b: int) -> str:
        return f"{b:>9,} B  ~{estimate_tokens(b):>7,} tok"

    print("Ambient rule load\n" + "=" * 58)
    print(f"  unconditional (what the budget gates on) {band(u)}")
    print(f"+ path-scoped but UNIVERSAL                {band(v)}")
    print("  " + "-" * 56)
    print(f"= effective load in a coding session       {band(u + v)}")
    print(f"  path-scoped and genuinely narrow         {band(n)}   (correctly free)")
    if u + v:
        print(f"\n  The gated number understates the effective load by "
              f"{100 * v / (u + v):.0f}%.")

    if universal:
        print("\nScoped, but broadly enough to load in most sessions:")
        for size, name, why in sorted(universal, reverse=True):
            print(f"  {size:>7,} B  {name:<34s} {why}")
    if narrow:
        print("\nScoped narrowly (exemption doing its job):")
        for size, name, why in sorted(narrow, reverse=True):
            print(f"  {size:>7,} B  {name:<34s} {why}")

    print("\nThis script reports; it does not gate. Tightening the exemption is a "
          "policy\nchoice: see manifests/ambient-budget.json, whose ceiling is "
          "derived from a\nledger, so any change is recorded with its byte count "
          "and reason.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
