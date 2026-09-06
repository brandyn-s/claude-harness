#!/usr/bin/env python3
"""Gate: the inventory numbers the top-level docs quote are generated, not typed.

bin/build-doc-counts.py --check must pass on the tree, the README must actually
carry markers (a gate over zero markers is vacuous), and a planted wrong number
must be caught (the check can fail). See the 2026-07-29 note in
bin/architecture-drift-check.py COUNT_CONTRACTS for why counts are generated.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "bin" / "build-doc-counts.py"


def _load():
    spec = importlib.util.spec_from_file_location("build_doc_counts", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_passes_on_the_tree():
    r = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr + r.stdout


def test_readme_and_architecture_carry_markers():
    mod = _load()
    for rel in ("README.md", "ARCHITECTURE.md", "AGENTS.md"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert mod.MARKER_RE.search(text), f"{rel} has no count markers; the gate would be vacuous there"


def test_no_unmarked_inventory_number_in_the_readme_headline():
    """The headline sentence is where the hand-typed numbers lived; every number in
    it must now sit inside a marker."""
    mod = _load()
    text = (REPO / "README.md").read_text(encoding="utf-8")
    headline = text.split("\n\n")[1] if text.startswith("# ") else text.split("\n\n")[0]
    stripped = mod.MARKER_RE.sub("", headline)
    import re
    bare = re.findall(r"\b\d[\d,]*\b", stripped)
    assert not bare, f"hand-typed numbers in the README headline: {bare}"


def test_every_marker_key_is_computed():
    mod = _load()
    counts = mod.compute()
    for rel in mod.DOCS:
        p = REPO / rel
        if not p.exists():
            continue
        for m in mod.MARKER_RE.finditer(p.read_text(encoding="utf-8")):
            assert m.group(2) in counts, f"{rel}: unknown key {m.group(2)}"


def test_a_planted_wrong_number_fails_the_check(tmp_path, monkeypatch):
    mod = _load()
    counts = mod.compute()
    (tmp_path / "README.md").write_text(
        "# x\n\n<!-- count:hooks -->9999<!-- /count --> hooks\n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "DOCS", ["README.md"])
    assert mod.apply(counts, check=True) == 1
    # and the generator repairs it
    assert mod.apply(counts, check=False) == 0
    assert f"<!-- count:hooks -->{counts['hooks']}<!-- /count -->" in (tmp_path / "README.md").read_text(encoding="utf-8")


def test_zero_markers_is_reported_as_vacuous(tmp_path, monkeypatch):
    mod = _load()
    counts = mod.compute()
    (tmp_path / "README.md").write_text("# x\n\nno markers here\n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "DOCS", ["README.md"])
    assert mod.apply(counts, check=True) == 1
