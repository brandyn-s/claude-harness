"""Layer D (fix-loop) tests for audit-architecture.

Reuses the audit-skill oracle fix_loop module — the module is
skill-agnostic. Tests the three classification outcomes against
architecture-specific finding patterns drawn from the calibration fixtures:

  VERIFIED        — reproducer flipped True → False across the fix
  STALE-PRE       — bug was already absent before the fix attempt
  FIX-INEFFECTIVE — fix edited the wrong thing; reproducer still fires

Architecture-specific finding patterns exercised:
  R3 — invalid JSON config (bash / python3 -c json.load)
  C2 — phantom server missing from routing rules (grep_absent)
  D5 — undocumented server in mcp.json (bash compound grep)

Re-run:
    pytest skills/audit-architecture/tests/test_audit_architecture_fix_loop.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in list(sys.modules):
        if mod in ("oracle", "oracle.finding", "oracle.fix_loop", "oracle.trace"):
            del sys.modules[mod]
    from oracle.finding import Finding, Reproducer
    from oracle.fix_loop import verify_fix_against_refs
    return Finding, Reproducer, verify_fix_against_refs


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True)


def _commit(path: Path, msg: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=path, check=True)
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path, capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


# ── R3: invalid JSON ───────────────────────────────────────────────────────────

def test_r3_VERIFIED_invalid_json_fixed(tmp_path):
    """R3: fixing bad-settings.json (invalid → valid JSON).
    Reproducer fires pre-fix; does not fire post-fix → VERIFIED."""
    Finding, Reproducer, verify = _load_oracle()
    _init_repo(tmp_path)

    (tmp_path / "settings.json").write_text("{not valid json,,}", encoding="utf-8")
    pre = _commit(tmp_path, "pre: invalid settings.json")

    (tmp_path / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    post = _commit(tmp_path, "post: valid settings.json")

    f = Finding(
        skill="architecture-fixture",
        code="R3",
        severity="drift",
        label="behavior-fix",
        description="settings.json is not valid JSON",
        reproducer=Reproducer(
            type="bash",
            command="python3 -c \"import json; json.load(open('settings.json'))\" 2>/dev/null",
            expected_exit=1,
        ),
    )
    r = verify(f, tmp_path, pre, post)
    assert r.status == "VERIFIED", (
        f"expected VERIFIED, got {r.status} "
        f"(pre_fires={r.pre_fires}, post_fires={r.post_fires})\n"
        f"pre evidence: {r.evidence_pre}\npost evidence: {r.evidence_post}"
    )


def test_r3_STALE_PRE_already_valid(tmp_path):
    """R3: finding is stale — settings.json was already valid before the fix."""
    Finding, Reproducer, verify = _load_oracle()
    _init_repo(tmp_path)

    (tmp_path / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    pre = _commit(tmp_path, "pre: already valid JSON")

    (tmp_path / "settings.json").write_text('{"hooks": {}, "note": "updated"}', encoding="utf-8")
    post = _commit(tmp_path, "post: cosmetic change")

    f = Finding(
        skill="architecture-fixture",
        code="R3",
        severity="drift",
        label="behavior-fix",
        description="settings.json not valid JSON (already resolved)",
        reproducer=Reproducer(
            type="bash",
            command="python3 -c \"import json; json.load(open('settings.json'))\" 2>/dev/null",
            expected_exit=1,
        ),
    )
    r = verify(f, tmp_path, pre, post)
    assert r.status == "STALE-PRE", (
        f"expected STALE-PRE, got {r.status}"
    )


def test_r3_FIX_INEFFECTIVE_wrong_file_edited(tmp_path):
    """R3: fix edited an unrelated file; settings.json is still invalid."""
    Finding, Reproducer, verify = _load_oracle()
    _init_repo(tmp_path)

    (tmp_path / "settings.json").write_text("{bad json}", encoding="utf-8")
    pre = _commit(tmp_path, "pre: invalid settings.json")

    (tmp_path / "notes.md").write_text("attempted fix\n", encoding="utf-8")
    post = _commit(tmp_path, "post: edited wrong file")

    f = Finding(
        skill="architecture-fixture",
        code="R3",
        severity="drift",
        label="behavior-fix",
        description="settings.json is not valid JSON",
        reproducer=Reproducer(
            type="bash",
            command="python3 -c \"import json; json.load(open('settings.json'))\" 2>/dev/null",
            expected_exit=1,
        ),
    )
    r = verify(f, tmp_path, pre, post)
    assert r.status == "FIX-INEFFECTIVE", (
        f"expected FIX-INEFFECTIVE, got {r.status}"
    )


# ── C2: missing routing rule ───────────────────────────────────────────────────

def test_c2_VERIFIED_routing_rule_added(tmp_path):
    """C2: phantom-server missing from routing-rules.json.
    Fix adds the routing entry → VERIFIED."""
    Finding, Reproducer, verify = _load_oracle()
    _init_repo(tmp_path)

    (tmp_path / "routing-rules.json").write_text('{"rules": []}', encoding="utf-8")
    pre = _commit(tmp_path, "pre: no routing rule for phantom-server")

    (tmp_path / "routing-rules.json").write_text(
        '{"rules": [{"server": "phantom-server", "route": "default"}]}',
        encoding="utf-8",
    )
    post = _commit(tmp_path, "post: routing rule added")

    f = Finding(
        skill="architecture-fixture",
        code="C2",
        severity="drift",
        label="behavior-fix",
        description="phantom-server has no routing rule",
        reproducer=Reproducer(
            type="grep_absent",
            command="grep -q 'phantom-server' routing-rules.json",
        ),
    )
    r = verify(f, tmp_path, pre, post)
    assert r.status == "VERIFIED", (
        f"expected VERIFIED, got {r.status} "
        f"(pre_fires={r.pre_fires}, post_fires={r.post_fires})"
    )


def test_c2_FIX_INEFFECTIVE_routing_rule_still_missing(tmp_path):
    """C2: fix edited the wrong file; routing rule remains absent → FIX-INEFFECTIVE."""
    Finding, Reproducer, verify = _load_oracle()
    _init_repo(tmp_path)

    (tmp_path / "routing-rules.json").write_text('{"rules": []}', encoding="utf-8")
    pre = _commit(tmp_path, "pre: no routing rule")

    (tmp_path / "notes.md").write_text("I think I fixed it\n", encoding="utf-8")
    post = _commit(tmp_path, "post: wrong file edited")

    f = Finding(
        skill="architecture-fixture",
        code="C2",
        severity="drift",
        label="behavior-fix",
        description="phantom-server has no routing rule",
        reproducer=Reproducer(
            type="grep_absent",
            command="grep -q 'phantom-server' routing-rules.json",
        ),
    )
    r = verify(f, tmp_path, pre, post)
    assert r.status == "FIX-INEFFECTIVE", (
        f"expected FIX-INEFFECTIVE, got {r.status}"
    )


# ── D5: undocumented server in mcp.json ───────────────────────────────────────

def test_d5_VERIFIED_server_documented(tmp_path):
    """D5: phantom-server in mcp.json but missing from ARCHITECTURE.md.
    Fix adds the entry to ARCHITECTURE.md → VERIFIED."""
    Finding, Reproducer, verify = _load_oracle()
    _init_repo(tmp_path)

    (tmp_path / "mcp.json").write_text(
        '{"mcpServers": {"phantom-server": {}}}', encoding="utf-8"
    )
    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture\n\n## Servers\n\n| real-server | ... |\n",
        encoding="utf-8",
    )
    pre = _commit(tmp_path, "pre: phantom-server undocumented")

    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture\n\n## Servers\n\n| real-server | ... |\n| phantom-server | ... |\n",
        encoding="utf-8",
    )
    post = _commit(tmp_path, "post: phantom-server documented")

    f = Finding(
        skill="architecture-fixture",
        code="D5",
        severity="info",
        label="doc-fix",
        description="phantom-server in mcp.json but absent from ARCHITECTURE.md",
        reproducer=Reproducer(
            type="bash",
            command=(
                "grep -q 'phantom-server' mcp.json && "
                "! grep -q 'phantom-server' ARCHITECTURE.md"
            ),
            expected_exit=0,
        ),
    )
    r = verify(f, tmp_path, pre, post)
    assert r.status == "VERIFIED", (
        f"expected VERIFIED, got {r.status} "
        f"(pre_fires={r.pre_fires}, post_fires={r.post_fires})"
    )
