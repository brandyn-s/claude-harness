"""Property-style verdict-mapping tests — drive the return code
deterministically and assert the verdict matches the SPEC.md exit-code
tables exactly at the 126/127/>=128 boundaries. Parametrized matrix (no
hypothesis dependency); extends the example-based contract tests in
test_oracle_calibration.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for m in ("oracle", "oracle.finding", "oracle.reverify", "oracle.trace"):
        sys.modules.pop(m, None)
    from oracle.finding import Finding, Reproducer  # noqa: E402
    from oracle.reverify import reverify  # noqa: E402
    return Finding, Reproducer, reverify


# SPEC.md "Exit-code contract for bash": rc==expected_exit -> STILL-FIRES;
# rc in {126,127} OR >=128 OR <0 (and != expected) -> ERROR; else STALE.
BASH_CASES = [
    (0, 0, "STILL-FIRES"),    # equality
    (1, 0, "STALE"),
    (2, 0, "STALE"),          # 2 is NOT in the instrument set for bash
    (126, 0, "ERROR"),        # not executable
    (127, 0, "ERROR"),        # command not found
    (128, 0, "ERROR"),        # signal boundary
    (137, 0, "ERROR"),        # 128+SIGKILL
    (139, 0, "ERROR"),        # 128+SIGSEGV
    (143, 0, "ERROR"),        # 128+SIGTERM
    (127, 127, "STILL-FIRES"),  # equality-wins control: author tests command-absence
]


@pytest.mark.parametrize("rc,exp,want", BASH_CASES)
def test_bash_rc_to_verdict(rc, exp, want, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "t.jsonl"))
    Finding, Reproducer, reverify = _load()
    f = Finding(skill="p", code="X", severity="info", label="doc-fix",
                description=f"bash exit {rc} (expected {exp})",
                reproducer=Reproducer(type="bash", command=f"exit {rc}", expected_exit=exp))
    [r] = reverify([f], tmp_path)
    assert r.status == want, f"rc={rc} exp={exp}: got {r.status} ({r.evidence})"


# SPEC.md "Exit-code contract for python": rc==0 -> STALE; instrument-pattern
# in stderr -> ERROR; other nonzero (intentional raise / sys.exit(n)) -> STILL-FIRES.
PYTHON_CASES = [
    ("import sys; sys.exit(0)", "STALE"),
    ("import sys; sys.exit(1)", "STILL-FIRES"),
    ("import sys; sys.exit(2)", "STILL-FIRES"),
    ("raise RuntimeError('bug')", "STILL-FIRES"),
    ("assert False", "STILL-FIRES"),
    ("pass", "STALE"),
    ("import nonexistent_module_xyzzy", "ERROR"),   # ModuleNotFoundError
    ("undefined_name_xyzzy", "ERROR"),              # NameError
]


@pytest.mark.parametrize("snippet,want", PYTHON_CASES)
def test_python_snippet_to_verdict(snippet, want, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "t.jsonl"))
    Finding, Reproducer, reverify = _load()
    f = Finding(skill="p", code="X", severity="info", label="doc-fix",
                description=f"python: {snippet}",
                reproducer=Reproducer(type="python", command=snippet))
    [r] = reverify([f], tmp_path)
    assert r.status == want, f"snippet={snippet!r}: got {r.status} ({r.evidence})"
