"""Behavior tests for the optional completion-claim measurement instrument."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
OBSERVER_PATH = REPO / "hooks" / "completion-claim-observer.py"
REPORT_PATH = REPO / "bin" / "completion-claim-report.py"

spec = importlib.util.spec_from_file_location("completion_claim_observer", OBSERVER_PATH)
observer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(observer)


def _line(role: str, content) -> str:
    return json.dumps({"message": {"role": role, "content": content}})


def test_same_turn_keeps_evidence_from_tool_results_before_a_later_read():
    raw = "\n".join(
        [
            _line("user", "Fix it and verify."),
            _line("assistant", [{"type": "tool_use", "id": "tests"}]),
            _line(
                "user",
                [{"type": "tool_result", "tool_use_id": "tests", "content": "3852 passed"}],
            ),
            _line("assistant", [{"type": "tool_use", "id": "read"}]),
            _line(
                "user",
                [{"type": "tool_result", "tool_use_id": "read", "content": "README contents"}],
            ),
            _line("assistant", [{"type": "text", "text": "Everything is now fixed."}]),
        ]
    )

    said, tool_output = observer.last_turn_text(raw)

    assert said == "Everything is now fixed."
    assert tool_output == "3852 passed\nREADME contents"
    assert observer.EVIDENCE.search(tool_output)


def test_report_rejects_one_hundred_unreadable_observations(tmp_path):
    log = tmp_path / "claims.jsonl"
    row = {
        "transcript_read": False,
        "claimed_done": False,
        "evidence_in_tool_output": False,
        "evidence_in_prose_only": False,
    }
    log.write_text("".join(json.dumps(row) + "\n" for _ in range(100)), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(REPORT_PATH), "--log", str(log), "--json"],
        text=True,
        capture_output=True,
        check=True,
    )
    report = json.loads(result.stdout)

    assert report["turns"] == 100
    assert report["readable_turns"] == 0
    assert report["sample_sufficient"] is False
