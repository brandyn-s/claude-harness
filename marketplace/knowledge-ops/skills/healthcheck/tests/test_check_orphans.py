"""Unit tests for healthcheck/references/_check_orphans.py (Check 9).

Focused backfill pinning the 9f dead-ref behaviors that carry documented
false-positive fixes — skill-local resolution, EXAMPLE_PLACEHOLDER skip, and
illustrative-text (fenced/backtick) stripping — plus load_settings_hooks'
shlex-based basename extraction (the PR #548 cross-reference motivation).
"""
import json
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_orphans",
    Path(__file__).resolve().parent.parent / "references" / "_check_orphans.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


def _wire(tmp_path, monkeypatch):
    claude = tmp_path / ".claude"
    skills = claude / "skills"
    hooks = claude / "hooks"
    scripts = claude / "scripts"
    for d in (skills, hooks, scripts):
        d.mkdir(parents=True)
    monkeypatch.setattr(hc, "SKILLS_DIR", skills)
    monkeypatch.setattr(hc, "HOOKS_DIR", hooks)
    monkeypatch.setattr(hc, "SCRIPTS_DIR", scripts)
    return skills, hooks, scripts


def _skill(skills, name, body, local_files=()):
    d = skills / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    for rel in local_files:
        fp = d / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text("# x", encoding="utf-8")


def test_9f_flags_missing_reference(tmp_path, monkeypatch):
    skills, _, _ = _wire(tmp_path, monkeypatch)
    _skill(skills, "myskill", "Run the helper scripts/ghost.py to do the thing.")
    issues = hc.check_skill_body_dead_refs()
    assert any("ghost.py" in i for i in issues)


def test_9f_resolves_skill_local_reference(tmp_path, monkeypatch):
    skills, _, _ = _wire(tmp_path, monkeypatch)
    _skill(skills, "myskill", "See references/real.py for details.",
           local_files=["references/real.py"])
    issues = hc.check_skill_body_dead_refs()
    assert not any("real.py" in i for i in issues)


def test_9f_skips_example_placeholder(tmp_path, monkeypatch):
    skills, _, _ = _wire(tmp_path, monkeypatch)
    _skill(skills, "myskill", "For example, scripts/foo.py would run here.")
    issues = hc.check_skill_body_dead_refs()
    assert not any("foo.py" in i for i in issues)


def test_9f_skips_reference_inside_backticks(tmp_path, monkeypatch):
    skills, _, _ = _wire(tmp_path, monkeypatch)
    # Illustrative span: `scripts/incode.py` is stripped before scanning.
    _skill(skills, "myskill", "Invoke `scripts/incode.py` as an example.")
    issues = hc.check_skill_body_dead_refs()
    assert not any("incode.py" in i for i in issues)


def test_strip_illustrative_removes_fenced_and_inline():
    text = "before\n```\nscripts/x.py\n```\nand `scripts/y.py` after"
    stripped = hc._strip_illustrative_text(text)
    assert "x.py" not in stripped
    assert "y.py" not in stripped
    assert "before" in stripped and "after" in stripped


def test_load_settings_hooks_extracts_basenames(tmp_path, monkeypatch):
    claude = tmp_path / ".claude"
    claude.mkdir()
    settings = claude / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"hooks": [{"type": "command", "command": "python3 $HOME/.claude/hooks/foo.py"}]}]}}),
        encoding="utf-8")
    monkeypatch.setattr(hc, "SETTINGS_JSON", settings)
    assert hc.load_settings_hooks() == {"foo.py"}


def test_load_settings_hooks_extracts_exec_form_args(tmp_path, monkeypatch):
    claude = tmp_path / ".claude"
    claude.mkdir()
    settings = claude / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"hooks": [{
            "type": "command",
            "command": str(claude / "hooks" / "run-hook"),
            "args": ["foo.py"],
        }]}
    ]}}), encoding="utf-8")
    monkeypatch.setattr(hc, "SETTINGS_JSON", settings)
    assert hc.load_settings_hooks() == {"foo.py"}


# ── 9b: pytest auto-collection is a consumer that names no file ─────────
# `validate.yml` runs `pytest scripts/`, so every scripts/test_*.py is consumed
# by the COLLECTOR. A basename cross-reference cannot see that, and reported all
# 34 as orphans (measured 2026-08-30). Deleting one on that evidence silently
# drops a test — the PR #548 mistake in a new place.

def _workflows(tmp_path, monkeypatch, **files):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    for name, text in files.items():
        (wf / name.replace("__", "-")).write_text(text, encoding="utf-8")
    monkeypatch.setattr(hc, "WORKFLOWS_DIR", wf)
    return wf


def test_pytest_collected_targets_reads_ci_invocations(tmp_path, monkeypatch):
    _workflows(tmp_path, monkeypatch, **{
        "validate.yml": (
            "jobs:\n  a:\n    steps:\n"
            "      - run: pytest scripts/ -q\n"
            "      - run: pytest hooks/test-hooks/ -q\n"
            "      - run: pytest scripts/test_one.py::test_x -q\n"
        )
    })
    targets = hc.pytest_collected_targets()
    assert "scripts" in targets
    assert "hooks/test-hooks" in targets
    assert "scripts/test_one.py" in targets
    assert not any(t.startswith("-") for t in targets)


def test_pytest_consumes_only_test_files():
    targets = {"scripts"}
    assert hc._pytest_consumes("test_thing.py", targets)
    assert hc._pytest_consumes("conftest.py", targets)
    # A non-test module is NOT consumed by collection; it still needs a referrer.
    assert not hc._pytest_consumes("build_something.py", targets)


def test_pytest_consumes_requires_a_covering_target():
    # scripts/ is not collected anywhere → no exemption.
    assert not hc._pytest_consumes("test_thing.py", {"hooks/test-hooks"})


def test_collected_test_file_is_not_an_orphan(tmp_path, monkeypatch):
    _skills, _hooks, scripts = _wire(tmp_path, monkeypatch)
    (scripts / "test_collected.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    _workflows(tmp_path, monkeypatch, **{
        "validate.yml": "jobs:\n  a:\n    steps:\n      - run: pytest scripts/ -q\n"
    })
    monkeypatch.setattr(hc, "KNOWN_CLI_UTILITIES", set(), raising=False)
    assert hc.check_orphan_scripts() == []


def test_uncollected_non_test_script_is_still_an_orphan(tmp_path, monkeypatch):
    """The narrowing must not silence real orphans."""
    _skills, _hooks, scripts = _wire(tmp_path, monkeypatch)
    (scripts / "nobody_calls_me.py").write_text("x = 1\n", encoding="utf-8")
    _workflows(tmp_path, monkeypatch, **{
        "validate.yml": "jobs:\n  a:\n    steps:\n      - run: pytest scripts/ -q\n"
    })
    monkeypatch.setattr(hc, "KNOWN_CLI_UTILITIES", set(), raising=False)
    issues = hc.check_orphan_scripts()
    assert any("nobody_calls_me.py" in i for i in issues), issues


# ── 9d: actions/checkout `path:` is a RUNTIME clone dir ─────────────────

def test_9d_strips_declared_checkout_prefix(tmp_path, monkeypatch):
    """Isolates the stripping: the target sits where NO basename fallback looks.

    Placing it under skills/_shared would let the basename fallback resolve it
    even with stripping disabled, so the test would pass via the wrong mechanism
    and the mutation would read MISSED (overlapping defences).
    """
    _skills, _hooks, _scripts = _wire(tmp_path, monkeypatch)
    claude = tmp_path / ".claude"
    tools = claude / "docs" / "tools"
    tools.mkdir(parents=True)
    (tools / "verify_thing.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(hc, "CLAUDE_DIR", claude)
    _workflows(tmp_path, monkeypatch, **{
        "trusted.yml": (
            "jobs:\n  a:\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "        with:\n          path: trusted-config\n"
            "      - run: python trusted-config/docs/tools/verify_thing.py\n"
        )
    })
    assert hc.check_ci_workflow_integrity() == []


def test_9d_still_reports_a_genuinely_missing_ref(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(hc, "CLAUDE_DIR", tmp_path / ".claude")
    _workflows(tmp_path, monkeypatch, **{
        "trusted.yml": (
            "jobs:\n  a:\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "        with:\n          path: trusted-config\n"
            "      - run: python trusted-config/scripts/absent.py\n"
        )
    })
    issues = hc.check_ci_workflow_integrity()
    assert any("absent.py" in i for i in issues), issues


def test_9d_does_not_strip_an_undeclared_prefix(tmp_path, monkeypatch):
    """Only prefixes the workflow actually declares may be stripped."""
    skills, _hooks, _scripts = _wire(tmp_path, monkeypatch)
    shared = skills / "_shared"
    shared.mkdir(parents=True)
    (shared / "verify_thing.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(hc, "CLAUDE_DIR", tmp_path / ".claude")
    _workflows(tmp_path, monkeypatch, **{
        "trusted.yml": (
            "jobs:\n  a:\n    steps:\n"
            "      - run: python not-a-checkout/scripts/absent.py\n"
        )
    })
    issues = hc.check_ci_workflow_integrity()
    assert any("absent.py" in i for i in issues), issues
