"""Acceptance tests for distill's coordination-marker writer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WRITER = REPO_ROOT / "skills" / "distill" / "scripts" / "write_marker.py"
VALIDATOR = REPO_ROOT / "manifests" / "validate_markers.py"


def _run(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    env_updates: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    env = os.environ.copy()
    for name in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"):
        env.pop(name, None)
    env.update(env_updates or {})
    return subprocess.run(
        [
            sys.executable,
            str(WRITER),
            "--input",
            str(payload_path),
            "--state-root",
            str(tmp_path / "state"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _validate(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "last-distill", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_writer_computes_marker_fields_and_preserves_friction(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        {
            "metrics": {"total_turns": 7, "efficiency_pct": 86},
            "lessons": [
                {
                    "title": "Required checks can register late",
                    "tier": "SKILL-ROUTED",
                    "target": "skills/ship/SKILL.md",
                    "friction": "skill-misfire",
                }
            ],
        },
        env_updates={"CODEX_THREAD_ID": "codex-thread-123"},
    )

    assert result.returncode == 0, result.stderr
    marker_path = tmp_path / "state" / "last-distill.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["session_id"] == "codex-thread-123"
    assert marker["lesson_count"] == 1
    assert marker["lessons"][0]["friction"] == "skill-misfire"
    validation = _validate(marker_path)
    assert validation.returncode == 0, validation.stdout + validation.stderr
    assert not list((tmp_path / "state").glob(".last-distill-*.tmp"))


def test_writer_prefers_claude_code_id_over_legacy_id(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        {"lessons": []},
        env_updates={
            "CLAUDE_CODE_SESSION_ID": "canonical-claude-id",
            "CLAUDE_SESSION_ID": "legacy-id",
        },
    )

    assert result.returncode == 0, result.stderr
    marker = json.loads(
        (tmp_path / "state" / "last-distill.json").read_text(encoding="utf-8")
    )
    assert marker["session_id"] == "canonical-claude-id"
    assert marker["lesson_count"] == 0
    assert "metrics" not in marker


def test_writer_rejects_unknown_friction_without_overwriting_marker(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    marker_path = state_root / "last-distill.json"
    marker_path.write_text("original\n", encoding="utf-8")

    result = _run(
        tmp_path,
        {
            "lessons": [
                {
                    "title": "Bad category",
                    "tier": "T4",
                    "target": "topics/example.md",
                    "friction": "mystery",
                }
            ]
        },
    )

    assert result.returncode == 2
    assert "friction" in result.stderr
    assert marker_path.read_text(encoding="utf-8") == "original\n"


def test_writer_rejects_caller_supplied_derived_fields(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        {"session_id": "forged", "lesson_count": 99, "lessons": []},
    )

    assert result.returncode == 2
    assert "unsupported payload keys" in result.stderr
    assert not (tmp_path / "state" / "last-distill.json").exists()
