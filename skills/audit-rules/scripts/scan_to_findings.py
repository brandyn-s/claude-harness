#!/usr/bin/env python3
"""Adapter: convert scan_violations.py JSON output → Finding YAML.

Phase 1 of the audit-rules oracle-lift. The scanner already emits
rule-violation metrics; this script wraps each rule's metric in a
Finding with a transcript_pattern reproducer so the oracle can:

  - act_on the worklist (with --skip-contract-check during the
    transition, until labels are aligned)
  - validate-for-dispatch (the standard pre-dispatch gate)
  - reverify on demand (re-runs scan_violations.py via the embedded
    reproducer command)
  - triage_status per rule (so closed rules stop re-surfacing)

Each emitted Finding has the rule-violation predicate baked in:

  - skill: audit-rules
    code: V<N>      # V1-V6 per scanner detector numbering
    severity: drift # if session_rate_pct >= threshold; else info
    label: behavior-fix   # drift severity → real bug surface
    description: "<rule> session rate is X% (threshold Y%); ..."
    reproducer:
      type: transcript_pattern
      command: "python3 skills/audit-rules/references/scan_violations.py --rule <rule> --json"
      metric_path: "violations.<rule>.session_rate_pct"
      threshold: <promotion-trigger threshold>
      threshold_op: gte

Usage:
  python3 skills/audit-rules/scripts/scan_to_findings.py
      [--out AUDIT-TRACKERS/rule-violations.findings.yaml]
      [--threshold 10.0]   # promotion-trigger threshold in percent
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills" / "_shared"))

from oracle.finding import Finding, Reproducer  # noqa: E402
from oracle.tracker import _to_yaml  # noqa: E402

# Map scanner-emitted rule keys → audit-skill finding code (V1-V8)
# in the order they appear in scan_violations.py. V9 prototyped and
# disabled at 73% FP rate — see test_detectors_v7_v8.py.
RULE_TO_CODE = {
    "encoding-missing-open":      "V1",
    "missing-stdout-reconfigure": "V2",
    "inline-python-c":            "V3",
    "str-replace-crlf-risk":      "V4",
    "git-commit-no-branch-check": "V5",
    "websearch-webfetch-used":    "V6",
    "curl-verbose-with-auth":     "V7",
    "pip-install-upgrade-all":    "V8",
}


def _load_forbidden_signatures(repo_root: Path) -> dict[str, list[dict]]:
    """Invoke extract_forbidden_signatures.py and return a
    {rule_name: [{identifier, keywords, line}, ...]} mapping. Empty
    dict on failure — the GAP-finding hint is a nice-to-have, not a
    hard requirement."""
    import subprocess
    script = repo_root / "skills" / "audit-rules" / "scripts" / "extract_forbidden_signatures.py"
    if not script.exists():
        return {}
    try:
        r = subprocess.run(
            [sys.executable, str(script), "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return {}
        data = json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {}
    return {
        r["name"]: r.get("forbidden_signatures", [])
        for r in data.get("rules", [])
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "AUDIT-TRACKERS" / "rule-violations.findings.yaml",
        help="output path for the Findings YAML",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=10.0,
        help="promotion-trigger threshold (session_rate_pct >= threshold "
             "→ severity=drift, label=behavior-fix; below → severity=info, "
             "label=doc-fix)",
    )
    ap.add_argument(
        "--days", type=int, default=14,
        help="scan window in days (passed through to scan_violations.py)",
    )
    ap.add_argument(
        "--include-uncovered", action="store_true",
        help=(
            "emit a coverage-gap finding per ambient rule that has no "
            "detector. Closes the observability gap between "
            "rules/*.md (~31 files) and scan_violations.py (~6 detectors)."
        ),
    )
    args = ap.parse_args()

    scanner = REPO / "skills" / "audit-rules" / "references" / "scan_violations.py"
    if not scanner.exists():
        print(f"error: scanner not found at {scanner}", file=sys.stderr)
        return 2

    # Measure
    r = subprocess.run(
        [sys.executable, str(scanner), "--json", "--days", str(args.days)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"error: scan_violations.py rc={r.returncode}", file=sys.stderr)
        print(r.stderr, file=sys.stderr)
        return 1

    data = json.loads(r.stdout)
    violations = data.get("violations", {})
    if not violations:
        print("no violations measured; nothing to emit", file=sys.stderr)
        return 0

    # Build a Finding per rule. The transcript_pattern reproducer
    # re-runs the scanner on demand so reverify is always live.
    findings: list[Finding] = []
    for rule, metrics in violations.items():
        rate = metrics.get("session_rate_pct", 0.0)
        sessions = metrics.get("unique_sessions", 0)
        count = metrics.get("count", 0)
        # The scanner now emits zero-count entries for every detector
        # (measured-clean marker). A clean detector is not a finding.
        if count == 0:
            continue
        # Severity threshold: promotion-trigger >= args.threshold
        is_drift = rate >= args.threshold
        severity = "drift" if is_drift else "info"
        # Label per contract: drift → behavior-fix (auto reproducer),
        # info → doc-fix (still auto reproducer, lower priority).
        label = "behavior-fix" if is_drift else "doc-fix"
        code = RULE_TO_CODE.get(rule, "V?")
        description = (
            f"Rule '{rule}' session_rate_pct={rate}% "
            f"(promotion trigger: >= {args.threshold}%; "
            f"{count} violations across {sessions} sessions over "
            f"last {args.days} days)"
        )
        reproducer = Reproducer(
            type="transcript_pattern",
            command=(
                f"python3 skills/audit-rules/references/scan_violations.py "
                f"--rule {rule} --json --days {args.days}"
            ),
            metric_path=f"violations.{rule}.session_rate_pct",
            threshold=args.threshold,
            threshold_op="gte",
            description=(
                f"Re-measures rule '{rule}' violation rate from "
                f"session transcripts; fires iff session_rate_pct "
                f">= {args.threshold}"
            ),
        )
        findings.append(Finding(
            skill="audit-rules",
            code=code,
            severity=severity,
            label=label,
            description=description,
            reproducer=reproducer,
            source=f"~/.claude/projects/*/sessions (last {args.days} days)",
            triage_status="open",
        ))

    # Optionally emit coverage-gap findings for ambient rules that have
    # no detector wired into scan_violations.py. This closes the
    # observability gap between rules/*.md (~31 files) and the ~8
    # opinionated detectors. Each uncovered rule gets a Finding with
    # code GAP, severity=info, type=manual + label=unverified per
    # contract — the gap is real but the predicate is "needs a
    # detector authored," not directly auto-checkable.
    #
    # Map detector names to the rules they measure. Rules may have
    # multiple detectors (e.g., platform-constraints has V7, V8) and
    # rules without detectors are uncovered.
    DETECTOR_TO_RULE = {
        "encoding-missing-open":      "platform-constraints",
        "missing-stdout-reconfigure": "platform-constraints",
        "inline-python-c":            "platform-constraints",
        "str-replace-crlf-risk":      "platform-constraints",
        "git-commit-no-branch-check": "git-hygiene",
        "websearch-webfetch-used":    "web-search-preference",
        "curl-verbose-with-auth":     "platform-constraints",
        "pip-install-upgrade-all":    "platform-constraints",
    }
    if args.include_uncovered:
        rules_dir = REPO / "rules"
        covered = set(DETECTOR_TO_RULE.values())
        ambient_rules = sorted(p.stem for p in rules_dir.glob("*.md")
                                if p.stem not in ("incidents",))
        uncovered = [r for r in ambient_rules if r not in covered]

        # Load FORBIDDEN-signature seeds (Phase 7a) so GAP findings
        # carry a detector-authoring hint when the rule has snake_case
        # FORBIDDEN identifiers. Helps prioritize detector work.
        sig_seeds = _load_forbidden_signatures(REPO)

        for rule_name in uncovered:
            seed_sigs = sig_seeds.get(rule_name, [])
            seed_hint = ""
            if seed_sigs:
                identifiers = ", ".join(s["identifier"] for s in seed_sigs[:3])
                more = f" (+{len(seed_sigs) - 3} more)" if len(seed_sigs) > 3 else ""
                seed_hint = (
                    f" Detector-authoring seed: rule has {len(seed_sigs)} "
                    f"parseable FORBIDDEN identifier(s): {identifiers}{more}."
                )
            findings.append(Finding(
                skill="audit-rules",
                code="GAP",
                severity="info",
                label="unverified",
                description=(
                    f"Ambient rule 'rules/{rule_name}.md' has no detector "
                    f"in scan_violations.py — compliance is unmeasured. "
                    f"Coverage gap; promotion decisions on this rule have "
                    f"no quantitative basis.{seed_hint}"
                ),
                reproducer=Reproducer(
                    type="manual",
                    description=(
                        f"Authoring a detector for rule '{rule_name}' "
                        f"requires identifying a syntactic pattern that "
                        f"surfaces in assistant-generated tool_use payloads "
                        f"when the rule is violated. See "
                        f"skills/audit-rules/references/scan_violations.py "
                        f"for the detector schema (V1-V6)."
                    ),
                ),
                source=f"rules/{rule_name}.md",
                triage_status="open",
                extra={
                    "coverage_gap": True,
                    "rule_file": f"rules/{rule_name}.md",
                    "forbidden_signatures": [s["identifier"] for s in seed_sigs],
                },
            ))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_to_yaml(findings), encoding="utf-8")
    print(f"wrote {len(findings)} findings to {args.out}")
    drift_n = sum(1 for f in findings if f.severity == "drift")
    gap_n = sum(1 for f in findings if f.code == "GAP")
    print(f"  drift (>= {args.threshold}% rate): {drift_n}")
    print(f"  info (< {args.threshold}% rate):  {len(findings) - drift_n - gap_n}")
    if gap_n:
        print(f"  coverage gaps (no detector):     {gap_n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
