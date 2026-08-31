"""Verify integrity of all code-graph + code-search indexes.

Called by /healthcheck Check 11. Safe to run anytime — read-only, does not
lock or modify any index. Exits 0 if clean, 2 if any corruption detected.

Checks performed:

    code-graph (~/.cache/codebase-memory-mcp/*.db)
      - SQLite PRAGMA integrity_check (page-level corruption)
      - Orphan edges (source_id or target_id not in nodes)
      - Orphan embeddings (node_id not in nodes)
      - Orphan *.db-wal / *.db-shm sidecars (parent DB deleted)

    code-search (~/.claude_code_search/projects/*/index/)
      - chunk_ids.pkl size > 10 bytes (5-byte empty-pickle is the
        known 2026-04-20 corruption sentinel — see CORRUPTION_FIX_NOTES.md)
      - chunk_ids.pkl unpickles to a non-empty list
      - SQLite integrity on metadata.db and fts5.db
      - Aborted indexes (dir exists but missing code.index or chunk_ids.pkl)

Not reported as corruption (informational only):
  - Stale WAL files with pending data: SQLite replays on next open
  - Duplicate provider-hash project directories: disk waste, not corrupt
  - embeddings=0 in code-graph DBs: expected when VOYAGE_API_KEY unset
"""
from __future__ import annotations

import argparse
import json
import pickle
import sqlite3
import sys
from pathlib import Path

CG_CACHE = Path.home() / ".cache" / "codebase-memory-mcp"
CS_PROJECTS = Path.home() / ".claude_code_search" / "projects"


def _open_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)


# A "database is locked"/"busy" error is transient contention (a concurrent
# indexer holding the DB), NOT corruption. Tagging it lets main() classify it
# as WARN instead of failing the whole check (exit 2).
_BUSY = "BUSY (transient lock, not corruption — re-run when indexing settles): "


def _is_lock(e: Exception) -> bool:
    s = str(e).lower()
    return "locked" in s or "database is busy" in s


def check_codegraph_db(db_path: Path) -> list[str]:
    """Returns list of error strings (empty = clean)."""
    errs: list[str] = []
    try:
        conn = _open_ro(db_path)
    except Exception as e:
        prefix = _BUSY if _is_lock(e) else ""
        return [f"{prefix}{db_path.name}: open failed: {e}"]

    cur = conn.cursor()
    try:
        cur.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        if row and row[0] != "ok":
            errs.append(f"{db_path.name}: integrity_check: {row[0]}")
    except Exception as e:
        prefix = _BUSY if _is_lock(e) else ""
        errs.append(f"{prefix}{db_path.name}: integrity_check failed: {e}")

    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
    except Exception as e:
        errs.append(f"{db_path.name}: list tables: {e}")
        conn.close()
        return errs

    if "edges" in tables and "nodes" in tables:
        try:
            cur.execute(
                "SELECT COUNT(*) FROM edges e LEFT JOIN nodes n ON e.source_id = n.id WHERE n.id IS NULL"
            )
            src = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM edges e LEFT JOIN nodes n ON e.target_id = n.id WHERE n.id IS NULL"
            )
            tgt = cur.fetchone()[0]
            if src or tgt:
                errs.append(f"{db_path.name}: orphan edges: src={src} tgt={tgt}")
        except Exception as e:
            errs.append(f"{db_path.name}: orphan edge check: {e}")

    if "embeddings" in tables:
        try:
            cur.execute(
                "SELECT COUNT(*) FROM embeddings e LEFT JOIN nodes n ON e.node_id = n.id WHERE n.id IS NULL"
            )
            orp = cur.fetchone()[0]
            if orp:
                errs.append(f"{db_path.name}: orphan embeddings: {orp}")
        except Exception as e:
            errs.append(f"{db_path.name}: orphan embeddings check: {e}")

    conn.close()
    return errs


def check_orphan_sidecars(cache_dir: Path) -> list[str]:
    """Find *.db-wal / *.db-shm with no parent *.db."""
    errs: list[str] = []
    for sidecar in list(cache_dir.glob("*.db-wal")) + list(cache_dir.glob("*.db-shm")):
        parent = sidecar.with_name(sidecar.name.rsplit("-", 1)[0])
        if not parent.exists():
            errs.append(f"orphan sidecar: {sidecar.name} (parent {parent.name} missing)")
    return errs


def check_codesearch_project(proj_dir: Path) -> list[str]:
    errs: list[str] = []
    idx = proj_dir / "index"
    if not idx.exists():
        return []

    ck = idx / "chunk_ids.pkl"
    code_idx = idx / "code.index"
    md = idx / "metadata.db"
    fts = idx / "fts5.db"

    if code_idx.exists() and not ck.exists():
        errs.append(f"{proj_dir.name}: code.index present but chunk_ids.pkl missing (aborted index)")
    if ck.exists() and not code_idx.exists():
        errs.append(f"{proj_dir.name}: chunk_ids.pkl present but code.index missing (aborted index)")

    if ck.exists():
        size = ck.stat().st_size
        if size <= 10:
            errs.append(
                f"{proj_dir.name}: chunk_ids.pkl is {size} bytes (known-corrupt empty-pickle sentinel)"
            )
        else:
            try:
                with ck.open("rb") as f:
                    data = pickle.load(f)
                if not isinstance(data, list):
                    errs.append(f"{proj_dir.name}: chunk_ids.pkl is {type(data).__name__}, not list")
                elif len(data) == 0:
                    errs.append(f"{proj_dir.name}: chunk_ids.pkl unpickles to empty list")
            except Exception as e:
                errs.append(f"{proj_dir.name}: chunk_ids.pkl unpickle failed: {e}")

    for name, path in (("metadata.db", md), ("fts5.db", fts)):
        if not path.exists():
            continue
        try:
            conn = _open_ro(path)
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row and row[0] != "ok":
                errs.append(f"{proj_dir.name}: {name} integrity: {row[0]}")
            conn.close()
        except Exception as e:
            prefix = _BUSY if _is_lock(e) else ""
            errs.append(f"{prefix}{proj_dir.name}: {name} open failed: {e}")

    return errs


def _as_record(err: str, cg: bool) -> dict[str, str]:
    """Split an error string into its provenance and detail.

    Every check emits `"<name>: <detail>"` where name is the DB filename
    (code-graph) or the project dir (code-search). Parsing that back is
    deliberate: restructuring six check functions to return dicts would be a
    far larger change to a script whose human output other callers display.
    Tolerates a missing separator rather than raising on an unexpected shape.
    """
    body = err.removeprefix(_BUSY)
    name, _, detail = body.partition(": ")
    if not detail:  # no separator — keep the whole string as the detail
        name, detail = "", body
    rec = {"project": name[:-3] if cg and name.endswith(".db") else name,
           "detail": detail}
    if cg and name:
        rec["db_path"] = str(CG_CACHE / name)
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit machine-readable findings on stdout instead of the human report",
    )
    # Parsed strictly: an unknown flag is an ERROR, not silently ignored. This
    # script previously read no argv at all, so `--json` (which
    # session_start_modules/code_graph_health.py has always passed) was accepted
    # and ignored — the hook's structured-findings branch could never run, and
    # nothing surfaced that. A lenient parser would let the same class recur.
    args = ap.parse_args(argv)

    cg_errors: list[str] = []
    cs_errors: list[str] = []
    skipped = False

    if CG_CACHE.exists():
        for db in sorted(CG_CACHE.glob("*.db")):
            cg_errors.extend(check_codegraph_db(db))
        cg_errors.extend(check_orphan_sidecars(CG_CACHE))
    else:
        skipped = True
        if not args.as_json:
            print(f"Indexes: SKIP — {CG_CACHE} not found")

    cs_projects = []
    if CS_PROJECTS.exists():
        cs_projects = sorted(p for p in CS_PROJECTS.iterdir() if p.is_dir())
        for proj in cs_projects:
            cs_errors.extend(check_codesearch_project(proj))

    all_errors = cg_errors + cs_errors
    n_cg = len(list(CG_CACHE.glob("*.db"))) if CG_CACHE.exists() else 0
    n_cs = len(cs_projects)

    busy = [e for e in all_errors if e.startswith(_BUSY)]
    hard = [e for e in all_errors if not e.startswith(_BUSY)]

    if args.as_json:
        status = "fail" if hard else ("warn" if busy else ("skip" if skipped else "clean"))
        print(json.dumps({
            "status": status,
            "counts": {"code_graph_dbs": n_cg, "code_search_projects": n_cs},
            "code_graph_corruption": [
                _as_record(e, cg=True) for e in cg_errors if not e.startswith(_BUSY)
            ],
            "code_search_corruption": [
                _as_record(e, cg=False) for e in cs_errors if not e.startswith(_BUSY)
            ],
            "transient_locks": [_as_record(e, cg=False) for e in busy],
        }, indent=2))
        return 2 if hard else 0

    if hard:
        print(f"Indexes: FAIL — {len(hard)} issues across {n_cg} code-graph DBs + {n_cs} code-search projects")
        for e in hard:
            print(f"  {e}")
        if busy:
            print(f"  (+ {len(busy)} transient lock/busy, not counted as corruption — see WARN below)")
        print()
        print("To clean up aborted indexes or duplicates, review and run:")
        print("  python ~/.claude/scripts/cleanup-indexes.py            # dry-run")
        print("  python ~/.claude/scripts/cleanup-indexes.py --execute  # delete")
        return 2

    if busy:
        print(f"Indexes: WARN — {len(busy)} DB(s) locked/busy (transient contention, not corruption); re-run when indexing settles")
        for e in busy:
            print(f"  {e}")
        return 0

    print(f"Indexes: PASS — {n_cg} code-graph DBs + {n_cs} code-search projects clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
