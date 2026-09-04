#!/usr/bin/env python3
"""variant-analysis oracle / verifier — components 2 + 8 of the harness framework.

Runs the variant-hunt verification suite deterministically (no LLM in the loop)
and emits structured per-pattern verdicts. This is the Tier-1+2 oracle that
replaces prose-driven "trust the hunter" verification.

Stratification:
  pattern_parse        — Tier 1 (regex/Semgrep syntax check; mechanical)
  exact_baseline       — Tier 1 (Level-0 pattern must match the seed bug)
  variant_run          — Tier 2 (sandbox executor: grep/semgrep over target tree)
  fp_rate_gate         — Tier 2 (sampled AST/context check, optional)
  semgrep_validate     — Tier 2 (`semgrep --validate <rule>` when available)

What this script does NOT do (intentionally):
  exploitability triage — requires human reasoning + reachability analysis
  fix recommendations   — separate skill (/pr-fix)

Usage:
    verify_variants.py <hunt-spec.json> [--target DIR] [--ndjson PATH] [--strict] [--json]

hunt-spec.json shape:
    {
      "hunt_id": "sql-injection-2026-05-30",
      "root_cause": "Untrusted input reaches cursor.execute via string concat",
      "seed_file": "api/users.py",
      "seed_line": 42,
      "patterns": [
        {"level": 0, "kind": "rg", "pattern": "exact-vulnerable-string", "sampled_fp": 0},
        {"level": 1, "kind": "rg", "pattern": "regex-with-metavars", "sampled_fp": 1},
        {"level": 2, "kind": "semgrep", "rule_path": "resources/semgrep/python.yaml", "sampled_fp": 0}
      ],
      "fp_rate_cap": 0.5
    }

Each pattern's "sampled_fp" is the count of false positives found when
sampling that pattern's matches (Step 5 triage). Under --strict, a pattern
with matches but no "sampled_fp" makes the fp_rate_gate report UNVERIFIED
and the run exit 1.

Exit codes:
    0   all required checks passed
    1   one or more required checks failed (e.g., FP-rate gate, baseline miss)
    2   runner error (bad args, missing tool, malformed spec)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def emit(record, ndjson_handle):
    if ndjson_handle is None:
        return
    ndjson_handle.write(json.dumps(record) + "\n")


def _now():
    return os.environ.get("VARIANT_RUN_ID") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_pattern_parse(pattern_spec, ndjson):
    """Tier 1: does the pattern parse as a regex (rg) or load as a Semgrep rule?"""
    kind = pattern_spec.get("kind", "rg")
    pat = pattern_spec.get("pattern") or pattern_spec.get("rule_path", "")
    record = {"run_id": _now(), "check": "pattern_parse", "kind": kind, "pattern_id": pattern_spec.get("level", "?")}
    if kind == "rg":
        try:
            re.compile(pat)
            record["passed"] = True
        except re.error as e:
            record["passed"] = False
            record["reason"] = f"regex compile error: {e}"
    elif kind == "semgrep":
        rule_path = Path(pat)
        if not rule_path.is_file():
            record["passed"] = False
            record["reason"] = f"semgrep rule not found: {rule_path}"
        else:
            try:
                r = subprocess.run(
                    ["semgrep", "--validate", "--config", str(rule_path)],
                    capture_output=True, text=True, timeout=30,
                )
                record["passed"] = r.returncode == 0
                if r.returncode != 0:
                    record["reason"] = r.stderr.strip()[:500]
            except FileNotFoundError:
                record["passed"] = False
                record["reason"] = "semgrep-not-installed; validate skipped"
                record["verdict"] = "SKIPPED"
            except subprocess.TimeoutExpired:
                record["passed"] = False
                record["reason"] = "semgrep --validate timed out"
    else:
        record["passed"] = False
        record["reason"] = f"unknown kind: {kind}"
    emit(record, ndjson)
    return record["passed"]


def run_pattern(pattern_spec, target_dir, ndjson):
    """Tier 2: run the pattern against the target tree, collect matches."""
    kind = pattern_spec.get("kind", "rg")
    record = {"run_id": _now(), "check": "variant_run", "kind": kind, "pattern_id": pattern_spec.get("level", "?")}
    matches = []
    try:
        if kind == "rg":
            if shutil.which("rg"):
                cmd = ["rg", "-n", "--no-heading", pattern_spec["pattern"], str(target_dir)]
            else:
                # ripgrep binary not on PATH (e.g. hosts where `rg` is only a
                # shell function); grep -rnE emits the same file:line:content
                # shape and the same 1-on-zero-matches exit convention.
                cmd = ["grep", "-rnE", pattern_spec["pattern"], str(target_dir)]
                record["fallback"] = "grep"
            r = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=60,
            )
            # rg/grep return 1 when zero matches; treat as empty, not error
            if r.returncode not in (0, 1):
                record["passed"] = False
                record["reason"] = f"rg exit {r.returncode}: {r.stderr.strip()[:200]}"
                emit(record, ndjson)
                return record, []
            for line in r.stdout.splitlines():
                parts = line.split(":", 2)
                if len(parts) >= 2:
                    matches.append({"file": parts[0], "line": parts[1], "snippet": parts[2] if len(parts) > 2 else ""})
        elif kind == "semgrep":
            r = subprocess.run(
                ["semgrep", "--config", pattern_spec["rule_path"], "--json", str(target_dir)],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode not in (0, 1):
                record["passed"] = False
                record["reason"] = f"semgrep exit {r.returncode}: {r.stderr.strip()[:200]}"
                emit(record, ndjson)
                return record, []
            try:
                payload = json.loads(r.stdout)
                for m in payload.get("results", []):
                    matches.append({
                        "file": m.get("path"),
                        "line": m.get("start", {}).get("line"),
                        "snippet": m.get("extra", {}).get("lines", "")[:200],
                    })
            except json.JSONDecodeError:
                record["passed"] = False
                record["reason"] = "semgrep returned non-JSON output"
                emit(record, ndjson)
                return record, []
    except FileNotFoundError as e:
        record["passed"] = False
        record["reason"] = f"tool not installed: {e.filename}"
        emit(record, ndjson)
        return record, []
    except subprocess.TimeoutExpired:
        record["passed"] = False
        record["reason"] = "pattern run timed out"
        emit(record, ndjson)
        return record, []

    record["passed"] = True
    record["n_matches"] = len(matches)
    emit(record, ndjson)
    return record, matches


def check_baseline(seed_file, seed_line, matches, ndjson):
    """Tier 1: the Level-0 pattern MUST match the seed bug location."""
    record = {"run_id": _now(), "check": "exact_baseline", "seed_file": seed_file, "seed_line": seed_line}
    if not seed_file:
        record["passed"] = True
        record["reason"] = "no seed declared; baseline check skipped"
        emit(record, ndjson)
        return True
    hit = any(
        m.get("file", "").endswith(seed_file) and str(m.get("line")) == str(seed_line)
        for m in matches
    )
    record["passed"] = hit
    if not hit:
        record["reason"] = f"seed {seed_file}:{seed_line} not in {len(matches)} match(es)"
    emit(record, ndjson)
    return hit


def check_fp_gate(n_matches, fp_rate_cap, sampled_fp, ndjson):
    """Tier 2: false-positive gate. If sampled_fp not provided, gate reports UNVERIFIED and returns False under --strict."""
    record = {"run_id": _now(), "check": "fp_rate_gate", "n_matches": n_matches, "cap": fp_rate_cap}
    if n_matches == 0:
        record["passed"] = True
        record["reason"] = "no matches; FP rate vacuously 0 (within cap)"
        emit(record, ndjson)
        return True
    if sampled_fp is None:
        # A non-empty match set with no FP sample has ZERO evidence the FP rate
        # is under cap. A bare PASS here makes the cap — variant-analysis's only
        # quality bound — inert (a 5000-line match set would clear --strict). Per
        # the "skipped checks don't masquerade as passes" contract, report
        # UNVERIFIED (non-PASS) so the cap can't be silently satisfied.
        record["passed"] = False
        record["verdict"] = "UNVERIFIED"
        record["reason"] = (f"{n_matches} matches but no FP sample; cap UNVERIFIED — "
                            f"provide sampled_fp to verify the rate is <= {fp_rate_cap:.0%}")
        emit(record, ndjson)
        return False
    fp_rate = sampled_fp / n_matches
    record["fp_rate"] = fp_rate
    record["passed"] = fp_rate <= fp_rate_cap
    if not record["passed"]:
        record["reason"] = f"FP rate {fp_rate:.0%} > cap {fp_rate_cap:.0%} — generalized too far"
    emit(record, ndjson)
    return record["passed"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hunt_spec", help="Path to hunt-spec.json")
    ap.add_argument("--target", default=".", help="Target codebase directory (default: cwd)")
    ap.add_argument("--ndjson", help="Optional NDJSON event-log path")
    ap.add_argument("--strict", action="store_true", help="Fail on any check failure")
    ap.add_argument("--json", action="store_true", help="Emit summary JSON to stdout")
    args = ap.parse_args()

    spec_path = Path(args.hunt_spec)
    if not spec_path.is_file():
        print(f"ERROR: spec not found: {spec_path}", file=sys.stderr)
        return 2
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: malformed spec: {e}", file=sys.stderr)
        return 2
    if not isinstance(spec, dict):
        print(f"ERROR: malformed spec: top-level value must be a JSON object, got {type(spec).__name__}",
              file=sys.stderr)
        print("hint: see the hunt-spec.json shape in this script's docstring", file=sys.stderr)
        return 2
    patterns = spec.get("patterns", [])
    if not isinstance(patterns, list) or not all(isinstance(p, dict) for p in patterns):
        print("ERROR: malformed spec: 'patterns' must be a list of objects", file=sys.stderr)
        print("hint: see the hunt-spec.json shape in this script's docstring", file=sys.stderr)
        return 2
    for i, pat in enumerate(patterns):
        kind = pat.get("kind", "rg")
        if kind == "rg" and not pat.get("pattern"):
            print(f"ERROR: malformed spec: patterns[{i}] (kind=rg) is missing a non-empty 'pattern' key",
                  file=sys.stderr)
            print("hint: see the hunt-spec.json shape in this script's docstring", file=sys.stderr)
            return 2
        if kind == "semgrep" and not pat.get("rule_path"):
            print(f"ERROR: malformed spec: patterns[{i}] (kind=semgrep) is missing a non-empty 'rule_path' key",
                  file=sys.stderr)
            print("hint: see the hunt-spec.json shape in this script's docstring", file=sys.stderr)
            return 2

    ndjson = open(args.ndjson, "a", encoding="utf-8") if args.ndjson else None
    try:
        results = {"hunt_id": spec.get("hunt_id", "?"), "patterns": []}
        all_passed = True
        for pat in spec.get("patterns", []):
            parsed = check_pattern_parse(pat, ndjson)
            if not parsed:
                all_passed = False
                results["patterns"].append({"level": pat.get("level"), "parsed": False, "n_matches": 0})
                continue
            run_rec, matches = run_pattern(pat, args.target, ndjson)
            if not run_rec.get("passed"):
                all_passed = False
                results["patterns"].append({"level": pat.get("level"), "parsed": True, "ran": False})
                continue
            if pat.get("level") == 0:
                baseline_ok = check_baseline(spec.get("seed_file"), spec.get("seed_line"), matches, ndjson)
                if not baseline_ok:
                    all_passed = False
            fp_ok = check_fp_gate(
                len(matches), spec.get("fp_rate_cap", 0.5),
                pat.get("sampled_fp"), ndjson,
            )
            if not fp_ok:
                all_passed = False
            results["patterns"].append({
                "level": pat.get("level"), "kind": pat.get("kind"),
                "n_matches": len(matches), "fp_ok": fp_ok,
            })
        results["all_passed"] = all_passed
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"Hunt {results['hunt_id']}: {'PASS' if all_passed else 'FAIL'}")
            for p in results["patterns"]:
                print(f"  level={p.get('level')} kind={p.get('kind', '?')} n_matches={p.get('n_matches', 0)}")
        return 0 if all_passed or not args.strict else 1
    finally:
        if ndjson:
            ndjson.close()


if __name__ == "__main__":
    sys.exit(main())
