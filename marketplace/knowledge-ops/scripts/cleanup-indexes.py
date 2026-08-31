"""Plan and execute cleanup of stale MCP indexes.

Referenced from /healthcheck Check 11 output when aborted indexes or
duplicate provider-hash directories are detected.

    python ~/.claude/scripts/cleanup-indexes.py            # dry-run (print plan)
    python ~/.claude/scripts/cleanup-indexes.py --execute  # actually delete

Deletion rule (empirically validated 2026-04-22):

    PHASE 1 — aborted indexes:
      code-graph  ~/.cache/codebase-memory-mcp/*.db under 200 KB with 0 nodes
      code-search ~/.claude_code_search/projects/*/index/ missing chunk_ids.pkl
                  OR missing code.index (both required for a working index)

    PHASE 2 — duplicate provider-hash directories:
      code-search projects follow the pattern {base}_{8hexdigits}.
      When the same base has multiple hashes, the hashes are stale embedding-
      provider fingerprints from provider migrations.

      Rule: KEEP the directory with the MOST chunks (pickled list length
            in chunk_ids.pkl); tiebreak on most recent mtime of
            index/code.index.

      Why chunks-first, not mtime-first: "newest wins" picked a 160-chunk
      partial re-index over a 4465-chunk healthy index for ~/.claude in
      testing. A smaller newer index is almost always a failed or
      narrower-scope re-run; larger is the substantive one.

      Why mtime tiebreak: when two copies have identical chunk counts
      (observed on mcp-infra, mcp-servers, memory-search — byte-identical
      dirs after provider migration), pick the one most recently touched.

Sidecar cleanup:
    After deleting a *.db, also remove *.db-wal and *.db-shm if present.
    Otherwise /healthcheck Check 11 flags them as orphans on next run.
"""
from __future__ import annotations

import datetime
import pickle
import shutil
import sys
from collections import defaultdict
from pathlib import Path

CG_CACHE = Path.home() / ".cache" / "codebase-memory-mcp"
CS_PROJECTS = Path.home() / ".claude_code_search" / "projects"


def chunk_count(p: Path) -> int:
    ck = p / "index" / "chunk_ids.pkl"
    if not ck.exists():
        return -1
    try:
        with ck.open("rb") as f:
            data = pickle.load(f)
        return len(data) if isinstance(data, list) else -1
    except Exception:
        return -1


def dir_mtime(p: Path) -> float:
    for c in (p / "index" / "code.index", p / "index", p):
        if c.exists():
            return c.stat().st_mtime
    return 0.0


def dir_size_bytes(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def bytes_human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def plan_phase1_aborted() -> list[Path]:
    """Aborted code-graph .db files (small + 0 nodes) and code-search index dirs
    missing chunk_ids.pkl or code.index."""
    targets: list[Path] = []

    if CG_CACHE.exists():
        import sqlite3
        for db in CG_CACHE.glob("*.db"):
            if db.stat().st_size > 200_000:
                continue
            try:
                conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes'")
                if not cur.fetchone():
                    conn.close()
                    continue
                cur.execute("SELECT COUNT(*) FROM nodes")
                n = cur.fetchone()[0]
                conn.close()
                if n == 0 and db.name != "_config.db":
                    targets.append(db)
            except Exception:
                pass

    if CS_PROJECTS.exists():
        for proj in CS_PROJECTS.iterdir():
            if not proj.is_dir():
                continue
            idx = proj / "index"
            if not idx.exists():
                continue
            ck = idx / "chunk_ids.pkl"
            code_idx = idx / "code.index"
            if ck.exists() != code_idx.exists():
                targets.append(proj)

    return targets


def plan_phase2_duplicates() -> tuple[list[Path], list[tuple[Path, int, float]]]:
    """Returns (to_delete, kept_records). kept_records = (dir, chunks, mtime)."""
    if not CS_PROJECTS.exists():
        return [], []

    by_base: dict[str, list[Path]] = defaultdict(list)
    for p in CS_PROJECTS.iterdir():
        if not p.is_dir():
            continue
        parts = p.name.rsplit("_", 1)
        if len(parts) == 2 and len(parts[1]) == 8 and all(
            c in "0123456789abcdef" for c in parts[1]
        ):
            by_base[parts[0]].append(p)

    to_delete: list[Path] = []
    kept: list[tuple[Path, int, float]] = []
    for _, dirs in sorted(by_base.items()):
        if len(dirs) == 1:
            continue
        ranked = sorted(dirs, key=lambda p: (chunk_count(p), dir_mtime(p)), reverse=True)
        winner = ranked[0]
        kept.append((winner, chunk_count(winner), dir_mtime(winner)))
        to_delete.extend(ranked[1:])
    return to_delete, kept


def remove_target(t: Path) -> None:
    """Remove a file or directory target, plus WAL/SHM sidecars if it's a .db."""
    if t.is_file():
        t.unlink()
        if t.suffix == ".db":
            for sidecar_suffix in (".db-wal", ".db-shm"):
                sidecar = t.with_name(t.stem + sidecar_suffix)
                if sidecar.exists():
                    sidecar.unlink()
    else:
        shutil.rmtree(t)


def main() -> int:
    execute = "--execute" in sys.argv

    p1 = plan_phase1_aborted()
    p2_dirs, p2_kept = plan_phase2_duplicates()

    print("=" * 80)
    print("PHASE 1: aborted indexes")
    print("=" * 80)
    p1_bytes = 0
    for t in p1:
        sz = t.stat().st_size if t.is_file() else dir_size_bytes(t)
        p1_bytes += sz
        print(f"  DELETE  {t}  ({bytes_human(sz)})")
    if not p1:
        print("  (nothing to do)")

    print()
    print("=" * 80)
    print("PHASE 2: duplicate provider-hash directories (keep largest by chunks)")
    print("=" * 80)
    if p2_kept:
        print("\nKEEPING:")
        for winner, chunks, mt in p2_kept:
            when = datetime.datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
            print(f"  KEEP    {winner.name:<50} chunks={chunks:>6}  {when}")
    p2_bytes = 0
    if p2_dirs:
        print("\nDELETING:")
        for d in p2_dirs:
            sz = dir_size_bytes(d)
            p2_bytes += sz
            when = datetime.datetime.fromtimestamp(dir_mtime(d)).strftime("%Y-%m-%d %H:%M")
            print(f"  DELETE  {d.name:<50} chunks={chunk_count(d):>6}  {when}  ({bytes_human(sz)})")
    else:
        print("  (no duplicates)")

    print()
    print("=" * 80)
    print(f"TOTAL to reclaim: {bytes_human(p1_bytes + p2_bytes)}")
    print("=" * 80)

    if not execute:
        if p1 or p2_dirs:
            print("\nDry-run. Re-run with --execute to delete.")
        return 0

    print("\nExecuting...")
    errors = 0
    for t in p1 + p2_dirs:
        try:
            remove_target(t)
            print(f"  ok: {t.name}")
        except Exception as e:
            errors += 1
            print(f"  FAIL: {t.name}: {e}")
    print(f"\nDone. {errors} error(s).")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
