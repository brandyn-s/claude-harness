#!/usr/bin/env python3
"""Tests for the mega-distill corpus-mode friction spine (Phase A, deterministic, no LLM):
  bin/transcript_friction.py    — per-session friction extractor (raw transcript -> signature histogram)
  bin/transcript_recurrence.py  — cross-session reduce (records -> breadth-ranked table)
  bin/transcript_friction_gate.py — grounding + arithmetic + no-stray gate

The spine is the anti-census core: it counts recurring FRICTION EVENTS by normalized SIGNATURE
across sessions and ranks by BREADTH (how many distinct sessions), because a pattern in 40/200
sessions is the systemic signal a per-session distill can't see. These tests pin: signature
normalization (volatile substrings stripped so the same event class groups), correction detection,
breadth aggregation, the no-fabrication / arithmetic gate, and the recurrence-ranking roundtrip."""
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


tf = _load("transcript_friction")
tr = _load("transcript_recurrence")


def _err(body):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "is_error": True, "content": body}]}}


def _user(text):
    return {"type": "user", "message": {"content": text}}


def _write(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


# ── transcript_friction.py ──────────────────────────────────────────────────────────────────────

def test_classify_error_known_signatures():
    """Real error bodies (grounded in eff98a2f) map to the right coarse signatures."""
    cases = {
        'PreToolUse:Bash hook error: bash-security-guard.py blocked rm -rf /tmp/x': "guard:bash-security",
        'bash-tail-buffering-guard BLOCKED: | tail': "guard:tail-buffering",
        '<tool_use_error>File has not been read yet. Read it first': "gate:read-before-edit",
        'EPERM: operation not permitted, open /Users/x': "fs:eperm",
        'Exit code 143\nCommand timed out after 2m 0s': "proc:timeout",
        'Permission for this action was denied by the Claude Code auto mode classifier': "deny:bash-classifier",
        "The user doesn't want to proceed with this tool use": "deny:user-rejected-tool",
        'No such tool available': "mcp:tool-unavailable",
    }
    for body, expect in cases.items():
        got = tf.classify_error(body)
        assert got == expect, f"{body[:40]!r} -> {got}, expected {expect}"
    print("[friction] known error signatures classify correctly OK")


def test_signature_strips_volatile_substrings():
    """Two occurrences of the SAME event class with different paths/pids/hex must collapse to ONE
    signature (FLAW-3 lesson: recurring events carry unique bodies; the class is the signal)."""
    a = tf.classify_error("weird error blah at /Users/a/foo.py:123 pid 4567 sha deadbeef1234")
    b = tf.classify_error("weird error blah at /Users/b/bar.py:999 pid 8888 sha cafef00d5678")
    assert a == b, f"same event class must group: {a!r} vs {b!r}"
    assert a.startswith("error:other:"), "unmatched body falls to normalized-prefix bucket"
    print("[friction] volatile substrings stripped; same class groups OK")


def test_extract_counts_errors_corrections_compaction():
    """A small transcript: 1 known guard block, 1 correction, 1 compaction boundary, 1 success
    (must be ignored). Histogram must reflect exactly those."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "s.jsonl")
        _write(src, [
            _user("do the thing"),
            _err("PreToolUse:Bash hook error: bash-tail-buffering-guard BLOCKED: | tail -5"),
            _user("no, that's wrong, you keep doing it"),                 # correction
            {"type": "user", "message": {"content": [                      # SUCCESS result -> ignored
                {"type": "tool_result", "is_error": False, "content": "ok"}]}},
            {"type": "system", "isCompactSummary": True},
        ])
        rec = tf.extract(src)
        sigs = rec["signatures"]
        assert sigs.get("guard:tail-buffering") == 1, sigs
        assert sigs.get("correction:user-rebuke") == 1, sigs
        assert sigs.get("session:compaction-boundary") == 1, sigs
        assert rec["counts"]["error"] == 1 and rec["counts"]["correction"] == 1
        assert rec["events_total"] == 3, "success result must NOT be counted"
        print("[friction] extract counts errors/corrections/compaction, ignores success OK")


def test_correction_long_instruction_not_flagged():
    """A long user turn that happens to contain a rebuke phrase is a fresh instruction, not a
    correction — must not inflate the correction count."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "s.jsonl")
        long_instruction = "Please build the following system. " + ("detail " * 120) + " you keep this in mind."
        _write(src, [_user(long_instruction)])
        rec = tf.extract(src)
        assert "correction:user-rebuke" not in rec["signatures"], "long instruction must not count as correction"
        print("[friction] long instruction not mis-flagged as correction OK")


# ── transcript_recurrence.py ────────────────────────────────────────────────────────────────────

def test_recurrence_ranks_by_breadth_not_frequency():
    """THE anti-census property: a signature in MANY sessions outranks one with higher raw count in
    ONE session. breadth (distinct sessions) is the sort key, not total."""
    records = [
        {"session": "s1", "signatures": {"guard:tail-buffering": 1, "proc:timeout": 50}},
        {"session": "s2", "signatures": {"guard:tail-buffering": 1}},
        {"session": "s3", "signatures": {"guard:tail-buffering": 1}},
    ]
    out = tr.aggregate(records, min_breadth=2)
    top = out["clusters"][0]
    assert top["signature"] == "guard:tail-buffering", "breadth (3 sessions) must outrank 1-session frequency (50)"
    assert top["breadth"] == 3 and top["total"] == 3
    # proc:timeout is breadth 1 -> dropped at min_breadth=2 (not 'recurring across sessions')
    assert all(c["signature"] != "proc:timeout" for c in out["clusters"]), "single-session sig dropped"
    print("[recurrence] ranks by breadth not frequency; min_breadth drops single-session OK")


def test_recurrence_breadth_pct_and_dedup():
    """breadth_pct is breadth/corpus_sessions; a session repeating a signature counts ONCE toward breadth."""
    records = [
        {"session": "s1", "signatures": {"gate:read-before-edit": 7}},   # 7 hits, 1 session
        {"session": "s2", "signatures": {"gate:read-before-edit": 2}},
        {"session": "s3", "signatures": {}},                              # zero-friction session
        {"session": "s4", "signatures": {}},
    ]
    out = tr.aggregate(records, min_breadth=2)
    c = out["clusters"][0]
    assert c["breadth"] == 2 and c["total"] == 9, c
    assert c["breadth_pct"] == 50.0, c["breadth_pct"]   # 2 of 4 corpus sessions
    assert out["corpus_sessions"] == 4
    print("[recurrence] breadth_pct correct; per-session breadth dedup OK")


# ── transcript_friction_gate.py ─────────────────────────────────────────────────────────────────

def test_gate_passes_clean_and_fails_fabricated():
    """Gate OK on a grounded table; FAIL (exit 3) when a cluster references a session not in cohort."""
    gate = os.path.join(BIN, "transcript_friction_gate.py")
    with tempfile.TemporaryDirectory() as d:
        cohort = os.path.join(d, "cohort.txt")
        with open(cohort, "w", encoding="utf-8") as fh:
            fh.write("s1\ns2\ns3\n")
        good = {"corpus_sessions": 3, "clusters": [
            {"signature": "guard:tail-buffering", "breadth": 2, "breadth_pct": 66.7,
             "total": 5, "sessions": ["s1", "s2"]}]}
        gp = os.path.join(d, "good.json")
        json.dump(good, open(gp, "w", encoding="utf-8"))
        r = subprocess.run(["python3", gate, "--recurrence", gp, "--cohort", cohort],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"clean table must pass: {r.stderr}"

        # fabricated: cluster cites s9 which is not in cohort
        bad = {"corpus_sessions": 3, "clusters": [
            {"signature": "x", "breadth": 2, "breadth_pct": 66.7, "total": 2, "sessions": ["s1", "s9"]}]}
        bp = os.path.join(d, "bad.json")
        json.dump(bad, open(bp, "w", encoding="utf-8"))
        r2 = subprocess.run(["python3", gate, "--recurrence", bp, "--cohort", cohort],
                            capture_output=True, text=True)
        assert r2.returncode == 3, "fabricated/stray session id must FAIL the gate"
        assert "GROUNDING" in r2.stderr
        print("[gate] passes clean, fails fabricated session id (exit 3) OK")


def test_gate_catches_arithmetic_drift():
    """A cluster whose breadth != unique-session-count must FAIL even if all ids are real."""
    gate = os.path.join(BIN, "transcript_friction_gate.py")
    with tempfile.TemporaryDirectory() as d:
        cohort = os.path.join(d, "cohort.txt")
        with open(cohort, "w", encoding="utf-8") as fh:
            fh.write("s1\ns2\ns3\n")
        drift = {"corpus_sessions": 3, "clusters": [
            {"signature": "x", "breadth": 3, "breadth_pct": 100.0, "total": 4, "sessions": ["s1", "s2"]}]}
        dp = os.path.join(d, "drift.json")
        json.dump(drift, open(dp, "w", encoding="utf-8"))
        r = subprocess.run(["python3", gate, "--recurrence", dp, "--cohort", cohort],
                           capture_output=True, text=True)
        assert r.returncode == 3 and "ARITHMETIC" in r.stderr, f"breadth drift must fail: {r.stderr}"
        print("[gate] catches arithmetic drift (breadth != unique sessions) OK")


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
