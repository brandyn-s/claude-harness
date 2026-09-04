"""Alias-file contract for references/discovery.py.

The public harness must not ship one environment's MCP-server inventory, so
discovery.py has an EMPTY built-in alias map and reads server -> topic aliases
from an optional, user-owned file:

    $CLAUDE_CONFIG_DIR/audit-architecture/aliases.json   (when the var is set)
    ~/.claude/audit-architecture/aliases.json            (otherwise)

as a flat JSON object {"server-name": "topic-alias"}. Pinned here:

  1. an alias file is honoured by name_variants(), ahead of mechanical variants
  2. a missing file yields no aliases at all
  3. a malformed file fails loudly with its path (CLI exit 2, the existing
     config-parse-failure code) while an otherwise clean config exits 0
  4. the shipped skill content (SKILL.md, context, references) names none of
     the former inventory

Re-run:
    pytest skills/audit-architecture/tests/test_audit_architecture_aliases.py -q
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SKILL = REPO / "skills" / "audit-architecture"
DISCOVERY = SKILL / "references" / "discovery.py"

# Names from the former hard-coded inventory. Anchored at a word start so the
# harness's own "defaultEnabled" does not trip "tenable".
FORMER_INVENTORY = re.compile(
    r"\b(?:airlock|hologram|netcloud|knowbe4|palantir|paloalto|pa-cdss|ashby|"
    r"lever\b|ramp\b|cornerstone|crowdstrike|tenable|security-remix|lucid|jamf|"
    r"intune|govcloud|sec-automation|claude-compliance|mcp\.example\.internal|"
    r"technological-ivory)",
    re.IGNORECASE,
)


def _load_discovery(monkeypatch, *, config_dir: Path | None, home: Path):
    """Import discovery.py fresh so its module-level BASE/HOME see the env."""
    if config_dir is None:
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("HOME", str(home))
    spec = importlib.util.spec_from_file_location(
        f"audit_architecture_discovery_{os.getpid()}_{id(monkeypatch)}", DISCOVERY
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _alias_file(config_dir: Path, text: str) -> Path:
    path = config_dir / "audit-architecture" / "aliases.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _minimal_config(config_dir: Path, home: Path) -> None:
    """Just enough config that discovery.py records no other parse errors."""
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.json").write_text("{}", encoding="utf-8")
    home.mkdir(parents=True, exist_ok=True)
    (home / ".claude.json").write_text("{}", encoding="utf-8")


def _run_cli(config_dir: Path, home: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config_dir), "HOME": str(home)}
    return subprocess.run(
        [sys.executable, str(DISCOVERY)], env=env, capture_output=True, text=True, check=False
    )


def test_alias_file_is_honoured_by_name_variants(tmp_path, monkeypatch):
    _alias_file(tmp_path, json.dumps({"example-server": "example-topic"}))
    mod = _load_discovery(monkeypatch, config_dir=tmp_path, home=tmp_path)

    variants = mod.name_variants("example-server")

    assert "example-topic" in variants
    # Explicit beats fuzzy: the alias precedes the mechanical prefix variant.
    assert variants.index("example-topic") < variants.index("example")


def test_missing_alias_file_yields_no_aliases(tmp_path, monkeypatch):
    mod = _load_discovery(monkeypatch, config_dir=tmp_path, home=tmp_path)

    assert not Path(mod.aliases_path()).exists()
    assert mod.ALIASES == {}, "the built-in map must ship empty"
    assert mod.load_aliases() == {}
    assert mod.name_variants("example-server") == ["example-server", "example"]


def test_alias_path_follows_config_dir_then_home(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    home = tmp_path / "home"
    mod = _load_discovery(monkeypatch, config_dir=cfg, home=home)
    assert Path(mod.aliases_path()) == cfg / "audit-architecture" / "aliases.json"

    mod = _load_discovery(monkeypatch, config_dir=None, home=home)
    assert Path(mod.aliases_path()) == home / ".claude" / "audit-architecture" / "aliases.json"


@pytest.mark.parametrize(
    "text",
    ["{not json", json.dumps(["not", "an", "object"]), json.dumps({"server": 1})],
    ids=["invalid-json", "list-not-object", "non-string-value"],
)
def test_malformed_alias_file_raises_with_its_path(tmp_path, monkeypatch, text):
    path = _alias_file(tmp_path, text)
    mod = _load_discovery(monkeypatch, config_dir=tmp_path, home=tmp_path)

    with pytest.raises(mod.AliasFileError) as excinfo:
        mod.load_aliases()
    assert str(path) in str(excinfo.value)


def test_cli_exits_2_and_names_the_malformed_alias_file(tmp_path):
    cfg = tmp_path / "cfg"
    home = tmp_path / "home"
    _minimal_config(cfg, home)

    control = _run_cli(cfg, home)
    assert control.returncode == 0, control.stderr
    assert json.loads(control.stdout)["errors"] == []

    path = _alias_file(cfg, "{not json")
    broken = _run_cli(cfg, home)
    assert broken.returncode == 2
    assert str(path) in broken.stderr
    assert any(str(path) in e for e in json.loads(broken.stdout)["errors"])


# Everything the marketplace bundle ships for this skill. Tests and fixtures are
# excluded on purpose: a fixture may use a generic vendor word; an inventory it
# is not.
SHIPPED = [
    SKILL / "SKILL.md",
    SKILL / "audit-context.md",
    SKILL / "audit-suppress.yaml",
    SKILL / "manifest.yaml",
    *sorted(p for p in (SKILL / "references").iterdir() if p.is_file()),
]


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.relative_to(SKILL).as_posix())
def test_shipped_skill_content_names_none_of_the_former_inventory(path):
    text = path.read_text(encoding="utf-8")
    hits = sorted({m.group(0).lower() for m in FORMER_INVENTORY.finditer(text)})
    assert not hits, f"{path.relative_to(SKILL)} still names the former inventory: {hits}"
