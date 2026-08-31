"""Trace-replay audit-the-auditor logic tests (Phase-9 decision rule,
sampling bounds, robust trace reading)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load():
    p = REPO / "skills" / "audit-skill" / "scripts" / "audit_the_auditor.py"
    spec = importlib.util.spec_from_file_location("audit_the_auditor", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_the_auditor"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_classify_axis_decision_rule():
    a = _load()
    assert a.classify_axis(["INSTRUMENT"] * 3 + ["REAL"] * 2) == "fix-instrument"
    assert a.classify_axis(["REAL"] * 4 + ["UNCLEAR"]) == "real-failure-mode"
    assert a.classify_axis(["REAL", "INSTRUMENT", "UNCLEAR", "REAL", "INSTRUMENT"]) == "expand-sample"
    assert a.classify_axis([]) == "no-sample"


def test_sample_records_caps_and_groups_per_layer():
    a = _load()
    recs = [{"layer": "A", "verdict": "STALE", "skill": "s",
             "finding_id": "x" * 16, "evidence": "e"} for _ in range(10)]
    recs += [{"layer": "D", "verdict": "VERIFIED", "skill": "s",
              "finding_id": "y" * 16, "evidence": "e"} for _ in range(2)]
    sampled = a.sample_records(recs, per_layer=5, seed=1)
    assert len(sampled["A"]) == 5      # capped
    assert len(sampled["D"]) == 2      # fewer than cap -> all


def test_render_worksheet_lists_layers_and_class_column():
    a = _load()
    sampled = {"A": [{"verdict": "STALE", "skill": "s",
                      "finding_id": "z" * 16, "evidence": "ev"}]}
    ws = a.render_worksheet(sampled)
    assert "## Layer A" in ws and "**class:**" in ws and "STALE" in ws


def test_read_records_skips_garbage(tmp_path):
    a = _load()
    p = tmp_path / "t.jsonl"
    p.write_text('{"layer":"A","verdict":"STALE"}\nnot json\n\n{"layer":"D","verdict":"VERIFIED"}\n',
                 encoding="utf-8")
    recs = a.read_records(p)
    assert len(recs) == 2
    assert {r["layer"] for r in recs} == {"A", "D"}
