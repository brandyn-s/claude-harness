"""Layer D (fix-loop) tests.

Exercises ``oracle.fix_loop.verify_fix_in_place`` against the
calibration set's true_fixture / false_fixture. The flow per test:

  1. Write the fixture in a "bug present" state.
  2. Run the loop. Pre = bug-present state (Reproducer fires).
     Then revert (via tmp git repo or in-memory shuffle) to the "no
     bug" state. Post = bug-absent state (Reproducer does NOT fire).
  3. Verify the loop classifies as VERIFIED.

Also exercises the failure-mode classification:
  - STALE-PRE: when the "bug" never existed pre-fix.
  - FIX-INEFFECTIVE: when the patch doesn't actually fix the predicate.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _isolate_trace(tmp_path, monkeypatch):
    """Layer D now writes trace records (the enforced-gate change).
    Redirect the trace to a per-test tmp file so the suite never appends
    to the operator's real ~/.claude/oracle-trace.jsonl."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "oracle-trace.jsonl"))


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in ("oracle", "oracle.finding", "oracle.fix_loop", "oracle.trace"):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle.finding import Finding, Reproducer  # noqa: E402
    from oracle.fix_loop import (  # noqa: E402
        verify_fix_against_refs,
        verify_fix_in_place,
    )
    return Finding, Reproducer, verify_fix_against_refs, verify_fix_in_place


def _init_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)


def _commit_all(repo: Path, msg: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True)
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_verify_fix_against_refs_VERIFIED(tmp_path):
    """A real fix that removes a known-phantom MCP tool reference
    from a file. Pre-fix the grep fires; post-fix it does not.
    Layer D must classify as VERIFIED."""
    Finding, Reproducer, verify_against_refs, _ = _load_oracle()
    _init_repo(tmp_path)
    target = tmp_path / "skill.md"

    # Pre: bug present
    target.write_text(
        "---\nname: example\nallowed-tools: Read mcp__code-graph__index_status\n---\n# body\n",
        encoding="utf-8",
    )
    pre_sha = _commit_all(tmp_path, "pre: contains phantom tool")

    # Apply the "fix": remove the phantom tool from allowed-tools
    target.write_text(
        "---\nname: example\nallowed-tools: Read\n---\n# body\n",
        encoding="utf-8",
    )
    post_sha = _commit_all(tmp_path, "post: phantom tool removed")

    f = Finding(
        skill="example",
        code="T1",
        severity="drift",
        label="behavior-fix",
        description="known-phantom mcp__code-graph__index_status reference",
        reproducer=Reproducer(
            type="grep",
            command="grep -q 'mcp__code-graph__index_status' skill.md",
        ),
    )
    result = verify_against_refs(f, tmp_path, pre_sha, post_sha)
    assert result.status == "VERIFIED", (
        f"expected VERIFIED, got {result.status} "
        f"(pre_fires={result.pre_fires}, post_fires={result.post_fires})"
    )


def test_verify_fix_against_refs_STALE_PRE(tmp_path):
    """The "bug" never existed in pre. Layer D must classify as
    STALE-PRE — caller should not act on this finding."""
    Finding, Reproducer, verify_against_refs, _ = _load_oracle()
    _init_repo(tmp_path)
    target = tmp_path / "skill.md"

    # Pre: NO bug present
    target.write_text("---\nname: example\nallowed-tools: Read\n---\n", encoding="utf-8")
    pre_sha = _commit_all(tmp_path, "pre: clean")

    # "Fix" (no-op since the bug wasn't there)
    target.write_text("---\nname: example\nallowed-tools: Read\n---\n# updated\n", encoding="utf-8")
    post_sha = _commit_all(tmp_path, "post: cosmetic change")

    f = Finding(
        skill="example",
        code="T1",
        severity="drift",
        label="behavior-fix",
        description="hallucinated phantom tool",
        reproducer=Reproducer(
            type="grep",
            command="grep -q 'mcp__code-graph__index_status' skill.md",
        ),
    )
    result = verify_against_refs(f, tmp_path, pre_sha, post_sha)
    assert result.status == "STALE-PRE", (
        f"expected STALE-PRE (bug never existed), got {result.status}"
    )


def test_verify_fix_against_refs_FIX_INEFFECTIVE(tmp_path):
    """The patch edited the wrong file or otherwise failed to resolve
    the Reproducer predicate. Layer D must classify as FIX-INEFFECTIVE."""
    Finding, Reproducer, verify_against_refs, _ = _load_oracle()
    _init_repo(tmp_path)
    target = tmp_path / "skill.md"

    # Pre: bug present
    target.write_text(
        "---\nname: example\nallowed-tools: Read mcp__code-graph__index_status\n---\n",
        encoding="utf-8",
    )
    pre_sha = _commit_all(tmp_path, "pre: phantom present")

    # "Fix": edited an unrelated file, the phantom is still in skill.md
    other = tmp_path / "notes.md"
    other.write_text("Some notes — I claim to have fixed the phantom tool.\n", encoding="utf-8")
    post_sha = _commit_all(tmp_path, "post: claims fix but actually changed wrong file")

    f = Finding(
        skill="example",
        code="T1",
        severity="drift",
        label="behavior-fix",
        description="known-phantom reference",
        reproducer=Reproducer(
            type="grep",
            command="grep -q 'mcp__code-graph__index_status' skill.md",
        ),
    )
    result = verify_against_refs(f, tmp_path, pre_sha, post_sha)
    assert result.status == "FIX-INEFFECTIVE", (
        f"expected FIX-INEFFECTIVE (vacuous fix), got {result.status}"
    )


def test_layer_d_writes_trace_records(tmp_path, monkeypatch):
    """Each fix-loop run should write structured trace records to the
    oracle trace file. (Smoke check — the trace integration in fix_loop
    is currently lighter than Layer A's; this guards against silent
    regression if/when we add trace_invocation there.)"""
    # For now this just confirms the trace path env var is honored
    # for downstream Layer A reproducer calls invoked by fix_loop.
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, verify_against_refs, _ = _load_oracle()
    _init_repo(tmp_path)
    target = tmp_path / "skill.md"
    target.write_text("bug-line\n", encoding="utf-8")
    pre_sha = _commit_all(tmp_path, "pre")
    target.write_text("clean-line\n", encoding="utf-8")
    post_sha = _commit_all(tmp_path, "post")
    f = Finding(
        skill="example",
        code="X1",
        severity="drift",
        label="behavior-fix",
        description="grep bug",
        reproducer=Reproducer(type="grep", command="grep -q 'bug-line' skill.md"),
    )
    result = verify_against_refs(f, tmp_path, pre_sha, post_sha)
    assert result.status == "VERIFIED"
    # Layer D now writes a trace record (added alongside the enforced
    # SubagentStop gate). Confirm exactly one layer="D" record landed
    # with the VERIFIED verdict and a session_id attribution key.
    trace_file = tmp_path / "trace.jsonl"
    recs = [json.loads(l) for l in trace_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    d_recs = [r for r in recs if r.get("layer") == "D"]
    assert len(d_recs) == 1, f"expected 1 Layer-D record, got {len(d_recs)}"
    assert d_recs[0]["verdict"] == "VERIFIED"
    assert "session_id" in d_recs[0]["input"]
