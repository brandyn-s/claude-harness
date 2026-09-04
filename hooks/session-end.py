"""Write a bounded, durable receipt when a Claude Code session ends.

SessionEnd is a latency-sensitive lifecycle event. This hook records only the
fields needed to locate and process a finished session later; it does not scan
the transcript, inspect repositories, call the network, or mutate knowledge
and configuration state. Rich analysis remains an explicit ``/retro`` or
scheduled workflow.

The hook is fail-open and intentionally emits no stdout. SessionEnd cannot
control whether the session exits, so output would only add noise.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomic_write import atomic_write
from session_runtime import (
    bounded as _bounded,
)
from session_runtime import (
    initial_runtime_provenance,
    read_session_start_seed,
    safe_session_filename,
)

SCHEMA_VERSION = 3


def _receipt_dir() -> Path:
    override = os.environ.get("CLAUDE_SESSION_END_RECEIPT_DIR")
    return Path(override) if override else Path.home() / ".claude" / "session-end-receipts"


def write_receipt(event: dict) -> Path:
    """Atomically persist the minimal SessionEnd event and return its path."""

    session_id = _bounded(event.get("session_id")) or "unknown"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "transcript_path": _bounded(event.get("transcript_path")),
        "cwd": _bounded(event.get("cwd")),
        "reason": _bounded(event.get("reason")),
        "runtime_provenance": initial_runtime_provenance(
            read_session_start_seed(session_id)
        ),
        "enrichment": {
            "status": "pending",
            "source": "transcript",
        },
        "ended_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt_dir = _receipt_dir()
    receipt_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = receipt_dir / safe_session_filename(session_id)
    atomic_write(path, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        if not isinstance(event, dict):
            event = {}
        write_receipt(event)
    except Exception:  # noqa: S110, BLE001 -- fail-open: receipt capture is observability only
        # Receipt capture is observability, never a reason to block exit.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
