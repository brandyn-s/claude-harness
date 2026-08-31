"""End-to-end golden tests for audit-architecture/doc_accuracy_audit.py.

Covers the May 2026 audit fix: bare open() calls in load_actual_state()
were wrapped in try/except for FileNotFoundError + JSONDecodeError so a
missing or malformed `settings.json` / `~/.claude.json` no longer crashes
the audit. The audit must still produce structured JSON output even when
config files are absent.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPT = SKILL_DIR / "references" / "doc_accuracy_audit.py"


def _make_minimal_claude_dir(root: Path):
    """Create the minimum file tree the auditor expects to read."""
    arch = root / "ARCHITECTURE.md"
    arch.write_text("# ARCHITECTURE\n\nhas 0 agents defined.\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# CLAUDE\n", encoding="utf-8")
    proj = root / "projects" / "test-project"
    proj.mkdir(parents=True)
    (proj / "CLAUDE.md").write_text("# project claude\n", encoding="utf-8")
    mem_dir = proj / "memory"
    mem_dir.mkdir()
    (mem_dir / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    # Empty subdirectories the script enumerates
    (root / "skills").mkdir()
    (root / "rules").mkdir()
    (root / "hooks").mkdir()
    (root / "agent-memory" / "topics").mkdir(parents=True)


def test_audit_handles_missing_config_files(tmp_path):
    """No settings.json, no ~/.claude.json — auditor must not crash; must
    print ERROR messages to stderr and continue with empty defaults."""
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    _make_minimal_claude_dir(config_dir)

    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    env["HOME"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env,
        cwd=str(tmp_path),
    )
    # The auditor exits 0 when no drift OR 1 when drift detected; either is
    # acceptable for this test — what matters is that it didn't crash with
    # an unhandled exception.
    assert r.returncode in (0, 1), (
        f"auditor crashed with rc={r.returncode}\nstderr:\n{r.stderr}"
    )
    # Stdout must be valid JSON with the expected top-level shape.
    output = json.loads(r.stdout)
    for key in ("architecture_md", "claude_md", "memory_md", "orphan_hooks",
                "total_issues"):
        assert key in output, f"missing top-level key {key} in audit JSON"
    # Stderr should mention the missing config files (the graceful-handler
    # messages — not Python tracebacks).
    assert "Traceback" not in r.stderr, (
        f"unexpected traceback — graceful handling regressed:\n{r.stderr}"
    )


def test_audit_handles_malformed_settings_json(tmp_path):
    """settings.json exists but is not valid JSON. Auditor still completes."""
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    _make_minimal_claude_dir(config_dir)
    (config_dir / "settings.json").write_text("not-json-at-all{", encoding="utf-8")

    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    env["HOME"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, env=env,
        cwd=str(tmp_path),
    )
    assert r.returncode in (0, 1), (
        f"auditor crashed with rc={r.returncode} on malformed settings.json\n"
        f"stderr:\n{r.stderr}"
    )
    assert "Traceback" not in r.stderr
    output = json.loads(r.stdout)
    assert "total_issues" in output
