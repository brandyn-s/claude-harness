"""Tests for the `contract-check` oracle subcommand.

Phase 2 contract: type=manual reproducer ⟺ label=unverified.

The CLI surfaces violations independently of dispatch validation,
so operators can spot label/reproducer drift before running act-on.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
ORACLE_CLI = REPO / "bin" / "audit-skill-oracle.py"


def _run(args: list[str], cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ORACLE_CLI), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _write_findings(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "findings.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_contract_check_clean_file_exits_0(tmp_path):
    findings = _write_findings(tmp_path, """\
        findings:
          - skill: foo
            code: D4
            severity: info
            label: doc-fix
            description: OK with auto reproducer
            reproducer:
              type: grep
              command: "grep -q foo bar"
          - skill: foo
            code: D4
            severity: info
            label: unverified
            description: OK with manual reproducer
            reproducer:
              type: manual
              description: needs human
    """)
    r = _run(["contract-check", str(findings)])
    assert r.returncode == 0
    assert "0 violation" in r.stdout
    assert "contract OK" in r.stdout


def test_contract_check_detects_manual_not_unverified(tmp_path):
    findings = _write_findings(tmp_path, """\
        findings:
          - skill: foo
            code: D4
            severity: info
            label: doc-fix
            description: manual paired with doc-fix
            reproducer:
              type: manual
    """)
    r = _run(["contract-check", str(findings)])
    assert "MANUAL_NOT_UNVERIFIED" in r.stdout
    assert "1 violation" in r.stdout
    assert "backfill_reproducers.py" in r.stdout


def test_contract_check_detects_auto_but_unverified(tmp_path):
    findings = _write_findings(tmp_path, """\
        findings:
          - skill: foo
            code: D4
            severity: info
            label: unverified
            description: auto reproducer mis-labeled unverified
            reproducer:
              type: grep
              command: "grep -q foo bar"
    """)
    r = _run(["contract-check", str(findings)])
    assert "AUTO_BUT_UNVERIFIED" in r.stdout
    assert "1 violation" in r.stdout


def test_contract_check_strict_exits_nonzero_on_violation(tmp_path):
    """--strict makes this gateable from CI / orchestrators."""
    findings = _write_findings(tmp_path, """\
        findings:
          - skill: foo
            code: D4
            severity: info
            label: behavior-fix
            description: violation
            reproducer:
              type: manual
    """)
    r = _run(["contract-check", str(findings), "--strict"])
    assert r.returncode == 1
    assert "MANUAL_NOT_UNVERIFIED" in r.stdout


def test_contract_check_skips_triage_closed_findings(tmp_path):
    """Closed findings don't need to satisfy the contract — they're
    out of flight."""
    findings = _write_findings(tmp_path, """\
        findings:
          - skill: foo
            code: D4
            severity: info
            label: doc-fix
            description: closed finding with violating label
            triage_status: STALE
            triage_note: closed by re-audit
            reproducer:
              type: manual
    """)
    r = _run(["contract-check", str(findings), "--strict"])
    assert r.returncode == 0
    assert "0 violation" in r.stdout


def test_act_on_refuses_on_contract_violation_and_emits_no_worklist(tmp_path):
    """act-on enforces the contract by default. A violating input must
    NOT produce a worklist — that would route manual findings to a
    fix-batch as if they were verified."""
    findings = _write_findings(tmp_path, """\
        findings:
          - skill: foo
            code: D4
            severity: info
            label: doc-fix
            description: violation - manual reproducer with doc-fix label
            reproducer:
              type: manual
    """)
    out = tmp_path / "worklist.yaml"
    r = _run(["act-on", str(findings), "--out", str(out)])
    assert r.returncode == 1
    assert "contract violations" in r.stderr.lower()
    assert "MANUAL_NOT_UNVERIFIED" in r.stderr
    # Worklist must NOT be written when the gate trips.
    assert not out.exists(), (
        "act-on must not emit a worklist when contract is violated; "
        "the worklist would route unverified findings to fix-batch"
    )


def test_act_on_skip_contract_check_emits_worklist(tmp_path):
    """--skip-contract-check is the forensic escape hatch. It DOES
    produce a worklist, but the worklist is explicitly not safe for
    fix-batch dispatch (the caller takes responsibility)."""
    findings = _write_findings(tmp_path, """\
        findings:
          - skill: foo
            code: D4
            severity: info
            label: doc-fix
            description: violation - manual reproducer with doc-fix label
            reproducer:
              type: manual
    """)
    out = tmp_path / "worklist.yaml"
    r = _run(["act-on", str(findings), "--out", str(out), "--skip-contract-check"])
    assert r.returncode == 0
    assert out.exists()


def test_act_on_passes_on_clean_input(tmp_path):
    """A contract-compliant input must produce a worklist as before."""
    findings = _write_findings(tmp_path, """\
        findings:
          - skill: foo
            code: D4
            severity: info
            label: unverified
            description: clean manual finding
            reproducer:
              type: manual
              description: needs human review
    """)
    out = tmp_path / "worklist.yaml"
    r = _run(["act-on", str(findings), "--out", str(out)])
    assert r.returncode == 0
    assert out.exists()
    assert "act_on summary" in r.stderr
