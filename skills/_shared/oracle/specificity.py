"""Specificity guard — break proposer↔reproducer authorship coupling.

The oracle's decorrelation holds at *execution* (mechanical bash/grep/python
vs the LLM proposer) but NOT at *authorship*: the same agent often writes
both the finding and its reproducer. A vacuous predicate (``grep -q .``)
fires regardless of repository content, so a STILL-FIRES verdict certifies
nothing — the proposer graded its own homework. This module catches that
reward-hacking class with two complementary, deterministic mechanisms:

  STATIC  — ``finding.static_vacuity`` regex-matches always-true predicates
            (``grep -q .``, ``grep -qE '.*'``, ``test -e .``, bare ``true``).
            Zero I/O.

  CONTROL — run the reproducer against a known-clean control where the bug is
            ABSENT. If it still fires, the predicate is non-specific. Two
            controls, strongest first:
              1. ``true_fixture`` → ``false_fixture`` swap (content-aware;
                 the false_fixture is "bug-shaped but correct" by
                 construction) when the command targets a calibration
                 fixture.
              2. a synthetic benign control tree — create benign placeholder
                 files at the command's path tokens and run there. A
                 *specific* predicate (grep for a real bug token) won't match
                 benign content; a vacuous one will.

The verdict feeds ``validate.REJECT_NONSPECIFIC_REPRODUCER`` (pre-dispatch)
and the ``specificity-check`` CLI subcommand.

Fail-safe by design: when the control is inconclusive (no parseable paths,
the reproducer errors on the control, an unsupported type) the verdict is
SPECIFIC — the guard never rejects a legitimate reproducer on ambiguity. It
only rejects on a positive vacuity signal.
"""
from __future__ import annotations

import re
import shlex
import tempfile
from pathlib import Path

from .finding import Reproducer, static_vacuity


BENIGN_CONTROL_CONTENT = (
    "# oracle specificity control file\n"
    "Benign placeholder content with no bug signal of any kind.\n"
    "lorem ipsum dolor sit amet 1234567890\n"
)

# A token is "path-ish" if it contains a path separator or has a file
# extension. Used to locate the files a reproducer reads so the control
# run can stand them up with benign content.
_PATHISH = re.compile(r"[\w./\-]+\.[A-Za-z0-9_]+")


def _extract_paths(command: str) -> list[str]:
    """Best-effort extraction of file-path tokens from a shell command.
    Skips flags. Falls back to whitespace split if the command isn't
    cleanly shlex-parseable (e.g. multi-line with redirects)."""
    try:
        toks = shlex.split(command)
    except ValueError:
        toks = command.split()
    paths: list[str] = []
    for t in toks:
        t = t.strip("'\"")
        if t.startswith("-") or not t:
            continue
        if "/" in t or _PATHISH.fullmatch(t):
            paths.append(t)
    return paths


def control_run(reproducer: Reproducer, repo_root: Path) -> tuple[bool, str]:
    """Return (is_nonspecific, evidence). Empirical specificity check.

    Scoped to grep/bash — grep_absent's inverse semantics need a
    bug-present control (out of scope for v1; static_vacuity still
    guards literal-vacuous grep_absent). Never raises; on any
    inconclusive condition returns (False, ...) so the guard does not
    false-reject."""
    if reproducer.type not in ("grep", "bash"):
        return False, f"control-run N/A for type={reproducer.type}"
    cmd = reproducer.command or ""
    if not cmd.strip():
        return False, "empty command; control-run inconclusive"

    # Mechanism 1 (strongest): true_fixture → false_fixture content-aware
    # swap. The false_fixture is "bug-shaped but correct"; a specific
    # reproducer returns no-fire there, a vacuous one fires.
    if "true_fixture" in cmd:
        swapped = cmd.replace("true_fixture", "false_fixture")
        ctrl = Reproducer(type=reproducer.type, command=swapped,
                          expected_exit=reproducer.expected_exit)
        try:
            fires, ev = ctrl.fires(repo_root)
        except Exception as e:  # instrument error on control → inconclusive
            return False, f"false_fixture control inconclusive ({type(e).__name__})"
        if fires:
            return True, f"fires against false_fixture (bug-absent control) → non-specific: {ev}"
        return False, f"specific (no fire against false_fixture): {ev}"

    # Mechanism 2: synthetic benign control tree. Stand up benign files at
    # the command's path tokens, then run with cwd=control-dir. Relative
    # tokens resolve via cwd (no command rewrite — cross-platform, avoids
    # the Windows backslash-in-bash trap); absolute tokens are rewritten to
    # a forward-slash (`as_posix`) path under the control dir so Git Bash
    # on Windows resolves them.
    paths = _extract_paths(cmd)
    if not paths:
        return False, "no file paths in command; control-run inconclusive"
    with tempfile.TemporaryDirectory(prefix="oracle-specificity-") as td:
        tdp = Path(td)
        rewritten = cmd
        for p in paths:
            pp = Path(p)
            target = (tdp / pp.name) if pp.is_absolute() else (tdp / pp)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(BENIGN_CONTROL_CONTENT, encoding="utf-8")
            except OSError:
                continue
            if pp.is_absolute():
                rewritten = rewritten.replace(p, target.as_posix())
        ctrl = Reproducer(type=reproducer.type, command=rewritten,
                          expected_exit=reproducer.expected_exit)
        try:
            fires, ev = ctrl.fires(tdp)
        except Exception as e:  # instrument error on benign control → inconclusive
            return False, f"benign control inconclusive (reproducer raised {type(e).__name__})"
    if fires:
        return True, f"fires against benign control content → non-specific: {ev}"
    return False, f"specific (no fire against benign control): {ev}"


def specificity_verdict(reproducer: Reproducer, repo_root: Path | None = None) -> tuple[str, str]:
    """Classify a reproducer's specificity.

    Returns (verdict, evidence) where verdict is one of:
      SPECIFIC             — depends on real repository content.
      NONSPECIFIC_STATIC   — matches a known vacuous pattern (no I/O).
      NONSPECIFIC_CONTROL  — fires against a bug-absent control tree.

    ``repo_root`` is required for the control-run; when None, only the
    static layer runs (still catches the literal `grep -q .` class)."""
    static = static_vacuity(reproducer)
    if static:
        return "NONSPECIFIC_STATIC", static
    if repo_root is None:
        return "SPECIFIC", "static-only (no repo_root for control-run)"
    nonspecific, ev = control_run(reproducer, repo_root)
    if nonspecific:
        return "NONSPECIFIC_CONTROL", ev
    return "SPECIFIC", ev


def is_nonspecific(verdict: str) -> bool:
    """True if the verdict indicates a non-specific (gameable) predicate."""
    return verdict.startswith("NONSPECIFIC")
