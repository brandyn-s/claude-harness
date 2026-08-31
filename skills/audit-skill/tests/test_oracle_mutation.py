"""Mutation testing of finding.py's exit-code contract.

Each mutation flips one branch of Reproducer.fires()'s instrument-vs-
predicate routing, re-execs the module standalone, and checks the verdict
on a probe input. A mutation that does NOT change behavior is a SURVIVOR
— proof the calibration corpus has a blind spot at that branch. Every
mutation here must be KILLED (behavior must differ from the original).

Bespoke mutator (no cosmic-ray/mutmut dependency) targeting the five
contract branches confirmed at finding.py:250/286/291/303/338.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FINDING_SRC = (REPO / "skills" / "_shared" / "oracle" / "finding.py").read_text(encoding="utf-8")

_exec_counter = 0


def _exec_module(src: str) -> dict:
    """Exec finding.py source as a standalone module and return its dict.

    finding.py imports only stdlib and has no relative imports, so it execs
    standalone — BUT @dataclasses.dataclass resolves field types via
    sys.modules[cls.__module__], so the module must be registered there
    under a unique name (not a bare dict namespace)."""
    global _exec_counter
    _exec_counter += 1
    name = f"finding_mut_{_exec_counter}"
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    exec(compile(src, f"{name}.py", "exec"), mod.__dict__)
    return mod.__dict__


def _behavior(ns: dict, kwargs: dict, repo_root: Path):
    """Canonical behavior tag for Reproducer.fires() on a probe:
    ('ERROR', None) when it raises (instrument failure), else ('fires', bool)."""
    rep = ns["Reproducer"](**kwargs)
    try:
        fires, _ev = rep.fires(repo_root)
        return ("fires", fires)
    except RuntimeError:
        return ("ERROR", None)


def test_exit_code_contract_mutants_are_killed(tmp_path):
    (tmp_path / "has_foo.txt").write_text("contains foo here\n", encoding="utf-8")
    nope = (tmp_path / "nope.txt").as_posix()
    has_foo = (tmp_path / "has_foo.txt").as_posix()

    # (label, old_substr, new_substr, probe reproducer kwargs)
    cases = [
        ("grep rc>=2 -> rc>2 (file-not-found stops routing to ERROR)",
         "r.returncode >= 2", "r.returncode > 2",
         {"type": "grep", "command": f"grep -q foo {nope}"}),
        ("bash instrument set drops 127 (command-not-found stops being ERROR)",
         "r.returncode in (126, 127)", "r.returncode in (126,)",
         {"type": "bash", "command": "this-command-does-not-exist-xyzzy", "expected_exit": 0}),
        ("python drops NameError from instrument patterns",
         '"NameError"', '"NoSuchInstrumentPatternXYZ"',
         {"type": "python", "command": "some_undefined_variable_xyzzy"}),
        ("grep fires polarity 0 -> 1",
         "fires = (r.returncode == 0)", "fires = (r.returncode == 1)",
         {"type": "grep", "command": f"grep -q foo {has_foo}"}),
    ]

    orig = _exec_module(FINDING_SRC)
    survivors = []
    for label, old, new, kwargs in cases:
        assert old in FINDING_SRC, f"mutation anchor not found: {old!r}"
        mutated = FINDING_SRC.replace(old, new)
        assert mutated != FINDING_SRC, label
        base = _behavior(orig, kwargs, tmp_path)
        after = _behavior(_exec_module(mutated), kwargs, tmp_path)
        if base == after:
            survivors.append(f"{label}: behavior unchanged ({base})")
    assert not survivors, (
        "surviving mutants (calibration/contract gap):\n  " + "\n  ".join(survivors)
    )
