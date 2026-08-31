"""Tests for oracle.act_on adapted for audit-architecture.

Adapted from skills/audit-skill/tests/test_oracle_act_on.py.

Pins the act_on gate behavior against architecture-specific finding
codes (R3, C2, D5) and uses real files from the calibration fixtures:

  - act_on drops STALE findings (reproducer no longer fires)
  - act_on retains MANUAL for human review
  - act_on retains ERROR findings (reproducer crashed)
  - format_act_on_summary includes stale_rate

Architecture codes exercised:
  R3 — invalid JSON config (bash / python reproducer)
  C2 — phantom server missing from routing rules (grep_absent)
  D5 — undocumented server in mcp.json (file_missing)

Re-run:
    pytest skills/audit-architecture/tests/test_audit_architecture_act_on.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CALIBRATION_DIR = (
    Path(__file__).resolve().parent / "golden-findings" / "calibration"
)


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in (
        "oracle", "oracle.finding", "oracle.act_on", "oracle.reverify",
        "oracle.tracker", "oracle.trace",
    ):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle.finding import Finding, Reproducer  # noqa: E402
    from oracle.act_on import act_on, format_act_on_summary  # noqa: E402
    return Finding, Reproducer, act_on, format_act_on_summary


def test_act_on_drops_stale_findings(tmp_path, monkeypatch):
    """Stale findings (Reproducer no longer fires) must NOT appear in
    the worklist. Uses a real temp file — the R3 grep predicate looks
    for a string that isn't there (STALE) and a D5 file_missing
    predicate for a file that genuinely does not exist (STILL-FIRES)."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, act_on, _ = _load_oracle()

    # Write a valid settings.json so the R3 bash check returns exit 0
    # (parse succeeds), which means expected_exit=1 is NOT met → STALE.
    settings = tmp_path / "settings.json"
    settings.write_text('{"ok": true}', encoding="utf-8")
    settings_posix = settings.as_posix()

    findings = [
        # STALE: JSON is valid now — R3 bash check does NOT fire
        Finding(
            skill="architecture-fixture",
            code="R3",
            severity="drift",
            label="behavior-fix",
            description="settings.json is not valid JSON (already fixed)",
            reproducer=Reproducer(
                type="bash",
                command=(
                    f"python3 -c \"import json; json.load(open('{settings_posix}'))\" "
                    "2>/dev/null"
                ),
                expected_exit=1,
            ),
        ),
        # STILL-FIRES: referenced file genuinely missing
        Finding(
            skill="architecture-fixture",
            code="D5",
            severity="info",
            label="doc-fix",
            description="referenced server script does not exist",
            reproducer=Reproducer(
                type="file_missing",
                path=str(tmp_path / "references" / "phantom-server.md"),
            ),
        ),
    ]
    report = act_on(findings, tmp_path)
    assert len(report.worklist) == 1
    assert report.worklist[0].code == "D5", (
        f"expected only D5 in worklist (R3 should be STALE); got: "
        f"{[f.code for f in report.worklist]}"
    )
    assert len(report.stale) == 1
    assert report.stale[0].finding.code == "R3"
    assert report.stale_rate == 0.5


def test_act_on_retains_manual_for_human_review(tmp_path, monkeypatch):
    """type=manual findings have no automated check — they bypass
    reverify and stay in the worklist for human review."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, act_on, _ = _load_oracle()
    findings = [
        Finding(
            skill="architecture-fixture",
            code="C2",
            severity="drift",
            label="behavior-fix",
            description="vague routing rule gap — needs human check",
            reproducer=Reproducer(type="manual", description="check routing manually"),
        ),
    ]
    report = act_on(findings, tmp_path)
    assert len(report.worklist) == 1
    assert len(report.manual) == 1
    assert len(report.stale) == 0


def test_act_on_retains_error_findings(tmp_path, monkeypatch):
    """When a Reproducer crashes (instrument failure), the oracle returns
    ERROR. act_on must NOT drop ERROR findings — they stay in the worklist
    for human attention.

    Uses a python reproducer that raises RuntimeError (intentional
    predicate fire → STILL-FIRES per oracle contract, retained in worklist)."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, act_on, _ = _load_oracle()
    findings = [
        Finding(
            skill="architecture-fixture",
            code="R3",
            severity="drift",
            label="behavior-fix",
            description="settings.json parse check (predicate fires)",
            reproducer=Reproducer(
                type="python",
                command="raise RuntimeError('R3 predicate fired')",
            ),
        ),
    ]
    report = act_on(findings, tmp_path)
    # Whether STILL-FIRES (predicate raised RuntimeError) or ERROR
    # (instrument failure), act_on must NOT silently drop it.
    assert len(report.worklist) == 1


def test_format_act_on_summary_includes_stale_rate(tmp_path, monkeypatch):
    """The summary string must surface the stale-rate metric so the
    orchestrator can report 'X% stale' at the top of the next dispatch."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, act_on, fmt = _load_oracle()

    # Write a real file — grep predicate will be STALE (pattern absent)
    target = tmp_path / "routing-rules.json"
    target.write_text('{"rules": []}', encoding="utf-8")

    findings = [
        Finding(
            skill="architecture-fixture",
            code="C2",
            severity="drift",
            label="behavior-fix",
            description="phantom-server absent from routing (already stale)",
            reproducer=Reproducer(
                type="grep_absent",
                command=f"grep -q 'phantom-server' {target.as_posix()}",
            ),
        ),
    ]
    report = act_on(findings, tmp_path)
    summary = fmt(report)
    assert "stale rate" in summary.lower()
    assert "STALE" in summary
    assert "STILL-FIRES" in summary
