#!/usr/bin/env python3
"""Tests for postcompact-audit.py — the compaction drift auditor.

These hooks run at compaction time, when a failure is maximally expensive: an
exception in PreCompact that exited non-zero would BLOCK compaction near the
context limit and end the session. So the tests emphasise the fail-open paths.

Each test isolates the home directory (HOME *and* USERPROFILE) so nothing touches
the real ~/.claude/session-ledgers.

Run: pytest hooks/test-hooks/test_postcompact_audit.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent
PRECOMPACT = HOOKS / "precompact-ledger.py"
POSTCOMPACT = HOOKS / "postcompact-audit.py"


def run_hook_isolated(script: Path, payload, home: Path):
    """Invoke a hook with an isolated home directory so ledgers land in tmp.

    BOTH `HOME` and `USERPROFILE` are set: `Path.home()` reads `HOME` on POSIX but
    `USERPROFILE` on Windows, so a HOME-only overlay passes on macOS/Linux and fails
    ONLY on the Windows CI leg -- there with `RuntimeError: Could not determine home
    directory.`, because this env dict REPLACES the environment rather than
    extending it. See rules/tdd-quality.md item 10; caught by windows-2022 on
    PR #1727, which is the only leg that can catch it.

    PATH is inherited from the parent rather than hardcoded to POSIX paths, since
    `/usr/bin:/bin` is meaningless on Windows.
    """
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
    if isinstance(body, str):
        body = body.encode()
    return subprocess.run(
        [sys.executable, str(script)],
        input=body,
        capture_output=True,
        env=env,
        timeout=60,
    )


def ledger_file(home: Path, sid: str) -> Path:
    return home / ".claude" / "session-ledgers" / f"{sid}.json"


# ---------------------------------------------------------------------------
# postcompact-audit: observation only
# ---------------------------------------------------------------------------
def test_postcompact_is_silent_with_no_ledger(tmp_path):
    p = run_hook_isolated(
        POSTCOMPACT, {"session_id": "ghost", "compact_summary": "stuff"}, tmp_path
    )
    assert p.returncode == 0
    assert p.stdout.strip() == b""


def test_postcompact_flags_a_dropped_rejection(tmp_path):
    """THE DRIFT ALARM: a rejection missing from the summary must surface."""
    run_hook_isolated(PRECOMPACT, {"session_id": "s5"}, tmp_path)
    f = ledger_file(tmp_path, "s5")
    data = json.loads(f.read_text(encoding="utf-8"))
    data["entries"].append(
        {
            "kind": "rejected",
            "text": "never introduce an opt-in default",
            "restated": 0,
            "satisfied": None,
        }
    )
    f.write_text(json.dumps(data), encoding="utf-8")

    p = run_hook_isolated(
        POSTCOMPACT,
        {"session_id": "s5", "compact_summary": "We refactored unrelated helpers."},
        tmp_path,
    )
    assert p.returncode == 0
    out = json.loads(p.stdout.decode())
    assert "rejected" in out["systemMessage"].lower()


def test_postcompact_is_quiet_when_rejection_survives(tmp_path):
    """No alarm when the summary still carries the rejection -- avoids alarm fatigue."""
    run_hook_isolated(PRECOMPACT, {"session_id": "s6"}, tmp_path)
    f = ledger_file(tmp_path, "s6")
    data = json.loads(f.read_text(encoding="utf-8"))
    data["entries"].append(
        {"kind": "rejected", "text": "never introduce opt-in defaults",
         "restated": 0, "satisfied": None}
    )
    f.write_text(json.dumps(data), encoding="utf-8")

    p = run_hook_isolated(
        POSTCOMPACT,
        {"session_id": "s6",
         "compact_summary": "Decided to never introduce opt-in defaults; flipped it on."},
        tmp_path,
    )
    assert p.stdout.strip() == b""


def test_postcompact_writes_an_audit_log(tmp_path):
    run_hook_isolated(PRECOMPACT, {"session_id": "s7"}, tmp_path)
    run_hook_isolated(
        POSTCOMPACT, {"session_id": "s7", "compact_summary": "summary text"}, tmp_path
    )
    log = tmp_path / ".claude" / "session-ledgers" / "audits" / "s7.jsonl"
    assert log.exists()
    rec = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
    assert rec["session_id"] == "s7"
    assert "total_entries" in rec


@pytest.mark.parametrize("payload", [b"", b"not json", b"{}", b'{"session_id":"x"}'])
def test_postcompact_never_fails_on_bad_input(tmp_path, payload):
    p = run_hook_isolated(POSTCOMPACT, payload, tmp_path)
    assert p.returncode == 0


def test_postcompact_does_not_mutate_the_ledger(tmp_path):
    """An audit hook must be read-only with respect to acceptance state."""
    run_hook_isolated(PRECOMPACT, {"session_id": "s8"}, tmp_path)
    f = ledger_file(tmp_path, "s8")
    before = f.read_text(encoding="utf-8")
    run_hook_isolated(
        POSTCOMPACT, {"session_id": "s8", "compact_summary": "anything"}, tmp_path
    )
    assert f.read_text(encoding="utf-8") == before
