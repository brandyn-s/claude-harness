"""Gate: `ruff check` must report zero findings under the repo's own ruff.toml.

ruff.toml pins the selection to the correctness core (E4, E7, E9, F: undefined
names, unused imports and variables, syntax errors, statement hygiene). The
repo reached zero findings under it on 2026-09-04; this test keeps it there, so
a regression shows up as a failing test with the findings printed, not as a
lint count nobody reads.

ruff is resolved from PATH first, then as `python -m ruff` from the running
interpreter. If neither exists the test FAILS rather than skips: a skip here
would be a vacuous pass (a gate that cannot run has measured nothing). ruff is
in requirements-dev.txt so CI always has it.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ruff_command() -> list[str]:
    exe = shutil.which("ruff")
    if exe:
        return [exe]
    if importlib.util.find_spec("ruff") is not None:
        return [sys.executable, "-m", "ruff"]
    pytest.fail(
        "ruff is not installed: not on PATH and not importable from "
        f"{sys.executable}. Install requirements-dev.txt. This gate does not "
        "skip; a gate that cannot run has measured nothing."
    )


def _ruff(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _ruff_command() + args,
        cwd=cwd, capture_output=True, text=True, check=False, timeout=300,
    )


def test_ruff_check_is_clean_under_repo_config():
    """Repo config, no extra flags: exactly what `ruff check .` at the root means."""
    proc = _ruff(["check", "--output-format", "concise", "."], cwd=REPO_ROOT)
    assert proc.returncode == 0, (
        f"ruff check exited {proc.returncode}. Fix the findings; an import that "
        "must follow a sys.path insert takes `# noqa: E402 -- <why>` on its line.\n"
        f"{proc.stdout}{proc.stderr}"
    )


def test_gate_fires_on_a_known_violation(tmp_path):
    """Known-positive control: the repo config must still flag a real defect.

    Without this, an empty or mis-scoped `select` would let the test above pass
    for the wrong reason (AGENTS.md section 6: pair every zero with a control).
    """
    bad = tmp_path / "positive.py"
    bad.write_text("import os\n", encoding="utf-8")  # F401: unused import
    proc = _ruff(
        ["check", "--config", str(REPO_ROOT / "ruff.toml"),
         "--output-format", "concise", str(bad)],
        cwd=tmp_path,
    )
    assert proc.returncode == 1 and "F401" in proc.stdout, (
        f"exit {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
