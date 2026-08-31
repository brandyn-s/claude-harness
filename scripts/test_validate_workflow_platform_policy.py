"""Contract tests for the validate workflow's platform policy.

Automatic CI validates the Claude Code architecture. It does not claim that
Windows, macOS, or Ubuntu are supported product surfaces. Platform-specific
compatibility runs are an operator-invoked diagnostic, not a merge gate.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "validate.yml"


def _job_block(text: str, job: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
        text,
    )
    assert match is not None, f"workflow job {job!r} is missing"
    return match.group(1)


def test_automatic_architecture_validation_is_not_an_os_matrix():
    text = WORKFLOW.read_text(encoding="utf-8")
    job = _job_block(text, "architecture-validate")

    assert "strategy:" not in job
    assert "matrix." not in job
    assert "runs-on:" in job
    assert "ubuntu-24.04" in job
    assert "matrix-validate:" not in text
    assert "Detect platform-relevant changes" not in text


def test_platform_compatibility_is_only_operator_invoked():
    text = WORKFLOW.read_text(encoding="utf-8")
    job = _job_block(text, "architecture-validate")

    assert "\n  schedule:" not in text
    assert "workflow_dispatch:" in text
    assert "runner:" in text
    assert "type: choice" in text
    for runner in ("ubuntu-24.04", "windows-2022", "macos-14"):
        assert f"          - {runner}" in text

    assert "github.event_name == 'workflow_dispatch'" in job
    assert "inputs.runner" in job
