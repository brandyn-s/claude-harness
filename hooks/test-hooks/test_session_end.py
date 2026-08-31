"""Contract tests for the bounded SessionEnd receipt hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


HOOKS_DIR = Path(__file__).resolve().parent.parent
HOOK = HOOKS_DIR / "session-end.py"
PYTHON = sys.executable


def _run(tmp_path: Path, event: object):
    receipt_dir = tmp_path / "receipts"
    env = {
        **os.environ,
        "CLAUDE_SESSION_END_RECEIPT_DIR": str(receipt_dir),
        "CLAUDE_SESSION_RUNTIME_DIR": str(tmp_path / "runtime-seeds"),
    }
    started = time.monotonic()
    result = subprocess.run(
        [PYTHON, str(HOOK)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        cwd=str(HOOKS_DIR.parent),
        env=env,
    )
    return result, time.monotonic() - started, receipt_dir


def test_writes_minimal_private_receipt_without_output(tmp_path):
    event = {
        "session_id": "session-123",
        "transcript_path": "/tmp/session.jsonl",
        "cwd": "/tmp/project",
        "reason": "logout",
        "untrusted_extra": "must not persist",
    }
    result, elapsed, receipt_dir = _run(tmp_path, event)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert elapsed < 0.5
    receipt_path = receipt_dir / "session-123.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == 3
    assert receipt["session_id"] == "session-123"
    assert receipt["transcript_path"] == "/tmp/session.jsonl"
    assert receipt["cwd"] == "/tmp/project"
    assert receipt["reason"] == "logout"
    assert "untrusted_extra" not in receipt
    if os.name != "nt":
        assert receipt_path.stat().st_mode & 0o777 == 0o600


def test_session_end_does_not_trust_unsupported_model_or_effort_fields(tmp_path):
    event = {
        "session_id": "provenance-123",
        "transcript_path": "/tmp/provenance-123.jsonl",
        "requested_model": "claude-fable-5",
        "effective_model": "claude-opus-5",
        "fallback_model": "claude-opus-5",
        "effort_level": "high",
        "switch_reason": "model_safeguard",
        "stop_reason": "refusal",
    }
    result, _elapsed, receipt_dir = _run(tmp_path, event)

    assert result.returncode == 0
    receipt = json.loads((receipt_dir / "provenance-123.json").read_text())
    provenance = receipt["runtime_provenance"]
    assert provenance["requestedModel"] == "runtime-unknown"
    assert provenance["effectiveModel"] == "runtime-unknown"
    assert provenance["requestedEffort"] == "runtime-unknown"
    assert provenance["effectiveEffort"] == "runtime-unknown"
    assert provenance["switchReason"] == "runtime-unknown"
    assert provenance["refusalState"] == "runtime-unknown"
    assert provenance["evidenceStatus"] == "pending-transcript-enrichment"
    assert "model_provenance" not in receipt
    assert receipt["enrichment"]["status"] == "pending"
    assert receipt["enrichment"]["source"] == "transcript"


def test_receipt_uses_only_the_official_session_start_model_seed(tmp_path):
    seed_dir = tmp_path / "runtime-seeds"
    seed_dir.mkdir()
    (seed_dir / "seeded-session.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": "seeded-session",
                "session_start_model": "claude-fable-5",
                "session_start_source": "startup",
                "agent_type": "",
            }
        ),
        encoding="utf-8",
    )

    result, _elapsed, receipt_dir = _run(
        tmp_path,
        {
            "hook_event_name": "SessionEnd",
            "session_id": "seeded-session",
            "reason": "other",
        },
    )

    assert result.returncode == 0
    receipt = json.loads((receipt_dir / "seeded-session.json").read_text())
    provenance = receipt["runtime_provenance"]
    assert provenance["effectiveModel"] == "claude-fable-5"
    assert provenance["fieldSources"]["effectiveModel"] == "SessionStart.model"


def test_filename_cannot_escape_receipt_directory(tmp_path):
    result, _elapsed, receipt_dir = _run(
        tmp_path,
        {"session_id": "../../outside", "reason": "other"},
    )

    assert result.returncode == 0
    files = list(receipt_dir.glob("*.json"))
    assert len(files) == 1
    assert files[0].parent == receipt_dir
    assert not (tmp_path / "outside.json").exists()


def test_malformed_input_fails_open_without_creating_receipt(tmp_path):
    receipt_dir = tmp_path / "receipts"
    env = {**os.environ, "CLAUDE_SESSION_END_RECEIPT_DIR": str(receipt_dir)}
    result = subprocess.run(
        [PYTHON, str(HOOK)],
        input="{not-json",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        cwd=str(HOOKS_DIR.parent),
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert not receipt_dir.exists()


def test_source_has_no_heavy_or_network_operations():
    source = HOOK.read_text(encoding="utf-8")
    forbidden = (
        "subprocess",
        "requests",
        "urllib",
        "transcript_path).read",
        "git status",
        "run_strategic_synthesis",
        "pending-config",
    )
    assert all(token not in source for token in forbidden)


def test_default_receipts_are_ignored_by_the_config_checkout():
    """A normal SessionEnd must never dirty the live ~/.claude Git checkout."""
    repo = HOOKS_DIR.parent
    result = subprocess.run(
        ["git", "check-ignore", "-q", "session-end-receipts/probe.json"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, (
        "session-end-receipts/ is not ignored; every session end will dirty "
        "the live configuration checkout"
    )


def test_replaced_dormant_lifecycle_subgraphs_are_absent():
    """Git history, not executable dead code, is the rollback source."""
    retired = (
        HOOKS_DIR / "session-stop.py",
        HOOKS_DIR / "session_stop_modules" / "guardrail_capture.py",
        HOOKS_DIR / "session_stop_modules" / "strategic_synthesis.py",
        HOOKS_DIR / "instructions-loaded-validator.py",
        HOOKS_DIR / "manifests" / "session-stop.yaml",
        HOOKS_DIR / "manifests" / "instructions-loaded-validator.yaml",
    )
    assert not [path for path in retired if path.exists()]
