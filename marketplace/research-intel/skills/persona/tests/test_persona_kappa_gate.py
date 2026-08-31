"""persona analyze.py --strict kappa gate.

Promotes the advisory in-band `kappa<0.6` flag to an enforced exit code.
The kappa-paradox guard still holds: only RCs whose keyword AND LLM-judge
base rates are both in [0.2, 0.8] can gate.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
ANALYZE = SKILL / "scripts" / "analyze.py"


def _make_run(tmp: Path, kw_flags, jd_flags) -> Path:
    pdir = tmp / "results-by-persona"
    pdir.mkdir(parents=True, exist_ok=True)
    for i, (kw, jd) in enumerate(zip(kw_flags, jd_flags)):
        rec = {
            "dispatch": {"ok": True},
            "scoring": {
                "keyword": {"rcs": {"RC1": "endorse" if kw else "reject"}},
                "llm_judge": {"judgment": {"rc1": "endorse" if jd else "reject"}},
            },
        }
        (pdir / f"persona_{i:03d}.json").write_text(json.dumps(rec), encoding="utf-8")
    return tmp


def _run(run_dir: Path, strict: bool):
    cmd = [sys.executable, str(ANALYZE), str(run_dir)]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def test_strict_gates_on_in_band_low_kappa(tmp_path):
    # keyword endorses the first half, judge the second half -> they never
    # agree (kappa = -1) while both base rates are 0.5 (in band).
    kw = [True] * 5 + [False] * 5
    jd = [False] * 5 + [True] * 5
    rd = _make_run(tmp_path, kw, jd)
    r = _run(rd, strict=True)
    assert r.returncode == 1, f"expected gate fail; stderr={r.stderr}"
    assert "GATE FAIL" in r.stderr and "RC1" in r.stderr


def test_no_strict_is_advisory(tmp_path):
    kw = [True] * 5 + [False] * 5
    jd = [False] * 5 + [True] * 5
    rd = _make_run(tmp_path, kw, jd)
    r = _run(rd, strict=False)
    assert r.returncode == 0  # default unchanged: writes analysis.md, exits 0


def test_strict_passes_on_high_agreement(tmp_path):
    kw = [True] * 5 + [False] * 5
    jd = list(kw)  # identical -> kappa = 1.0
    rd = _make_run(tmp_path, kw, jd)
    r = _run(rd, strict=True)
    assert r.returncode == 0, f"high agreement should pass; stderr={r.stderr}"


def test_strict_does_not_gate_out_of_band(tmp_path):
    # Extreme base rate (1 endorse / 9 reject on both) -> low kappa but
    # OUT of band; the kappa-paradox guard must keep the gate from firing.
    kw = [True] + [False] * 9
    jd = [False] + [True] + [False] * 8  # disagree, but rates ~0.1 (out of band)
    rd = _make_run(tmp_path, kw, jd)
    r = _run(rd, strict=True)
    assert r.returncode == 0, f"out-of-band low kappa must not gate; stderr={r.stderr}"


def test_malformed_persona_json_clean_error(tmp_path):
    # Error-path contract: a truncated/corrupt persona write must produce a
    # clean "error: ..." on stderr and exit 2 - never a raw JSONDecodeError
    # traceback (audit finding: unguarded json.loads in analyze.py).
    pdir = tmp_path / "results-by-persona"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "persona_001.json").write_text("{bad", encoding="utf-8")
    r = _run(tmp_path, strict=False)
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}; stderr={r.stderr}"
    assert "error:" in r.stderr and "persona_001.json" in r.stderr
    assert "Traceback" not in r.stderr
