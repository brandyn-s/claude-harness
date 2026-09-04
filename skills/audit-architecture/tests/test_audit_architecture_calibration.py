"""Oracle calibration for /audit-architecture.

Loads the labeled findings in
tests/golden-findings/calibration/findings.yaml and measures Layer A's
TPR / TNR / ERROR-pathway TPR. Fails the build if floors are not met.

Uses the same oracle infrastructure as audit-skill — the finding schema
and Reproducer mechanics are skill-agnostic. Both skills share
~/.claude/bin/audit-skill-oracle.py.

Re-run:
    pytest skills/audit-architecture/tests/test_audit_architecture_calibration.py -q

Floors (same as audit-skill SPEC.md §"Calibration"):
  predicate TPR  >= 0.95
  predicate TNR  >= 0.80
  ERROR-pathway TPR >= 1.00
  ERROR-pathway FPR <= 0.05
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CALIBRATION_DIR = Path(__file__).resolve().parent / "golden-findings" / "calibration"

MIN_TPR = 0.95
MIN_TNR = 0.80
MIN_ERR_TPR = 1.0
MAX_ERR_FPR = 0.05


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in ("oracle", "oracle.finding", "oracle.reverify", "oracle.trace"):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle import finding as f_mod
    from oracle import reverify as r_mod
    from oracle import trace as t_mod
    return f_mod, r_mod, t_mod


def _expected_status(f) -> str:
    """Map extra metadata to expected oracle status."""
    es = str(f.extra.get("expected_status", "")).upper()
    if es:
        return es
    ef = str(f.extra.get("expected_fires", "")).lower()
    if ef == "true":
        return "STILL-FIRES"
    if ef == "false":
        return "STALE"
    return ""


def test_calibration_tpr_tnr_above_floor(tmp_path, monkeypatch):
    """Layer A TPR/TNR must exceed floors for autonomous use.

    A regression here means the oracle has started producing too many
    false positives (low TNR) or missing real bugs (low TPR). Fix the
    reproducer or the oracle layer — do not silence the test."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    f_mod, r_mod, _ = _load_oracle()

    fs = f_mod.load_findings(CALIBRATION_DIR / "findings.yaml")
    assert fs, "calibration set is empty"

    expected_true = [f for f in fs if _expected_status(f) == "STILL-FIRES"]
    expected_false = [f for f in fs if _expected_status(f) == "STALE"]
    expected_error = [f for f in fs if _expected_status(f) == "ERROR"]
    assert len(expected_true) >= 20, "need at least 20 known-true findings"
    assert len(expected_false) >= 20, "need at least 20 known-false findings"
    assert len(expected_error) >= 4, "need at least 4 known-ERROR findings"

    results = r_mod.reverify(fs, REPO)
    by_id = {(r.finding.skill, r.finding.code, r.finding.description): r for r in results}

    tp = fp = tn = fn = 0
    tp_err = fn_err = fp_err = 0
    refusals = 0
    misclassified: list[str] = []

    for f in fs:
        r = by_id[(f.skill, f.code, f.description)]
        expected = _expected_status(f)
        if r.status == "MANUAL":
            refusals += 1
            continue
        if expected == "ERROR":
            if r.status == "ERROR":
                tp_err += 1
            else:
                fn_err += 1
                misclassified.append(
                    f"FN(err): {f.skill}/{f.code} expected ERROR, observed "
                    f"{r.status} ({f.description[:50]!r})"
                )
            continue
        if r.status == "ERROR":
            fp_err += 1
            misclassified.append(
                f"FP(err): {f.skill}/{f.code} expected {expected}, "
                f"observed ERROR — {r.evidence[:80]!r}"
            )
            continue
        fired = (r.status == "STILL-FIRES")
        expected_true_b = (expected == "STILL-FIRES")
        if expected_true_b and fired:
            tp += 1
        elif expected_true_b and not fired:
            fn += 1
            misclassified.append(
                f"FN: {f.skill}/{f.code} ({f.description[:60]!r}) — {r.evidence}"
            )
        elif not expected_true_b and not fired:
            tn += 1
        else:
            fp += 1
            misclassified.append(
                f"FP: {f.skill}/{f.code} ({f.description[:60]!r}) — {r.evidence}"
            )

    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    err_tpr = tp_err / (tp_err + fn_err) if (tp_err + fn_err) else 0.0
    err_fpr = (
        fp_err / (tp + fn + tn + fp + fp_err)
        if (tp + fn + tn + fp + fp_err)
        else 0.0
    )
    refusal_rate = refusals / len(fs)

    print("\n=== audit-architecture oracle calibration ===")
    print(f"predicate TPR={tpr:.3f} (need >= {MIN_TPR})")
    print(f"predicate TNR={tnr:.3f} (need >= {MIN_TNR})")
    print(f"ERROR-pathway TPR={err_tpr:.3f} (need >= {MIN_ERR_TPR})")
    print(f"ERROR-pathway FPR={err_fpr:.3f} (need <= {MAX_ERR_FPR})")
    print(f"refusal_rate={refusal_rate:.3f}")
    print(
        f"TP={tp} TN={tn} FP={fp} FN={fn} "
        f"TP_err={tp_err} FN_err={fn_err} FP_err={fp_err} refusals={refusals}"
    )
    if misclassified:
        print("Misclassified:")
        for m in misclassified:
            print(f"  {m}")

    assert tpr >= MIN_TPR, f"predicate TPR={tpr:.3f} below floor {MIN_TPR}"
    assert tnr >= MIN_TNR, f"predicate TNR={tnr:.3f} below floor {MIN_TNR}"
    assert err_tpr >= MIN_ERR_TPR, (
        f"ERROR-pathway TPR={err_tpr:.3f} below floor {MIN_ERR_TPR} — "
        f"rc>=2 / instrument-failure conflation may have regressed"
    )
    assert err_fpr <= MAX_ERR_FPR, (
        f"ERROR-pathway FPR={err_fpr:.3f} above ceiling {MAX_ERR_FPR} — "
        f"instrument-failure pattern list may be too aggressive"
    )


def test_every_reverify_writes_a_trace_record(tmp_path, monkeypatch):
    """Every Layer A invocation must write a TraceRecord per SPEC.md."""
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(trace_file))
    f_mod, r_mod, t_mod = _load_oracle()

    fs = f_mod.load_findings(CALIBRATION_DIR / "findings.yaml")
    r_mod.reverify(fs, REPO)
    records = t_mod.read_records(trace_file)
    assert len(records) == len(fs), (
        f"expected {len(fs)} trace records, got {len(records)}"
    )
    for rec in records:
        assert rec.layer == "A"
        assert rec.finding_id
        assert rec.skill
        assert rec.verdict in ("STILL-FIRES", "STALE", "MANUAL", "ERROR")
        assert rec.ts
        assert rec.procedure_version
        assert rec.latency_ms >= 0
        assert "reproducer_type" in rec.input
        assert "reproducer_command_sha" in rec.input


def test_findings_yaml_loads_without_error():
    """The calibration findings.yaml must be parseable without raising.

    This catches authoring mistakes (malformed YAML, missing required
    fields, invalid reproducer type) before they silently break the
    calibration test."""
    f_mod, _, _ = _load_oracle()
    findings = f_mod.load_findings(CALIBRATION_DIR / "findings.yaml")
    assert len(findings) >= 20, (
        f"expected at least 20 calibration findings, got {len(findings)}"
    )
    for f in findings:
        assert f.skill, f"finding missing skill: {f}"
        assert f.code, f"finding missing code: {f}"
        assert f.reproducer.type in (
            "grep", "grep_absent", "bash", "python",
            "file_exists", "file_missing", "manual",
        ), f"unknown reproducer type in {f.skill}/{f.code}"
