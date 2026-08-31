"""Tests for scripts/backfill_reproducers.py.

The backfiller turns 'cites X — file doesn't exist' descriptions into
machine-checkable reproducers, and demotes the label of remaining
manual findings to 'unverified' per the Phase 2 contract.

These tests pin the conversion behavior so future edits don't silently
weaken the heuristic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "skills" / "audit-skill" / "scripts" / "backfill_reproducers.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("backfill_reproducers", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_detects_cites_md_file_missing():
    m = _load_module()
    desc = "SKILL.md line 18 cites `~/Documents/knowledge-base/topics/foo.md` — file doesn't exist on disk."
    assert m.detect_file_missing(desc) == "~/Documents/knowledge-base/topics/foo.md"


def test_detects_cites_py_file_missing():
    m = _load_module()
    desc = "Phase 4.5 cites `~/.claude/scripts/missing.py` — file doesn't exist."
    assert m.detect_file_missing(desc) == "~/.claude/scripts/missing.py"


def test_does_not_detect_prose_only():
    m = _load_module()
    desc = "Phase 4.5 prose says X but no code writes it."
    assert m.detect_file_missing(desc) is None


def test_external_path_matched_against_registry():
    m = _load_module()
    pats = m.load_external_patterns()
    assert m.is_external_path("~/Documents/knowledge-base/topics/x.md", pats)
    assert not m.is_external_path("rules/foo.md", pats)


def test_backfill_external_path_demoted_not_converted():
    m = _load_module()
    pats = m.load_external_patterns()
    f = {
        "skill": "brainstorm",
        "code": "D4",
        "label": "doc-fix",
        "description": "Line 18 cites `~/Documents/knowledge-base/topics/x.md` — file doesn't exist.",
        "reproducer": {"type": "manual", "description": "..."},
    }
    _, action = m.backfill_one(f, pats)
    assert action == "skipped_external_path"
    assert f["label"] == "unverified"
    assert "external" in f.get("triage_note", "").lower()


def test_backfill_deploy_path_converted_to_bash_with_repo_check():
    """~/.claude/rules/X.md should check BOTH repo path and deployed
    path — the bug fires only if both are missing. Prevents
    false-positives on a properly-deployed system."""
    m = _load_module()
    pats = m.load_external_patterns()
    f = {
        "skill": "deep-dive",
        "code": "D4",
        "label": "behavior-fix",
        "description": "SKILL.md cites `~/.claude/rules/web-search-preference.md` — file doesn't exist.",
        "reproducer": {"type": "manual"},
    }
    _, action = m.backfill_one(f, pats)
    assert action == "converted_file_missing"
    rep = f["reproducer"]
    assert rep["type"] == "bash"
    # Must check the repo-relative path AND the deployed path.
    assert "rules/web-search-preference.md" in rep["command"]
    assert "$HOME/.claude/rules/web-search-preference.md" in rep["command"]
    # Label preserved (not demoted) because the reproducer is now auto.
    assert f["label"] == "behavior-fix"


def test_backfill_skill_relative_path_prefixed_with_skill_dir():
    """H1-shape citations are written relative to the SKILL directory,
    but the oracle resolves file_missing paths against repo_root — so a
    bare `plans/X.md` citation from skill `recall` must be checked at
    `skills/recall/plans/X.md`. Unprefixed, the reproducer was an
    always-fires tautology (2026-06-12 campaign finding audit-skill/D1:
    a citation to an EXISTING references/ file reported STILL-FIRES
    'exists=False')."""
    m = _load_module()
    pats = m.load_external_patterns()
    f = {
        "skill": "recall",
        "code": "D4",
        "label": "doc-fix",
        "description": "Cites `plans/2026-05-17-recall.md` — file doesn't exist.",
        "reproducer": {"type": "manual"},
    }
    _, action = m.backfill_one(f, pats)
    assert action == "converted_file_missing"
    assert f["reproducer"]["type"] == "file_missing"
    assert f["reproducer"]["path"] == "skills/recall/plans/2026-05-17-recall.md"


def test_backfill_repo_root_path_not_prefixed():
    """Citations that already name a repo-root tree (rules/, hooks/,
    bin/, ...) are repo-relative as written and must NOT be re-rooted
    under skills/<skill>/."""
    m = _load_module()
    pats = m.load_external_patterns()
    f = {
        "skill": "recall",
        "code": "D4",
        "label": "doc-fix",
        "description": "Cites `rules/no-such-rule.md` — file doesn't exist.",
        "reproducer": {"type": "manual"},
    }
    _, action = m.backfill_one(f, pats)
    assert action == "converted_file_missing"
    assert f["reproducer"]["type"] == "file_missing"
    assert f["reproducer"]["path"] == "rules/no-such-rule.md"


def test_backfill_demotes_manual_with_wrong_label():
    """Findings that remain type=manual must have label=unverified per
    the Phase 2 contract. The backfiller enforces this."""
    m = _load_module()
    pats = m.load_external_patterns()
    f = {
        "skill": "api-ingest",
        "code": "D4",
        "label": "doc-fix",
        "description": "Phase 4.5 prose says X but no code writes it.",
        "reproducer": {"type": "manual"},
    }
    _, action = m.backfill_one(f, pats)
    assert action == "demoted_to_unverified"
    assert f["label"] == "unverified"
    # Reproducer stays manual — we can't auto-check semantic claims.
    assert f["reproducer"]["type"] == "manual"


def test_backfill_skips_already_auto_reproducer():
    m = _load_module()
    pats = m.load_external_patterns()
    f = {
        "skill": "foo",
        "code": "H1",
        "label": "doc-fix",
        "description": "any",
        "reproducer": {
            "type": "grep",
            "command": "grep -q foo SKILL.md",
        },
    }
    _, action = m.backfill_one(f, pats)
    assert action == "no_change"
    assert f["reproducer"]["type"] == "grep"


def test_backfill_preserves_unverified_label():
    """If the agent already labeled the finding unverified, leave it
    alone (no demotion needed)."""
    m = _load_module()
    pats = m.load_external_patterns()
    f = {
        "skill": "foo",
        "code": "A3",
        "label": "unverified",
        "description": "Some semantic claim",
        "reproducer": {"type": "manual"},
    }
    _, action = m.backfill_one(f, pats)
    assert action == "no_change"
    assert f["label"] == "unverified"


def test_backfill_refuses_shell_metacharacters_in_path():
    """Security: paths extracted from descriptions are untrusted.
    A description containing shell metacharacters (that pass the
    regex character class) must NOT produce a bash reproducer
    interpolating them — that would be command injection when the
    oracle runs the reproducer against the live tree.

    The character class in FILE_MISSING_RE excludes whitespace and
    quotes (`, ', "), but allows $, (, ), ;, |, &, >, <, *, \\. The
    _is_safe_for_shell allowlist must reject these explicitly so the
    bash path resolves cleanly OR the finding is demoted.
    """
    m = _load_module()
    pats = m.load_external_patterns()
    # Paths that pass the regex character class but contain shell
    # metacharacters that would be active in a bash -c '...' command.
    for malicious_path, malicious_desc in [
        ("~/.claude/rules/$(touch /tmp/pwned).md",
         "cites ~/.claude/rules/$(touch /tmp/pwned).md — file doesn't exist"),
        ("~/foo;rm-rf.md",
         "cites ~/foo;rm-rf.md — file doesn't exist"),
        ("~/foo|cat.md",
         "cites ~/foo|cat.md — file doesn't exist"),
        ("~/foo&job.md",
         "cites ~/foo&job.md — file doesn't exist"),
        ("~/foo>out.md",
         "cites ~/foo>out.md — file doesn't exist"),
    ]:
        f = {
            "skill": "x",
            "code": "D4",
            "label": "doc-fix",
            "description": malicious_desc,
            "reproducer": {"type": "manual"},
        }
        _, action = m.backfill_one(f, pats)
        # The safety filter MUST trip and demote rather than build a
        # bash command containing the metacharacter.
        assert action == "demoted_to_unverified", (
            f"Malicious path {malicious_path!r} should have been "
            f"demoted, but action was {action!r}; reproducer is "
            f"{f.get('reproducer')!r}"
        )
        assert f["reproducer"]["type"] == "manual"
        assert f["label"] == "unverified"


def test_safe_path_filter_allows_normal_paths():
    """Sanity: normal paths must pass the safety filter."""
    m = _load_module()
    assert m._is_safe_for_shell("rules/foo.md")
    assert m._is_safe_for_shell("~/.claude/rules/foo.md")
    assert m._is_safe_for_shell("$HOME/.claude/rules/foo.md")
    assert m._is_safe_for_shell("skills/foo-bar/SKILL.md")
    assert m._is_safe_for_shell("a/b/c/d.py")


def test_safe_path_filter_rejects_metacharacters():
    """The allowlist excludes shell metacharacters even when they
    appear inside an otherwise-valid path."""
    m = _load_module()
    for bad in [
        "$(evil)",                # command substitution
        "foo;evil",               # statement separator
        "foo|evil",               # pipe
        "foo&evil",               # background
        "foo>out",                # redirection
        "foo<in",                 # redirection
        "foo*glob",               # glob
        "foo`backtick`",          # backtick (also would fail regex)
        "foo 'quoted'",           # space and quote
    ]:
        assert not m._is_safe_for_shell(bad), (
            f"Should reject metachar-bearing path: {bad!r}"
        )
