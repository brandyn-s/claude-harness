"""Tests for semgrep/scripts/merge_sarif.py merge_sarif_pure_python().

Covers the pure-Python SARIF merge fallback: union of rules (by id),
dedup of results (by ruleId+uri+startLine), graceful skip of unparseable
files, and the all-unparseable refusal.
"""
import importlib.util
import json
import os

import pytest

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "merge_sarif.py")
_spec = importlib.util.spec_from_file_location("merge_sarif", _SCRIPT)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)


def _sarif(rule_id, uri, line):
    return {
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "semgrep", "rules": [{"id": rule_id}]}},
            "results": [{
                "ruleId": rule_id,
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": uri},
                    "region": {"startLine": line},
                }}],
            }],
        }],
    }


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_merges_distinct_results(tmp_path):
    f1 = _write(tmp_path, "a.sarif", _sarif("rule1", "a.py", 10))
    f2 = _write(tmp_path, "b.sarif", _sarif("rule2", "b.py", 20))
    merged = _m.merge_sarif_pure_python([f1, f2])
    results = merged["runs"][0]["results"]
    assert {r["ruleId"] for r in results} == {"rule1", "rule2"}
    rules = merged["runs"][0]["tool"]["driver"]["rules"]
    assert {r["id"] for r in rules} == {"rule1", "rule2"}


def test_dedupes_identical_result(tmp_path):
    f1 = _write(tmp_path, "a.sarif", _sarif("rule1", "a.py", 10))
    f2 = _write(tmp_path, "b.sarif", _sarif("rule1", "a.py", 10))  # same key
    merged = _m.merge_sarif_pure_python([f1, f2])
    assert len(merged["runs"][0]["results"]) == 1


def test_skips_unparseable_but_merges_rest(tmp_path):
    good = _write(tmp_path, "good.sarif", _sarif("rule1", "a.py", 10))
    bad = tmp_path / "bad.sarif"
    bad.write_text("{not valid json", encoding="utf-8")
    merged = _m.merge_sarif_pure_python([good, bad])
    assert len(merged["runs"][0]["results"]) == 1


def test_all_unparseable_raises(tmp_path):
    bad1 = tmp_path / "b1.sarif"; bad1.write_text("{x", encoding="utf-8")
    bad2 = tmp_path / "b2.sarif"; bad2.write_text("}y", encoding="utf-8")
    with pytest.raises(RuntimeError):
        _m.merge_sarif_pure_python([bad1, bad2])


def test_empty_input_yields_no_runs(tmp_path):
    merged = _m.merge_sarif_pure_python([])
    assert merged["runs"] == []
    assert merged["version"] == "2.1.0"
