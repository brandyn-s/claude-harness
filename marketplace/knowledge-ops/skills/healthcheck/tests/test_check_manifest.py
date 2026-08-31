"""Unit tests for healthcheck/references/_check_manifest.py (Check 10/12).

Pins the registration classification (phantom = registered-but-absent → FAIL;
on-disk-but-unregistered → WARN; LOCAL_ONLY skills are neither) and the
AST-based PLUGINS parse that must not leak a `glob("skills/*/SKILL.md")` call
as a phantom skill named `*` (healthcheck false-FAIL, 2026-06-12).
"""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_manifest",
    Path(__file__).resolve().parent.parent / "references" / "_check_manifest.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


def _setup(tmp_path, monkeypatch, build_src, disk_skills):
    claude = tmp_path / ".claude"
    skills = claude / "skills"
    scripts = claude / "scripts"
    skills.mkdir(parents=True)
    scripts.mkdir()
    for s in disk_skills:
        (skills / s).mkdir()
        (skills / s / "SKILL.md").write_text("x", encoding="utf-8")
    build = scripts / "build-marketplace.py"
    build.write_text(build_src, encoding="utf-8")
    monkeypatch.setattr(hc, "SKILLS", skills)
    monkeypatch.setattr(hc, "BUILD_SCRIPT", build)
    monkeypatch.setattr(hc, "MARKETPLACE", claude / "marketplace")
    return claude


# __S__ placeholder + .replace, NOT .format — the literal { } of the JSON dict
# would otherwise be read as format fields (platform-constraints str.format trap).
_ONE_PLUGIN = ('PLUGINS = [{"name": "p", "files": '
               '[("skills/__S__/SKILL.md", "skills/__S__/SKILL.md")]}]\n')


def test_parse_plugins_extracts_tuples(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, _ONE_PLUGIN.replace("__S__", "foo"), ["foo"])
    plugins = hc.parse_plugins()
    assert plugins == [{"name": "p", "files": [("skills/foo/SKILL.md", "skills/foo/SKILL.md")]}]


def test_parse_plugins_ignores_glob_call(tmp_path, monkeypatch):
    # A glob CALL (not a literal tuple) must not register a skill named "*".
    src = (_ONE_PLUGIN.replace("__S__", "real")
           + 'EXTRA = somedir.glob("skills/*/SKILL.md")\n')
    _setup(tmp_path, monkeypatch, src, ["real"])
    warn, fail = hc.check_registration()
    assert fail == []                      # no phantom "*" skill
    assert not any("*" in w for w in warn)


def test_phantom_registered_but_absent_fails(tmp_path, monkeypatch):
    # foo is registered but NOT on disk → broken bundle → FAIL.
    _setup(tmp_path, monkeypatch, _ONE_PLUGIN.replace("__S__", "foo"), disk_skills=[])
    _warn, fail = hc.check_registration()
    assert any("foo" in f and "absent on disk" in f for f in fail)


def test_unregistered_on_disk_warns(tmp_path, monkeypatch):
    # bar is on disk but in no PLUGINS entry and not LOCAL_ONLY → WARN.
    _setup(tmp_path, monkeypatch, "PLUGINS = []\n", ["bar"])
    warn, fail = hc.check_registration()
    assert fail == []
    assert any("bar" in w and "not in PLUGINS" in w for w in warn)


def test_local_only_skill_not_flagged(tmp_path, monkeypatch):
    only = sorted(hc.LOCAL_ONLY_SKILLS)[0]
    _setup(tmp_path, monkeypatch, "PLUGINS = []\n", [only])
    warn, fail = hc.check_registration()
    assert fail == []
    assert not any(only in w for w in warn)


# ── Check 12: transform-aware drift ────────────────────────────────────
# The builder rewrites `$CONFIG_ROOT`-family paths to `${CLAUDE_PLUGIN_ROOT}` in
# the PUBLISHED copy only, so a raw byte compare reported every such file as
# drift and prescribed a rebuild that provably changed 0 files (measured
# 2026-08-30: 64 differing, 64 explained, 0 real). These tests pin BOTH
# directions — the transform is not drift, and a real content change still is.

_REWRITE_FN = (
    "def _rewrite_cached_paths(plugin_dir):\n"
    "    replacements = (\n"
    '        ("$CONFIG_ROOT/scripts/", "${CLAUDE_PLUGIN_ROOT}/scripts/"),\n'
    '        ("~/.claude/bin/", "${CLAUDE_PLUGIN_ROOT}/bin/"),\n'
    "    )\n"
    "    return replacements\n"
)


def _setup_drift(tmp_path, monkeypatch, src_text, bundle_text, *,
                 rewrite_fn=_REWRITE_FN, name="SKILL.md"):
    """Build a one-file plugin whose source and bundle contents are given."""
    claude = _setup(
        tmp_path, monkeypatch,
        _ONE_PLUGIN.replace("__S__", "foo").replace("SKILL.md", name) + rewrite_fn,
        ["foo"],
    )
    monkeypatch.setattr(hc, "CLAUDE_DIR", claude)
    src = claude / "skills" / "foo" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(src_text, encoding="utf-8")
    tgt = claude / "marketplace" / "p" / "skills" / "foo" / name
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_text(bundle_text, encoding="utf-8")
    return claude


def test_parse_path_rewrites_extracts_table(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, "PLUGINS = []\n" + _REWRITE_FN, [])
    assert hc.parse_path_rewrites() == [
        ("$CONFIG_ROOT/scripts/", "${CLAUDE_PLUGIN_ROOT}/scripts/"),
        ("~/.claude/bin/", "${CLAUDE_PLUGIN_ROOT}/bin/"),
    ]


def test_parse_path_rewrites_matches_the_real_builder(monkeypatch):
    """Parity pin: the real builder must still expose a parseable table.

    If `_rewrite_cached_paths` is renamed or its local is no longer a literal
    tuple, this fails loudly instead of the drift check silently reverting to a
    raw byte compare and re-reporting ~58 phantom drifts.

    Resolves the builder from THIS REPO (via `__file__`), not from the module's
    `CLAUDE_DIR` default. The pin's subject is the builder this checkout ships;
    binding it to `$CLAUDE_CONFIG_DIR` instead made it pass on a dev machine that
    happens to have a deployed `~/.claude` and raise FileNotFoundError on a CI
    runner that does not (measured 2026-08-30: `/home/runner/.claude/scripts/
    build-marketplace.py`). That is a self-confirming local pass — the resource
    the test needed was ambient on the author's host only.
    """
    repo_root = Path(__file__).resolve().parents[3]
    builder = repo_root / "scripts" / "build-marketplace.py"
    assert builder.is_file(), f"repo builder missing at {builder}"
    monkeypatch.setattr(hc, "BUILD_SCRIPT", builder)
    pairs = hc.parse_path_rewrites()
    assert pairs, "could not parse the builder's path-rewrite table"
    assert ("$CONFIG_ROOT/scripts/", "${CLAUDE_PLUGIN_ROOT}/scripts/") in pairs


def test_intended_path_rewrite_is_not_drift(tmp_path, monkeypatch):
    _setup_drift(
        tmp_path, monkeypatch,
        'REGISTRAR="$CONFIG_ROOT/scripts/wire_hooks.py"\n',
        'REGISTRAR="${CLAUDE_PLUGIN_ROOT}/scripts/wire_hooks.py"\n',
    )
    warn, fail = hc.check_marketplace_drift()
    assert fail == []
    assert not any("drift:" in w for w in warn), warn


def test_real_content_change_is_still_drift(tmp_path, monkeypatch):
    """The narrowing must not pass everything — a genuine edit still reports."""
    _setup_drift(
        tmp_path, monkeypatch,
        'REGISTRAR="$CONFIG_ROOT/scripts/wire_hooks.py"\n',
        'REGISTRAR="${CLAUDE_PLUGIN_ROOT}/scripts/wire_hooks.py"\nSENTINEL\n',
    )
    warn, fail = hc.check_marketplace_drift()
    assert fail == []
    assert any("drift:" in w and "foo" in w for w in warn), warn


def test_python_expanduser_transform_is_not_drift(tmp_path, monkeypatch):
    _setup_drift(
        tmp_path, monkeypatch,
        'p = os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], "skills", "foo/x.py")\n',
        'p = os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], "skills", "foo/x.py")\n',
        name="helper.py",
    )
    warn, fail = hc.check_marketplace_drift()
    assert fail == []
    assert not any("drift:" in w for w in warn), warn


def test_unparseable_rewrite_table_fails_loud(tmp_path, monkeypatch):
    """No table must FAIL, never degrade to a raw compare that invents drift."""
    _setup_drift(
        tmp_path, monkeypatch,
        'REGISTRAR="$CONFIG_ROOT/scripts/wire_hooks.py"\n',
        'REGISTRAR="${CLAUDE_PLUGIN_ROOT}/scripts/wire_hooks.py"\n',
        rewrite_fn="def _rewrite_cached_paths(d):\n    return ()\n",
    )
    _warn, fail = hc.check_marketplace_drift()
    assert any("path-rewrite table" in f for f in fail), fail
