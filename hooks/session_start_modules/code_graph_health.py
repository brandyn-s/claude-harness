"""SessionStart hook: surface code-graph indexes that need recovery.

Companion to `mcp_zombie_cleanup.py` (which clears stale processes) and
the new `internal/store/auto_recovery.go` (which optionally auto-recovers
corrupt DBs when CODE_GRAPH_AUTO_RECOVERY is set).

This module covers the gap: what about operators who DON'T enable
auto-recovery? They should see an actionable warning at SessionStart
when an index is in a manual-recovery state (Mode 4 corrupt header,
Mode 5 orphan sidecar, Mode 7 BulkWrite crash).

Implementation: invoke `verify-indexes.py --json` and surface each
corruption finding as a systemMessage. Read-only; never modifies an index.

The `--json` contract landed 2026-07-29. Before that the script parsed no
argv at all, so the flag was accepted-and-ignored, stdout was always the
human report, and this module's structured branch was unreachable — every
run fell through to the generic exit-code fallback, which is still kept for
an older checkout where the flag predates the script's support for it.

Budget: <2s. The verify-indexes.py script runs PRAGMA integrity_check
on each indexed DB. Typical workstation has 17 projects × ~50ms per
check ≈ 0.9s. Within the budget defined in the plan's Phase B3.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

VERIFY_INDEXES_SCRIPT = Path.home() / ".claude" / "scripts" / "verify-indexes.py"
TIMEOUT_SECS = 5  # hard ceiling; script's typical wall is <2s


def check_code_graph_health() -> list[str]:
    """Return list of warning strings for code-graph indexes needing recovery.

    Empty list = all indexes clean (steady state). Non-empty = at least one
    index has detectable corruption that wouldn't be auto-recovered if
    CODE_GRAPH_AUTO_RECOVERY is unset.

    Errors during invocation (script missing, timeout, parse failure) are
    silently swallowed — this hook is best-effort observability, not a
    correctness gate. Failure to run produces no warnings rather than a
    confusing message.
    """
    if not VERIFY_INDEXES_SCRIPT.exists():
        return []

    try:
        r = subprocess.run(
            [sys.executable, str(VERIFY_INDEXES_SCRIPT), "--json"],
            capture_output=True,
            timeout=TIMEOUT_SECS,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    # verify-indexes.py exits 0 if clean, 2 if corruption. Parse JSON
    # output if --json supported; otherwise fall back to exit code.
    if r.returncode == 0:
        return []

    out = r.stdout.decode("utf-8", errors="replace").strip()
    findings: list[str] = []

    # Try JSON first. Fields must match what verify-indexes.py --json actually
    # emits: project / detail / db_path. An earlier version read a `mode` key
    # that the script never produced, which would have rendered as
    # "mode=<unclassified>" on every finding had this branch ever executed --
    # it could not, because the script ignored argv entirely and always returned
    # human text, so every call fell through to the exit-code fallback below.
    try:
        data = json.loads(out)
        for item in data.get("code_graph_corruption", []):
            project = item.get("project") or "<unknown>"
            detail = item.get("detail") or "unspecified"
            db_path = item.get("db_path", "")
            where = f", db={db_path}" if db_path else ""
            findings.append(
                f"CODE-GRAPH HEALTH: {project} has detectable corruption "
                f"({detail}{where}). Run "
                f"`mcp__codebase-memory-mcp__delete_project(project_name=\"{project}\")` then "
                f"`mcp__codebase-memory-mcp__index_repository(repo_path=...)`. "
                f"Or set CODE_GRAPH_AUTO_RECOVERY=1 + restart Claude Code "
                f"to auto-recover on next open."
            )
        for item in data.get("code_search_corruption", []):
            project = item.get("project") or "<unknown>"
            detail = item.get("detail") or "unspecified"
            findings.append(
                f"CODE-SEARCH HEALTH: {project} has detectable corruption "
                f"({detail}). Run `python {VERIFY_INDEXES_SCRIPT}` for the full "
                f"report, then re-index that project."
            )
    except json.JSONDecodeError:
        # Fall back to summary line for stderr-style output.
        if r.returncode == 2:
            findings.append(
                f"CODE-GRAPH HEALTH: verify-indexes.py exited 2 (corruption "
                f"detected). Run `python {VERIFY_INDEXES_SCRIPT}` for "
                f"per-index diagnosis. Set CODE_GRAPH_AUTO_RECOVERY=1 to "
                f"enable auto-recovery on next OpenPath."
            )

    return findings
