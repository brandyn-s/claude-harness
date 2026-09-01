"""Acceptance tests for compiler-derived enforcement topology."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("manifest_compile", REPO / "manifests" / "compile.py")
compiler = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(compiler)


def _write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def test_compiled_graph_derives_rule_back_reference_without_declared_field(tmp_path):
    _write_yaml(
        tmp_path / "hooks" / "manifests" / "guard.yaml",
        {"id": "guard", "type": "hook", "enforces": ["safety-rule"]},
    )
    _write_yaml(
        tmp_path / "rules" / "manifests" / "safety-rule.yaml",
        {
            "id": "safety-rule",
            "type": "rule",
            "description": "A safety rule.",
            "enforcement_coverage": "partial",
        },
    )
    (tmp_path / "rules" / "safety-rule.md").write_text("# Safety\n", encoding="utf-8")
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"hooks": [{"type": "command", "command": "python hooks/guard.py"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    issue_count = compiler.compile_graph(tmp_path, no_reindex=True, quiet=True)
    graph = json.loads((tmp_path / "manifests" / "graph.json").read_text(encoding="utf-8"))

    assert issue_count == 0
    assert graph["safety-rule"]["enforced_by"] == ["guard"]


def test_gate_rejects_coverage_that_denies_a_derived_edge(tmp_path):
    _write_yaml(
        tmp_path / "hooks" / "manifests" / "guard.yaml",
        {"id": "guard", "type": "hook", "enforces": ["safety-rule"]},
    )
    _write_yaml(
        tmp_path / "rules" / "manifests" / "safety-rule.yaml",
        {
            "id": "safety-rule",
            "type": "rule",
            "description": "A safety rule.",
            "enforcement_coverage": "none",
        },
    )
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"hooks": [{"type": "command", "command": "python hooks/guard.py"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    components = compiler.load_manifests(tmp_path)
    issues = compiler.validate_enforcement_edges(components, tmp_path)

    assert len(issues) == 1
    assert "COVERAGE-DRIFT" in issues[0]
    assert "guard" in issues[0]
