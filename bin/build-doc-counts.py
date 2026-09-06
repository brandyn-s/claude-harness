#!/usr/bin/env python3
"""Generate the inventory numbers the top-level docs quote, from the tree.

WHY
    bin/architecture-drift-check.py emptied COUNT_CONTRACTS on 2026-07-29 with the
    note "DO NOT re-add a count contract... If you need a count to be visible,
    GENERATE it rather than asserting it in hand-edited prose." The counts came back
    anyway: on 2026-09-06 README said 59 hooks and seven agents, ARCHITECTURE said 73
    hooks, 38 rules and 3 default hooks, AGENTS.md said coverage 180/192, and the
    tree said 61 / 6 / 33 / 5 / 162-173. Every one was a hand-typed number.

    This is the generator that note asked for. A doc marks a number with

        <!-- count:hooks -->53<!-- /count -->

    and this script rewrites the text between the markers from the tree. CI runs
    `--check`, which fails when any marked number differs from the computed one, so
    a file add fails the build with the fix in the message instead of failing a
    reader's trust in the README.

DEFINITIONS (the parenthetical the docs carry is the load-bearing part)
    hooks            hook SCRIPTS: hooks/*.py that are not `_`-prefixed and either
                     carry a __main__ guard or exit at module level
    hook_modules     the remaining hooks/*.py: shared libraries hooks import
    hooks_files      hooks/*.py minus `_`-prefixed -- the denominator
                     manifests/query_engine.py `coverage` uses
    hooks_wired      distinct scripts registered in settings.json, directly or
                     through the two dispatchers' GUARDS tables
    hook_registrations  number of hook entries in settings.json
    rules / rules_ambient / rules_scoped   rules/*.md, split on `paths:` frontmatter
                     exactly as hooks/rule_context_budget.py splits them
    ambient_bytes / ambient_tokens         the same module's unconditional bytes and
                     its bytes/4 proxy
    skills           skills/*/SKILL.md, excluding _shared
    agents           agents/*.md excluding README.md and TEMPLATE.md
    manifests_coverage   "manifested/total (pct%)" over skills + hooks_files + rules
    fresh_core_hooks     hook registrations install.sh writes for menu option 1
    dispatcher_bash / dispatcher_write    GUARDS rows in the two dispatchers
    source_files     tracked files outside marketplace/  (git ls-files)
    marketplace_files    tracked files under marketplace/

USAGE
    python3 bin/build-doc-counts.py            # rewrite markers in place
    python3 bin/build-doc-counts.py --check    # exit 1 on any stale marker (CI)
    python3 bin/build-doc-counts.py --print    # show every computed value
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = ["README.md", "ARCHITECTURE.md", "AGENTS.md", "hooks/README.md", "profiles/README.md"]
MARKER_RE = re.compile(r"(<!--\s*count:([a-z_]+)\s*-->)(.*?)(<!--\s*/count\s*-->)", re.DOTALL)

sys.path.insert(0, str(REPO / "hooks"))


def _hook_files() -> list[Path]:
    return sorted(p for p in (REPO / "hooks").glob("*.py") if p.name != "__init__.py" and not p.name.startswith("_"))


def _is_script(p: Path) -> bool:
    text = p.read_text(encoding="utf-8", errors="replace")
    return bool(re.search(r"__name__\s*==\s*['\"]__main__['\"]", text)) or bool(re.search(r"^sys\.exit\(", text, re.M))


def _guards(filename: str) -> list[str]:
    text = (REPO / "hooks" / filename).read_text(encoding="utf-8")
    block = text[text.index("GUARDS = ["):]
    block = block[:block.index("\n]")]
    return re.findall(r'\(\s*"[^"]+",\s*"([^"]+\.py)"', block)


def _settings_scripts(settings: dict) -> tuple[set[str], int]:
    scripts, n = set(), 0
    for groups in settings.get("hooks", {}).values():
        for g in groups:
            for hk in g.get("hooks", []):
                n += 1
                for m in re.findall(r"([\w\-]+\.(?:py|sh))", (hk.get("command") or "") + " " + " ".join(hk.get("args") or [])):
                    scripts.add(m)
    return scripts, n


def _fresh_core_hooks() -> int:
    text = (REPO / "install.sh").read_text(encoding="utf-8")
    i = text.index("1) hooks=(")
    j = text.index("hook_configs=(", i)
    k = text.index(")", j)
    return len(re.findall(r"'[^']+'", text[j:k]))


def _git_files(pattern: str | None = None, exclude_prefix: str | None = None) -> int:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"] + ([pattern] if pattern else []),
                         capture_output=True, text=True, timeout=30)
    files = [f for f in out.stdout.splitlines() if f.strip()]
    if exclude_prefix:
        files = [f for f in files if not f.startswith(exclude_prefix)]
    return len(files)


def compute() -> dict[str, str]:
    import rule_context_budget as rcb  # noqa: E402 -- resolves via the sys.path insert above

    hook_files = _hook_files()
    scripts = [p for p in hook_files if _is_script(p)]
    modules = [p for p in hook_files if not _is_script(p)]
    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    direct, registrations = _settings_scripts(settings)
    wired = set(direct) | set(_guards("bash-pretooluse-dispatcher.py")) | set(_guards("write-edit-dispatcher.py"))
    wired = {w for w in wired if w.endswith(".py")}

    rules = sorted((REPO / "rules").glob("*.md"))
    ambient = rcb.unconditional_rule_files(REPO / "rules")
    ambient_bytes = rcb.unconditional_rule_bytes(REPO / "rules")
    skills = sorted(p for p in (REPO / "skills").glob("*/SKILL.md") if p.parent.name != "_shared")
    agents = [p for p in (REPO / "agents").glob("*.md") if p.name not in ("README.md", "TEMPLATE.md")]

    manifested = (len(list((REPO / "skills").glob("*/manifest.yaml")))
                  + len(list((REPO / "hooks" / "manifests").glob("*.yaml")))
                  + len(list((REPO / "rules" / "manifests").glob("*.yaml"))))
    total = len(skills) + len(hook_files) + len(rules)

    return {
        "hooks": str(len(scripts)),
        "hook_modules": str(len(modules)),
        "hooks_files": str(len(hook_files)),
        "hooks_wired": str(len(wired)),
        "hook_registrations": str(registrations),
        "rules": str(len(rules)),
        "rules_ambient": str(len(ambient)),
        "rules_scoped": str(len(rules) - len(ambient)),
        "ambient_bytes": f"{ambient_bytes:,}",
        "ambient_tokens": f"{rcb.estimate_tokens(ambient_bytes):,}",
        "skills": str(len(skills)),
        "agents": str(len(agents)),
        "manifests_coverage": f"{manifested}/{total} ({100 * manifested // total}%)",
        "fresh_core_hooks": str(_fresh_core_hooks()),
        "dispatcher_bash": str(len(_guards("bash-pretooluse-dispatcher.py"))),
        "dispatcher_write": str(len(_guards("write-edit-dispatcher.py"))),
        "source_files": f"{_git_files(exclude_prefix='marketplace/'):,}",
        "marketplace_files": f"{_git_files('marketplace/'):,}",
    }


def apply(counts: dict[str, str], check: bool) -> int:
    stale = []
    seen = 0
    for rel in DOCS:
        path = REPO / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")

        def repl(m):
            nonlocal seen
            key, current = m.group(2), m.group(3)
            seen += 1
            if key not in counts:
                stale.append(f"{rel}: unknown count key `{key}`")
                return m.group(0)
            want = counts[key]
            if current != want:
                stale.append(f"{rel}: count:{key} says {current!r}, tree says {want!r}")
            return f"{m.group(1)}{want}{m.group(4)}"

        new = MARKER_RE.sub(repl, text)
        if not check and new != text:
            path.write_text(new, encoding="utf-8")
    if seen == 0:
        print("build-doc-counts: no count markers found -- the gate would be vacuous", file=sys.stderr)
        return 1
    if check and stale:
        print("build-doc-counts --check: stale numbers (run `python3 bin/build-doc-counts.py` to regenerate):", file=sys.stderr)
        for s in stale:
            print(f"  {s}", file=sys.stderr)
        return 1
    if not check and stale:
        print(f"build-doc-counts: regenerated {len(stale)} number(s) across {seen} marker(s)")
    elif check:
        print(f"build-doc-counts --check: {seen} marker(s) match the tree")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any marked number is stale")
    ap.add_argument("--print", action="store_true", help="print every computed value")
    args = ap.parse_args()
    counts = compute()
    if args.print:
        for k, v in counts.items():
            print(f"{k:22s} {v}")
        return 0
    return apply(counts, args.check)


if __name__ == "__main__":
    sys.exit(main())
