"""compile.py must prove its own detectors still fire, and must not call an empty tree clean.

A validator whose regex silently stopped matching reports a clean repo forever
(trailofbits/skills keeps a validator --self-test for exactly this reason).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COMPILE = REPO / "manifests" / "compile.py"


def _run(*args, cwd=REPO):
    return subprocess.run([sys.executable, str(COMPILE), *args], capture_output=True, text=True, timeout=300, cwd=cwd)


def test_self_test_proves_every_detector_fires():
    p = _run("--self-test", "--root", str(REPO))
    assert p.returncode == 0, p.stdout + p.stderr
    for detector in ("DANGLING", "PLACEHOLDER", "MISSING_SOURCE", "DRIFT", "ZERO_MANIFESTS"):
        assert f"{detector}: fired" in p.stdout, (detector, p.stdout)


def test_zero_manifests_is_a_failure_not_a_clean_report(tmp_path):
    (tmp_path / "skills").mkdir()
    (tmp_path / "hooks" / "manifests").mkdir(parents=True)
    (tmp_path / "rules" / "manifests").mkdir(parents=True)
    (tmp_path / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    p = _run("--check", "--no-reindex", "--root", str(tmp_path))
    assert p.returncode != 0, p.stdout
    assert "ZERO_MANIFESTS" in p.stdout
