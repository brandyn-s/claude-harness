#!/usr/bin/env python3
"""Tests for bin/transcript_meta.py — the mega-retro META-analysis pass (recurrence elevation +
rule-gap worklist). Deterministic, no LLM.

The meta-pass closes the gap measured 2026-06-21: mega-retro's context-isolated chunk extractors
produced 1 rule-gap / 0 why-was-I-wrong across 976 findings, because they can't see the rule
corpus or other chunks. The recurrence signal is computed for free by structural clustering;
this pass elevates it (a 24x guard-block is a 'the harness should change' meta-finding, not 24
separate friction notes)."""
import importlib.util
import json
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.abspath(os.path.join(HERE, "..", "..", "bin", "transcript_meta.py"))
spec = importlib.util.spec_from_file_location("transcript_meta", BIN)
tm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tm)


def _run(prep, final, threshold, out):
    return subprocess.run(
        ["python3", BIN, "--prep", prep, "--final", final,
         "--recur-threshold", str(threshold), "--out", out],
        capture_output=True, text=True,
    )


def test_recurrence_elevation_threshold():
    """Clusters with count >= threshold become recurrence meta-findings; below-threshold do not."""
    with tempfile.TemporaryDirectory() as d:
        prep = os.path.join(d, "prep.json")
        json.dump({"clusters": [
            {"signature": "guard:inline-python", "bucket": "errors_failures", "count": 24,
             "representative": "inline-python-guard blocked", "first_ground": "rec n=10"},
            {"signature": "guard:credential", "bucket": "errors_failures", "count": 3,
             "representative": "credential-guard blocked", "first_ground": "rec n=20"},
            {"signature": "friction:wasted-read", "bucket": "errors_failures", "count": 2,
             "representative": "wasted read", "first_ground": "rec n=30"},
        ]}, open(prep, "w", encoding="utf-8"))
        final = os.path.join(d, "final.json")
        json.dump({"summary": {"session": "test"}, "findings": []}, open(final, "w", encoding="utf-8"))
        out = os.path.join(d, "meta.json")
        r = _run(prep, final, 3, out)
        assert r.returncode == 0, r.stderr
        m = json.load(open(out, encoding="utf-8"))
        sigs = {x["signature"]: x["count"] for x in m["recurrence_meta_findings"]}
        # count>=3 elevated (24, 3), count=2 NOT elevated
        assert "guard:inline-python" in sigs and "guard:credential" in sigs
        assert "friction:wasted-read" not in sigs, "count=2 < threshold 3 must not elevate"
        # sorted by count descending
        counts = [x["count"] for x in m["recurrence_meta_findings"]]
        assert counts == sorted(counts, reverse=True)
        print("[meta] recurrence elevation respects threshold + sorts by count OK")


def test_rulegap_worklist_filters_to_distill_errors():
    """The rule-gap worklist carries only errors/abandoned findings tagged distill|both (the ones
    a meta agent should grep the rule corpus against) — not capture-only insights/decisions."""
    with tempfile.TemporaryDirectory() as d:
        prep = os.path.join(d, "prep.json")
        json.dump({"clusters": []}, open(prep, "w", encoding="utf-8"))
        final = os.path.join(d, "final.json")
        json.dump({"summary": {"session": "t"}, "findings": [
            {"_bucket": "errors_failures", "for": "distill", "summary": "e1", "ground": "rec n=1",
             "root_cause": "rc", "proposed_fix": "fix", "tier_hint": "T1-rule", "target_hint": "x.md"},
            {"_bucket": "errors_failures", "for": "both", "summary": "e2", "ground": "rec n=2"},
            {"_bucket": "decisions", "for": "capture", "summary": "d1", "ground": "rec n=3"},
            {"_bucket": "insights_patterns", "for": "capture", "summary": "i1", "ground": "rec n=4"},
            {"_bucket": "abandoned_approaches", "for": "distill", "summary": "a1", "ground": "rec n=5"},
        ]}, open(final, "w", encoding="utf-8"))
        out = os.path.join(d, "meta.json")
        r = _run(prep, final, 3, out)
        assert r.returncode == 0, r.stderr
        m = json.load(open(out, encoding="utf-8"))
        wl = m["rulegap_worklist"]
        summaries = {w["summary"] for w in wl}
        assert summaries == {"e1", "e2", "a1"}, f"worklist should be the 3 distill errors/abandoned, got {summaries}"
        # remediation fields preserved when present
        e1 = next(w for w in wl if w["summary"] == "e1")
        assert e1["tier_hint"] == "T1-rule" and e1["root_cause"] == "rc"
        print("[meta] rule-gap worklist filters to distill errors/abandoned + preserves fields OK")


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
