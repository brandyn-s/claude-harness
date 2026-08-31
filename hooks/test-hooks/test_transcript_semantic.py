#!/usr/bin/env python3
"""Tests for the mega-distill corpus-mode SEMANTIC layer (Phase B) deterministic scaffolding:
  bin/transcript_cohort.py        — cohort selection + coverage report (B1)
  bin/transcript_semantic_gate.py — completeness gate (B3) + cluster gate (B5)
  bin/transcript_cluster_input.py — lesson collation for clustering (B4 prep)

The LLM stages (B2 map, B4 cluster) are exercised live via Workflow, not unit-tested here; these
tests pin the DETERMINISTIC brackets that make the LLM output trustworthy: completeness (no silent
map under-delivery, FLAW-7), no-fabrication + coverage + deterministic breadth recompute (FLAW-4)."""
import importlib.util
import json
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.abspath(os.path.join(HERE, "..", "..", "bin"))


def _load(mod):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(BIN, mod + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cohort = _load("transcript_cohort")


def _write_lessons(d, sid, lessons):
    with open(os.path.join(d, f"lessons_{sid}.json"), "w", encoding="utf-8") as fh:
        json.dump({"session": sid, "lessons": lessons}, fh)


# ── transcript_cohort.py (B1) ────────────────────────────────────────────────────────────────────

def test_cohort_min_size_filter_and_coverage():
    """--min-size keeps only large sessions; coverage math reports the uncovered remainder."""
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "projects", "p")
        os.makedirs(proj)
        big = os.path.join(proj, "big.jsonl")
        small = os.path.join(proj, "small.jsonl")
        with open(big, "w", encoding="utf-8") as fh:
            fh.write("x" * 5000 + "\n")
        with open(small, "w", encoding="utf-8") as fh:
            fh.write("y\n")
        sel, full, full_n = cohort.select(os.path.join(d, "projects"), [], False,
                                          min_size=2000, min_lines=0, compacted=False)
        assert full_n == 2, full_n
        assert len(sel) == 1 and sel[0].endswith("big.jsonl"), sel
        print("[cohort] min-size filter selects only large sessions; full count correct OK")


def test_cohort_all_equals_full_corpus():
    """--all returns the full corpus as the cohort (friction-spine cohort)."""
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "projects", "p")
        os.makedirs(proj)
        for i in range(3):
            with open(os.path.join(proj, f"s{i}.jsonl"), "w", encoding="utf-8") as fh:
                fh.write("z\n")
        sel, full, full_n = cohort.select(os.path.join(d, "projects"), [], True, 0, 0, False)
        assert len(sel) == 3 and full_n == 3
        print("[cohort] --all -> cohort == full corpus OK")


def test_cohort_recursive_scan_across_project_dirs():
    """Scan is RECURSIVE — the corpus spans many per-repo/per-tmp project dirs (flaw #3: a single-dir
    scan missed ~63% of the corpus)."""
    with tempfile.TemporaryDirectory() as d:
        root = os.path.join(d, "projects")
        for sub in ("-", "-Users-x", "-Users-x/nested"):
            os.makedirs(os.path.join(root, sub), exist_ok=True)
            with open(os.path.join(root, sub, "a.jsonl"), "w", encoding="utf-8") as fh:
                fh.write("q\n")
        found = cohort._scan(root)
        assert len(found) == 3, f"recursive scan must find all 3 across dirs, got {len(found)}"
        print("[cohort] recursive scan finds transcripts across all project dirs OK")


# ── transcript_semantic_gate.py (B3 completeness + B5 cluster) ─────────────────────────────────────

def test_completeness_gate_passes_full_fails_missing():
    """B3: lesson file for every cohort session passes; a missing one fails (exit 3) — FLAW-7."""
    gate = os.path.join(BIN, "transcript_semantic_gate.py")
    with tempfile.TemporaryDirectory() as d:
        ld = os.path.join(d, "lessons")
        os.makedirs(ld)
        cohort_f = os.path.join(d, "cohort.txt")
        with open(cohort_f, "w", encoding="utf-8") as fh:
            fh.write("s1\ns2\n")
        _write_lessons(ld, "s1", [{"summary": "a"}])
        _write_lessons(ld, "s2", [])
        r = subprocess.run(["python3", gate, "--mode", "completeness", "--lessons-dir", ld,
                            "--cohort", cohort_f], capture_output=True, text=True)
        assert r.returncode == 0, f"full coverage must pass: {r.stderr}"
        # remove s2 -> missing -> fail
        os.remove(os.path.join(ld, "lessons_s2.json"))
        r2 = subprocess.run(["python3", gate, "--mode", "completeness", "--lessons-dir", ld,
                             "--cohort", cohort_f], capture_output=True, text=True)
        assert r2.returncode == 3 and "COMPLETENESS" in r2.stderr, f"missing lesson file must fail: {r2.stderr}"
        print("[semantic-gate] completeness passes full, fails on missing lesson file (exit 3) OK")


def test_cluster_gate_recomputes_breadth_and_catches_fabrication():
    """B5: breadth recomputed deterministically; coverage enforced; fabricated keys fail."""
    gate = os.path.join(BIN, "transcript_semantic_gate.py")
    with tempfile.TemporaryDirectory() as d:
        ld = os.path.join(d, "lessons")
        os.makedirs(ld)
        cohort_f = os.path.join(d, "cohort.txt")
        with open(cohort_f, "w", encoding="utf-8") as fh:
            fh.write("s1\ns2\n")
        _write_lessons(ld, "s1", [{"summary": "x"}, {"summary": "y"}])  # s1::0, s1::1
        _write_lessons(ld, "s2", [{"summary": "z"}])                     # s2::0

        # GOOD: all 3 keys assigned across 2 clusters; breadth recomputed.
        good = {"clusters": [
            {"name": "c1", "members": ["s1::0", "s2::0"], "breadth": 99},   # lies breadth=99
            {"name": "c2", "members": ["s1::1"]},
        ]}
        gp = os.path.join(d, "clusters.json")
        json.dump(good, open(gp, "w", encoding="utf-8"))
        outp = os.path.join(d, "verified.json")
        r = subprocess.run(["python3", gate, "--mode", "cluster", "--clusters", gp,
                            "--lessons-dir", ld, "--cohort", cohort_f, "--out", outp],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"full-coverage clusters must pass: {r.stderr}"
        verified = json.load(open(outp, encoding="utf-8"))
        c1 = [c for c in verified["clusters"] if c["name"] == "c1"][0]
        assert c1["breadth"] == 2, f"breadth must be RECOMPUTED to 2 (not the LLM's 99), got {c1['breadth']}"

        # BAD: a lesson key left unassigned (coverage failure).
        bad_cov = {"clusters": [{"name": "c1", "members": ["s1::0", "s2::0"]}]}  # s1::1 dropped
        json.dump(bad_cov, open(gp, "w", encoding="utf-8"))
        r2 = subprocess.run(["python3", gate, "--mode", "cluster", "--clusters", gp,
                             "--lessons-dir", ld, "--cohort", cohort_f], capture_output=True, text=True)
        assert r2.returncode == 3 and "COVERAGE" in r2.stderr, f"unassigned lesson must fail: {r2.stderr}"

        # BAD: fabricated key not in the map output.
        bad_fab = {"clusters": [{"name": "c1", "members": ["s1::0", "s1::1", "s2::0", "s9::5"]}]}
        json.dump(bad_fab, open(gp, "w", encoding="utf-8"))
        r3 = subprocess.run(["python3", gate, "--mode", "cluster", "--clusters", gp,
                             "--lessons-dir", ld, "--cohort", cohort_f], capture_output=True, text=True)
        assert r3.returncode == 3 and "NO-FABRICATION" in r3.stderr, f"fabricated key must fail: {r3.stderr}"
        print("[semantic-gate] cluster gate recomputes breadth, catches coverage gap + fabrication OK")


# ── transcript_cluster_input.py (B4 prep) ──────────────────────────────────────────────────────────

def test_cluster_input_collates_with_stable_keys():
    """Collation produces sid::index keys and a flat list the cluster gate can verify against."""
    ci = _load("transcript_cluster_input")
    with tempfile.TemporaryDirectory() as d:
        _write_lessons(d, "s1", [{"summary": "a", "kind": "insight"}, {"summary": "b", "kind": "error-pattern"}])
        _write_lessons(d, "s2", [{"summary": "c", "kind": "insight"}])
        out = ci.collate(d)
        assert out["n_sessions"] == 2 and out["n_lessons"] == 3, out
        keys = {le["key"] for le in out["lessons"]}
        assert keys == {"s1::0", "s1::1", "s2::0"}, keys
        print("[cluster-input] collates lessons with stable sid::index keys OK")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
