"""Tests for audit_hook_matchers.py.

Exercises the audit logic by:
1. Confirming current state is clean (real-world regression check)
2. Simulating a dead-matcher scenario via patched settings + hook pairs to
   verify the audit FINDS the mismatch
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from conftest import PYTHON

AUDIT_SCRIPT = Path(__file__).parent / "audit_hook_matchers.py"


def _run_audit(extra_env=None):
    env = None
    if extra_env:
        import os
        env = {**os.environ, **extra_env}
    result = subprocess.run(
        [PYTHON, str(AUDIT_SCRIPT), "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
    )
    return result


def test_current_state_is_clean():
    """Regression guard: the current settings.json + hooks should audit clean.

    If this fails, someone shipped a dead STATIC_MAP / STATIC_RULE_MAP entry
    without broadening the matcher. Fix by either widening the matcher or
    removing the dead entry. See PR #669 for the worked example.
    """
    result = _run_audit()
    assert result.returncode == 0, (
        f"Audit found dead entries:\n{result.stdout}"
    )
    data = json.loads(result.stdout)
    assert data["findings_count"] == 0, (
        f"Expected 0 findings, got {data['findings_count']}: {data['findings']}"
    )


def test_audit_detects_dead_entry_via_simulated_hook(tmp_path, monkeypatch):
    """Create a synthetic hook + settings.json where the matcher excludes
    one of the hook's internal tool prefixes. The audit MUST flag it.
    """
    # Build a fake .claude tree
    fake_root = tmp_path / ".claude"
    fake_hooks = fake_root / "hooks"
    fake_hooks.mkdir(parents=True)

    # Hook script with a STATIC_MAP entry for mcp__tavily__ and WebSearch
    synthetic_hook = fake_hooks / "synthetic-dead.py"
    synthetic_hook.write_text(
        'STATIC_MAP = {\n'
        '    "mcp__remote-foo__": "foo.md",\n'
        '    "mcp__tavily__": "bar.md",\n'  # this will be DEAD
        '    "WebSearch": "baz.md",\n'  # this will be DEAD
        '}\n',
        encoding="utf-8",
    )

    # settings.json with a matcher that only covers mcp__remote-foo__
    fake_settings = fake_root / "settings.json"
    fake_settings.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "mcp__remote-.*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{fake_hooks}/run-hook" synthetic-dead.py',
                        }
                    ],
                }
            ]
        }
    }), encoding="utf-8")

    # Point the audit at our fake root using HOME override via a wrapper
    # (simpler approach: monkey-patch via a small shim script)
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        f'import sys, pathlib\n'
        f'sys.path.insert(0, r"{AUDIT_SCRIPT.parent}")\n'
        f'import audit_hook_matchers as m\n'
        f'm.CLAUDE_ROOT = pathlib.Path(r"{fake_root}")\n'
        f'm.SETTINGS_PATH = m.CLAUDE_ROOT / "settings.json"\n'
        f'm.HOOKS_DIR = m.CLAUDE_ROOT / "hooks"\n'
        f'sys.argv = ["audit", "--format", "json"]\n'
        f'sys.exit(m.main())\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [PYTHON, str(wrapper)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert result.returncode == 1, (
        f"Audit should have returned 1 on synthetic dead-matcher:\n{result.stdout}\n{result.stderr}"
    )
    data = json.loads(result.stdout)
    missing = {f["missing_prefix"] for f in data["findings"]}
    assert "mcp__tavily__" in missing, f"tavily prefix should be flagged: {missing}"
    assert "WebSearch" in missing, f"WebSearch should be flagged: {missing}"
    assert "mcp__remote-foo__" not in missing, (
        f"remote-foo IS covered by matcher, should NOT be flagged: {missing}"
    )


def test_audit_text_format_readable():
    """--format text produces human-readable output (used by pre-commit hook)."""
    result = subprocess.run(
        [PYTHON, str(AUDIT_SCRIPT), "--verbose"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0
    assert "AUDIT CLEAN" in result.stdout or "FINDINGS" in result.stdout
    assert "hook registration" in result.stdout.lower()
