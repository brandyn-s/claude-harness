"""The grounding-based A/B harnesses must refuse to start without httpx.

Why: anthropic>=1.3 no longer depends on httpx, yet gather-intel and
gather-research import it lazily inside the grounding step, AFTER the paid model
call. On 2026-09-03 that turned every SUPPORTED verdict into CALL_ERROR while
the refuted/fabricated verdicts parsed fine, so the all-failed guard never fired
and the run exited 0 with a hollow "inconclusive". Fail before spending money.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GROUNDING_HARNESSES = ("gather-intel", "gather-research")


@pytest.mark.parametrize("skill", GROUNDING_HARNESSES)
def test_missing_httpx_fails_before_any_model_call(skill, tmp_path):
    script = REPO / "skills" / skill / "harness" / "run_live.py"
    out = tmp_path / "out.json"
    bootstrap = textwrap.dedent(f"""
        import runpy, sys, types
        sys.modules["httpx"] = None                          # `import httpx` -> ImportError
        sys.modules["anthropic"] = types.ModuleType("anthropic")  # SDK present, never usable
        ns = runpy.run_path({str(script)!r}, run_name="harness_under_test")
        sys.exit(ns["main"](["--model", "claude-fable-5-1", "--runs", "1", "--output", {str(out)!r},
                             "--acknowledge-retired-fixture"]))  # the fixture is retired (2026-09-04); the dependency check is downstream of that gate
    """)
    env = {**os.environ, "ANTHROPIC_API_KEY": "dummy-not-a-key"}
    proc = subprocess.run([sys.executable, "-c", bootstrap], capture_output=True, text=True,
                          timeout=120, cwd=str(script.parent), env=env)
    assert proc.returncode == 2, proc.stderr[-800:]
    assert "httpx" in proc.stderr, proc.stderr[-800:]
    assert not out.exists(), "a dependency failure must not write results"
