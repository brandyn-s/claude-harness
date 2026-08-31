#!/usr/bin/env python3
"""Negative fixtures for the skill-rubric CI gate (audit finding M4).

THE DEFECT

validate.yml wrapped the rubric checker in:

    if <checker>; then echo "All skills >= A-tier"; fi

with NO `else`. In Bash, a false `if` condition with no `else` leaves the compound
command SUCCESSFUL, so a genuinely below-threshold skill printed `::error::` and the
required check still went GREEN. Reproduced 2026-07-26: `search-campaign` scored
12/14 while this gate passed.

A required gate that cannot fail is worse than no gate: it launders the absence of
checking into the appearance of coverage.

THE FIX under test: the exit contract moved into the tool (`--gate N` exits 1), and
the workflow calls it directly with no shell conditional.

These tests assert BOTH halves:
  1. the tool exits nonzero when a skill is below the gate (and zero when not);
  2. the workflow no longer contains the fail-open `if` shape.

Run: pytest scripts/test_validate_skills_gate.py -q
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "scripts" / "validate-skills.py"
WORKFLOW = REPO / ".github" / "workflows" / "validate.yml"


def run(*args, cwd=REPO):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=300,
    )


# ---------------------------------------------------------------------------
# the shell mechanism that caused the defect
# ---------------------------------------------------------------------------
def test_the_workflow_step_does_not_rely_on_shell_conditional_semantics():
    """Pins WHY the old shape was fail-open, so nobody reintroduces it.

    The mechanism: in POSIX shell, an `if` whose condition FAILS and which has no
    `else` branch leaves the compound command SUCCESSFUL — `set -e` does not help,
    because a condition is explicitly allowed to fail. So the step exited 0 while
    printing `::error::`.

    Deliberately asserted WITHOUT shelling out to a shell. An earlier version of
    this test spawned one as a subprocess, and the repo's own auditor flagged it
    (C10): on Windows a bare shell name resolves to the WSL launcher, which cannot
    read `C:/...` paths. The mechanism is a property of shell semantics, not of this
    repo, so the durable guard is structural — assert the workflow expresses its
    gate through the TOOL's exit code and never through an `if` wrapper. That is
    what `test_workflow_has_no_if_wrapper_around_the_rubric_checker` enforces, and
    it is portable and instant.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text[text.index("Skill rubric validator"):]
    step = step[: step.index("- name:", 10) if "- name:" in step[10:] else len(step)]
    assert "--gate" in step, "the rubric step must use the tool's own exit contract"
    assert not re.search(r"^\s*if\b", step, re.MULTILINE), (
        "no shell conditional may wrap the rubric gate — a false `if` with no "
        "`else` exits 0 and the required check goes green"
    )


# ---------------------------------------------------------------------------
# the tool's exit contract
# ---------------------------------------------------------------------------
def test_gate_fails_when_a_skill_is_below_threshold():
    """THE M4 FIX. A below-gate skill must make the process exit nonzero.

    Uses an impossibly high gate so the test does not depend on any particular
    skill being weak -- it asserts the CONTRACT, not the current corpus.
    """
    p = run("--gate", "99")
    assert p.returncode == 1, "a below-threshold skill must fail the gate"
    assert "::error::" in p.stdout
    assert "GATE FAILED" in p.stderr


def test_gate_passes_when_all_skills_meet_threshold():
    """Not vacuously pessimistic: a satisfiable gate must exit 0."""
    p = run("--gate", "1")
    assert p.returncode == 0, p.stderr
    assert "GATE PASSED" in p.stdout


def test_repo_currently_satisfies_the_shipped_gate():
    """The gate the workflow actually runs must be green on this tree.

    Without this, someone could ship a red gate and discover it in CI.
    """
    p = run("--gate", "13")
    assert p.returncode == 0, f"the shipped gate is RED:\n{p.stdout}\n{p.stderr}"


@pytest.mark.parametrize("extra", [["--json"], ["--skill", "search-campaign"], []])
def test_gate_is_honoured_in_every_output_mode(extra):
    """Every display branch must return the gate code.

    main() has several early `return`s; one of them dropping gate_rc is exactly how
    a gate silently stops gating. Caught in verification: the default tabular path
    printed "GATE FAILED" and still exited 0.
    """
    p = run("--gate", "99", *extra)
    assert p.returncode == 1, f"gate lost in mode {extra}"


def test_no_gate_flag_is_backward_compatible():
    """Existing callers that just want the report must keep exiting 0."""
    for args in ([], ["--json"], ["--triggers"], ["--below", "13"]):
        p = run(*args)
        assert p.returncode == 0, f"{args} regressed to nonzero"


# ---------------------------------------------------------------------------
# the workflow must not reintroduce the fail-open shape
# ---------------------------------------------------------------------------
def test_workflow_calls_the_gate_directly():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "validate-skills.py --gate 13" in text, (
        "the workflow must invoke the tool's own exit contract"
    )


def test_workflow_has_no_if_wrapper_around_the_rubric_checker():
    """Regression guard: an `if ... validate-skills ...; then` shape is fail-open."""
    text = WORKFLOW.read_text(encoding="utf-8")
    offenders = [
        ln.strip()
        for ln in text.splitlines()
        if re.search(r"^\s*if\b.*validate-skills", ln)
    ]
    assert offenders == [], f"fail-open `if` wrapper reintroduced: {offenders}"
