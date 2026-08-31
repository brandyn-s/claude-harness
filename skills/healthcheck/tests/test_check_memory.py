"""Unit tests for healthcheck/references/_check_memory.py.

_check_memory delegates to doc_accuracy_audit.py's audit_memory_md (the single
source of truth that correctly resolves ~/Documents KB-topic links). This file
pins the thin wrapper's contract: parse the audit's memory_md block and map
issues→exit code. The cross-directory link resolution itself is doc_accuracy's
responsibility and is tested there.
"""
import json
import types
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_memory",
    Path(__file__).resolve().parent.parent / "references" / "_check_memory.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


def _fake_audit(monkeypatch, tmp_path, stdout):
    """Make AUDIT exist and stub the subprocess to emit `stdout`."""
    audit = tmp_path / "doc_accuracy_audit.py"
    audit.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(hc, "AUDIT", str(audit))
    monkeypatch.setattr(hc.subprocess, "run",
                        lambda *_, **__: types.SimpleNamespace(stdout=stdout, returncode=0))


def test_clean_memory_passes(tmp_path, monkeypatch, capsys):
    _fake_audit(monkeypatch, tmp_path, json.dumps(
        {"memory_md": {"issues": 0, "lines": 66, "links": 54, "findings": []}}))
    rc = hc.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS" in out and "54 links" in out


def test_issues_warn(tmp_path, monkeypatch, capsys):
    _fake_audit(monkeypatch, tmp_path, json.dumps(
        {"memory_md": {"issues": 2, "lines": 66, "links": 54,
                       "findings": ["orphan: x.md", "missing: y.md"]}}))
    rc = hc.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "WARN" in out and "orphan: x.md" in out


def test_audit_missing_is_exit_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hc, "AUDIT", str(tmp_path / "does-not-exist.py"))
    rc = hc.main()
    assert rc == 2
    assert "WARN" in capsys.readouterr().out


def test_unparseable_output_is_exit_2(tmp_path, monkeypatch, capsys):
    _fake_audit(monkeypatch, tmp_path, "this is not json")
    rc = hc.main()
    assert rc == 2
    assert "WARN" in capsys.readouterr().out
