#!/usr/bin/env python3
"""Dedup / contradiction search over the knowledge base WITHOUT the memory-search MCP tool.

WHY THIS EXISTS: /capture's dedup gate (Step 3), contradiction gate (Step 4a),
and /distill's Step 3 all call `mcp__memory-search__memory_search`. When that
tool is unreachable — the server can show Connected while its registry entry
is dead in the current session, observed 2026-07-28 — the documented fallback
is "degrade to keyword Grep". That loses ranking entirely, and in practice the
recovery got hand-rolled from scratch each time, re-deriving the same two
traps:

  1. The index is a local SQLite DB with an FTS5 table
     (~/.claude/memory-search.db), so it is queryable directly. Grep is a
     needless downgrade.
  2. FTS5 treats bare punctuation as SYNTAX. A query containing `re-read` or
     `read:analytics` raises `sqlite3.OperationalError: no such column: read`
     — an error that reads like a schema bug and sends you the wrong way.
     Every term must be quoted.

This is BM25 relevance, not cosine similarity, so the skills' 0.85 / 0.7 /
0.65 cosine thresholds DO NOT transfer. Output is a ranked list for judgment;
a `--json` mode is provided so a caller can post-process. Any capture/distill
run that used this path must say so in its summary — the gate ran degraded.

Usage:
  kb-dedup.py "entry summary or claim" ["second query" ...]
  kb-dedup.py --scope all "query"        # include rules/, agent-memory/, skills/
  kb-dedup.py --json "query"
  kb-dedup.py --selftest                 # verify the DB + FTS are usable

Exit codes:
  0  ran (matches may be empty — an empty result is a legitimate NOVEL verdict)
  3  index unusable (missing DB, no FTS table) — caller must fall back to Grep
"""

import argparse
import json
import pathlib
import re
import sqlite3
import sys

DB = pathlib.Path.home() / ".claude" / "memory-search.db"
HOME = str(pathlib.Path.home())

SCOPES = {
    # The default: only KB topic pages, which is what capture dedups against.
    "topics": ("%knowledge-base/topics/%",),
    # distill Step 3 also needs rules / agent-memory / skills.
    "all": None,
}


def fts_query(text: str) -> str:
    """Build a safe FTS5 MATCH expression from free text.

    Every token is double-quoted so FTS5 never interprets punctuation as
    syntax. This is the trap that cost two failed queries on 2026-07-28:
    `re-read` and `read:analytics` both raise "no such column: <word>",
    which looks like a schema error and is really a tokenizer error.
    """
    terms = re.findall(r"[A-Za-z0-9_]+", text)
    terms = [t for t in terms if len(t) > 1]
    if not terms:
        raise ValueError(f"no usable search terms in {text!r}")
    return " OR ".join('"%s"' % t for t in terms)


def open_db():
    if not DB.exists():
        return None, f"index not found at {DB}"
    try:
        db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("SELECT 1 FROM chunks_fts LIMIT 1").fetchone()
        return db, None
    except sqlite3.Error as e:
        return None, f"index unusable: {e}"


def search(db, query: str, scope: str, limit: int):
    like = SCOPES.get(scope, SCOPES["topics"])
    sql = [
        "SELECT c.source_file, c.entry_title, bm25(chunks_fts) AS score",
        "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid",
        "WHERE chunks_fts MATCH ?",
    ]
    params: list[object] = [fts_query(query)]
    if like:
        sql.append("AND c.source_file LIKE ?")
        params.append(like[0])
    sql.append("ORDER BY score LIMIT ?")
    params.append(limit)
    rows = db.execute(" ".join(sql), params).fetchall()
    return [
        {
            "source": str(r["source_file"] or "").replace(HOME, "~"),
            "slug": pathlib.Path(str(r["source_file"] or "")).stem,
            "entry": str(r["entry_title"] or "")[:110],
            # BM25 is negative-better in SQLite; report it verbatim rather than
            # rescaling into something that could be mistaken for cosine.
            "bm25": round(r["score"], 2),
        }
        for r in rows
    ]


def selftest() -> int:
    db, err = open_db()
    if db is None:
        print(f"FAIL: {err}", file=sys.stderr)
        return 3
    n = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    # Punctuation-bearing probe: the exact shape that used to raise.
    hits = search(db, "re-read read:analytics drift-detection", "topics", 1)
    print(f"OK: {n} chunks indexed; punctuation-bearing query ran "
          f"({len(hits)} hit(s))")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="*")
    ap.add_argument("--scope", choices=sorted(SCOPES), default="topics")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.queries:
        ap.error("give at least one query, or --selftest")

    db, err = open_db()
    if db is None:
        print(f"{err}\nFall back to Grep over "
              f"~/Documents/knowledge-base/topics/ and say so in the summary.",
              file=sys.stderr)
        return 3

    results = {}
    for q in args.queries:
        try:
            results[q] = search(db, q, args.scope, args.limit)
        except ValueError as e:
            print(f"skipped {q!r}: {e}", file=sys.stderr)
            results[q] = []

    if args.json:
        print(json.dumps({"mode": "bm25-degraded", "scope": args.scope,
                          "results": results}, indent=2))
        return 0

    print("MODE: BM25 over the local index (memory-search MCP not used).")
    print("Cosine thresholds (0.85 / 0.7 / 0.65) DO NOT apply — judge by rank "
          "and by reading the matched entry.\n")
    for q, rows in results.items():
        print(f"=== {q[:96]}")
        if not rows:
            print("    (no match — NOVEL, pending your read)")
        for r in rows:
            print(f"    {r['bm25']:8.2f}  {r['slug']}")
            print(f"              {r['entry']}")
        print()
    print("Report in the run summary that semantic dedup ran in DEGRADED mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
