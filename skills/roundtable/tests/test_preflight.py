"""Preflight abort/warn split — the safety property of probe-before-panel.

Retirement-class probe results (exit 1) must ABORT the panel; transient/auth-
infra results (exit 2) must WARN, not abort (a 30s vendor blip or an env-vs-
Keychain key mismatch must not train operators to reach for --skip-preflight).
"""
import importlib.util
import pathlib
import sys
import types

_ADAPTERS = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "adapters"
sys.path.insert(0, str(_ADAPTERS))
sys.path.insert(0, str(_ADAPTERS.parent))

_SPEC = importlib.util.spec_from_file_location(
    "rt_harness", _ADAPTERS.parent / "harness.py"
)
assert _SPEC is not None and _SPEC.loader is not None
h = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(h)


class _FakePath:
    def __init__(self, exists):
        self._exists = exists
    def exists(self):
        return self._exists
    def __fspath__(self):
        return "/fake/probe_models.py"


def _fake_run(returncode, tail="line"):
    def run(cmd, capture_output, text, timeout):  # noqa: ARG001
        return types.SimpleNamespace(returncode=returncode, stdout=tail, stderr="")
    return run


def test_retirement_aborts(monkeypatch):
    monkeypatch.setattr(h, "_PROBE", _FakePath(True))
    monkeypatch.setattr(h, "subprocess", types.SimpleNamespace(run=_fake_run(1, "SILENT REDIRECT")))
    aborts, warns = h.preflight_probe()
    assert aborts and not warns


def test_transient_warns_not_aborts(monkeypatch):
    monkeypatch.setattr(h, "_PROBE", _FakePath(True))
    monkeypatch.setattr(h, "subprocess", types.SimpleNamespace(run=_fake_run(2, "5xx transient")))
    aborts, warns = h.preflight_probe()
    assert warns and not aborts


def test_all_present_clean(monkeypatch):
    monkeypatch.setattr(h, "_PROBE", _FakePath(True))
    monkeypatch.setattr(h, "subprocess", types.SimpleNamespace(run=_fake_run(0, "PRESENT")))
    aborts, warns = h.preflight_probe()
    assert not aborts and not warns


def test_missing_probe_warns_not_aborts(monkeypatch):
    monkeypatch.setattr(h, "_PROBE", _FakePath(False))
    aborts, warns = h.preflight_probe()
    assert not aborts and warns and "not found" in warns[0]
