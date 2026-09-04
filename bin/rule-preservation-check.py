#!/usr/bin/env python3
"""Literal-preservation oracle for rule diets.

A diet (reflow, merge, relocation, compaction) of rules/*.md is easy to get
plausibly right and hard to get exactly right: the slimmed body reads well and one
qualifier -- a byte limit, a path, an env var, a NEVER line -- is gone. This tool
records the load-bearing literals BEFORE the diet and reports every one that no
longer appears anywhere in the rule set AFTER it. Moving text between files or
rewrapping it is not a loss; deleting it is.

  rule-preservation-check.py extract --rules DIR --out manifest.json
  rule-preservation-check.py verify  --rules DIR --manifest manifest.json
                                     [--allow-drop FILE] [--also PATH ...]

Literal classes, per rule file: markdown headings; banner lines carrying
CRITICAL/MUST/NEVER/ALWAYS; inline code spans and fenced code blocks; environment
variable names (ALL_CAPS_WITH_UNDERSCORES); file paths; URLs; numbers with units.
Comparison is whitespace-insensitive so a reflow never reads as a loss.

`--allow-drop FILE` is a JSON list of {"literal": ..., "reason": ...} entries, or
{"file": "<rule>.md", "reason": ...} to drop every remaining literal of a rule that
is being deleted whole (verify first WITHOUT it, move the sentences that need a home,
then record the remainder). Every entry needs a reason, because an unexplained drop
is exactly the failure this exists to catch. `--also PATH` adds files or directories
(rules/incidents/, docs/rule-reference/, skills/_shared/) in which a relocated
literal still counts as preserved.

Exit codes: 0 every literal preserved; 1 losses listed on stdout; 2 bad input.
Stdlib only. Concept from claude-forge's harness-diet preservation_check.py (MIT).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

KINDS = ("headings", "banners", "code", "env_vars", "paths", "urls", "numbers")

HEADING_RX = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
BANNER_RX = re.compile(r"\b(?:CRITICAL|MUST|NEVER|ALWAYS)\b")
DECORATION_RX = re.compile(r"^[>#\s|*-]+")
FENCE_RX = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE_RX = re.compile(r"`([^`\n]{2,})`")
ENV_RX = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
URL_RX = re.compile(r"https?://[^\s<>()\"'`]+")
PATH_RX = re.compile(r"(?<![\w/])(?:~|\.{1,2})?/?[\w.@*{}-]+(?:/[\w.@*{}-]+)*/?")
UNITS = (
    r"B|KB|MB|GB|bytes?|chars?|characters?|tokens?|lines?|min|mins|minutes?|hours?|hrs?"
    r"|days?|weeks?|months?|sec|secs|seconds?|ms|pp|x|files?|turns?|sessions?|results?"
    r"|items?|commits?|PRs?"
)
NUMBER_RX = re.compile(
    r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?:[\s_-]?%|[\s_-]?(?:" + UNITS + r")\b)"
)
TRAILING_PUNCT = ".,;:)]}'\""


def normalize(text: str) -> str:
    """Collapse all whitespace runs; the comparison unit that makes reflow free."""
    return " ".join(text.split())


def _looks_like_path(token: str) -> bool:
    if "/" not in token:
        return False
    # A dot, a trailing slash, or a root/home/relative prefix marks a path; a bare
    # `a/b/c` is usually a slash-separated word list ("stop/kill/delete") in prose.
    return "." in token or token.endswith("/") or token.startswith(("~", "/", "./", "../"))


def extract_literals(text: str) -> dict[str, list[str]]:
    """Return the load-bearing literals of one rule body, grouped by kind."""
    found: dict[str, list[str]] = {k: [] for k in KINDS}
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str) -> None:
        value = normalize(value)
        if len(value) < 2 or (kind, value) in seen:
            return
        seen.add((kind, value))
        found[kind].append(value)

    fence: list[str] | None = None
    fence_marker = ""
    for line in text.splitlines():
        m = FENCE_RX.match(line)
        if fence is None and m:
            fence, fence_marker = [], m.group(1)
            continue
        if fence is not None:
            if m and m.group(1).startswith(fence_marker[0]) and len(m.group(1)) >= len(fence_marker):
                if fence:
                    add("code", "\n".join(fence))
                fence = None
            else:
                fence.append(line)
            continue
        h = HEADING_RX.match(line)
        if h:
            add("headings", h.group(1))
        if BANNER_RX.search(line):
            add("banners", DECORATION_RX.sub("", line))
    if fence:  # unterminated fence: still a literal worth keeping
        add("code", "\n".join(fence))

    for m in INLINE_CODE_RX.finditer(text):
        add("code", m.group(1))
    for m in ENV_RX.finditer(text):
        add("env_vars", m.group(0))
    urls = []
    for m in URL_RX.finditer(text):
        urls.append(m.group(0).rstrip(TRAILING_PUNCT))
        add("urls", urls[-1])
    without_urls = URL_RX.sub(" ", text)
    for m in PATH_RX.finditer(without_urls):
        token = m.group(0).rstrip(TRAILING_PUNCT)
        if _looks_like_path(token):
            add("paths", token)
    for m in NUMBER_RX.finditer(text):
        add("numbers", m.group(0))
    return found


def rule_files(rules_dir: Path) -> list[Path]:
    """Top-level rule files only; rules/incidents/ and other subdirectories are not the ambient set."""
    return sorted(p for p in rules_dir.glob("*.md") if p.is_file())


def extract(rules_dir: Path) -> dict:
    rules = {}
    for path in rule_files(rules_dir):
        rules[path.name] = extract_literals(path.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "rules_dir": str(rules_dir),
        "literal_count": sum(len(v) for kinds in rules.values() for v in kinds.values()),
        "rules": rules,
    }


def _corpus(rules_dir: Path, also: list[Path] | None) -> str:
    texts = [p.read_text(encoding="utf-8") for p in rule_files(rules_dir)]
    for extra in also or []:
        files = sorted(extra.rglob("*.md")) if extra.is_dir() else [extra]
        texts.extend(p.read_text(encoding="utf-8") for p in files if p.is_file())
    return normalize(" \n ".join(texts))


def verify(rules_dir: Path, manifest: dict, allow: dict[str, str] | None = None,
           also: list[Path] | None = None, allow_files: dict[str, str] | None = None) -> list[dict]:
    """Return every manifest literal absent from the current rule set (and --also paths).

    `allow` silences named literals; `allow_files` silences every literal recorded
    from a named rule file. Both are keyed to their reason. Dropped literals are
    not returned; the CLI reports how many each entry covered.
    """
    corpus = _corpus(rules_dir, also)
    allow = allow or {}
    allow_files = allow_files or {}
    lost = []
    for name, kinds in manifest["rules"].items():
        for kind, values in kinds.items():
            for value in values:
                if value in corpus or value in allow or name in allow_files:
                    continue
                lost.append({"file": name, "kind": kind, "literal": value})
    return lost


def load_allow_drop(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({literal: reason}, {file: reason}); every entry must carry a reason."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("allow-drop file must be a JSON list of {literal|file, reason}")
    allow: dict[str, str] = {}
    allow_files: dict[str, str] = {}
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"allow-drop[{i}] is not an object")
        literal, file, reason = entry.get("literal"), entry.get("file"), entry.get("reason")
        key = literal if isinstance(literal, str) and literal.strip() else file
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"allow-drop[{i}] names neither a literal nor a file")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"allow-drop[{i}] ({key[:40]!r}) has no reason; every drop must say why")
        if key is literal:
            allow[normalize(literal)] = reason
        else:
            allow_files[file] = reason
    return allow, allow_files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="record the load-bearing literals of every rule")
    ex.add_argument("--rules", required=True, type=Path)
    ex.add_argument("--out", required=True, type=Path)
    ve = sub.add_parser("verify", help="report manifest literals missing from the current rule set")
    ve.add_argument("--rules", required=True, type=Path)
    ve.add_argument("--manifest", required=True, type=Path)
    ve.add_argument("--allow-drop", type=Path)
    ve.add_argument("--also", type=Path, action="append", default=[],
                    help="file or directory where a relocated literal still counts (repeatable)")
    args = ap.parse_args(argv)

    if not args.rules.is_dir():
        print(f"error: --rules {args.rules} is not a directory", file=sys.stderr)
        return 2

    if args.cmd == "extract":
        manifest = extract(args.rules)
        args.out.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"recorded {manifest['literal_count']} literals from {len(manifest['rules'])} rules -> {args.out}")
        return 0

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        allow, allow_files = load_allow_drop(args.allow_drop) if args.allow_drop else ({}, {})
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not isinstance(manifest, dict) or "rules" not in manifest:
        print("error: manifest has no 'rules' map; produce it with `extract`", file=sys.stderr)
        return 2

    strict = verify(args.rules, manifest, also=args.also)      # what is really gone
    lost = verify(args.rules, manifest, allow, args.also, allow_files)
    total = sum(len(v) for kinds in manifest["rules"].values() for v in kinds.values())
    for entry in lost:
        print(f"LOST [{entry['kind']}] {entry['file']}: {entry['literal']}")
    dropped = [e for e in strict if e not in lost]
    used_literals = {e["literal"] for e in dropped if e["literal"] in allow}
    for literal in sorted(set(allow) - used_literals):
        print(f"note: allow-drop literal never needed: {literal[:80]}", file=sys.stderr)
    for name, reason in allow_files.items():
        n = sum(1 for e in dropped if e["file"] == name and e["literal"] not in allow)
        if n == 0 and name not in manifest["rules"]:
            print(f"note: allow-drop file {name} is not in the manifest", file=sys.stderr)
        print(f"dropped {n} literals from {name}: {reason}")
    print(f"preserved {total - len(strict)}/{total} literals; {len(lost)} lost"
          + (f"; {len(dropped)} dropped with a reason" if dropped else ""))
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
