"""Calibration test for the audit-rules transcript_pattern path.

Loads the labeled findings in golden-findings/calibration/findings.yaml
and measures Layer A's TPR / TNR / ERROR-pathway TPR.

Documented floors per the revised superplan Phase 2:
  TPR ≥ 0.90 (slightly relaxed vs audit-skill 0.95 because the audit-
              rules predicate operates on noisier transcript data)
  TNR ≥ 0.75 (same logic)
  ERROR-pathway TPR ≥ 0.95 (all known-broken instruments MUST route
                            to ERROR; the harness can't silently
                            misclassify them as STALE)

The reverify path runs each reproducer's command through
``["bash", "-c", self.command]`` (oracle.finding._fires_transcript_pattern).
Every command in the calibration findings.yaml is an ``echo '{json}'``
shape — the exact pattern that fails on Windows GHA with rc=1 and
empty stderr (see commits cb09c05 + 0e48404 for the transcript_pattern
reproducer Windows triage). The production audit-rules runner targets
Linux/macOS only; skipping this test on Windows matches the deployment
reality without weakening any assertion. The pure-Python distribution
sanity test below still runs on all three platforms.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CALIBRATION = Path(__file__).resolve().parent / "golden-findings" / "calibration"

sys.path.insert(0, str(REPO / "skills" / "_shared"))

from oracle.finding import load_findings  # noqa: E402
from oracle.reverify import reverify  # noqa: E402

MIN_TPR = 0.90
MIN_TNR = 0.75
MIN_ERROR_TPR = 0.95


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="bash subprocess on Windows GHA is unreliable for echo '{json}' "
    "commands (rc=1, empty stderr); production audit-rules runner is "
    "Linux/macOS — see cb09c05 + 0e48404 for the transcript_pattern triage",
)
def test_audit_rules_calibration_above_floors(tmp_path, monkeypatch):
    """TPR ≥ 0.90, TNR ≥ 0.75, ERROR-TPR ≥ 0.95 on the labeled set."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    findings = load_findings(CALIBRATION / "findings.yaml")
    assert findings, "calibration set is empty"

    # Partition by ground truth.
    expected_true = [f for f in findings
                     if str(f.extra.get("expected_fires", "")).lower() == "true"]
    expected_false = [f for f in findings
                      if str(f.extra.get("expected_fires", "")).lower() == "false"]
    expected_error = [f for f in findings
                      if str(f.extra.get("expected_fires", "")).lower() == "error"]

    assert len(expected_true) >= 8, (
        f"need ≥ 8 known-true findings; got {len(expected_true)}"
    )
    assert len(expected_false) >= 8, (
        f"need ≥ 8 known-false findings; got {len(expected_false)}"
    )
    assert len(expected_error) >= 3, (
        f"need ≥ 3 known-ERROR findings; got {len(expected_error)}"
    )

    results = reverify(findings, REPO)
    by_id = {(r.finding.skill, r.finding.code, r.finding.description): r
             for r in results}

    tp = fp = tn = fn = 0
    error_tp = error_fp = 0
    misclassified: list[str] = []

    for f in findings:
        r = by_id[(f.skill, f.code, f.description)]
        expected = str(f.extra.get("expected_fires", "")).lower()
        verdict = r.status

        if expected == "true":
            if verdict == "STILL-FIRES":
                tp += 1
            else:
                fn += 1
                misclassified.append(
                    f"FN: {f.skill}/{f.code} expected STILL-FIRES got {verdict}; "
                    f"evidence: {r.evidence[:80]}"
                )
        elif expected == "false":
            if verdict == "STALE":
                tn += 1
            else:
                fp += 1
                misclassified.append(
                    f"FP: {f.skill}/{f.code} expected STALE got {verdict}; "
                    f"evidence: {r.evidence[:80]}"
                )
        elif expected == "error":
            if verdict == "ERROR":
                error_tp += 1
            else:
                error_fp += 1
                misclassified.append(
                    f"ERROR_FP: {f.skill}/{f.code} expected ERROR got {verdict}; "
                    f"evidence: {r.evidence[:80]}"
                )

    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    error_tpr = error_tp / len(expected_error)

    print("\n=== audit-rules Layer A calibration ===")
    print(f"TPR={tpr:.3f}     (need ≥ {MIN_TPR})")
    print(f"TNR={tnr:.3f}     (need ≥ {MIN_TNR})")
    print(f"ERROR-TPR={error_tpr:.3f} (need ≥ {MIN_ERROR_TPR})")
    print(f"TP={tp} TN={tn} FP={fp} FN={fn} error_TP={error_tp} error_FP={error_fp}")
    if misclassified:
        print("Misclassified:")
        for m in misclassified:
            print(f"  {m}")

    assert tpr >= MIN_TPR, f"TPR={tpr:.3f} below floor {MIN_TPR}"
    assert tnr >= MIN_TNR, f"TNR={tnr:.3f} below floor {MIN_TNR}"
    assert error_tpr >= MIN_ERROR_TPR, (
        f"ERROR-TPR={error_tpr:.3f} below floor {MIN_ERROR_TPR}"
    )


def test_audit_rules_calibration_set_distribution():
    """Sanity: the labeled set has a sensible mix of known-true /
    known-false / known-error entries. Guards against a future edit
    accidentally removing a category."""
    findings = load_findings(CALIBRATION / "findings.yaml")
    labels = [str(f.extra.get("expected_fires", "")).lower() for f in findings]
    n_true = labels.count("true")
    n_false = labels.count("false")
    n_error = labels.count("error")
    n_total = len(findings)

    assert n_total >= 20, f"calibration set too small: {n_total}"
    assert n_true >= 8, f"need known-true ≥ 8; got {n_true}"
    assert n_false >= 8, f"need known-false ≥ 8; got {n_false}"
    assert n_error >= 3, f"need known-error ≥ 3; got {n_error}"
