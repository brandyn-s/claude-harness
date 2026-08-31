"""Tests for detect_demotion_candidates.py (Phase 7b).

The detector joins classify_rules.py (which rules are hook-enforced)
with scan_violations.py (per-rule session_rate). It flags rules where
both conditions hold: hook-enforced AND high rate. Those are
ambiguous signals — coverage gap, agent workaround, or hook
over-fires — that deserve operator investigation.

These tests pin the join logic and threshold filtering against a
synthetic transcript fixture. The fixture seeds session-transcripts/
with violations of every hook-enforced rule scan_violations.py knows
about (V1 encoding-missing-open, V3 inline-python-c, V4
str-replace-crlf-risk, V5 git-commit-no-branch-check), so the scanner
reports 100% session_rate on all of them — guaranteed candidates for
the join.

Why the fixture: CI runners have no ~/.claude/projects/* or
~/.claude/session-transcripts/, so a "live data" smoke test would
always fail with rc=1 "no transcript directories found". Setting
HOME + USERPROFILE to a tmp dir with a curated jsonl gives the
subprocess deterministic input on every platform.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "skills" / "audit-rules" / "scripts" / "detect_demotion_candidates.py"


def _seed_transcript_home(tmp_path: Path) -> Path:
    """Build a tmp HOME with a session-transcripts/ dir containing one
    .jsonl fixture that triggers every hook-enforced detector
    scan_violations.py covers. Returns the HOME dir path."""
    home = tmp_path / "home"
    transcripts = home / ".claude" / "session-transcripts"
    transcripts.mkdir(parents=True)

    long_py_body = "import json; " * 30 + "print('x')"
    events = [
        # V1 encoding-missing-open (hook: post-write-edit.py)
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Write", "input": {
                "file_path": "/tmp/x.py",
                "content": (
                    "import json\n"
                    "def load():\n"
                    "    f = open('/tmp/data.json')\n"
                    "    return json.load(f)\n"
                ),
            }}
        ]}},
        # V3 inline-python-c (hook: post-write-edit.py)
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": f'python3 -c "{long_py_body}"'}}
        ]}},
        # V4 str-replace-crlf-risk (hook: post-write-edit.py)
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Write", "input": {
                "file_path": "/tmp/y.py",
                "content": (
                    "with open('/tmp/data.txt', encoding='utf-8') as f:\n"
                    "    text = f.read()\n"
                    "cleaned = text.replace('\\n', ' ')\n"
                ),
            }}
        ]}},
        # V5 git-commit-no-branch-check (hook: bash-security-guard.py)
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "git commit -m 'x'"}}
        ]}},
    ]
    fixture = transcripts / "demotion-fixture.jsonl"
    with fixture.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return home


def _run(args: list[str], home: Path) -> subprocess.CompletedProcess:
    """Invoke detect_demotion_candidates.py with HOME + USERPROFILE
    overridden to the seeded fixture dir. USERPROFILE is what
    `pathlib.Path.home()` reads on Windows."""
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=120,
        cwd=str(REPO), env=env,
    )


def test_smoke_against_seeded_fixture(tmp_path):
    """Smoke test: the script runs against the synthetic fixture
    without crashing. Returns valid JSON when --json passed."""
    home = _seed_transcript_home(tmp_path)
    r = _run(["--json"], home)
    assert r.returncode == 0, f"rc={r.returncode}; stderr={r.stderr[:300]!r}"
    data = json.loads(r.stdout)
    assert "demotion_candidates" in data
    assert "threshold_pct" in data
    assert "scan_window_days" in data
    assert "total_hook_enforced_rules" in data
    assert isinstance(data["demotion_candidates"], list)


def test_threshold_filtering_works(tmp_path):
    """A higher threshold should produce fewer or equal candidates."""
    home = _seed_transcript_home(tmp_path)
    r1 = _run(["--json", "--threshold", "10"], home)
    r2 = _run(["--json", "--threshold", "90"], home)
    assert r1.returncode == 0 and r2.returncode == 0
    d1 = json.loads(r1.stdout)
    d2 = json.loads(r2.stdout)
    assert len(d2["demotion_candidates"]) <= len(d1["demotion_candidates"]), (
        f"higher threshold should yield fewer candidates: "
        f"got {len(d1['demotion_candidates'])} at 10% vs "
        f"{len(d2['demotion_candidates'])} at 90%"
    )


def test_threshold_at_100_excludes_all(tmp_path):
    """Threshold > 100.0 should exclude everything since no rule has
    rate > 100%."""
    home = _seed_transcript_home(tmp_path)
    r = _run(["--json", "--threshold", "100.1"], home)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["demotion_candidates"] == []


def test_candidate_records_hook_source(tmp_path):
    """Each demotion candidate must name the enforcing hook so the
    operator can investigate (widen, document, or demote)."""
    home = _seed_transcript_home(tmp_path)
    r = _run(["--json", "--threshold", "10"], home)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    # The fixture is designed to trigger every hook-enforced detector,
    # so at threshold=10 we should see candidates.
    assert data["demotion_candidates"], (
        "seeded fixture should produce candidates at threshold=10; "
        f"got {data['demotion_candidates']}"
    )
    for c in data["demotion_candidates"]:
        assert "hook_source" in c, "candidate missing hook_source"
        assert c["hook_source"].endswith(".py"), (
            f"hook_source should be a .py file: {c['hook_source']!r}"
        )


def test_candidate_records_hypothesis(tmp_path):
    """Each candidate carries a hypothesis string so the operator
    knows what to investigate without re-reading the SKILL.md."""
    home = _seed_transcript_home(tmp_path)
    r = _run(["--json", "--threshold", "10"], home)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["demotion_candidates"], "seeded fixture should produce candidates"
    for c in data["demotion_candidates"]:
        assert "hypothesis" in c
        # Hypothesis should mention the three possible causes
        hyp = c["hypothesis"].lower()
        assert "coverage gap" in hyp or "workaround" in hyp or "over-fires" in hyp


def test_human_readable_output_includes_followup_pointer(tmp_path):
    """The default (non-JSON) output should tell the operator where to
    look next (SKILL.md demotion workflow)."""
    home = _seed_transcript_home(tmp_path)
    r = _run([], home)
    assert r.returncode == 0
    if "demotion candidates" in r.stdout.lower():
        # If candidates exist, must point at the workflow
        assert "Demotion workflow" in r.stdout or "SKILL.md" in r.stdout
