"""Tests for hooks/_environment_catalog.py: merge order, fail-open, defaults.

The catalog is the only place hooks read environment names from, so its loader
has to be boring and predictable: a missing layer means "inherit", a malformed
layer means "skip with a note", and a layer that defines a section replaces
that section wholesale.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _environment_catalog as cat

HOOKS_DIR = Path(__file__).resolve().parent.parent
FIXTURE = HOOKS_DIR / "test-hooks" / "fixtures" / "environment-catalog.json"
DEFAULT = HOOKS_DIR.parent / "contracts" / "environment-catalog.json"
EXAMPLE = HOOKS_DIR.parent / "contracts" / "environment-catalog.example.json"


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return path


@pytest.fixture
def layers(tmp_path, monkeypatch):
    """Isolate all three layers under tmp_path; returns (default, home, override) paths.

    The default layer is redirected by monkeypatching `default_path`, the home
    layer through CLAUDE_CONFIG_DIR, the override through CLAUDE_ENVIRONMENT_CATALOG
    (unset until a test writes it).
    """
    default = tmp_path / "repo" / "contracts" / cat.FILE_NAME
    home_dir = tmp_path / "config"
    override = tmp_path / "override.json"
    monkeypatch.setattr(cat, "default_path", lambda: default)
    monkeypatch.setenv(cat.CONFIG_DIR_ENV, str(home_dir))
    monkeypatch.delenv(cat.OVERRIDE_ENV, raising=False)
    return default, home_dir / cat.FILE_NAME, override


# ── defaults ──────────────────────────────────────────────────────────────


def test_missing_files_yield_empty_sections(layers, capsys):
    catalog = cat.load_catalog()
    assert catalog == cat.empty_catalog()
    assert set(catalog) == set(cat.SECTIONS)
    assert all(v in ({}, []) for v in catalog.values())
    assert capsys.readouterr().err == "", "an absent layer is not an error"


def test_shipped_default_is_well_formed_and_empty():
    data = json.loads(DEFAULT.read_text(encoding="utf-8"))
    for name, kind in cat.SECTIONS.items():
        assert isinstance(data[name], kind), name
    merged = cat._strip_comments({k: v for k, v in data.items() if k in cat.SECTIONS})
    assert merged["expected_servers"] == []
    assert merged["repo_paths"] == {}
    assert merged["session_start"] == {"config_repo": None}
    for sub in merged["security_write_confirm"].values():
        assert sub in ({}, []), "shipped default must not name any server"
    for sub in merged["topic_routes"].values():
        assert sub == {}
    for sub in merged["failure_patterns"].values():
        assert sub == {}
    for sub in merged["agent_dispatch"].values():
        assert sub == []
    assert merged["env_exports"] == {"values": {}, "secrets": []}
    assert merged["safe_domains"] == []


def test_example_catalog_fills_every_section_with_placeholders():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    for name, kind in cat.SECTIONS.items():
        assert isinstance(data[name], kind), name
    swc = data["security_write_confirm"]
    assert swc["servers"] and swc["operation_rules"] and swc["wrapper_tools"]
    assert data["topic_routes"]["by_tool_prefix"] and data["topic_routes"]["by_keyword"]
    assert data["failure_patterns"]["servers"] and data["failure_patterns"]["hints"]
    assert data["agent_dispatch"]["auth_mcp_keywords"] and data["agent_dispatch"]["protected_repo_paths"]
    assert data["expected_servers"] and data["repo_paths"]
    assert data["session_start"]["config_repo"]["path"]
    assert data["env_exports"]["values"] and data["env_exports"]["secrets"]
    assert data["safe_domains"]
    text = EXAMPLE.read_text(encoding="utf-8").lower()
    for vendor in ("crowdstrike", "tenable", "airlock", "msgraph", "netcloud"):
        assert vendor not in text, f"the example must use placeholder names, found {vendor}"


def test_fixture_catalog_defines_every_section():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for name, kind in cat.SECTIONS.items():
        assert isinstance(data[name], kind), name


# ── merge order ───────────────────────────────────────────────────────────


def test_home_layer_replaces_default_section_and_inherits_the_rest(layers):
    default, home, _ = layers
    _write(default, {"expected_servers": ["a"], "repo_paths": {"r": "~/r"}})
    _write(home, {"expected_servers": ["b", "c"]})
    catalog = cat.load_catalog()
    assert catalog["expected_servers"] == ["b", "c"], "defined section replaces wholesale"
    assert list(catalog["repo_paths"]) == ["r"], "omitted section is inherited"


def test_override_wins_over_home_and_default(layers, monkeypatch):
    default, home, override = layers
    _write(default, {"expected_servers": ["a"]})
    _write(home, {"expected_servers": ["b"], "topic_routes": {"by_tool_prefix": {"mcp__x__": "x.md"}}})
    _write(override, {"expected_servers": ["c"]})
    monkeypatch.setenv(cat.OVERRIDE_ENV, str(override))
    catalog = cat.load_catalog()
    assert catalog["expected_servers"] == ["c"]
    assert catalog["topic_routes"] == {"by_tool_prefix": {"mcp__x__": "x.md"}}, "home layer still contributes"
    assert cat.layer_paths() == [default, home, override]


def test_home_layer_follows_claude_config_dir_then_home(tmp_path, monkeypatch):
    monkeypatch.setenv(cat.CONFIG_DIR_ENV, str(tmp_path / "cfg"))
    assert cat.home_path() == tmp_path / "cfg" / cat.FILE_NAME
    monkeypatch.delenv(cat.CONFIG_DIR_ENV)
    assert cat.home_path() == Path.home() / ".claude" / cat.FILE_NAME


def test_comment_keys_are_stripped_at_every_level(layers):
    default, _, _ = layers
    _write(default, {
        "_comment": "top",
        "security_write_confirm": {"_comment": "x", "servers": {"_comment": "y", "mcp__a__": {"label": "A"}}},
        "expected_servers": ["a"],
    })
    catalog = cat.load_catalog()
    assert catalog["security_write_confirm"] == {"servers": {"mcp__a__": {"label": "A"}}}
    assert catalog["expected_servers"] == ["a"]


# ── fail-open ─────────────────────────────────────────────────────────────


def test_malformed_layer_is_skipped_with_one_stderr_line(layers, capsys):
    default, home, _ = layers
    _write(default, {"expected_servers": ["a"]})
    _write(home, "{not json")
    catalog = cat.load_catalog()
    assert catalog["expected_servers"] == ["a"], "the good layer survives the bad one"
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "malformed" in err and str(home) in err


def test_wrong_container_type_is_skipped_per_section(layers, capsys):
    default, home, _ = layers
    _write(default, {"expected_servers": ["a"]})
    _write(home, {"expected_servers": "not-a-list", "repo_paths": {"r": "~/r"}})
    catalog = cat.load_catalog()
    assert catalog["expected_servers"] == ["a"]
    assert list(catalog["repo_paths"]) == ["r"], "the well-typed section of the same layer is used"
    assert "expected_servers" in capsys.readouterr().err


def test_non_object_top_level_is_skipped(layers, capsys):
    default, _, _ = layers
    _write(default, [1, 2, 3])
    assert cat.load_catalog() == cat.empty_catalog()
    assert "top level" in capsys.readouterr().err


def test_named_but_missing_override_is_noted_and_ignored(layers, monkeypatch, capsys):
    default, _, override = layers
    _write(default, {"expected_servers": ["a"]})
    monkeypatch.setenv(cat.OVERRIDE_ENV, str(override))  # never written
    assert cat.load_catalog()["expected_servers"] == ["a"]
    assert cat.OVERRIDE_ENV in capsys.readouterr().err


def test_unknown_section_name_is_a_programming_error(layers):
    with pytest.raises(KeyError):
        cat.load_section("no_such_section")


# ── repo_paths normalisation ──────────────────────────────────────────────


def test_repo_entries_accept_string_and_object_forms(capsys):
    entries = cat.repo_entries({
        "cfg": {"path": "~/.claude", "session_sync": True},
        "kb": "~/Documents/kb",
        "bad": 42,
        "empty": {"path": "  "},
    })
    assert [(e["name"], e["session_sync"]) for e in entries] == [("cfg", True), ("kb", False)]
    assert entries[0]["path"] == Path.home() / ".claude"
    assert entries[1]["path"] == Path.home() / "Documents" / "kb"
    err = capsys.readouterr().err
    assert "'bad'" in err and "'empty'" in err


def test_repo_entries_of_empty_section_is_empty():
    assert cat.repo_entries({}) == []
    assert cat.repo_entries(None) == []


# ── the suite's own wiring ────────────────────────────────────────────────


def test_suite_points_the_override_at_the_fixture(monkeypatch):
    """conftest.py sets CLAUDE_ENVIRONMENT_CATALOG for every test and subprocess,
    so the hooks under test read the fixture, not this machine's catalog."""
    import os
    assert Path(os.environ[cat.OVERRIDE_ENV]).resolve() == FIXTURE.resolve()
    assert cat.load_section("expected_servers"), "the fixture must be in effect"


def test_loader_is_importable_standalone_and_stdlib_only():
    """A hook copied into ~/.claude/hooks or a plugin bundle imports the loader
    beside itself; it must not need the repo, a package, or third-party modules."""
    spec = importlib.util.spec_from_file_location("env_cat_standalone", HOOKS_DIR / "_environment_catalog.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    source = (HOOKS_DIR / "_environment_catalog.py").read_text(encoding="utf-8")
    imports = {ln.split()[1].split(".")[0] for ln in source.splitlines()
               if ln.startswith(("import ", "from ")) and not ln.startswith("from __future__")}
    assert imports <= {"json", "os", "sys", "pathlib"}, imports
