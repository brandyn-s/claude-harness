#!/usr/bin/env python3
"""Parse rules/**/*.md for snake_case FORBIDDEN identifiers and emit
keyword signatures.

Closes part of the coverage gap surfaced by audit-rules: ~16 of ~31
ambient rules carry `FORBIDDEN: <snake_case_identifier>` blocks that
encode the anti-pattern in identifier form. This script extracts them
into a YAML registry that:

  1. Tells operators which rules have machine-parseable FORBIDDEN
     blocks (vs prose-only forbidden statements that need bespoke
     detector logic).
  2. Gives each rule's GAP finding (in
     AUDIT-TRACKERS/rule-violations.findings.yaml) a starting keyword
     signature, so detector-authoring has a clear seed.

The output is NOT itself a detector — auto-generating detectors from
keyword sets produces too many false positives (the keywords are
generic English words). But the signature is a useful seed: an
operator authoring a real detector for, e.g.,
``pip_install_upgrade_all_outdated`` can start with
``["pip", "install", "upgrade", "all", "outdated"]`` and refine.

Output format:

    rules:
      - name: platform-constraints
        path: rules/platform-constraints.md
        forbidden_signatures:
          - identifier: pip_install_upgrade_all_outdated
            keywords: [pip, install, upgrade, all, outdated]
            line: 247
          - identifier: subprocess_run_text_true_for_external_apis
            keywords: [subprocess, run, text, true, external, apis]
            line: 251

Usage:
  extract_forbidden_signatures.py
  extract_forbidden_signatures.py --json
  extract_forbidden_signatures.py --out skills/audit-rules/forbidden-signatures.yaml
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Common-word filter — keywords this generic are not useful detector
# signals on their own. Mirrors the noise filter in
# lifecycle_check.py's rule-name extractor.
COMMON_WORDS = frozenset({
    "to", "of", "for", "with", "the", "and", "or", "in", "on",
    "at", "by", "from", "as", "is", "be", "a", "an",
    "all", "no", "not", "do", "any", "this", "that", "these",
})

# Snake_case identifier after FORBIDDEN: — only this shape is
# auto-parseable. Prose-style FORBIDDEN blocks are NOT extracted.
FORBIDDEN_LINE = re.compile(
    r"^FORBIDDEN:\s+([a-z][a-z0-9_]+)\s*$",
    re.MULTILINE,
)


def extract_signatures_from_file(path: Path) -> list[dict]:
    """Return [{identifier, keywords, line}, ...] for one rule file."""
    text = path.read_text(encoding="utf-8")
    sigs: list[dict] = []
    for m in FORBIDDEN_LINE.finditer(text):
        identifier = m.group(1)
        line_no = text[:m.start()].count("\n") + 1
        # Split snake_case into keywords, drop common words.
        raw_keywords = identifier.split("_")
        keywords = [k for k in raw_keywords if k not in COMMON_WORDS]
        sigs.append({
            "identifier": identifier,
            "keywords": keywords,
            "line": line_no,
        })
    return sigs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--rules-dir", type=Path, default=None,
        help="path to rules/ directory (default: REPO/rules)",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="emit JSON instead of YAML",
    )
    ap.add_argument(
        "--out", type=Path, default=None,
        help="write output to this path (default: stdout)",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    rules_dir = args.rules_dir or (repo_root / "rules")
    if not rules_dir.is_dir():
        print(f"error: rules dir not found: {rules_dir}", file=sys.stderr)
        return 2

    out_rules: list[dict] = []
    total_sigs = 0
    # Context-budget pruning moves incident detail out of ambient rules/*.md
    # into rules/incidents/*.md. Those references remain part of the detector-
    # authoring corpus, so scan recursively rather than silently dropping their
    # machine-readable seeds.
    for rule_file in sorted(rules_dir.rglob("*.md")):
        sigs = extract_signatures_from_file(rule_file)
        if not sigs:
            continue
        # Use relative_to repo_root when the rule file is inside the
        # repo; for tests passing --rules-dir outside the repo, fall
        # back to the absolute path. This lets the script work in both
        # production and unit-test fixtures.
        try:
            rel_path = str(rule_file.relative_to(repo_root))
        except ValueError:
            rel_path = str(rule_file)
        out_rules.append({
            "name": rule_file.stem,
            "path": rel_path,
            "forbidden_signatures": sigs,
        })
        total_sigs += len(sigs)

    if args.json:
        text = json.dumps({"rules": out_rules}, indent=2)
    else:
        text = _to_yaml({"rules": out_rules})

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(
            f"wrote {len(out_rules)} rules with {total_sigs} "
            f"FORBIDDEN signatures → {args.out}",
            file=sys.stderr,
        )
    else:
        print(text)

    return 0


def _to_yaml(data: dict) -> str:
    """Minimal YAML emitter for the signatures schema. Avoids PyYAML
    dep to match the rest of audit-rules' minimalist approach."""
    lines = ["rules:"]
    for rule in data.get("rules", []):
        lines.append(f"  - name: {rule['name']}")
        lines.append(f"    path: {rule['path']}")
        lines.append(f"    forbidden_signatures:")
        for sig in rule.get("forbidden_signatures", []):
            lines.append(f"      - identifier: {sig['identifier']}")
            keywords_str = ", ".join(sig["keywords"])
            lines.append(f"        keywords: [{keywords_str}]")
            lines.append(f"        line: {sig['line']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
