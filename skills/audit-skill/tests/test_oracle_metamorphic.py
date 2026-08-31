"""Metamorphic tests — relations that must hold across reproducer
rewrites, independent of the specific verdict value.

  R1 (invariance): two reproducers that encode the SAME predicate by
      different syntax must yield the SAME verdict.
  R2 (instrument≠predicate): a deliberately BROKEN reproducer (typo'd
      binary, malformed regex) must yield ERROR, never STALE — a broken
      instrument must not masquerade as "bug absent."
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for m in ("oracle", "oracle.finding", "oracle.reverify", "oracle.trace"):
        sys.modules.pop(m, None)
    from oracle.finding import Finding, Reproducer  # noqa: E402
    from oracle.reverify import reverify  # noqa: E402
    return Finding, Reproducer, reverify


def _status(reverify, Finding, Reproducer, command, repo_root, kind="grep"):
    f = Finding(skill="p", code="X", severity="info", label="doc-fix",
                description=command, reproducer=Reproducer(type=kind, command=command))
    return reverify([f], repo_root)[0].status


def test_equivalent_reproducers_same_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "t.jsonl"))
    Finding, Reproducer, reverify = _load()
    (tmp_path / "f.txt").write_text("foobar baseline\n", encoding="utf-8")
    fp = (tmp_path / "f.txt").as_posix()
    # Same predicate ("the file contains foo"), three syntaxes.
    variants = [f"grep -q foo {fp}", f"grep -qE 'fo+' {fp}", f"grep -q 'foo' {fp}"]
    verdicts = {_status(reverify, Finding, Reproducer, c, tmp_path) for c in variants}
    assert verdicts == {"STILL-FIRES"}, f"non-invariant across rewrites: {verdicts}"


def test_equivalent_absent_predicate_same_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "t.jsonl"))
    Finding, Reproducer, reverify = _load()
    (tmp_path / "f.txt").write_text("nothing relevant here\n", encoding="utf-8")
    fp = (tmp_path / "f.txt").as_posix()
    variants = [f"grep -q absent_token {fp}", f"grep -qE 'absent_(token|word)' {fp}"]
    verdicts = {_status(reverify, Finding, Reproducer, c, tmp_path) for c in variants}
    assert verdicts == {"STALE"}, f"non-invariant across rewrites: {verdicts}"


def test_broken_reproducer_is_error_not_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "t.jsonl"))
    Finding, Reproducer, reverify = _load()
    (tmp_path / "f.txt").write_text("data\n", encoding="utf-8")
    fp = (tmp_path / "f.txt").as_posix()
    broken = [
        f"grpe -q foo {fp}",        # typo'd binary -> command-not-found (rc 127)
        f"grep -qE '[' {fp}",       # malformed regex -> grep error (rc 2)
        f"grep -q foo {(tmp_path / 'does-not-exist.txt').as_posix()}",  # missing file (rc 2)
    ]
    for cmd in broken:
        status = _status(reverify, Finding, Reproducer, cmd, tmp_path)
        assert status == "ERROR", f"broken reproducer {cmd!r} -> {status}, expected ERROR"
