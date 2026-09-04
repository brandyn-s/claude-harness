"""Tests for ``oracle.report`` — the Phase 4 bundling.

Phase 4 used to be prose-assembled by the calling agent. This module
gives it the same mechanical guarantees as Phase 1 / Phase 3 by
running deterministic transforms over the NDJSON + worklist YAML.

These tests pin:
- Phase 1 NDJSON records render as numbered markdown rows
- Phase 2/3 worklist YAML rows render with oracle verdict + reproducer hint
- closed-triage findings are excluded
- the header counts match per-severity / per-verdict totals
- JSON format is structurally identical to markdown (same fields)
- error paths (missing inputs, malformed JSON) are clean
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_report_module():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in (
        "oracle", "oracle.finding", "oracle.report",
    ):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle import report  # noqa: E402
    return report


def _write_ndjson(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


def _write_findings_yaml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_phase1_only_renders_numbered_markdown(tmp_path):
    """Phase 1 NDJSON in, numbered markdown out. Each row gets a
    location, message, and action hint."""
    report = _load_report_module()
    p1 = tmp_path / "p1.ndjson"
    _write_ndjson(p1, [
        {"run_id": "t", "skill": "alpha", "code": "H5", "severity": "drift",
         "msg": "broken cite", "path": "skills/alpha/SKILL.md", "line": 12},
        {"run_id": "t", "skill": "beta", "code": "C2", "severity": "info",
         "msg": "/tmp/ POSIX-only", "path": "skills/beta/SKILL.md", "line": 7},
    ])
    entries, header = report.build_report(phase1_path=p1)
    assert header["phase1_total"] == 2
    assert header["phase1_drift"] == 1
    assert header["phase1_info"] == 1
    md = report.render_markdown(entries, header)
    assert "## 1. `alpha` H5 [drift]" in md
    assert "## 2. `beta` C2 [info]" in md
    assert "skills/alpha/SKILL.md:12" in md
    assert "broken cite" in md
    assert "needs-fix" in md  # for the drift row
    assert "track for hygiene" in md  # for the info row


def test_phase2_only_emits_oracle_verdict_and_reproducer_hint(tmp_path):
    """Phase 2/3 worklist YAML in, markdown out. The verdict and
    reproducer kind+payload are surfaced so a reader can act without
    chasing the YAML."""
    report = _load_report_module()
    p2 = tmp_path / "wl.yaml"
    _write_findings_yaml(p2, """findings:
  - skill: gamma
    code: D4
    severity: drift
    label: doc-fix
    description: "stale citation"
    reproducer:
      type: file_missing
      path: skills/gamma/oracle/SPEC.md
  - skill: delta
    code: A3
    severity: drift
    label: unverified
    description: "invariant unverified"
    reproducer:
      type: manual
      description: "manual reproducer description"
""")
    entries, header = report.build_report(phase2_path=p2)
    assert header["phase2_still_fires"] == 1
    assert header["phase2_manual"] == 1
    md = report.render_markdown(entries, header)
    assert "STILL-FIRES" in md
    assert "MANUAL" in md
    assert "`file_missing`" in md
    assert "skills/gamma/oracle/SPEC.md" in md
    # MANUAL findings should route to needs-human-judgement
    delta_section = md[md.index("`delta`"):]
    assert "needs-human-judgement" in delta_section


def test_closed_triage_findings_excluded(tmp_path):
    """Findings with FIXED / STALE / FALSE_POSITIVE / DEFER triage
    statuses must NOT appear in the final report — they're closed by
    the operator and the agent shouldn't see them as actionable."""
    report = _load_report_module()
    p2 = tmp_path / "wl.yaml"
    _write_findings_yaml(p2, """findings:
  - skill: live
    code: H5
    severity: drift
    label: doc-fix
    description: "still actionable"
    reproducer:
      type: file_missing
      path: nope.md
  - skill: closed
    code: H5
    severity: drift
    label: doc-fix
    description: "already fixed"
    reproducer:
      type: file_missing
      path: was-nope.md
    triage_status: FIXED
    triage_note: "fixed in PR #999"
""")
    entries, _ = report.build_report(phase2_path=p2)
    assert len(entries) == 1
    assert entries[0].skill == "live"


def test_both_phases_combined_in_one_numbered_list(tmp_path):
    """Phase 1 + Phase 2/3 must render in one sequence — Phase 1 first,
    Phase 2/3 after, numbered globally."""
    report = _load_report_module()
    p1 = tmp_path / "p1.ndjson"
    _write_ndjson(p1, [
        {"run_id": "t", "skill": "a", "code": "C2", "severity": "info",
         "msg": "msg-a", "path": "skills/a/SKILL.md", "line": 1},
    ])
    p2 = tmp_path / "wl.yaml"
    _write_findings_yaml(p2, """findings:
  - skill: b
    code: D4
    severity: drift
    label: doc-fix
    description: "msg-b"
    reproducer:
      type: file_missing
      path: missing.md
""")
    entries, header = report.build_report(phase1_path=p1, phase2_path=p2)
    md = report.render_markdown(entries, header)
    # Phase 1 row is #1, Phase 2/3 row is #2.
    assert md.index("## 1. `a`") < md.index("## 2. `b`")
    assert "Phase 1" in md
    assert "Phase 2/3" in md


def test_json_format_has_header_and_findings(tmp_path):
    """JSON output must mirror the markdown — same header counts, same
    finding count, so machine consumers don't drift from the markdown."""
    report = _load_report_module()
    p1 = tmp_path / "p1.ndjson"
    _write_ndjson(p1, [
        {"run_id": "t", "skill": "x", "code": "C2", "severity": "info",
         "msg": "m", "path": "p", "line": 1},
    ])
    entries, header = report.build_report(phase1_path=p1)
    j = json.loads(report.render_json(entries, header))
    assert j["header"]["phase1_total"] == 1
    assert len(j["findings"]) == 1
    assert j["findings"][0]["skill"] == "x"
    assert j["findings"][0]["phase"] == "1"


def test_build_report_requires_at_least_one_input():
    """Empty call must fail loudly, not return an empty report — the
    caller probably forgot to wire the inputs."""
    report = _load_report_module()
    try:
        report.build_report()
    except ValueError as e:
        assert "at least one" in str(e)
    else:
        raise AssertionError("expected ValueError for empty inputs")


def test_load_phase1_ndjson_skips_blank_lines(tmp_path):
    """NDJSON files sometimes have trailing newlines or blank lines.
    The loader must skip those, not raise json.JSONDecodeError."""
    report = _load_report_module()
    p1 = tmp_path / "p1.ndjson"
    p1.write_text('{"skill":"a","code":"X","severity":"info","msg":"m"}\n\n', encoding="utf-8")
    records = report.load_phase1_ndjson(p1)
    assert len(records) == 1
    assert records[0]["skill"] == "a"


def test_phase2_entries_truncate_long_reproducer_payload(tmp_path):
    """Reproducer commands can be long; the report shows only the
    first line capped at ~120 chars so the markdown stays readable."""
    report = _load_report_module()
    p2 = tmp_path / "wl.yaml"
    # 200-char command that should be truncated
    long_cmd = "x" * 200
    _write_findings_yaml(p2, f"""findings:
  - skill: q
    code: A1
    severity: drift
    label: behavior-fix
    description: "long-cmd test"
    reproducer:
      type: bash
      command: "{long_cmd}"
""")
    entries, _ = report.build_report(phase2_path=p2)
    assert len(entries[0].reproducer_payload) <= 120
