#!/usr/bin/env python3
"""Regression fixtures for M5: null matchers crashed the documented queries.

THE DEFECT

`dict.get("matcher", "")` returns None when the key EXISTS with a null value -- the
default only covers a MISSING key. Valid hook manifests legitimately carry
`matcher: null` (matcher-less components such as git_lock and macos_notify), so
every containment check against a raw `.get` crashed:

    TypeError: argument of type 'NoneType' is not a container or iterable

Both queries named in the docs exited 1 on a CORRECT manifest set. The manifest graph
is cited as authoritative enforcement topology, so a query that cannot run is not a
cosmetic problem -- and one that silently omitted a hook would be worse.

Second half: `compile.py --check` exited 0 with five manifests still carrying
`event: TODO_EVENT` / `matcher: "TODO_MATCHER"` from the scaffolder, meaning the graph
encoded placeholder topology as fact.

Run: pytest manifests/test_query_engine_matchers.py -q
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO / "manifests" / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qe = _load("qe", "query_engine.py")
comp = _load("comp", "compile.py")


# ---------------------------------------------------------------------------
# the normalizer
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "component,expected",
    [
        ({"matcher": None}, ""),        # THE CRASH CASE: key present, value null
        ({}, ""),                       # key absent
        ({"matcher": ""}, ""),
        ({"matcher": "Write|Edit"}, "Write|Edit"),
        ({"matcher": ".*"}, ".*"),
        ({"matcher": 123}, "123"),      # non-string coerced, never crashes
    ],
)
def test_matcher_normalizes_to_a_string(component, expected):
    assert qe._matcher(component) == expected


def test_matcher_never_returns_none():
    """A None return would just move the TypeError downstream."""
    for c in ({"matcher": None}, {}, {"matcher": False}):
        assert isinstance(qe._matcher(c), str)


def test_containment_against_a_null_matcher_does_not_raise():
    """The exact expression that used to crash."""
    c = {"matcher": None}
    assert ("Write" in qe._matcher(c)) is False  # no TypeError


# ---------------------------------------------------------------------------
# the documented queries must actually run
# ---------------------------------------------------------------------------
def run_query(*args):
    return subprocess.run(
        [sys.executable, str(REPO / "manifests" / "query_engine.py"),
         "--root", str(REPO), *args],
        capture_output=True, text=True, timeout=300,
    )


@pytest.mark.parametrize(
    "args",
    [
        ("hooks_for_tool", "Write"),
        ("hooks_for_tool", "Bash"),
        ("enforcement_chain", "Edit settings.json"),
        ("enforcement_chain", "Bash git push"),
    ],
)
def test_documented_queries_exit_zero(args):
    p = run_query(*args)
    assert p.returncode == 0, f"{args} failed:\n{p.stderr[-600:]}"


@pytest.mark.parametrize(
    "args",
    [("hooks_for_tool", "Write"), ("enforcement_chain", "Edit settings.json")],
)
def test_documented_queries_return_results_not_just_success(args):
    """Exit 0 with an empty list would be a silent regression, not a fix."""
    p = run_query(*args)
    assert '"hook"' in p.stdout, f"{args} returned no hooks: {p.stdout[:300]}"


def test_library_and_cli_components_are_not_reported_as_enforcement():
    """hook_input (a shared library) and sync-repo (a CLI) never fire.

    They were scaffolded as `type: hook` with placeholder events. Reporting them in
    an enforcement chain would overstate the guard surface.
    """
    p = run_query("hooks_for_tool", "Write")
    assert "hook_input" not in p.stdout
    assert "sync-repo" not in p.stdout


# ---------------------------------------------------------------------------
# the placeholder gate
# ---------------------------------------------------------------------------
def test_placeholder_values_are_rejected():
    issues = comp.validate_placeholders({
        "some-hook": {"type": "hook", "event": "TODO_EVENT", "matcher": "TODO_MATCHER"},
    })
    assert len(issues) == 2
    assert all("PLACEHOLDER" in i for i in issues)


@pytest.mark.parametrize("bad", ["TODO_EVENT", "TODO_MATCHER", "TODO", "FIXME", "CHANGEME"])
def test_each_placeholder_token_is_caught(bad):
    issues = comp.validate_placeholders({"h": {"event": bad}})
    assert len(issues) == 1


def test_real_values_are_not_flagged():
    issues = comp.validate_placeholders({
        "h": {"type": "hook", "event": "PreToolUse", "matcher": "Write|Edit"},
        "n": {"type": "hook", "event": None, "matcher": None},
    })
    assert issues == []


def test_placeholders_in_comments_are_allowed():
    """`enforces: []  # TODO: which rules?` is an honest open question.

    Only parsed VALUES are checked, which is what makes this gate safe to enforce --
    otherwise every scaffolded manifest with a TODO note would fail.
    """
    issues = comp.validate_placeholders({"h": {"enforces": [], "event": "PreToolUse"}})
    assert issues == []


def test_repo_manifests_are_placeholder_free():
    """The shipped tree must satisfy the gate it now enforces."""
    p = subprocess.run(
        [sys.executable, str(REPO / "manifests" / "compile.py"),
         "--root", str(REPO), "--check", "--no-reindex"],
        capture_output=True, text=True, timeout=300,
    )
    assert "PLACEHOLDER" not in p.stdout, p.stdout
    assert p.returncode == 0, p.stdout[-800:]
