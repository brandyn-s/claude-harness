"""Check codebase-memory on-disk indexes for corruption.

Complements index_staleness.py — staleness is "index is valid but behind
git HEAD", this is "index is physically broken on disk."

REPOINTED 2026-07-29. This previously walked `~/.claude_code_search/projects/*/`,
the storage of the SPLIT `code-search` server — which is not registered on this
host (`claude mcp list` has no `code-search` entry; the servers were consolidated
into `codebase-memory-mcp`). So it audited a graveyard it could never clean while
being blind to the 19 indexes actually in use, and the one entry it did flag was
an orphaned throwaway test fixture. The legacy tree (934 MB: 211 MB indexes,
624 MB regenerable embedding cache, 87 MB models; `query_history` empty) was
removed in the same change after confirming no config referenced it and no
process held it open.

This is the MCP-consolidation drift class from `check-before-change.md`: renaming
or merging a server leaves consumers wired by string match, and they fail
SILENTLY — a checker pointed at a dead path reports "healthy" forever.

The live store is FLAT SQLite, one `<project>.db` per repo — not a per-project
directory of FAISS artifacts — so the legacy fingerprints (missing `code.index`,
5-byte `chunk_ids.pkl`) do not exist here and are gone. The signals below were
derived empirically against all 19 live indexes on 2026-07-29 (every one:
`quick_check=ok`, nodes>0, edges>0).

Never blocks session start on failure.
"""

import sqlite3
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "codebase-memory-mcp"

# `_config.db` is server state, not a project index. WAL/SHM sidecars are normal
# runtime artifacts of an open database, never audited on their own.
_INTERNAL_PREFIX = "_"

# A real index always has graph content. An empty-but-valid DB means indexing
# created the schema then failed before writing — the "silently failed" mode the
# legacy empty-index/ check was there to catch, expressed in this layout.
_GRAPH_TABLES = ("nodes", "edges")

# `PRAGMA quick_check` over `integrity_check`: quick_check skips the (expensive)
# index-vs-table cross-verification, which on the 684 MB monorepo index is the
# difference between a fast session start and a stall. It still detects page-level
# corruption, which is what a truncated or half-written DB looks like.
_INTEGRITY_PRAGMA = "PRAGMA quick_check"

# Session start has a strict budget (see index_staleness.GRAPH_SWEEP_DEADLINE_SECS
# for the sibling constraint). A corrupt DB can make sqlite block; cap every open.
_SQLITE_TIMEOUT_SECS = 2


def _index_issue(db_path: Path) -> str | None:
    """Return a short failure reason, or None if the index looks healthy."""
    try:
        if db_path.stat().st_size == 0:
            return "0 bytes (indexing failed before any write)"
    except OSError:
        return "unreadable on disk"

    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True, timeout=_SQLITE_TIMEOUT_SECS
        )
    except sqlite3.Error as exc:
        return f"cannot open ({type(exc).__name__})"

    try:
        verdict = conn.execute(_INTEGRITY_PRAGMA).fetchone()
        if not verdict or verdict[0] != "ok":
            detail = (verdict[0] if verdict else "no result").split("\n")[0][:60]
            return f"sqlite integrity: {detail}"

        present = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = [t for t in _GRAPH_TABLES if t not in present]
        if missing:
            return f"missing table(s): {', '.join(missing)}"

        # An index with zero nodes is schema-only — created, never populated.
        node_count = conn.execute("SELECT count(*) FROM nodes").fetchone()[0]
        if node_count == 0:
            return "0 nodes (schema created but never populated)"
    except sqlite3.DatabaseError as exc:
        return f"query failed ({type(exc).__name__})"
    finally:
        conn.close()

    return None


def check_index_corruption():
    """Scan on-disk codebase-memory indexes for corruption fingerprints.

    Returns a list of warning strings (empty if healthy or the cache is absent).
    """
    if not CACHE_DIR.is_dir():
        return []

    findings: list[tuple[str, str]] = []
    try:
        for db_path in sorted(CACHE_DIR.glob("*.db")):
            if db_path.name.startswith(_INTERNAL_PREFIX):
                continue
            reason = _index_issue(db_path)
            if reason:
                findings.append((db_path.stem, reason))
    except OSError:
        return []

    if not findings:
        return []

    lines = [f"{name} — {reason}" for name, reason in findings]
    return [
        "CORRUPT codebase-memory indexes detected on disk ({n}): {items}. "
        "Re-index with /index-repo <path> to rebuild.".format(
            n=len(findings),
            items="; ".join(lines),
        )
    ]
