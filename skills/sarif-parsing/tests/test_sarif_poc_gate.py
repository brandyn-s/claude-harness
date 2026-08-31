"""SARIF PoC/staleness gate — drops findings whose flagged code is gone,
keeps the rest (conservative). Routes through the _shared/oracle reproducer.
"""
from __future__ import annotations

import sys
from pathlib import Path

RES = Path(__file__).resolve().parents[1] / "resources"
sys.path.insert(0, str(RES))
from sarif_helpers import extract_findings, gate_findings  # noqa: E402


def _result(rule_id, uri, line, snippet=None, message="msg"):
    region = {"startLine": line}
    if snippet is not None:
        region["snippet"] = {"text": snippet}
    return {
        "ruleId": rule_id,
        "level": "error",
        "message": {"text": message},
        "locations": [{"physicalLocation": {
            "artifactLocation": {"uri": uri},
            "region": region,
        }}],
    }


def _sarif(*results):
    return {"version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "test"}}, "results": list(results)}]}


def test_gate_present_stale_inconclusive(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = dangerous_call(user_input)\n", encoding="utf-8")

    sarif = _sarif(
        # PRESENT: snippet still in the file.
        _result("R1", "src/a.py", 1, snippet="dangerous_call(user_input)", message="m1"),
        # STALE: snippet not in the file (code was fixed/moved).
        _result("R2", "src/a.py", 1, snippet="eval(removed_long_ago)", message="m2"),
        # INCONCLUSIVE: no snippet to check, but file exists -> keep.
        _result("R3", "src/a.py", 1, snippet=None, message="m3"),
        # STALE: file does not exist at all.
        _result("R4", "src/gone.py", 1, snippet="whatever", message="m4"),
    )
    findings = extract_findings(sarif)
    res = gate_findings(findings, tmp_path)
    bv = res["by_verdict"]
    assert bv["PRESENT"] == 1
    assert bv["STALE"] == 2          # R2 (snippet gone) + R4 (file gone)
    assert bv["INCONCLUSIVE"] == 1   # R3
    # Only STALE is dropped; the rest are kept (conservative).
    assert res["summary"]["dropped_stale"] == 2
    assert res["summary"]["kept"] == 2
    kept_rules = {f.rule_id for f in res["kept"]}
    assert kept_rules == {"R1", "R3"}
    assert {f.rule_id for f in res["dropped"]} == {"R2", "R4"}


def test_gate_dedups_before_gating(tmp_path):
    (tmp_path / "a.py").write_text("dangerous()\n", encoding="utf-8")
    # Two identical results (same rule/file/line/message) -> one fingerprint.
    dup = _result("R1", "a.py", 1, snippet="dangerous()", message="same")
    sarif = _sarif(dup, dict(dup))
    res = gate_findings(extract_findings(sarif), tmp_path, dedup=True)
    assert res["summary"]["raw"] == 2
    assert res["summary"]["deduped"] == 1
    assert res["summary"]["kept"] == 1


def test_present_is_not_exploitability_claim(tmp_path):
    """PRESENT must only assert 'still at the cited location', documented in
    the summary note — it is not a true-positive/exploitability verdict."""
    (tmp_path / "a.py").write_text("token = SECRET\n", encoding="utf-8")
    sarif = _sarif(_result("R1", "a.py", 1, snippet="token = SECRET"))
    res = gate_findings(extract_findings(sarif), tmp_path)
    assert res["by_verdict"]["PRESENT"] == 1
    assert "NOT" in res["summary"]["note"] and "fp-check" in res["summary"]["note"]


def test_gate_non_object_sarif_exits_2_no_traceback(tmp_path):
    """Valid-JSON-but-non-object input (top-level []) is a SARIF load
    error: clean stderr message + exit 2, never a raw AttributeError
    traceback (sarif_poc_gate.py documented exit-code contract)."""
    import subprocess
    bad = tmp_path / "bad.sarif"
    bad.write_text("[]", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(RES / "sarif_poc_gate.py"), str(bad)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "Traceback" not in proc.stdout + proc.stderr
    assert "Error" in proc.stderr
