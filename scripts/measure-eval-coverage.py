#!/usr/bin/env python3
"""Measure skill eval-fixture coverage: which skills have a CI-GATING deterministic fixture.

Distinguishes three states, because "has a YAML" != "has a CI gate":
  A) deterministic  — tests/<skill>/*.yaml with a non-empty `deterministic:` block. CI-enforced.
  B) qualitative    — YAML exists but has NO deterministic block. run-skill-evals.py SKIPS these
                      silently (returns []), so they contribute ZERO enforcement.
  C) uncovered      — no fixture at all.

Usage:
    python3 scripts/measure-eval-coverage.py            # summary
    python3 scripts/measure-eval-coverage.py --json     # machine-readable
    python3 scripts/measure-eval-coverage.py --list-uncovered
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def classify():
    skills_root = REPO_ROOT / "skills"
    tests_root = REPO_ROOT / "tests"
    rows = []
    for p in sorted(skills_root.iterdir()):
        if not p.is_dir() or not (p / "SKILL.md").is_file():
            continue
        d = tests_root / p.name
        yamls = sorted(list(d.glob("*.yaml")) + list(d.glob("*.yml"))) if d.is_dir() else []
        n_assert = 0
        for y in yamls:
            try:
                doc = yaml.safe_load(y.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                doc = {}
            n_assert += len(doc.get("deterministic") or [])
        state = "deterministic" if n_assert else ("qualitative" if yamls else "uncovered")
        rows.append({
            "skill": p.name,
            "state": state,
            "fixtures": len(yamls),
            "assertions": n_assert,
            "has_scripts": any(
                x.suffix in (".py", ".sh") for x in p.rglob("*")
                if x.is_file() and "tests" not in x.parts
            ),
            "has_refs": (p / "references").is_dir() and any((p / "references").glob("*.md")),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-uncovered", action="store_true")
    args = ap.parse_args()

    rows = classify()
    det = [r for r in rows if r["state"] == "deterministic"]
    qual = [r for r in rows if r["state"] == "qualitative"]
    unc = [r for r in rows if r["state"] == "uncovered"]

    if args.json:
        json.dump({"total": len(rows), "deterministic": len(det),
                   "qualitative": len(qual), "uncovered": len(unc),
                   "skills": rows}, sys.stdout, indent=2)
        print()
        return 0

    print(f"skills with SKILL.md      : {len(rows)}")
    print(f"CI-gating (deterministic) : {len(det)}  ({len(det)/len(rows)*100:.0f}%)")
    print(f"qualitative-only (NO gate): {len(qual)}")
    print(f"uncovered (no fixture)    : {len(unc)}")
    print(f"total assertions enforced : {sum(r['assertions'] for r in det)}")

    if qual:
        print("\nWARNING: these have a fixture but NO deterministic block — CI skips them silently:")
        for r in qual:
            print(f"  {r['skill']}")

    if args.list_uncovered:
        print(f"\nuncovered ({len(unc)}):")
        for r in unc:
            surf = []
            if r["has_scripts"]:
                surf.append("scripts")
            if r["has_refs"]:
                surf.append("refs")
            print(f"  {r['skill']:34s} {'+'.join(surf) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
