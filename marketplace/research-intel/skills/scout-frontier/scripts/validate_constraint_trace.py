#!/usr/bin/env python3
"""Validate a constraint trace produced by /scout-frontier Phase 0.

Reads a YAML-like constraint trace block from stdin or a file path, and
exits non-zero if any of the FAIL conditions documented in SKILL.md
Step 0 are violated.

FAIL conditions (from SKILL.md):
- end_state must be concrete (must contain a measurable phrase: %, accuracy,
  precision, latency, recall, count, score, etc. — not abstract verbs alone)
- at least 1 friction entry must include evidence (a substring like "tested
  on", "measured", "observed", "evidence:", or a quantified number)
- abstracted_constraints must have at least 1 non-empty entry
- if 3+ friction entries exist, abstracted_constraints must contain at
  least 1 entry (else the trace is incomplete — friction wasn't reduced
  to its structural essence)

Usage:
    python validate_constraint_trace.py < trace.yaml
    python validate_constraint_trace.py path/to/trace.yaml

Exit codes:
    0 = trace passes all FAIL conditions
    1 = trace fails one or more conditions (stdout lists which)
    2 = malformed input (not parseable as YAML or missing required keys)
"""

import sys
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed; run `pip install pyyaml`", file=sys.stderr)
    sys.exit(2)


MEASURABLE_PHRASES = re.compile(
    r"\b(\d+\s*%|\d+\s*x|"
    r"accuracy|precision|recall|f1|latency|throughput|"
    r"queries?\s*per|tokens?\s*per|"
    r"under\s+\d|within\s+\d|"
    r"≥\s*\d|>=\s*\d|≤\s*\d|<=\s*\d|"
    r"\bbenchmark|hit\s*rate|p\d{2,3}\b)",
    re.IGNORECASE,
)

EVIDENCE_PHRASES = re.compile(
    r"\b(tested\s+on|measured|observed|evidence:|"
    r"in\s+(production|prod|the\s+monorepo)|"
    r"\d+\s*(seconds?|minutes?|ms|hours?|days?|files?|repos?|"
    r"calls?|queries?|symbols?|edges?|nodes?))",
    re.IGNORECASE,
)


def load_trace(source: str) -> dict:
    """Parse YAML; tolerate the constraint_trace: outer wrapper."""
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as e:
        print(f"FAIL: trace is not valid YAML: {e}")
        sys.exit(2)
    if isinstance(data, dict) and "constraint_trace" in data:
        return data["constraint_trace"]
    if isinstance(data, dict) and "end_state" in data:
        return data
    print("FAIL: trace must be a YAML mapping with end_state / friction / "
          "abstracted_constraints fields (or wrapped in constraint_trace:)")
    sys.exit(2)


def has_evidence(f) -> bool:
    """True if this friction entry cites evidence.

    Accepts both formats documented in SKILL.md Step 0:
    - legacy: friction is a string containing an evidence/measurable phrase
    - structured: friction is a dict with a non-empty 'measured' field
    """
    if isinstance(f, str):
        return bool(EVIDENCE_PHRASES.search(f))
    if isinstance(f, dict):
        measured = f.get("measured")
        if measured is None:
            return False
        if isinstance(measured, str):
            return bool(measured.strip())
        return True
    return False


def missing_id(f) -> bool:
    """True if a structured friction entry is missing its required 'id' field."""
    if isinstance(f, dict):
        return not f.get("id")
    return False


def validate(trace: dict) -> list[str]:
    failures = []

    end_state = trace.get("end_state", "")
    if not isinstance(end_state, str) or not end_state.strip():
        failures.append("end_state is empty")
    elif not MEASURABLE_PHRASES.search(end_state):
        failures.append(
            f"end_state lacks measurable phrase (no %, latency, accuracy, count, "
            f"benchmark, etc.): {end_state[:120]!r}"
        )

    friction = trace.get("friction") or []
    if not isinstance(friction, list) or len(friction) == 0:
        failures.append("friction must be a non-empty list")
    else:
        evidence_count = sum(1 for f in friction if has_evidence(f))
        if evidence_count == 0:
            failures.append(
                f"none of the {len(friction)} friction entries cite evidence "
                f"(legacy: tested on / measured / observed / quantified number; "
                f"structured: non-empty 'measured' field)"
            )
        missing_ids = sum(1 for f in friction if missing_id(f))
        if missing_ids > 0:
            failures.append(
                f"{missing_ids} structured friction entries missing required 'id' "
                f"field (use F1, F2, F3, ... per SKILL.md Step 0)"
            )

    abstracted = trace.get("abstracted_constraints") or []
    if not isinstance(abstracted, list) or len(abstracted) == 0:
        if isinstance(friction, list) and len(friction) >= 3:
            failures.append(
                "3+ friction entries with 0 abstracted constraints — "
                "trace is incomplete; reduce friction to structural essence"
            )
        else:
            failures.append("abstracted_constraints must have ≥1 non-empty entry")

    return failures


def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(
            "usage: validate_constraint_trace.py [<trace.md>]\n"
            "  Validate that a constraint trace satisfies Phase 0 FAIL conditions.\n"
            "  Reads from <trace.md> if provided, otherwise from stdin."
        )
        sys.exit(0)
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"FAIL: file not found: {path}", file=sys.stderr)
            sys.exit(2)
        source = path.read_text(encoding="utf-8")
    else:
        source = sys.stdin.read()

    if not source.strip():
        print("FAIL: empty input")
        sys.exit(2)

    trace = load_trace(source)
    failures = validate(trace)

    if failures:
        print("FAIL: constraint trace incomplete")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    print("PASS: constraint trace satisfies Phase 0 FAIL conditions")
    sys.exit(0)


if __name__ == "__main__":
    main()
