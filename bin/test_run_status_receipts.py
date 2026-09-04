#!/usr/bin/env python3
"""Tests for the durable-receipt fields and the verified-success gate in run-status.

The behaviour under test (added 2026-07-26, audit Phase 1):

  * `start` captures execution IDENTITY (cwd, git toplevel/branch/HEAD, worktree
    flag, pid) plus task id and log/artifact paths, so a background run is
    auditable after the fact.
  * `done` REFUSES to write a `.done` marker without evidence. A `.done` is a
    verified-success claim, not a "we stopped looping" claim -- the same
    summary-as-success defect the workflow journals exhibited.
  * terminal_state is recorded explicitly and is never inferred from the absence
    of a failure.

All tests use a disposable CLAUDE_RUNS_DIR. Run:
    pytest bin/test_run_status_receipts.py -q
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_status", pathlib.Path(__file__).with_name("run-status.py")
)
assert _SPEC and _SPEC.loader
rs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rs)


@pytest.fixture()
def runs(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_RUNS_DIR", str(tmp_path / "runs"))
    return tmp_path / "runs"


def ns(**kw):
    import argparse

    base = {
        "id": "r1",
        "phase": None,
        "detail": None,
        "pct": None,
        "summary": None,
        "reason": None,
        "task_id": None,
        "log": None,
        "artifact": None,
        "verify_cmd": None,
        "verified_by": None,
        "force": False,
        "exit_code": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def status(runs, run_id="r1") -> dict:
    return json.loads((runs / run_id / "status.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# identity capture
# ---------------------------------------------------------------------------
def test_start_records_execution_identity(runs):
    assert rs.cmd_start(ns()) == 0
    st = status(runs)
    ident = st["identity"]
    assert ident["cwd"] == os.getcwd()
    assert isinstance(ident["pid"], int)
    # The git KEYS must always be present so a receipt always states whether the
    # run was version-pinned. Their VALUES are None when cwd is not inside a repo,
    # which is legitimate -- pytest may be invoked from anywhere, so asserting a
    # non-None HEAD here made the test depend on the caller's cwd.
    for key in ("git_toplevel", "git_branch", "git_head", "is_worktree"):
        assert key in ident, f"receipt must always record {key}"


def test_start_records_git_head_when_inside_a_repo(runs, monkeypatch):
    """Inside a git repo the identity fields must actually resolve."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    monkeypatch.chdir(repo)
    assert rs.cmd_start(ns(id="r-git")) == 0
    ident = status(runs, "r-git")["identity"]
    assert ident["git_head"], "git HEAD must be captured when cwd is inside a repo"
    assert ident["git_toplevel"]


def test_start_records_task_and_evidence_paths(runs):
    assert rs.cmd_start(ns(task_id="t-42", log="runs/r1/run.log", artifact="out.json")) == 0
    st = status(runs)
    assert st["task_id"] == "t-42"
    assert st["log_path"] == "runs/r1/run.log"
    assert st["artifact_path"] == "out.json"


def test_start_leaves_terminal_state_unknown(runs):
    """A fresh run must NOT read as successful."""
    rs.cmd_start(ns())
    st = status(runs)
    assert st["terminal_state"] is None
    assert st["verifier"] is None
    assert not (runs / "r1" / ".done").exists()


# ---------------------------------------------------------------------------
# the verified-success gate -- NEGATIVE FIXTURES FIRST
# ---------------------------------------------------------------------------
def test_done_without_evidence_is_refused(runs):
    """The core fix: success cannot be asserted with no evidence."""
    rs.cmd_start(ns())
    rc = rs.cmd_done(ns(summary="all good"))
    assert rc == 2, "done with no evidence must be refused"
    assert not (runs / "r1" / ".done").exists(), ".done must NOT be written"
    st = status(runs)
    assert st["terminal_state"] is None


def test_done_with_failing_verify_cmd_writes_fail_not_done(runs):
    """A failing verifier must produce .fail and withhold .done."""
    rs.cmd_start(ns())
    rc = rs.cmd_done(ns(verify_cmd="exit 3"))
    assert rc == 1
    assert not (runs / "r1" / ".done").exists()
    assert (runs / "r1" / ".fail").exists()
    st = status(runs)
    assert st["terminal_state"] == "failed"
    assert st["verifier"]["passed"] is False
    assert st["verifier"]["exit_code"] == 3


def test_done_with_passing_verify_cmd_writes_done(runs):
    rs.cmd_start(ns())
    assert rs.cmd_done(ns(verify_cmd="exit 0", summary="verified")) == 0
    assert (runs / "r1" / ".done").exists()
    st = status(runs)
    assert st["terminal_state"] == "completed_success"
    assert st["verifier"]["kind"] == "command"
    assert st["verifier"]["passed"] is True
    assert st["exit_code"] == 0


def test_done_with_attestation_is_recorded(runs):
    rs.cmd_start(ns())
    assert rs.cmd_done(ns(verified_by="operator diffed the output against baseline")) == 0
    st = status(runs)
    assert st["verifier"]["kind"] == "attestation"
    assert "baseline" in st["verifier"]["detail"]


def test_force_records_success_but_marks_it_unverified(runs):
    """--force must leave the missing evidence VISIBLE in the receipt."""
    rs.cmd_start(ns())
    assert rs.cmd_done(ns(force=True)) == 0
    st = status(runs)
    assert st["terminal_state"] == "completed_success"
    assert st["verifier"]["kind"] == "unverified"
    assert st["verifier"]["passed"] is None, "unverified must not claim passed=True"


def test_fail_records_exit_code(runs):
    rs.cmd_start(ns())
    assert rs.cmd_fail(ns(reason="boom", exit_code=42)) == 0
    st = status(runs)
    assert st["terminal_state"] == "failed"
    assert st["exit_code"] == 42
    assert (runs / "r1" / ".fail").exists()


def test_verify_cmd_output_tail_is_bounded(runs):
    """A verifier must not paste an unbounded log into the receipt."""
    rs.cmd_start(ns())
    rs.cmd_done(ns(verify_cmd="for i in $(seq 1 200); do echo line$i; done"))
    st = status(runs)
    assert len(st["verifier"]["output_tail"]) <= 5


def test_done_is_still_a_noop_on_unstarted_run_without_evidence(runs):
    """Refusal must apply even when no start record exists."""
    assert rs.cmd_done(ns(id="never-started")) == 2
    assert not (runs / "never-started" / ".done").exists()
