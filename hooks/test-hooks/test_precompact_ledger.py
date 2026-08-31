#!/usr/bin/env python3
"""Tests for precompact-ledger.py — persists the acceptance ledger before compaction.

These hooks run at compaction time, when a failure is maximally expensive: an
exception in PreCompact that exited non-zero would BLOCK compaction near the
context limit and end the session. So the tests emphasise the fail-open paths.

Each test isolates the home directory (HOME *and* USERPROFILE) so nothing touches
the real ~/.claude/session-ledgers.

Run: pytest hooks/test-hooks/test_precompact_ledger.py -q
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
# precompact-ledger: must ALWAYS exit 0 (never block compaction)
# ---------------------------------------------------------------------------
def test_precompact_creates_ledger_and_exits_zero(tmp_path):
    p = run_hook_isolated(PRECOMPACT, {"session_id": "s1", "cwd": "/repo"}, tmp_path)
    assert p.returncode == 0
    f = ledger_file(tmp_path, "s1")
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["compaction_count"] == 1
    assert data["cwd"] == "/repo"


def test_precompact_preserves_existing_entries(tmp_path):
    """A compaction must never wipe recorded acceptance state."""
    run_hook_isolated(PRECOMPACT, {"session_id": "s2"}, tmp_path)
    f = ledger_file(tmp_path, "s2")
    data = json.loads(f.read_text(encoding="utf-8"))
    data["entries"].append(
        {"kind": "rejected", "text": "no proxy", "restated": 0, "satisfied": None}
    )
    f.write_text(json.dumps(data), encoding="utf-8")

    run_hook_isolated(PRECOMPACT, {"session_id": "s2"}, tmp_path)
    again = json.loads(f.read_text(encoding="utf-8"))
    assert again["compaction_count"] == 2
    assert any(e["text"] == "no proxy" for e in again["entries"])


@pytest.mark.parametrize(
    "payload",
    [b"", b"not json", b"{}", b"[]", b'{"session_id": null}', b'{"session_id": 12345}'],
)
def test_precompact_never_blocks_on_bad_input(tmp_path, payload):
    """FAIL OPEN. A non-zero exit here would block compaction and end the session."""
    p = run_hook_isolated(PRECOMPACT, payload, tmp_path)
    assert p.returncode == 0, p.stderr.decode()


def test_precompact_exits_zero_when_ledger_dir_is_unwritable(tmp_path):
    """Disk/permission trouble must degrade to a warning, not a blocked compaction."""
    # Occupy the ledger directory path with a FILE so mkdir/write must fail.
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "session-ledgers").write_text("blocker", encoding="utf-8")
    p = run_hook_isolated(PRECOMPACT, {"session_id": "s3"}, tmp_path)
    assert p.returncode == 0
    # It should say something on stderr rather than fail silently.
    assert p.stderr  # a warning is expected


def test_precompact_writes_nothing_to_stdout(tmp_path):
    """PreCompact has no decision to make here; stray stdout could be parsed."""
    p = run_hook_isolated(PRECOMPACT, {"session_id": "s4"}, tmp_path)
    assert p.stdout.strip() == b""

# ---------------------------------------------------------------------------
# The stdin-drain race (regression, 2026-07-29)
#
# TWO hooks are registered on PreCompact and run SERIALLY over ONE shared stdin
# pipe: [0] precompact-checkpoint.py does `sys.stdin.read()`, which consumes the
# WHOLE stream, so [1] precompact-ledger.py (this hook) sees EOF and falls back
# to `{}` -> session_id "unknown". Measured before the fix: 113/113 audit records
# and the only ledger file all carried session_id="unknown", collapsing every
# session into one shared unknown.json with a merged compaction_count of 114.
#
# NOTE the existing tests above all pass an EXPLICIT payload, so none of them can
# ever observe this: they hand the hook exactly what the race removes. That is
# why the bug survived -- a self-confirming fixture (tdd-quality Gate 4). These
# tests drive EMPTY stdin, which is what the hook really receives in position 1.
# ---------------------------------------------------------------------------
def _write_checkpoint(home: Path, sid: str, age_secs: float, cwd: str = "/repo/x"):
    """Stand in for the sibling checkpoint hook, which already wrote what it read."""
    import time as _t

    d = home / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".precompact-state.json").write_text(
        json.dumps({"session_id": sid, "cwd": cwd, "timestamp": _t.time() - age_secs}),
        encoding="utf-8",
    )


def test_empty_stdin_recovers_session_id_from_fresh_checkpoint(tmp_path):
    """KILLS the mutation 'drop the _session_id_fallback() call'.

    With the fallback removed this writes unknown.json and the assert below fails.
    """
    _write_checkpoint(tmp_path, "402a8c9b", age_secs=0)
    p = run_hook_isolated(PRECOMPACT, b"", tmp_path)
    assert p.returncode == 0
    assert ledger_file(tmp_path, "402a8c9b").exists(), (
        "empty stdin must recover the real session_id from the sibling checkpoint, "
        "not collapse into unknown.json"
    )
    assert not ledger_file(tmp_path, "unknown").exists()
    data = json.loads(ledger_file(tmp_path, "402a8c9b").read_text(encoding="utf-8"))
    assert data["session_id"] == "402a8c9b"
    assert data["cwd"] == "/repo/x"


def test_empty_stdin_refuses_a_stale_checkpoint(tmp_path):
    """Freshness gate: a checkpoint from an EARLIER compaction must not be adopted.

    Mislabelling this compaction with a previous session's id is worse than
    "unknown", so past the 120s window the hook deliberately stays unknown.
    """
    _write_checkpoint(tmp_path, "402a8c9b", age_secs=300)
    p = run_hook_isolated(PRECOMPACT, b"", tmp_path)
    assert p.returncode == 0
    assert ledger_file(tmp_path, "unknown").exists()
    assert not ledger_file(tmp_path, "402a8c9b").exists()


def test_explicit_stdin_still_wins_over_checkpoint(tmp_path):
    """When stdin IS present (position 0), it is authoritative -- no regression."""
    _write_checkpoint(tmp_path, "wrong-id", age_secs=0)
    p = run_hook_isolated(PRECOMPACT, {"session_id": "s9", "cwd": "/real"}, tmp_path)
    assert p.returncode == 0
    assert ledger_file(tmp_path, "s9").exists()
    assert not ledger_file(tmp_path, "wrong-id").exists()
