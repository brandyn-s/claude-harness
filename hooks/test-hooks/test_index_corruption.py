"""Tests for the codebase-memory index-corruption checker.

There were NO tests for this module before 2026-07-29, which is exactly why it
went on scanning `~/.claude_code_search/projects/` (the retired split
`code-search` server's storage) for months after the servers were consolidated
into `codebase-memory-mcp`. A checker pointed at a dead path reports "healthy"
forever and nothing fails — the silent-drift class in `check-before-change.md`.

Every positive case builds a REAL sqlite database, so the checks exercise the
actual sqlite behaviour rather than a mock's idea of it. Negative controls prove
the checker still detects corruption it is supposed to catch — a checker that
returns [] unconditionally would pass a clean-tree-only test.
"""

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent


def _load(monkeypatch, cache_dir: Path):
    """Import the module with CACHE_DIR pointed at a sandbox."""
    sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location(
        "index_corruption_under_test",
        HOOKS / "session_start_modules" / "index_corruption.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "CACHE_DIR", cache_dir)
    return mod


def _healthy_index(path: Path, nodes: int = 3) -> None:
    """Write a database with the shape a real index has."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE nodes (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE edges (src INTEGER, dst INTEGER)")
    for i in range(nodes):
        conn.execute("INSERT INTO nodes (name) VALUES (?)", (f"n{i}",))
        conn.execute("INSERT INTO edges VALUES (?, ?)", (i, i))
    conn.commit()
    conn.close()


def test_healthy_indexes_produce_no_findings(monkeypatch, tmp_path):
    """The common case: every index is fine, the banner stays quiet.

    Verified against all 19 live indexes on 2026-07-29 — every one reported
    quick_check=ok with nodes>0 and edges>0.
    """
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in ("repo-a", "repo-b", "repo-c"):
        _healthy_index(cache / f"{name}.db")

    mod = _load(monkeypatch, cache)
    assert mod.check_index_corruption() == []


def test_absent_cache_dir_is_not_a_finding(monkeypatch, tmp_path):
    """A host that has never indexed anything is not corrupt."""
    mod = _load(monkeypatch, tmp_path / "does-not-exist")
    assert mod.check_index_corruption() == []


def test_server_internal_db_is_not_audited(monkeypatch, tmp_path):
    """`_config.db` is server state, not a project index.

    It legitimately has neither `nodes` nor `edges`, so auditing it would emit a
    permanent unclearable finding — the same failure shape as the phantom
    `- Agent` CRITICAL fixed in consistency.py the same day.
    """
    cache = tmp_path / "cache"
    cache.mkdir()
    _healthy_index(cache / "repo-a.db")
    conn = sqlite3.connect(cache / "_config.db")
    conn.execute("CREATE TABLE settings (k TEXT, v TEXT)")
    conn.commit()
    conn.close()

    mod = _load(monkeypatch, cache)
    assert mod.check_index_corruption() == []


def test_wal_and_shm_sidecars_are_not_audited(monkeypatch, tmp_path):
    """Sidecars of an open database are normal, never findings on their own."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _healthy_index(cache / "repo-a.db")
    (cache / "repo-a.db-wal").write_bytes(b"\x00" * 32)
    (cache / "repo-a.db-shm").write_bytes(b"\x00" * 32)

    mod = _load(monkeypatch, cache)
    assert mod.check_index_corruption() == []


# ── NEGATIVE CONTROLS: real corruption must still be caught ────────────────


def test_zero_byte_index_is_caught(monkeypatch, tmp_path):
    """Indexing that died before its first write leaves an empty file."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _healthy_index(cache / "repo-a.db")
    (cache / "repo-broken.db").touch()

    mod = _load(monkeypatch, cache)
    findings = mod.check_index_corruption()
    assert len(findings) == 1, findings
    assert "repo-broken" in findings[0]
    assert "0 bytes" in findings[0]
    # The healthy sibling must NOT be swept in.
    assert "repo-a" not in findings[0]


def test_schema_only_index_is_caught(monkeypatch, tmp_path):
    """A valid DB with zero nodes was created but never populated.

    This is the live-layout expression of the legacy "index/ dir empty
    (indexing failed)" fingerprint — the mode that motivated the original check.
    """
    cache = tmp_path / "cache"
    cache.mkdir()
    _healthy_index(cache / "repo-empty.db", nodes=0)

    mod = _load(monkeypatch, cache)
    findings = mod.check_index_corruption()
    assert len(findings) == 1, findings
    assert "0 nodes" in findings[0]


def test_missing_graph_tables_are_caught(monkeypatch, tmp_path):
    """A DB without nodes/edges is not an index, however valid its sqlite."""
    cache = tmp_path / "cache"
    cache.mkdir()
    conn = sqlite3.connect(cache / "repo-wrongshape.db")
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()

    mod = _load(monkeypatch, cache)
    findings = mod.check_index_corruption()
    assert len(findings) == 1, findings
    assert "missing table" in findings[0]


def test_garbage_file_is_caught_not_raised(monkeypatch, tmp_path):
    """A truncated/half-written DB must be reported, never crash the hook.

    Session start must not fail because one index is broken.
    """
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "repo-garbage.db").write_bytes(b"this is not a sqlite database" * 40)

    mod = _load(monkeypatch, cache)
    findings = mod.check_index_corruption()  # must not raise
    assert len(findings) == 1, findings
    assert "repo-garbage" in findings[0]


def test_multiple_findings_are_all_reported(monkeypatch, tmp_path):
    """The count in the message must match the number of broken indexes."""
    cache = tmp_path / "cache"
    cache.mkdir()
    _healthy_index(cache / "ok-1.db")
    _healthy_index(cache / "ok-2.db")
    (cache / "bad-1.db").touch()
    _healthy_index(cache / "bad-2.db", nodes=0)

    mod = _load(monkeypatch, cache)
    findings = mod.check_index_corruption()
    assert len(findings) == 1, "findings are joined into one banner line"
    assert "(2)" in findings[0], f"expected 2 broken indexes: {findings[0]}"
    assert "bad-1" in findings[0] and "bad-2" in findings[0]


def test_message_does_not_reference_the_retired_server(monkeypatch, tmp_path):
    """Guards the actual 2026-07-29 regression.

    The old message said "CORRUPT code-search indexes" and told the operator to
    run `/index-repo --audit`, whose delete plan targeted the now-deleted legacy
    tree. Both would send someone to the wrong place.
    """
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "repo-broken.db").touch()

    mod = _load(monkeypatch, cache)
    findings = mod.check_index_corruption()
    assert findings
    assert "code-search" not in findings[0], (
        "message still names the retired split server"
    )
    assert "codebase-memory" in findings[0]
    assert "claude_code_search" not in str(mod.CACHE_DIR)


if __name__ == "__main__":  # standalone runner; guarded so pytest collection is a no-op
    sys.exit(pytest.main([__file__, "-v"]))
