"""Tests for skills/insecure-defaults/scripts/verify_defaults.py.

Exercise the Tier-1 oracle (file_locates + fail_open_classify +
not_test_fixture) against synthetic source trees. The Tier-2 sandbox
executor is tested separately when a probe_cmd is provided; here we
focus on the deterministic static checks.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

ORACLE = Path(__file__).resolve().parents[1] / "scripts" / "verify_defaults.py"


def _run(spec_path, root, ndjson, strict=True):
    cmd = [sys.executable, str(ORACLE), str(spec_path),
           "--root", str(root), "--ndjson", str(ndjson), "--json"]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _load_ndjson(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_classify_fail_open_python_get(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "config.py").write_text(
        "import os\n"
        "JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-default')\n",
        encoding="utf-8",
    )
    spec = {"report_id": "t", "findings": [{
        "id": "py-fallback", "file": "app/config.py", "line": 2,
        "pattern": r"os\.environ\.get\(.*default.*\)", "claim": "fail_open",
    }]}
    spec_path = tmp_path / "findings.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(spec_path, tmp_path, ndjson)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["all_passed"] is True
    assert out["findings"][0]["static_verdict"] == "fail_open"


def test_classify_fail_secure_rust_expect(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text(
        textwrap.dedent("""
        fn main() {
            let secret = std::env::var(\"JWT_SECRET\")
                .expect(\"JWT_SECRET required at boot\");
            println!(\"{}\", secret);
        }
        """),
        encoding="utf-8",
    )
    spec = {"report_id": "t", "findings": [{
        "id": "rs-expect", "file": "src/main.rs", "line": 3,
        "pattern": r"env::var\(", "claim": "fail_secure",
    }]}
    spec_path = tmp_path / "findings.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(spec_path, tmp_path, ndjson)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["findings"][0]["static_verdict"] == "fail_secure"


def test_test_fixture_path_dropped(tmp_path):
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "fake.ts").write_text(
        "const k = process.env.X || 'fake';\n", encoding="utf-8",
    )
    spec = {"report_id": "t", "findings": [{
        "id": "fixture", "file": "tests/fixtures/fake.ts", "line": 1,
        "pattern": r"process\.env\.X \|\|", "claim": "fail_open",
    }]}
    spec_path = tmp_path / "findings.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(spec_path, tmp_path, ndjson)
    assert r.returncode == 1  # not_test_fixture trips
    events = _load_ndjson(ndjson)
    fixture_check = [e for e in events if e.get("check") == "not_test_fixture"]
    assert fixture_check and fixture_check[0]["passed"] is False


def test_finding_locates_fails_when_line_missing(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "f.ts").write_text("// short\n", encoding="utf-8")
    spec = {"report_id": "t", "findings": [{
        "id": "stale", "file": "src/f.ts", "line": 99,
        "pattern": r"anything", "claim": "fail_open",
    }]}
    spec_path = tmp_path / "findings.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(spec_path, tmp_path, ndjson)
    assert r.returncode == 1
    events = _load_ndjson(ndjson)
    locate = [e for e in events if e.get("check") == "finding_locates"]
    assert locate and locate[0]["passed"] is False


def test_startup_probe_fail_open(tmp_path):
    """Tier-2 sandbox executor: probe succeeds without env var -> fail-open."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "boot.py").write_text(
        "import os, sys; sys.exit(0)  # boots regardless of env\n",
        encoding="utf-8",
    )
    spec = {"report_id": "t", "findings": [{
        "id": "boot", "file": "app/boot.py", "line": 1,
        "pattern": r"sys\.exit", "claim": None,
        "env_var": "JWT_SECRET",
        "probe_cmd": [sys.executable, "app/boot.py"],  # argv list = the secure form
    }]}
    spec_path = tmp_path / "findings.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(spec_path, tmp_path, ndjson, strict=False)
    assert r.returncode == 0, r.stderr
    events = _load_ndjson(ndjson)
    probe = [e for e in events if e.get("check") == "startup_probe"]
    assert probe and probe[0].get("verdict") == "fail_open"


def test_contradicted_claim_fails(tmp_path):
    """A finding whose claim is the definite opposite of the static classification
    must FAIL the run (exit 1) — the verdict gates, it isn't just reported. This is
    the regression guard for the 'computed-then-discarded verdict' bug."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "config.py").write_text(
        "import os\n"
        "TOKEN = os.environ.get('TOKEN', 'dev-default')  # fail-open fallback\n",
        encoding="utf-8",
    )
    spec = {"report_id": "t", "findings": [{
        "id": "contradiction", "file": "app/config.py", "line": 2,
        "pattern": r"os\.environ\.get\(", "claim": "fail_secure",  # WRONG: code is fail_open
    }]}
    spec_path = tmp_path / "findings.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    r = _run(spec_path, tmp_path, ndjson)  # strict
    assert r.returncode == 1, r.stdout
    out = json.loads(r.stdout)
    f0 = out["findings"][0]
    assert f0["static_verdict"] == "fail_open"
    assert f0["classify_contradicts"] is True
    assert f0["passed"] is False


def test_probe_cmd_metacharacters_do_not_execute(tmp_path):
    """probe_cmd is findings.json-authored; with shell=False it runs as argv, so
    shell metacharacters cannot inject a second command (RCE closed)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "boot.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    sentinel = tmp_path / "PWNED"
    # Under the old shell=True, `&& touch <sentinel>` would execute and create the
    # file. Under shell=False + shlex.split it is inert argv passed to python.
    spec = {"report_id": "t", "findings": [{
        "id": "inject", "file": "app/boot.py", "line": 1,
        "pattern": r"sys\.exit", "claim": None, "env_var": "X",
        "probe_cmd": f"{sys.executable} app/boot.py && touch {sentinel}",
    }]}
    spec_path = tmp_path / "findings.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ndjson = tmp_path / "run.ndjson"
    _run(spec_path, tmp_path, ndjson, strict=False)
    assert not sentinel.exists(), "shell metacharacters in probe_cmd executed -> RCE not closed"


def test_malformed_spec_shapes_exit_2_no_traceback(tmp_path):
    """Runner errors (malformed finding entries, unwritable --ndjson path) must
    exit 2 with a clean ERROR line per the docstring contract — not a raw
    traceback exiting 1, which a CI consumer misreads as 'checks failed'."""
    # (a) finding entry missing id/file/line; (b) "line" given as a string
    for bad in ({}, {"id": "x", "file": "f.py", "line": "3"}):
        spec_path = tmp_path / "bad.json"
        spec_path.write_text(json.dumps({"findings": [bad]}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(ORACLE), str(spec_path)],
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 2, (r.returncode, r.stderr)
        assert "Traceback" not in r.stderr, r.stderr
        assert "ERROR:" in r.stderr
    # (c) --ndjson pointing into a nonexistent directory
    spec_path = tmp_path / "ok.json"
    spec_path.write_text(json.dumps({"findings": []}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ORACLE), str(spec_path),
                        "--ndjson", str(tmp_path / "no-such-dir" / "run.ndjson")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "Traceback" not in r.stderr, r.stderr
    assert "ERROR:" in r.stderr
