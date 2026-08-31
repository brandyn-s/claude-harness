"""End-to-end golden tests for /audit-fix's Step-0 worklist validation
gates (AUDIT-TRACKERS/02-golden-tests.md, B8f F4: "worklist-gate
fixtures (malformed/stale/no-trace worklists exercise the three Step-0
validate gates)").

Pattern (copied from skills/supergoal/tests/):
    tests/golden/<scenario>.worklist.yaml   Input fixtures
    tests/test_audit_fix_golden.py          This module:
        - invokes scripts/validate_worklist.py via subprocess
          (not import-level reuse — catches CLI bugs)
        - asserts exit code AND output schema (not exact bytes)
        - uses tmp_path so nothing touches ~/.claude/

The trace file is redirected into tmp_path via the
AUDIT_SKILL_ORACLE_TRACE env var (the same contract the oracle uses).
Trace records are generated at test time, not stored as fixtures — a
frozen timestamp would age past the 30-minute TTL, which is precisely
the condition gate 2 exists to reject.

Re-run:
    python3 -m pytest skills/audit-fix/tests/ -q
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "validate_worklist.py"
GOLDEN = Path(__file__).resolve().parent / "golden"


def _run(*args, env=None):
    """Run validate_worklist.py; return (rc, stdout, stderr)."""
    e = os.environ.copy()
    if env:
        e.update(env)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, env=e,
    )
    return r.returncode, r.stdout, r.stderr


def _isolated_env(tmp_path):
    """Point the oracle trace into tmp_path so tests never read or
    write the operator's real ~/.claude/oracle-trace.jsonl."""
    return {"AUDIT_SKILL_ORACLE_TRACE": str(tmp_path / "trace.jsonl")}


def _fixture(tmp_path, name):
    """Copy a golden fixture into tmp_path (isolation per the pattern)."""
    dst = tmp_path / name
    shutil.copy(GOLDEN / name, dst)
    return dst


def _finding_id(skill, code, description):
    """The oracle's trace join key: sha256(skill 0x1f code 0x1f
    description)[:16] — mirrors skills/_shared/oracle/trace.finding_id."""
    h = hashlib.sha256()
    h.update(skill.encode("utf-8"))
    h.update(b"\x1f")
    h.update(code.encode("utf-8"))
    h.update(b"\x1f")
    h.update(description.encode("utf-8"))
    return h.hexdigest()[:16]


def _write_trace_record(trace_file, fid, skill, *, age_seconds=0,
                        verdict="STILL-FIRES"):
    """Append one Layer-A trace record with a controlled age."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    record = {
        "ts": ts.isoformat(timespec="seconds"),
        "layer": "A",
        "finding_id": fid,
        "skill": skill,
        "verdict": verdict,
        "evidence": "grep rc=0; match=yes",
        "procedure_version": "golden-test",
        "model_version": None,
        "latency_ms": 5,
        "cost_usd": None,
        "input": {"reproducer_type": "grep"},
        "schema_version": "1.0",
        "breadth": None,
    }
    trace_file.parent.mkdir(parents=True, exist_ok=True)
    with trace_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# (a) valid worklist → exit 0 + summary schema
# ---------------------------------------------------------------------------

def test_valid_worklist_exits_0_with_summary_schema(tmp_path):
    """Fresh Layer-A trace record + well-formed worklist: all three
    gates pass, exit 0, and the stdout JSON summary carries every field
    the Step-1 dispatch plan reads."""
    env = _isolated_env(tmp_path)
    worklist = _fixture(tmp_path, "valid.worklist.yaml")
    fid = _finding_id(
        "gather-repos", "D2",
        "SKILL.md cites scripts/sync.py but the script is missing",
    )
    _write_trace_record(tmp_path / "trace.jsonl", fid, "gather-repos",
                        age_seconds=60)

    rc, out, err = _run(str(worklist), env=env)
    assert rc == 0, f"expected exit 0, got {rc}\nstdout={out}\nstderr={err}"

    summary = json.loads(out)
    # Schema completeness — every field the orchestrator reads must exist.
    required = ["status", "worklist", "finding_count", "gates",
                "max_age_seconds", "trace_path", "findings"]
    missing = [k for k in required if k not in summary]
    assert not missing, f"summary missing fields: {missing}"

    assert summary["status"] == "ok"
    assert summary["finding_count"] == 1
    assert summary["gates"] == {
        "gate-1-malformed": "pass",
        "gate-2-stale": "pass",
        "gate-3-no-trace": "pass",
        "gate-4-error-verdict": "pass",
    }
    (entry,) = summary["findings"]
    for key in ("skill", "code", "finding_id", "reproducer_type",
                "trace_age_seconds", "verdict"):
        assert key in entry, f"finding entry missing {key!r}"
    assert entry["skill"] == "gather-repos"
    assert entry["finding_id"] == fid
    assert entry["verdict"] == "STILL-FIRES"
    assert 0 <= entry["trace_age_seconds"] <= 1800


# ---------------------------------------------------------------------------
# (b) malformed worklist → exit 2 naming gate 1
# ---------------------------------------------------------------------------

def test_malformed_worklist_trips_gate_1(tmp_path):
    """A worklist that violates the act-on format (finding with no
    reproducer block, missing fields) trips gate 1 (malformed)."""
    env = _isolated_env(tmp_path)
    worklist = _fixture(tmp_path, "malformed.worklist.yaml")

    rc, out, err = _run(str(worklist), env=env)
    assert rc == 2, f"expected exit 2, got {rc}\nstdout={out}\nstderr={err}"

    report = json.loads(out)
    assert report["status"] == "rejected"
    assert report["gates_tripped"] == ["gate-1-malformed"]
    assert all(r["gate"] == "gate-1-malformed" and r["gate_number"] == 1
               for r in report["rejections"])
    assert "gate-1-malformed" in err  # stderr names the gate + reason


def test_manual_reproducer_trips_gate_1(tmp_path):
    """The first Step-0 prose bullet: a finding whose reproducer is
    `type: manual` (no auto-check possible) is not dispatchable —
    gate 1 trips even though the YAML itself parses cleanly."""
    env = _isolated_env(tmp_path)
    worklist = _fixture(tmp_path, "manual.worklist.yaml")

    rc, out, err = _run(str(worklist), env=env)
    assert rc == 2, f"expected exit 2, got {rc}\nstdout={out}\nstderr={err}"

    report = json.loads(out)
    assert report["gates_tripped"] == ["gate-1-malformed"]
    (rejection,) = report["rejections"]
    assert rejection["skill"] == "gather-repos"
    assert "manual" in rejection["reason"]
    assert "gate-1-malformed" in err


# ---------------------------------------------------------------------------
# (c) stale worklist → exit 2 naming gate 2
# ---------------------------------------------------------------------------

def test_stale_trace_trips_gate_2(tmp_path):
    """A Layer-A trace record older than the 30-minute TTL trips
    gate 2 (stale): the worklist must be re-verified via act-on."""
    env = _isolated_env(tmp_path)
    worklist = _fixture(tmp_path, "stale.worklist.yaml")
    fid = _finding_id(
        "gather-intel", "A1",
        "manifest declares WebSearch but the tool is never invoked",
    )
    # Two hours old — well past the 1800s default TTL.
    _write_trace_record(tmp_path / "trace.jsonl", fid, "gather-intel",
                        age_seconds=7200)

    rc, out, err = _run(str(worklist), env=env)
    assert rc == 2, f"expected exit 2, got {rc}\nstdout={out}\nstderr={err}"

    report = json.loads(out)
    assert report["gates_tripped"] == ["gate-2-stale"]
    (rejection,) = report["rejections"]
    assert rejection["gate"] == "gate-2-stale"
    assert rejection["gate_number"] == 2
    assert rejection["finding_id"] == fid
    assert "TTL" in rejection["reason"]
    assert "gate-2-stale" in err


def test_fresh_trace_with_custom_ttl_trips_gate_2(tmp_path):
    """The TTL is operator-tunable: a 60s-old record passes the default
    gate but trips gate 2 under --max-age-seconds 10 (pins that
    staleness is measured against the flag, not a hardcoded constant)."""
    env = _isolated_env(tmp_path)
    worklist = _fixture(tmp_path, "stale.worklist.yaml")
    fid = _finding_id(
        "gather-intel", "A1",
        "manifest declares WebSearch but the tool is never invoked",
    )
    _write_trace_record(tmp_path / "trace.jsonl", fid, "gather-intel",
                        age_seconds=60)

    rc, out, _ = _run(str(worklist), env=env)
    assert rc == 0, f"60s-old record must pass the default TTL\n{out}"

    rc, out, err = _run(str(worklist), "--max-age-seconds", "10", env=env)
    assert rc == 2, f"expected exit 2 under a 10s TTL, got {rc}\n{out}"
    assert json.loads(out)["gates_tripped"] == ["gate-2-stale"]
    assert "gate-2-stale" in err


# ---------------------------------------------------------------------------
# (d) no-trace worklist → exit 2 naming gate 3
# ---------------------------------------------------------------------------

def test_no_trace_record_trips_gate_3(tmp_path):
    """A worklist referencing a finding with no Layer-A trace record
    (act-on wasn't run) trips gate 3 (no-trace)."""
    env = _isolated_env(tmp_path)
    worklist = _fixture(tmp_path, "no-trace.worklist.yaml")
    # No trace file is written at all.

    rc, out, err = _run(str(worklist), env=env)
    assert rc == 2, f"expected exit 2, got {rc}\nstdout={out}\nstderr={err}"

    report = json.loads(out)
    assert report["gates_tripped"] == ["gate-3-no-trace"]
    (rejection,) = report["rejections"]
    assert rejection["gate"] == "gate-3-no-trace"
    assert rejection["gate_number"] == 3
    assert rejection["skill"] == "scout-skills"
    assert "act-on" in rejection["reason"]
    assert "gate-3-no-trace" in err


def test_trace_for_different_finding_still_trips_gate_3(tmp_path):
    """A trace record for some OTHER finding doesn't satisfy gate 3 —
    the join is per finding_id, not per trace-file existence."""
    env = _isolated_env(tmp_path)
    worklist = _fixture(tmp_path, "no-trace.worklist.yaml")
    _write_trace_record(tmp_path / "trace.jsonl",
                        _finding_id("some-other-skill", "Z9", "unrelated"),
                        "some-other-skill", age_seconds=10)

    rc, out, _ = _run(str(worklist), env=env)
    assert rc == 2
    assert json.loads(out)["gates_tripped"] == ["gate-3-no-trace"]


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------

def test_help_short_circuits():
    """--help exits 0 and prints usage without touching any worklist
    or trace state."""
    rc, out, err = _run("--help")
    assert rc == 0, f"--help must exit 0, got {rc}\nstderr={err}"
    assert "usage" in out.lower()
    assert "gate" in out.lower()


def test_missing_worklist_is_operator_error_not_gate_trip(tmp_path):
    """A nonexistent worklist path is an operator error (exit 1), kept
    distinct from a gate rejection (exit 2) so orchestrators can tell
    'you typo'd the path' apart from 'the worklist is not dispatchable'."""
    env = _isolated_env(tmp_path)
    rc, out, err = _run(str(tmp_path / "does-not-exist.yaml"), env=env)
    assert rc == 1, f"expected exit 1, got {rc}\nstdout={out}\nstderr={err}"
    assert "not found" in err


# ---------------------------------------------------------------------------
# (h) ERROR verdict → exit 2 naming gate 4
# ---------------------------------------------------------------------------

def test_error_verdict_trips_gate_4(tmp_path):
    """A finding whose latest Layer-A verdict is ERROR has a broken
    reproducer — dispatching it wastes a fix-agent and produces an
    unexplainable batch-gate deviation (2026-08-22: two ERROR rows
    passed validation and needed hand-filtering)."""
    env = _isolated_env(tmp_path)
    worklist = _fixture(tmp_path, "valid.worklist.yaml")
    fid = _finding_id(
        "gather-repos", "D2",
        "SKILL.md cites scripts/sync.py but the script is missing",
    )
    _write_trace_record(tmp_path / "trace.jsonl", fid, "gather-repos",
                        age_seconds=60, verdict="ERROR")

    rc, out, err = _run(str(worklist), env=env)
    assert rc == 2, f"expected exit 2, got {rc}\nstdout={out}\nstderr={err}"
    report = json.loads(out)
    assert report["status"] == "rejected"
    assert "gate-4-error-verdict" in report["gates_tripped"]
    (rej,) = [r for r in report["rejections"]
              if r["gate"] == "gate-4-error-verdict"]
    assert rej["finding_id"] == fid
    assert "ERROR" in rej["reason"]
