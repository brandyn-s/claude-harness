"""Tests for scout-skills/scripts/verify_skip.py parse_verdict()."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "verify_skip.py")
_spec = importlib.util.spec_from_file_location("verify_skip", _SCRIPT)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)


def test_confirmed_covered_with_rationale():
    v, rationale = _m.parse_verdict("VERDICT: CONFIRMED-COVERED\nAlready handled by /superplan.")
    assert v == "CONFIRMED-COVERED"
    assert "superplan" in rationale


def test_gap_exists():
    v, _r = _m.parse_verdict("VERDICT: GAP-EXISTS")
    assert v == "GAP-EXISTS"


def test_ambiguous_case_insensitive_keyword():
    v, _r = _m.parse_verdict("some preamble\nverdict: ambiguous\nneeds more evidence")
    assert v == "AMBIGUOUS"


def test_non_canonical_verdict_is_parse_error():
    v, _r = _m.parse_verdict("VERDICT: MAYBE-LATER")
    assert v == "PARSE-ERROR"


def test_no_verdict_line_is_parse_error():
    v, rationale = _m.parse_verdict("just some freeform text with no verdict")
    assert v == "PARSE-ERROR"
    assert "freeform" in rationale


def test_rationale_is_truncated():
    v, rationale = _m.parse_verdict("VERDICT: GAP-EXISTS\n" + "x" * 900)
    assert v == "GAP-EXISTS"
    assert len(rationale) <= 500


def _run_script(argv):
    """Run verify_skip.py offline (API keys stripped so adapters fail fast)."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("OPENAI_API_KEY", "XAI_API_KEY")}
    return subprocess.run([sys.executable, _SCRIPT] + argv,
                          capture_output=True, text=True, env=env)


def test_all_missing_ours_exits_30_without_model_dispatch():
    """Error path: zero existing --ours destinations is invalid input
    (exit 30, JSON error with not_found list) — must not proceed to
    model dispatch (which would exit 0/10/20)."""
    with tempfile.TemporaryDirectory() as td:
        card = Path(td) / "card.md"
        card.write_text("card", encoding="utf-8")
        community = Path(td) / "community.md"
        community.write_text("community", encoding="utf-8")
        missing = [str(Path(td) / "missing1.md"), str(Path(td) / "missing2.md")]
        proc = _run_script([
            "--technique-card", str(card),
            "--community", str(community),
            "--ours", missing[0],
            "--ours", missing[1],
        ])
        assert proc.returncode == 30
        assert "Traceback" not in proc.stderr
        out = json.loads(proc.stdout)
        assert sorted(out["not_found"]) == sorted(missing)


def test_non_utf8_community_no_traceback():
    """Error path: a non-UTF8 --community file must not crash with a raw
    UnicodeDecodeError (read uses errors='replace'); with API keys
    stripped both adapters fail fast and the script abstains (exit 20)."""
    with tempfile.TemporaryDirectory() as td:
        card = Path(td) / "card.md"
        card.write_text("card", encoding="utf-8")
        community = Path(td) / "community.md"
        community.write_bytes(b"\xff\xfe\x00bad")
        ours = Path(td) / "ours.md"
        ours.write_text("ours", encoding="utf-8")
        proc = _run_script([
            "--technique-card", str(card),
            "--community", str(community),
            "--ours", str(ours),
        ])
        assert proc.returncode == 20
        assert "UnicodeDecodeError" not in proc.stderr
        assert "Traceback" not in proc.stderr
