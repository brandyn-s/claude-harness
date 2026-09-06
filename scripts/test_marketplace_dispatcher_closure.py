#!/usr/bin/env python3
"""The marketplace builder must refuse a bundle that ships a dispatcher without
every hook its GUARDS table runs.

Why this gate exists: a dispatcher loads its children by file name at run time,
so the import-containment check cannot see them, and a missing "closed" child
makes the dispatcher block EVERY call it fronts. On 2026-09-06
script-content-guard.py joined both dispatchers and the safety-net bundle shipped
the Bash dispatcher without it -- an installed plugin that would have refused all
Bash. This test pins the detector on a synthetic bundle and asserts the real
bundles are closed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

DISPATCHER_SRC = '''
GUARDS = [
    ("alpha-guard", "alpha-guard.py", "closed"),
    ("beta-nudge", "beta-nudge.py", "open"),
]
'''


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location(
        "build_marketplace_closure", ROOT / "scripts" / "build-marketplace.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle(root: Path, name: str, children: list[str]) -> None:
    hooks = root / name / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "x-dispatcher.py").write_text(DISPATCHER_SRC, encoding="utf-8")
    for c in children:
        (hooks / c).write_text("def check(h):\n    return (0, None, None)\n", encoding="utf-8")


def test_missing_child_is_reported_with_its_posture(builder, tmp_path, monkeypatch):
    _bundle(tmp_path, "p", ["beta-nudge.py"])            # alpha-guard.py missing
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", tmp_path)
    monkeypatch.setattr(builder, "PLUGINS", [{"name": "p"}])
    assert builder.check_dispatcher_closure() == [("p", "x-dispatcher.py", "alpha-guard.py", "closed")]


def test_complete_bundle_is_clean(builder, tmp_path, monkeypatch):
    _bundle(tmp_path, "p", ["alpha-guard.py", "beta-nudge.py"])
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", tmp_path)
    monkeypatch.setattr(builder, "PLUGINS", [{"name": "p"}])
    assert builder.check_dispatcher_closure() == []


def test_real_bundles_are_closed(builder):
    assert builder.check_dispatcher_closure() == []


def test_safety_net_ships_the_script_content_guard_beside_the_dispatcher():
    hooks = ROOT / "marketplace" / "safety-net" / "hooks"
    assert (hooks / "bash-pretooluse-dispatcher.py").is_file()
    assert (hooks / "script-content-guard.py").is_file()
    registrations = (hooks / "hooks.json").read_text(encoding="utf-8")
    assert "script-content-guard.py" in registrations
