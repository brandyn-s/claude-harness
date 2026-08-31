"""Tests for skills/variant-analysis/scripts/verify_variants.py.

Exercise the Tier-1 + Tier-2 oracle (ripgrep over a synthetic tree).
No semgrep / codeql dependency — the rg pass is the kernel verifier
that proves the harness gates work. Each test writes a tiny tree
under tmp_path, runs the oracle as a subprocess, and inspects the
JSON / NDJSON output.
"""
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ORACLE = Path(__file__).resolve().parents[1] / "scripts" / "verify_variants.py"


def _have(tool):
    return shutil.which(tool) is not None


def _make_tree(root):
    (root / "src" / "auth").mkdir(parents=True)
    (root / "src" / "auth" / "jwt.ts").write_text(
        "const secret = process.env.JWT_SECRET || 'default-dev-secret';\n",
        encoding="utf-8",
    )
    (root / "src" / "auth" / "session.ts").write_text(
        "const csrf = process.env.CSRF_KEY || 'fallback-csrf';\n",
        encoding="utf-8",
    )


def _run_oracle(spec_path, target, ndjson_path, strict=True):
    cmd = [sys.executable, str(ORACLE), str(spec_path),
           "--target", str(target), "--ndjson", str(ndjson_path), "--json"]
    if strict:
        cmd.append("--strict")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r


def _load_ndjson(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.skipif(not _have("rg"), reason="ripgrep not installed")
def test_baseline_pass_and_variant_run(tmp_path):
    _make_tree(tmp_path)
    spec = {
        "hunt_id": "test-baseline",
        "root_cause": "env || default",
        "seed_file": "src/auth/jwt.ts",
        "seed_line": 1,
        "patterns": [
            # sampled_fp now required for a clean PASS: the corrected FP gate
            # reports UNVERIFIED (non-PASS under --strict) for a non-empty match
            # set with no sample. These patterns match only real fallback-default
            # bugs, so the honest sampled-FP count is 0.
            {"level": 0, "kind": "rg", "pattern": "process\\.env\\.JWT_SECRET \\|\\| 'default-dev-secret'", "sampled_fp": 0},
            {"level": 1, "kind": "rg", "pattern": "process\\.env\\.[A-Z_]+ \\|\\| ['\"][^'\"]+['\"]", "sampled_fp": 0},
        ],
        "fp_rate_cap": 0.5,
    }
    spec_path = tmp_path / "hunt.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run_oracle(spec_path, tmp_path, ndjson)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["all_passed"] is True
    assert {p["level"] for p in out["patterns"]} == {0, 1}
    # Level-1 catches both files; level-0 catches only the seed.
    by_level = {p["level"]: p for p in out["patterns"]}
    assert by_level[0]["n_matches"] == 1
    assert by_level[1]["n_matches"] >= 2
    # Baseline check emitted with passed=true.
    events = _load_ndjson(ndjson)
    baseline = [e for e in events if e.get("check") == "exact_baseline"]
    assert baseline and baseline[0]["passed"] is True


@pytest.mark.skipif(not _have("rg"), reason="ripgrep not installed")
def test_baseline_fail_when_seed_wrong(tmp_path):
    _make_tree(tmp_path)
    spec = {
        "hunt_id": "test-baseline-miss",
        "root_cause": "env || default",
        "seed_file": "src/auth/jwt.ts",
        "seed_line": 99,  # line doesn't exist
        "patterns": [
            {"level": 0, "kind": "rg", "pattern": "process\\.env\\.JWT_SECRET"},
        ],
        "fp_rate_cap": 0.5,
    }
    spec_path = tmp_path / "hunt.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run_oracle(spec_path, tmp_path, ndjson)
    # --strict mode: baseline miss means non-zero exit.
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["all_passed"] is False
    events = _load_ndjson(ndjson)
    baseline = [e for e in events if e.get("check") == "exact_baseline"]
    assert baseline and baseline[0]["passed"] is False


def test_pattern_parse_fail_on_bad_regex(tmp_path):
    _make_tree(tmp_path)
    spec = {
        "hunt_id": "test-bad-regex",
        "root_cause": "x",
        "patterns": [{"level": 0, "kind": "rg", "pattern": "[unclosed"}],
        "fp_rate_cap": 0.5,
    }
    spec_path = tmp_path / "hunt.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run_oracle(spec_path, tmp_path, ndjson)
    assert r.returncode == 1
    events = _load_ndjson(ndjson)
    parse = [e for e in events if e.get("check") == "pattern_parse"]
    assert parse and parse[0]["passed"] is False
    assert "regex compile error" in parse[0]["reason"]


@pytest.mark.skipif(not _have("rg"), reason="ripgrep not installed")
def test_fp_rate_gate_trips(tmp_path):
    _make_tree(tmp_path)
    spec = {
        "hunt_id": "test-fp-gate",
        "root_cause": "x",
        "seed_file": "src/auth/jwt.ts",
        "seed_line": 1,
        "patterns": [
            {"level": 0, "kind": "rg", "pattern": "process\\.env\\.JWT_SECRET \\|\\| 'default-dev-secret'"},
            {"level": 3, "kind": "rg", "pattern": "process",
             "sampled_fp": 100},
        ],
        "fp_rate_cap": 0.5,
    }
    spec_path = tmp_path / "hunt.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run_oracle(spec_path, tmp_path, ndjson)
    assert r.returncode == 1
    events = _load_ndjson(ndjson)
    # Find the fp_rate_gate emitted for the level with sampled_fp (not the
    # informational level-0 record which has no sample).
    gate = [e for e in events if e.get("check") == "fp_rate_gate" and "fp_rate" in e]
    assert gate, "expected at least one fp_rate_gate record with fp_rate set"
    assert gate[0]["passed"] is False
    assert gate[0]["fp_rate"] > gate[0]["cap"]


def test_malformed_spec_shape_exits_2_clean(tmp_path):
    # Wrong-shape specs are runner errors (docstring: exit 2), not crashes:
    # (a) valid-JSON non-object top level; (b) rg pattern entry missing the
    # "pattern" key (previously KeyError in run_pattern).
    for bad in ("[]", json.dumps({"patterns": [{"level": 0, "kind": "rg"}]})):
        spec_path = tmp_path / "hunt.json"
        spec_path.write_text(bad, encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(ORACLE), str(spec_path), "--target", str(tmp_path)],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 2, (bad, r.returncode, r.stderr)
        assert "ERROR: malformed spec" in r.stderr
        assert "Traceback" not in r.stderr
