"""Unit tests for the SessionStart code-graph health module.

The module's structured-findings branch was UNREACHABLE until 2026-07-29:
verify-indexes.py parsed no argv, so `--json` was accepted-and-ignored, stdout
was always the human report, and every call fell through to the generic
exit-code fallback. These tests pin both branches so that cannot silently
recur — a JSON payload must produce per-project findings, and non-JSON output
must still produce the fallback.

The subprocess is stubbed rather than run: this module's contract is "given what
verify-indexes.py returns, emit these findings", and stubbing lets the malformed
and legacy shapes be exercised deterministically. The real script's `--json`
output shape is pinned separately by test_verify_indexes.py.
"""
import json
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import code_graph_health as mod  # noqa: E402 -- resolves via the sys.path insert above


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout.encode("utf-8")
        self.stderr = stderr.encode("utf-8")


def _stub(monkeypatch, result):
    """Make the module see its script as present and return `result`.

    Points VERIFY_INDEXES_SCRIPT at a file that genuinely exists (this test)
    rather than patching Path.exists globally — a global patch would also lie to
    pytest's own internals for the duration of the test.
    """
    monkeypatch.setattr(mod, "VERIFY_INDEXES_SCRIPT", Path(__file__))
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: result)


def test_clean_run_yields_no_findings(monkeypatch):
    _stub(monkeypatch, _Result(0, json.dumps({"status": "clean"})))
    assert mod.check_code_graph_health() == []


def test_json_payload_produces_per_project_findings(monkeypatch):
    """The branch that was dead: a real payload must yield a per-project finding."""
    payload = {
        "status": "fail",
        "code_graph_corruption": [
            {
                "project": "Users-me-Documents-GitHub-widget",
                "detail": "integrity_check: page 42 malformed",
                "db_path": "/Users/me/.cache/codebase-memory-mcp/x.db",
            }
        ],
    }
    _stub(monkeypatch, _Result(2, json.dumps(payload)))

    msgs = mod.check_code_graph_health()
    assert len(msgs) == 1
    assert "CODE-GRAPH HEALTH" in msgs[0]
    assert "Users-me-Documents-GitHub-widget" in msgs[0]
    # The DETAIL must reach the operator — the old code read a `mode` key the
    # script never emits, which would have rendered "<unclassified>" instead.
    assert "integrity_check: page 42 malformed" in msgs[0]
    assert "<unclassified>" not in msgs[0]
    assert "/Users/me/.cache/codebase-memory-mcp/x.db" in msgs[0]


def test_code_search_corruption_is_also_surfaced(monkeypatch):
    payload = {
        "status": "fail",
        "code_search_corruption": [
            {"project": "widget_abc123", "detail": "chunk_ids.pkl is a 5-byte empty pickle"}
        ],
    }
    _stub(monkeypatch, _Result(2, json.dumps(payload)))

    msgs = mod.check_code_graph_health()
    assert len(msgs) == 1
    assert "CODE-SEARCH HEALTH" in msgs[0]
    assert "chunk_ids.pkl is a 5-byte empty pickle" in msgs[0]


def test_multiple_findings_are_reported_individually(monkeypatch):
    payload = {
        "status": "fail",
        "code_graph_corruption": [
            {"project": "a", "detail": "d1", "db_path": "/tmp/a.db"},
            {"project": "b", "detail": "d2", "db_path": "/tmp/b.db"},
        ],
        "code_search_corruption": [{"project": "c", "detail": "d3"}],
    }
    _stub(monkeypatch, _Result(2, json.dumps(payload)))
    assert len(mod.check_code_graph_health()) == 3


def test_non_json_output_still_falls_back(monkeypatch):
    """An older checkout whose script predates --json must still warn."""
    _stub(monkeypatch, _Result(2, "Indexes: FAIL - 3 issues across 19 DBs"))

    msgs = mod.check_code_graph_health()
    assert len(msgs) == 1
    assert "exited 2" in msgs[0]


def test_missing_field_degrades_without_raising(monkeypatch):
    """A payload lacking detail/db_path must not KeyError or emit 'None'."""
    payload = {"status": "fail", "code_graph_corruption": [{"project": "solo"}]}
    _stub(monkeypatch, _Result(2, json.dumps(payload)))

    msgs = mod.check_code_graph_health()
    assert len(msgs) == 1
    assert "solo" in msgs[0]
    assert "None" not in msgs[0]


def test_timeout_is_swallowed_as_best_effort(monkeypatch):
    monkeypatch.setattr(mod, "VERIFY_INDEXES_SCRIPT", Path(__file__))

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="verify-indexes.py", timeout=5)

    monkeypatch.setattr(mod.subprocess, "run", boom)
    # SessionStart observability must never fail the session.
    assert mod.check_code_graph_health() == []


def test_missing_script_yields_no_findings(monkeypatch):
    monkeypatch.setattr(
        mod, "VERIFY_INDEXES_SCRIPT", Path(__file__).parent / "no-such-script.py"
    )
    assert mod.check_code_graph_health() == []
