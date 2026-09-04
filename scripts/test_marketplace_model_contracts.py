"""Bundles that package a skill reading the model contracts ship the contracts.

scripts/model_contracts.py and contracts/model-capabilities.json are read at run
time by the persona and roundtable skills (alias resolution, current model ids).
Until 2026-09-04 no bundle shipped them, so from an installed plugin alias
resolution failed fast and an exact id passed unvalidated (persona's
model_runtime.py documents that degradation). scripts/build-marketplace.py now
copies both files into any plugin whose packaged skill .py files name either,
records them in the dependency lock, and refuses a release where they are
missing or stale. These tests pin the detection, the copy, the built tree, and
the gate; scripts/check-marketplace-sync.py (which rebuilds and diffs) is the
end-to-end check that the committed bundles carry current copies.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / "marketplace"


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location(
        "build_marketplace_contracts", ROOT / "scripts" / "build-marketplace.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_plugin(root: Path, name: str, consumer_source: str | None) -> Path:
    plugin_dir = root / name
    scripts = plugin_dir / "skills" / "some-skill" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "helper.py").write_text(
        consumer_source if consumer_source is not None else "print('no contracts here')\n",
        encoding="utf-8",
    )
    return plugin_dir


@pytest.mark.parametrize(
    "source",
    [
        "from scripts import model_contracts as ids\n",
        "import model_contracts\n",
        'CONTRACT = ROOT / "contracts" / "model-capabilities.json"\n',
    ],
)
def test_detection_matches_an_import_or_a_contract_reference(builder, tmp_path, source):
    plugin_dir = _fake_plugin(tmp_path, "p", source)
    consumers = builder._model_contract_consumers(plugin_dir)
    assert [c.name for c in consumers] == ["helper.py"]


def test_detection_ignores_unrelated_code_and_missing_skills(builder, tmp_path):
    assert builder._model_contract_consumers(_fake_plugin(tmp_path, "p", None)) == []
    (tmp_path / "hooks-only").mkdir()
    assert builder._model_contract_consumers(tmp_path / "hooks-only") == []


def test_copy_ships_both_files_at_their_source_paths(builder, tmp_path):
    plugin_dir = _fake_plugin(tmp_path, "p", "from scripts import model_contracts\n")
    shipped = builder._copy_model_contracts(plugin_dir)
    assert shipped == list(builder.MODEL_CONTRACT_FILES)
    for rel in builder.MODEL_CONTRACT_FILES:
        assert (plugin_dir / rel).read_bytes() == (ROOT / rel).read_bytes(), rel


def test_copy_ships_nothing_without_a_consumer(builder, tmp_path):
    plugin_dir = _fake_plugin(tmp_path, "p", None)
    assert builder._copy_model_contracts(plugin_dir) == []
    assert not (plugin_dir / "scripts").exists()
    assert not (plugin_dir / "contracts").exists()


def test_release_gate_reports_missing_and_stale_copies(builder, tmp_path, monkeypatch):
    plugin_dir = _fake_plugin(tmp_path, "gated", "from scripts import model_contracts\n")
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", tmp_path)
    monkeypatch.setattr(builder, "PLUGINS", [{"name": "gated"}])
    problems = builder.check_model_contract_containment()
    assert {p[2] for p in problems} == {f"missing {rel}" for rel in builder.MODEL_CONTRACT_FILES}

    builder._copy_model_contracts(plugin_dir)
    assert builder.check_model_contract_containment() == []

    (plugin_dir / "contracts" / "model-capabilities.json").write_text("{}", encoding="utf-8")
    problems = builder.check_model_contract_containment()
    assert [p[2] for p in problems] == ["stale contracts/model-capabilities.json"]


def test_built_bundles_carry_current_contracts_where_a_skill_reads_them(builder):
    """The committed tree: every plugin packaging a consumer ships current copies;
    every plugin without one ships neither. Vacuity floor: persona and roundtable
    are packaged in at least one bundle, so the consumer set is never empty."""
    consumers_by_plugin = {}
    for plugin_dir in sorted(p for p in MARKETPLACE.iterdir() if p.is_dir()):
        consumers_by_plugin[plugin_dir.name] = builder._model_contract_consumers(plugin_dir)
    with_consumers = {name for name, found in consumers_by_plugin.items() if found}
    assert {"research-intel", "knowledge-ops"} <= with_consumers, consumers_by_plugin
    assert "safety-net" not in with_consumers

    for name in with_consumers:
        plugin_dir = MARKETPLACE / name
        for rel in builder.MODEL_CONTRACT_FILES:
            assert (plugin_dir / rel).is_file(), f"{name} lacks {rel}; rebuild the bundles"
            assert (plugin_dir / rel).read_bytes() == (ROOT / rel).read_bytes(), (
                f"{name}/{rel} is stale; run scripts/build-marketplace.py"
            )
        lock = (plugin_dir / ".claude-plugin" / "dependency-lock.json").read_text(encoding="utf-8")
        assert '"model_contracts"' in lock, f"{name} lock does not record the contracts"
    for name in set(consumers_by_plugin) - with_consumers:
        for rel in builder.MODEL_CONTRACT_FILES:
            assert not (MARKETPLACE / name / rel).exists(), f"{name} ships {rel} without a consumer"
