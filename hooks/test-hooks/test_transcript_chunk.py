#!/usr/bin/env python3
"""Completeness proof for bin/transcript_chunk.py — the "nothing dropped" invariant.

These tests are the load-bearing guarantee of the whole long-session-retro design: if the
chunker preserves every byte, no downstream extraction step can lose data the chunker kept.
They run with ZERO LLM cost and are deterministic.

Two invariant families:
  non-overlap mode:
    - concat(chunks in order) is BYTE-EXACT equal to the input file
    - sum(lines per chunk) == input line count
    - chunk spans partition the line range with no gaps and no overlaps
  overlap mode:
    - UNION of chunk line-sets covers every input line (no line missing)
    - the ONLY duplication is the declared backward margin (exact-margin accounting)
    - forward coverage reaches the last line

Run against real giant transcripts when present (the true test), plus a synthetic fixture with
hand-placed compaction boundaries (always runs, fast, CI-safe).
"""
import glob
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.abspath(os.path.join(HERE, "..", "..", "bin", "transcript_chunk.py"))

# import the module under test
spec = importlib.util.spec_from_file_location("transcript_chunk", BIN)
tc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tc)


# ---------- helpers ----------

def _make_synthetic(path, n_lines=2000, boundary_every=400):
    """Write a synthetic JSONL with compaction boundaries at known positions.

    Lines vary in size (some big to force mid-segment splits at a small budget).
    """
    import json
    with open(path, "wb") as fh:
        for i in range(n_lines):
            if i % boundary_every == 0 and i > 0:
                rec = {"type": "system", "isCompactSummary": True, "i": i}
            else:
                # vary payload size; every 50th line is large to force budget splits
                pad = "x" * (4000 if i % 50 == 0 else 80)
                rec = {"type": "assistant", "i": i, "pad": pad}
            fh.write((json.dumps(rec) + "\n").encode("utf-8"))


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _line_count(path):
    n = 0
    with open(path, "rb") as fh:
        for _ in fh:
            n += 1
    return n


# ---------- non-overlap invariants ----------

def _assert_non_overlap_complete(src, budget):
    spans, line_bytes, boundaries, n_lines = tc.plan_chunks(
        src, budget_tokens=budget, overlap_lines=0, mode="non-overlap"
    )
    # spans partition [0, n_lines) with no gaps / no overlaps
    assert spans[0][0] == 0, f"first chunk must start at line 0, got {spans[0][0]}"
    assert spans[-1][1] == n_lines, f"last chunk must end at {n_lines}, got {spans[-1][1]}"
    for k in range(1, len(spans)):
        assert spans[k][0] == spans[k - 1][1], (
            f"gap/overlap between chunk {k-1} {spans[k-1]} and {k} {spans[k]}"
        )
    # line conservation
    total = sum(e - s for s, e in spans)
    assert total == n_lines, f"line conservation: sum(spans)={total} != n_lines={n_lines}"

    # byte-exact reconstruction via the actual write path
    with tempfile.TemporaryDirectory() as d:
        paths = tc.write_chunks(src, spans, d)
        recon = b"".join(_read_bytes(p) for p in paths)
        assert recon == _read_bytes(src), "non-overlap: concat(chunks) != input (BYTES DIFFER)"
    return spans, boundaries, n_lines


def _assert_overlap_complete(src, budget, overlap_lines):
    spans, line_bytes, boundaries, n_lines = tc.plan_chunks(
        src, budget_tokens=budget, overlap_lines=overlap_lines, mode="overlap"
    )
    # union coverage: every line index appears in >=1 span
    covered = set()
    for s, e in spans:
        covered.update(range(s, e))
    assert covered == set(range(n_lines)), "overlap: union of chunks does NOT cover every line"
    # forward end reaches the last line
    assert max(e for _, e in spans) == n_lines
    # exact-margin duplication accounting: total span-lines minus n_lines == sum of per-boundary
    # margins. Each chunk after the first prepends min(overlap_lines, its_original_start) lines.
    nonov_spans, *_ = tc.plan_chunks(src, budget_tokens=budget, overlap_lines=0, mode="non-overlap")
    expected_dupe = 0
    for k in range(1, len(nonov_spans)):
        orig_start = nonov_spans[k][0]
        expected_dupe += min(overlap_lines, orig_start)
    total_span_lines = sum(e - s for s, e in spans)
    actual_dupe = total_span_lines - n_lines
    assert actual_dupe == expected_dupe, (
        f"overlap dup accounting: actual={actual_dupe} expected={expected_dupe}"
    )
    return spans, boundaries, n_lines


# ---------- tests: synthetic (always run) ----------

def test_synthetic_non_overlap():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "syn.jsonl")
        _make_synthetic(src)
        # small budget to force many mid-segment splits
        spans, boundaries, n = _assert_non_overlap_complete(src, budget=50_000)
        assert len(spans) > 1, "synthetic should produce multiple chunks at small budget"
        print(f"[synthetic non-overlap] {n} lines -> {len(spans)} chunks, {len(boundaries)} boundaries OK")


def test_synthetic_overlap():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "syn.jsonl")
        _make_synthetic(src)
        spans, boundaries, n = _assert_overlap_complete(src, budget=50_000, overlap_lines=25)
        print(f"[synthetic overlap] {n} lines -> {len(spans)} chunks OK")


def test_synthetic_boundary_preference():
    """A new chunk should start at each compaction boundary (when budget allows a chunk there)."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "syn.jsonl")
        _make_synthetic(src, n_lines=2000, boundary_every=400)
        spans, line_bytes, boundaries, n_lines = tc.plan_chunks(
            src, budget_tokens=10_000_000, overlap_lines=0, mode="non-overlap"
        )
        # With an enormous budget, the ONLY reason to split is a boundary. So chunk starts
        # (after 0) must be exactly the boundary line indices.
        starts = [s for s, _ in spans][1:]
        assert starts == boundaries, f"boundary-preference: starts {starts} != boundaries {boundaries}"
        print(f"[synthetic boundary-pref] splits exactly at {len(boundaries)} boundaries OK")


# ---------- tests: real transcripts (run when present) ----------

def _real_transcripts(limit_mb=80):
    proj = os.path.expanduser("~/.claude/projects/-Users-you")
    files = sorted(glob.glob(os.path.join(proj, "*.jsonl")), key=os.path.getsize, reverse=True)
    # take the biggest few that are under the safety limit
    return [f for f in files if os.path.getsize(f) < limit_mb * 1_000_000][:3]


def test_real_non_overlap_byte_exact():
    files = _real_transcripts()
    if not files:
        print("[real] no transcripts present; skipping")
        return
    for src in files:
        mb = os.path.getsize(src) / 1e6
        spans, boundaries, n = _assert_non_overlap_complete(src, budget=600_000)
        print(f"[real non-overlap] {os.path.basename(src)[:8]} {mb:.1f}MB {n} lines "
              f"-> {len(spans)} chunks, {len(boundaries)} boundaries, BYTE-EXACT OK")


def test_real_overlap_coverage():
    files = _real_transcripts()
    if not files:
        print("[real] no transcripts present; skipping")
        return
    for src in files:
        mb = os.path.getsize(src) / 1e6
        spans, boundaries, n = _assert_overlap_complete(src, budget=600_000, overlap_lines=40)
        print(f"[real overlap] {os.path.basename(src)[:8]} {mb:.1f}MB {n} lines "
              f"-> {len(spans)} chunks, coverage+margin OK")


# ---------- tests: grounding-validation gate (Phase C integrity) ----------

def _load_ground_check():
    gpath = os.path.abspath(os.path.join(HERE, "..", "..", "bin", "transcript_ground_check.py"))
    gspec = importlib.util.spec_from_file_location("transcript_ground_check", gpath)
    mod = importlib.util.module_from_spec(gspec)
    gspec.loader.exec_module(mod)
    return mod


def test_ground_check_catches_out_of_range():
    """The gate must flag findings citing a record number beyond the chunk's real count.

    Regression guard for the 2026-06-20 extractor-hallucination flaw: a subagent that read 436
    records cited rec n=1032 / n=1035. The gate partitions valid (in-range) from flagged
    (out-of-range / ungrounded) deterministically, with no LLM."""
    gc = _load_ground_check()
    findings = [
        {"summary": "real", "ground": "rec n=19"},
        {"summary": "real-edge-low", "ground": "rec n=1"},
        {"summary": "real-edge-high", "ground": "rec n=436"},
        {"summary": "hallucinated", "ground": "rec n=1032"},
        {"summary": "hallucinated2", "ground": "rec n=1035"},
        {"summary": "ungrounded", "ground": "see above"},
        {"summary": "nonpositive", "ground": "rec n=0"},
    ]
    valid, flagged, reasons = gc.validate(findings, record_count=436)
    assert len(valid) == 3, f"expected 3 valid, got {len(valid)}"
    assert len(flagged) == 4, f"expected 4 flagged, got {len(flagged)}"
    assert reasons["out_of_range"] == 2
    assert reasons["ungrounded"] == 1
    assert reasons["nonpositive"] == 1
    # the in-range edges (1 and 436) must be VALID, not flagged
    valid_summaries = {f["summary"] for f in valid}
    assert valid_summaries == {"real", "real-edge-low", "real-edge-high"}
    print("[ground-check] 3 valid / 4 flagged (2 out-of-range, 1 ungrounded, 1 nonpositive) OK")


def test_ground_check_global_offset():
    """GLOBAL-coordinate grounding (live-test FLAW-1 fix): a chunk at global offset 1844 covering
    359 records has valid range [1845, 2203]. Groundings the extractor naturally produces in that
    band (e.g. rec n=2019) must be VALID, while a LOCAL number (n=175) and a beyond-end number
    (n=2300) must be FLAGGED. This is the exact case the per-chunk-numbering scheme mis-flagged at
    up to 76% on the eff98a2f run."""
    gc = _load_ground_check()
    findings = [
        {"summary": "global-in-range-low", "ground": "rec n=1845"},
        {"summary": "global-in-range-mid", "ground": "rec n=2019"},
        {"summary": "global-in-range-high", "ground": "rec n=2203"},
        {"summary": "local-number-now-invalid", "ground": "rec n=175"},   # was valid under local scheme
        {"summary": "beyond-end", "ground": "rec n=2300"},
        {"summary": "before-start", "ground": "rec n=1844"},
    ]
    valid, flagged, reasons = gc.validate(findings, record_count=359, start_index=1844)
    valid_summaries = {f["summary"] for f in valid}
    assert valid_summaries == {"global-in-range-low", "global-in-range-mid", "global-in-range-high"}, \
        f"global-offset valid set wrong: {valid_summaries}"
    assert reasons["out_of_range"] == 1   # n=2300 > 2203
    assert reasons["nonpositive"] == 2    # n=175 and n=1844 are both < lo=1845
    print("[ground-check] global-offset [1845,2203]: 3 valid, n=2019 accepted, local n=175 flagged OK")


def test_ground_check_record_count_matches_renderer():
    """chunk_record_count must equal the renderer's record count (both skip blank lines), so the
    grounding range [1, N] aligns with the `rec n=N` tags the extractor actually sees."""
    gc = _load_ground_check()
    import importlib.util as _ilu
    fpath = os.path.abspath(os.path.join(HERE, "..", "..", "bin", "transcript_fit_gate.py"))
    fspec = _ilu.spec_from_file_location("transcript_fit_gate", fpath)
    fg = _ilu.module_from_spec(fspec)
    fspec.loader.exec_module(fg)
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "syn.jsonl")
        _make_synthetic(src, n_lines=300, boundary_every=100)
        gc_count = gc.chunk_record_count(src)
        # render_chunk now returns (text, (first_n, last_n)); at start_index=0 the count is last_n.
        _, (first_n, last_n) = fg.render_chunk(src, start_index=0)
        rendered_n = last_n
        assert first_n == 1, f"start_index=0 should render first record as n=1, got {first_n}"
        assert gc_count == rendered_n, f"gate count {gc_count} != renderer count {rendered_n}"
        # And with a global offset, the renderer's first/last shift by exactly that offset.
        _, (g_first, g_last) = fg.render_chunk(src, start_index=1844)
        assert g_first == 1845 and g_last == 1844 + gc_count, \
            f"global offset render wrong: ({g_first},{g_last}) expected (1845,{1844+gc_count})"
        print(f"[ground-check] record count agrees with renderer ({gc_count}); global offset shifts range OK")


# ---------- tests: reduce-step structural clustering (Pass 1 / FLAW-3 fix) ----------

def _load_reduce():
    rpath = os.path.abspath(os.path.join(HERE, "..", "..", "bin", "transcript_reduce.py"))
    rspec = importlib.util.spec_from_file_location("transcript_reduce", rpath)
    mod = importlib.util.module_from_spec(rspec)
    rspec.loader.exec_module(mod)
    return mod


def test_reduce_signature_clusters_recurring_events():
    """Structural clustering must collapse recurring-event findings that share an event signature
    but have DISTINCT summaries — the exact case naive string-dedup missed (FLAW-3): 'inline-python
    -guard blocked <cmd A>' and '<cmd B>' are one recurring event, not two distinct findings."""
    r = _load_reduce()
    # three distinct summaries, all the same recurring event class
    sigs = {
        r.signature("errors_failures", "Bash `python3 -c \"open(x)\"` BLOCKED by inline-python-guard"),
        r.signature("errors_failures", "inline-python-guard blocked a different 350-char python -c call"),
        r.signature("errors_failures", "the inline `python -c` guard fired again on a json dump"),
    }
    assert sigs == {("errors_failures", "guard:inline-python")}, f"should share one signature: {sigs}"
    # a non-recurring finding has no signature -> stays distinct
    assert r.signature("decisions", "Chose Bedrock over Vertex for GovCloud parity") is None
    # bucket is part of the key: same text in a different bucket clusters separately
    assert r.signature("insights_patterns", "post-write-edit hook schema") == ("insights_patterns", "hook:post-write-edit")
    print("[reduce] event-signature clustering keys recurring events, leaves distinct ones alone OK")


def test_reduce_singleton_clusters_demoted_to_distinct():
    """A 'cluster' with a single member is not actually recurring — _merge_for + the singleton
    demotion must keep it as a distinct finding, not a count=1 cluster (else the artifact lies
    about recurrence)."""
    r = _load_reduce()
    assert r._merge_for([{"for": "distill"}, {"for": "distill"}]) == "distill"
    assert r._merge_for([{"for": "distill"}, {"for": "capture"}]) == "both"
    assert r._merge_for([{"for": "both"}, {"for": "distill"}]) == "both"
    # gnum extracts the global record number for member ordering
    assert r.gnum({"ground": "rec n=1845"}) == 1845
    assert r.gnum({"ground": "no number here"}) == 10**9
    print("[reduce] _merge_for union + gnum ordering OK")


def test_reduce_completeness_guard():
    """FLAW-7 (2026-06-21): the map step's contract is 'write a findings file per chunk AND
    return'. Those diverged on a real run — the map workflow reported 79/79 ok while only 72
    findings files landed on disk. reduce consumes the DISK, so without a guard it silently
    distills a PARTIAL session (72 of 79) with no signal. The guard must FAIL loud (exit 3) when
    a chunk has no findings file, naming the missing ids, unless --allow-partial is set."""
    import subprocess as _sp
    bin_path = os.path.abspath(os.path.join(HERE, "..", "..", "bin", "transcript_reduce.py"))
    with tempfile.TemporaryDirectory() as d:
        fdir = os.path.join(d, "findings")
        cdir = os.path.join(d, "chunks")
        os.makedirs(fdir)
        os.makedirs(cdir)
        # 3 chunks, but chunk 001's findings file is missing (the FLAW-7 scenario)
        for cid in ("000", "001", "002"):
            with open(os.path.join(cdir, f"chunk_{cid}.jsonl"), "w", encoding="utf-8") as fh:
                fh.write('{"type":"user"}\n')
        for cid in ("000", "002"):
            with open(os.path.join(fdir, f"findings_{cid}.json"), "w", encoding="utf-8") as fh:
                json.dump({"chunk": cid, "records_read": 1, "findings": []}, fh)
        out = os.path.join(d, "prep.json")

        # CASE 1: missing chunk, no flag -> FAIL loud, exit 3, names the missing id
        r1 = _sp.run(["python3", bin_path, "--findings-dir", fdir, "--chunks-dir", cdir, "--out", out],
                     capture_output=True, text=True)
        assert r1.returncode == 3, f"missing chunk must exit 3, got {r1.returncode}"
        assert "001" in r1.stderr and "COMPLETENESS GUARD" in r1.stderr

        # CASE 2: --allow-partial -> proceed with WARN, exit 0
        r2 = _sp.run(["python3", bin_path, "--findings-dir", fdir, "--chunks-dir", cdir, "--out", out,
                      "--allow-partial"], capture_output=True, text=True)
        assert r2.returncode == 0, f"--allow-partial must proceed, got {r2.returncode}"
        assert "WARN (--allow-partial)" in r2.stderr

        # CASE 3: complete set -> pass clean, exit 0
        with open(os.path.join(fdir, "findings_001.json"), "w", encoding="utf-8") as fh:
            json.dump({"chunk": "001", "records_read": 1, "findings": []}, fh)
        r3 = _sp.run(["python3", bin_path, "--findings-dir", fdir, "--chunks-dir", cdir, "--out", out],
                     capture_output=True, text=True)
        assert r3.returncode == 0, f"complete set must pass, got {r3.returncode}: {r3.stderr}"
    print("[reduce] completeness guard: fail-loud on missing chunk / --allow-partial / complete OK")


def test_synth_check_coverage_and_fabrication():
    """The Pass-2 synthesis verification gate (FLAW-4 fix): a synthesis agent's self-reported
    counts and 'nothing lost' claim are NOT evidence. The gate must (a) flag a DROPPED input
    ground (coverage hole) and (b) flag a FABRICATED output ground, deterministically, ignoring
    the agent's count fields."""
    import subprocess as _sp
    bin_path = os.path.abspath(os.path.join(HERE, "..", "..", "bin", "transcript_synth_check.py"))
    with tempfile.TemporaryDirectory() as d:
        inp = os.path.join(d, "in.json")
        # 3 input findings
        with open(inp, "w", encoding="utf-8") as fh:
            json.dump([
                {"summary": "a", "ground": "rec n=10", "for": "distill"},
                {"summary": "b", "ground": "rec n=20", "for": "capture"},
                {"summary": "c", "ground": "rec n=30", "for": "both"},
            ], fh)

        # GOOD output: merges 20 into 10, keeps 30 — all 3 grounds accounted, none fabricated.
        good = os.path.join(d, "good.json")
        with open(good, "w", encoding="utf-8") as fh:
            json.dump({"input_count": 99, "synthesized_count": 99, "findings": [  # lying counts
                {"summary": "a+b", "ground": "rec n=10", "for": "both", "merged_from": ["rec n=20"]},
                {"summary": "c", "ground": "rec n=30", "for": "both"},
            ]}, fh)
        r = _sp.run(["python3", bin_path, "--input", inp, "--output", good],
                    capture_output=True, text=True)
        assert r.returncode == 0, f"good synthesis should pass, got rc={r.returncode}: {r.stdout}"
        rep = json.loads(r.stdout)
        assert rep["coverage_complete"] and rep["no_fabrication"]
        assert rep["input_count_actual"] == 3 and rep["output_count_actual"] == 2  # recomputed, not 99

        # BAD output: drops n=20 (keeps n=10 and n=30) AND fabricates n=999.
        bad = os.path.join(d, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            json.dump({"findings": [
                {"summary": "a", "ground": "rec n=10", "for": "distill"},
                {"summary": "c", "ground": "rec n=30", "for": "both"},
                {"summary": "fab", "ground": "rec n=999", "for": "both"},
            ]}, fh)
        r2 = _sp.run(["python3", bin_path, "--input", inp, "--output", bad],
                     capture_output=True, text=True)
        assert r2.returncode == 1, "bad synthesis (drop + fabricate) must fail the gate"
        rep2 = json.loads(r2.stdout)
        assert rep2["dropped_grounds"] == ["rec n=20"], rep2["dropped_grounds"]
        assert rep2["fabricated_grounds"] == ["rec n=999"], rep2["fabricated_grounds"]
    print("[synth-check] coverage hole + fabrication both caught; counts recomputed OK")


def test_synth_check_transitive_closure_hierarchical():
    """FLAW-6 fix: in HIERARCHICAL synthesis (cross-shard merge), an input item carries a
    `merged_from` (records a prior pass already merged). The output may cite those nested records.
    The gate's valid reference set must be the TRANSITIVE closure (top-level grounds + all nested
    merged_from), or it false-flags legitimate nested records as fabricated — observed live on the
    cross-shard insights merge (13/13 'fabrications' were all nested merged_from)."""
    import subprocess as _sp
    bin_path = os.path.abspath(os.path.join(HERE, "..", "..", "bin", "transcript_synth_check.py"))
    with tempfile.TemporaryDirectory() as d:
        # input item already merged n=20 into n=10 in a prior pass (n=20 lives in merged_from)
        inp = os.path.join(d, "in.json")
        with open(inp, "w", encoding="utf-8") as fh:
            json.dump([
                {"summary": "a+b", "ground": "rec n=10", "for": "both", "merged_from": ["rec n=10", "rec n=20"]},
                {"summary": "c", "ground": "rec n=30", "for": "both"},
            ], fh)
        # cross-shard output keeps n=10 (citing the nested n=20) and n=30 — n=20 is NOT top-level
        # in the input, only nested. A narrow gate would false-flag rec n=20.
        out = os.path.join(d, "out.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"findings": [
                {"summary": "a+b", "ground": "rec n=10", "for": "both", "merged_from": ["rec n=20", "rec n=30"]},
            ]}, fh)
        r = _sp.run(["python3", bin_path, "--input", inp, "--output", out], capture_output=True, text=True)
        rep = json.loads(r.stdout)
        assert rep["no_fabrication"], f"nested merged_from n=20 must NOT be flagged: {rep['fabricated_grounds']}"
        assert rep["coverage_complete"], f"all grounds incl. n=30-merged must be covered: {rep['dropped_grounds']}"
        assert r.returncode == 0
    print("[synth-check] transitive closure: nested merged_from records accepted (hierarchical) OK")


if __name__ == "__main__":
    # allow running directly: python3 test_transcript_chunk.py
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
