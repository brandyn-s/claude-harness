"""Tests for ``oracle.act_on`` — the pre-action gate.

The May 2026 fix campaign observed a 38% stale-finding rate when
fix-batches read the static AUDIT-TRACKERS markdown tracker without
running reverify first. act_on closes that gap.

These tests pin the gate's behavior:
  - Findings that no longer fire are dropped from the worklist
    (STALE classification).
  - Findings that still fire are retained (STILL-FIRES).
  - MANUAL and ERROR are retained because the oracle hasn't made a
    verification claim — the caller decides.
  - The summary's ``stale_rate`` is the empirical metric the orchestrator
    should report at the top of the next fix-batch dispatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in ("oracle", "oracle.finding", "oracle.act_on", "oracle.reverify",
                 "oracle.tracker", "oracle.trace"):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle.finding import Finding, Reproducer  # noqa: E402
    from oracle.act_on import act_on, format_act_on_summary  # noqa: E402
    from oracle.tracker import parse_tracker, convert_tracker_to_yaml  # noqa: E402
    return Finding, Reproducer, act_on, format_act_on_summary, parse_tracker, convert_tracker_to_yaml


def test_act_on_drops_stale_findings(tmp_path, monkeypatch):
    """Stale findings (Reproducer no longer fires) must NOT appear in
    the worklist. This is the gate's central contract — without it,
    the 38% stale rate from the May 2026 campaign returns."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, act_on, _, _, _ = _load_oracle()

    # Set up two real findings against a temp file:
    target = tmp_path / "skill.md"
    target.write_text("---\nname: example\nallowed-tools: Read\n---\n", encoding="utf-8")
    # Use POSIX form so bash doesn't see \U \B \T as escape sequences
    # when this runs on Windows. Without this, grep gets a path it
    # can't open and exits 2 — which is ERROR (instrument failure),
    # not STALE (bug absent). See test_grep_error_exit_routes_to_ERROR.
    target_posix = target.as_posix()

    findings = [
        # STALE: bug is "phantom tool" but the file has no phantom tool now.
        Finding(
            skill="example",
            code="T1",
            severity="drift",
            label="behavior-fix",
            description="phantom tool reference (already resolved)",
            reproducer=Reproducer(
                type="grep",
                command=f"grep -q 'mcp__code-graph__index_status' {target_posix}",
            ),
        ),
        # STILL-FIRES: bug is "missing reference" and the file is indeed missing.
        Finding(
            skill="example",
            code="H1",
            severity="drift",
            label="behavior-fix",
            description="reference doesn't exist",
            reproducer=Reproducer(
                type="file_missing",
                path=str(tmp_path / "references" / "missing.md"),
            ),
        ),
    ]
    report = act_on(findings, tmp_path)
    assert len(report.worklist) == 1
    assert report.worklist[0].code == "H1", (
        f"expected only H1 in worklist (T1 should be STALE); got: "
        f"{[f.code for f in report.worklist]}"
    )
    assert len(report.stale) == 1
    assert report.stale[0].finding.code == "T1"
    assert report.stale_rate == 0.5


def test_act_on_retains_manual_for_human_review(tmp_path, monkeypatch):
    """type=manual findings have no automated check — they bypass
    reverify and stay in the worklist for human review."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, act_on, _, _, _ = _load_oracle()
    findings = [
        Finding(
            skill="example",
            code="X1",
            severity="info",
            label="unverified",
            description="vague claim about behavior",
            reproducer=Reproducer(type="manual", description="prose only"),
        ),
    ]
    report = act_on(findings, tmp_path)
    assert len(report.worklist) == 1
    assert len(report.manual) == 1
    assert len(report.stale) == 0


def test_act_on_retains_error_findings(tmp_path, monkeypatch):
    """When a Reproducer crashes (timeout, malformed command, etc.),
    the oracle returns ERROR — meaning no verdict. The finding stays
    in the worklist for human attention; the orchestrator should NOT
    silently drop these."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, act_on, _, _, _ = _load_oracle()
    findings = [
        Finding(
            skill="example",
            code="X1",
            severity="drift",
            label="behavior-fix",
            description="bug that needs a python-script check",
            # `RuntimeError` is treated as an intentional predicate raise
            # under the python contract — not an instrument failure. This
            # exercises the STILL-FIRES path. For genuine instrument
            # failures (SyntaxError, ImportError, NameError, etc.) the
            # contract routes to ERROR; see
            # test_python_instrument_failure_routes_to_ERROR in
            # test_oracle_calibration.py for that case.
            reproducer=Reproducer(
                type="python",
                command="raise RuntimeError('predicate fired')",
            ),
        ),
    ]
    report = act_on(findings, tmp_path)
    # Whether the verdict is STILL-FIRES (predicate raised) or ERROR
    # (instrument failure), act_on must NOT silently drop it — both
    # statuses are retained in the worklist for human review.
    assert len(report.worklist) == 1


def test_tracker_to_yaml_roundtrip(tmp_path):
    """Markdown-tracker parsing yields well-formed Finding objects that
    the YAML loader can read back."""
    Finding, Reproducer, _, _, parse_tracker, convert = _load_oracle()
    tracker = tmp_path / "tracker.md"
    tracker.write_text(
        "# Phase 2 tracker\n"
        "\n"
        "### example-skill\n"
        "- [drift] [behavior-fix] H1: cited references/missing.md does not exist\n"
        "- [info] [doc-fix] M2: tool mcp__code-graph__index_status known-phantom\n"
        "- [info] [unverified] B1: skill ships scripts/ but no tests/\n"
        "\n",
        encoding="utf-8",
    )
    findings = list(parse_tracker(tracker))
    assert len(findings) == 3
    codes = {f.code for f in findings}
    assert codes == {"H1", "M2", "B1"}
    # H1 should have inferred a file_missing Reproducer
    h1 = next(f for f in findings if f.code == "H1")
    assert h1.reproducer.type == "file_missing"
    # M2 with phantom-tool prose should be type=grep
    m2 = next(f for f in findings if f.code == "M2")
    assert m2.reproducer.type == "grep"
    # B1 (no recognizable pattern) → manual
    b1 = next(f for f in findings if f.code == "B1")
    assert b1.reproducer.type == "manual"

    # Round-trip via the YAML emitter
    out_path = tmp_path / "out.yaml"
    n = convert(tracker, out_path)
    assert n == 3
    from oracle.finding import load_findings
    loaded = load_findings(out_path)
    assert len(loaded) == 3
    assert {f.code for f in loaded} == {"H1", "M2", "B1"}


def test_act_on_summary_text_includes_stale_rate(tmp_path, monkeypatch):
    """The summary string must surface the stale-rate metric — that's
    the diagnostic that turned the May 2026 38%-stale problem into an
    observable quantity."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, act_on, fmt, _, _ = _load_oracle()
    target = tmp_path / "skill.md"
    target.write_text("# clean\n", encoding="utf-8")
    findings = [
        Finding(skill="x", code="A1", severity="drift", label="behavior-fix",
                description="stale", reproducer=Reproducer(
                    type="grep", command=f"grep -q 'bug-pattern' {target.as_posix()}")),
    ]
    report = act_on(findings, tmp_path)
    summary = fmt(report)
    assert "stale rate" in summary.lower()
    assert "STALE" in summary
    assert "STILL-FIRES" in summary


def test_dispatchable_only_drops_manual_and_error(tmp_path, monkeypatch):
    """--auto-only's helper: the emitted worklist carries ONLY
    STILL-FIRES findings — MANUAL fails /audit-fix Gate 1 and ERROR
    fails Gate 4, so a bare worklist including them is not
    dispatchable as written (2026-08-22 close-out)."""
    Finding, Reproducer, *_ = _load_oracle()
    from oracle.act_on import ActOnReport, dispatchable_only
    from oracle.reverify import ReverifyResult

    def _res(status, code):
        f = Finding(skill="s", code=code, severity="drift",
                    label="behavior-fix" if status != "MANUAL" else "unverified",
                    description=f"d-{code}",
                    reproducer=Reproducer(
                        type="bash" if status != "MANUAL" else "manual",
                        command="true"))
        return ReverifyResult(finding=f, status=status, evidence="")

    fires = _res("STILL-FIRES", "A1")
    manual = _res("MANUAL", "B")
    error = _res("ERROR", "C")
    report = ActOnReport(
        worklist=[fires.finding, manual.finding, error.finding],
        stale=[], still_fires=[fires], manual=[manual], error=[error])
    subset = dispatchable_only(report)
    assert [f.code for f in subset] == ["A1"]
