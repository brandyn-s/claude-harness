"""Keyword scoring with stance check.

Reads a fixture.yaml (rubric definition) and a directory of persona
output JSON files, applies keyword matching with negation-context
detection, writes per-persona keyword scores back into each JSON.

Per F6 finding: keyword scoring alone has high false-positive rate.
Always pair with score_llm_judge.py and report Cohen's kappa via
analyze.py.

Usage:
    python3 score_keyword.py <run-dir> [--fixture path]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REJECT_PATTERNS = [
    "should not", "avoid ", "not the issue", "ignore ", "rule out",
    "is not the cause", "isn't the cause", "don't bother",
]


def load_fixture(path: Path) -> dict:
    """Load fixture.yaml. Falls back to manual parse if PyYAML missing."""
    if not path.exists():
        sys.exit(
            f"Fixture file not found: {path}\n"
            f"  Pass --fixture PATH or place fixture.yaml inside <run-dir>/."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        sys.exit(f"Could not read fixture {path}: {e}")
    try:
        import yaml
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as e:
            sys.exit(f"Fixture {path} is not valid YAML: {e}")
    except ImportError:
        # Manual parse — only handles simple structure of rubric.yaml
        sys.exit("PyYAML required for keyword scoring. pip install pyyaml")


def find_with_stance(text_lower: str, keywords: list[str]) -> str:
    """Return 'endorse', 'reject', or 'absent'."""
    for kw in keywords:
        kw_low = kw.lower()
        if kw_low not in text_lower:
            continue
        idx = text_lower.find(kw_low)
        window = text_lower[max(0, idx - 30):idx]
        if any(rp in window for rp in REJECT_PATTERNS):
            return "reject"
        return "endorse"
    return "absent"


def score(text: str, fixture: dict) -> dict:
    text_lower = text.lower()
    rcs = fixture.get("root_causes", {})
    rc_results: dict[str, str] = {}
    for rc_id, rc_def in rcs.items():
        keywords = rc_def.get("keywords", [])
        rc_results[rc_id] = find_with_stance(text_lower, keywords)

    fls = fixture.get("false_leads", {})
    fl_results: dict[str, str] = {}
    for fl_id, fl_def in fls.items():
        keywords = fl_def.get("keywords", [])
        fl_results[fl_id] = find_with_stance(text_lower, keywords)

    n_rc_endorsed = sum(1 for s in rc_results.values() if s == "endorse")
    n_fl_endorsed = sum(1 for s in fl_results.values() if s == "endorse")
    return {
        "rcs": rc_results,
        "fls": fl_results,
        "n_rc_endorsed": n_rc_endorsed,
        "n_fl_endorsed": n_fl_endorsed,
        "all_rc_endorsed": all(s == "endorse" for s in rc_results.values())
                            if rc_results else False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--fixture", default=None,
                     help="fixture.yaml path (defaults to run_dir/fixture.yaml)")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        sys.exit(
            f"Run directory not found: {run_dir}\n"
            f"  Pass an existing run directory (e.g., one produced by "
            f"dispatch.py rubric)."
        )
    fixture_path = Path(args.fixture) if args.fixture else run_dir / "fixture.yaml"
    fixture = load_fixture(fixture_path)
    persona_dir = run_dir / "results-by-persona"
    if not persona_dir.exists():
        sys.exit(f"No results-by-persona/ in {run_dir}")

    n_scored = 0
    for p in sorted(persona_dir.glob("persona_*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"error: malformed persona JSON in {p}: {e}", file=sys.stderr)
            print("  hint: delete or regenerate the corrupt file (re-run "
                  "dispatch.py) before re-running score_keyword.py.",
                  file=sys.stderr)
            sys.exit(2)
        # rec might be the dispatch dict directly OR a wrapper {dispatch: ...}
        dispatch = rec.get("dispatch") or rec
        if not dispatch.get("ok"):
            continue
        text = dispatch.get("text", "")
        rec.setdefault("scoring", {})
        rec["scoring"]["keyword"] = score(text, fixture)
        p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        n_scored += 1

    print(f"Keyword-scored {n_scored} persona outputs in {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
