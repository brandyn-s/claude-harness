#!/usr/bin/env python3
"""Run the test suite the way it is designed to be run: once per test directory.

A single root-level `pytest` DOES NOT WORK on this repository, and that is by
design rather than by defect:

  * Test modules import their siblings and their local `conftest.py` directly
    (`from conftest import PYTHON`). That relies on pytest's default prepend
    import mode inserting each test file's own directory on `sys.path`.
  * Two test files legitimately share a basename
    (`test_transcript_condense.py` under both `hooks/test-hooks/` and
    `skills/mega-distill/tests/`). Prepend mode keys modules on basename, so
    collecting both in ONE run aborts collection for the entire suite.
  * `--import-mode=importlib` fixes the basename clash and breaks every
    conftest import instead -- measured: 3 collection errors became 47.

Running one directory at a time satisfies both constraints, which is what the
original CI did across ~20 separate steps. This discovers the directories instead
of hard-coding them, so a new test directory is picked up automatically.

Exit status is non-zero if any directory fails, if any directory errors during
collection, or if the whole run collected zero tests (a suite that silently
collects nothing must not report success).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Known-failing baseline, printed on every run and gated in BOTH directions.
#
# Why a baseline rather than deleting the tests: this repository is a curated
# subset, and these tests assert on inventories the subset legitimately changed
# (which hooks are registered, which skills exist, which rules are in the context
# budget). Deleting them would green the suite by reducing coverage, which is
# worse than the gap it hides and leaves no signal that coverage moved. Tests
# whose SUBJECT was removed outright were dropped from the export instead; these
# are the ones whose subject still exists with different content.
#
# The gate is two-sided ON PURPOSE. Over the baseline is a regression. UNDER it
# means someone fixed something and the entry is now stale -- which must also
# fail, or the baseline silently becomes a place failures go to be forgotten.
#
# Measured 2026-08-31 against a source baseline of 4,426 passed / 2 failed.
KNOWN_FAILING = {
    "hooks/test-hooks": 14,          # hook-registration assertions vs the curated settings.json
    "manifests": 1,                  # manifest graph references an excluded skill
    "scripts": 31,                   # repo-inventory and policy meta-tests
    "skills/audit-rules/tests": 3,   # rule-corpus assertions vs the curated rules/
    "skills/audit-skill/tests": 2,   # skill-inventory assertions
}
SKIP_DIRS = {".git", "__pycache__", ".ruff_cache", ".mypy_cache", "marketplace",
             ".pytest_cache", "node_modules"}

SUMMARY = re.compile(
    r"(?:(\d+) failed)?[,\s]*(?:(\d+) passed)?[,\s]*(?:(\d+) skipped)?"
    r"[,\s]*(?:(\d+) error)?")


def test_dirs() -> list[str]:
    """Every directory directly containing at least one test_*.py."""
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if any(f.startswith("test_") and f.endswith(".py") for f in filenames):
            found.append(os.path.relpath(dirpath, ROOT))
    return sorted(found)


def parse_counts(text: str) -> dict:
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for line in reversed(text.strip().splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            for key in counts:
                m = re.search(rf"(\d+) {key}", line)
                if m:
                    counts[key] = int(m.group(1))
            if any(counts.values()):
                break
    return counts


def check_baseline(observed: dict, known: dict) -> list[tuple[str, int, int]]:
    """Return the drift: [(directory, expected, observed)] for every mismatch.

    Pure, so it can be exercised without running the suite -- see --selftest. A
    gate that has never been shown to fire is a hypothesis, and this one is
    otherwise only reachable via a ~10-minute full sweep.
    """
    drift = []
    for d, expected in sorted(known.items()):
        actual = observed.get(d, 0)
        if actual != expected:
            drift.append((d, expected, actual))
    for d, actual in sorted(observed.items()):
        if d not in known and actual:
            drift.append((d, 0, actual))
    return drift


def selftest() -> int:
    """Prove the baseline gate fires on regression, staleness, and new failures."""
    known = {"a": 2, "b": 0}
    cases = [
        ("holds",       {"a": 2, "b": 0}, 0),
        ("regressed",   {"a": 3, "b": 0}, 1),
        ("stale",       {"a": 1, "b": 0}, 1),
        ("new dir",     {"a": 2, "b": 0, "c": 4}, 1),
        ("dir vanished", {"b": 0}, 1),
    ]
    bad = 0
    for name, observed, want in cases:
        got = len(check_baseline(observed, known))
        ok = (got > 0) == (want > 0)
        print(f"  {'ok  ' if ok else 'FAIL'} {name:14s} drift={got} expected"
              f"{' >0' if want else ' 0'}")
        if not ok:
            bad += 1
    if bad:
        print(f"\nFAIL: {bad} self-test case(s) wrong - the gate is not trustworthy")
        return 1
    print("\nBaseline gate self-test passed: fires on regression, staleness, "
          "new failures and a vanished directory.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-k", "--filter", help="only run directories matching this substring")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show pytest output for passing directories too")
    # A directory that hangs would otherwise block the whole run forever, with no
    # signal distinguishing "slow" from "wedged". Bound it and report the timeout
    # as a FAILURE, because an unfinished directory has measured nothing.
    ap.add_argument("--timeout", type=int, default=600, metavar="SECONDS",
                    help="per-directory limit (default 600); a timeout is a failure")
    ap.add_argument("--selftest", action="store_true",
                    help="exercise the baseline gate without running the suite")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    dirs = test_dirs()
    if args.filter:
        dirs = [d for d in dirs if args.filter in d]
    if not dirs:
        print("FAIL: discovered no test directories", file=sys.stderr)
        return 1

    print(f"Running {len(dirs)} test director{'y' if len(dirs) == 1 else 'ies'} "
          f"from {ROOT}\n")

    totals = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    observed: dict[str, int] = {}
    bad: list[tuple[str, int, str]] = []

    for rel in dirs:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", rel, "-q", "-p", "no:cacheprovider"],
                cwd=ROOT, capture_output=True, text=True, check=False,
                timeout=args.timeout,
            )
            out = proc.stdout + proc.stderr
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            out = ((exc.stdout or "") + (exc.stderr or "")
                   if isinstance(exc.stdout, str) else "")
            out += f"\n\nTIMEOUT after {args.timeout}s"
            returncode = 124
        counts = parse_counts(out)
        for key in totals:
            totals[key] += counts[key]
        observed[rel] = counts["failed"] + counts["error"]

        # pytest exits 5 when a directory collected nothing. That is not a failure
        # of the code under test, but it IS worth surfacing: a directory of tests
        # that collects zero is usually a broken import, not an empty directory.
        if returncode == 5:
            status = "EMPTY"
        elif returncode == 124:
            status = "TIME"
            bad.append((rel, returncode, out))
        elif returncode == 0:
            status = "ok"
        else:
            status = "FAIL"
            bad.append((rel, returncode, out))

        line = (f"  {status:5s} {rel:58s} "
                f"{counts['passed']:4d}p {counts['failed']:2d}f "
                f"{counts['skipped']:2d}s {counts['error']:2d}e")
        print(line)
        if args.verbose and status == "ok":
            print("        " + out.strip().replace("\n", "\n        "))

    print(f"\nTOTAL: {totals['passed']} passed, {totals['failed']} failed, "
          f"{totals['skipped']} skipped, {totals['error']} errors "
          f"across {len(dirs)} directories")

    # Two-sided baseline gate. Only meaningful on a full run.
    if not args.filter:
        print(f"\nKnown-failing baseline ({sum(KNOWN_FAILING.values())} failures "
              f"across {len(KNOWN_FAILING)} directories):")
        for d, expected in sorted(KNOWN_FAILING.items()):
            actual = observed.get(d, 0)
            mark = "ok" if actual == expected else ("REGRESSED" if actual > expected
                                                    else "STALE")
            print(f"  {mark:9s} {d:44s} expected {expected:3d}, observed {actual:3d}")
        for d, actual in sorted(observed.items()):
            if d not in KNOWN_FAILING and actual:
                print(f"  {'NEW':9s} {d:44s} expected   0, observed {actual:3d}")
        drift = check_baseline(observed, KNOWN_FAILING)
        if drift:
            print("\nFAIL: the known-failing set moved. Over the baseline is a "
                  "regression; under it means the entry is stale and should be "
                  "removed from KNOWN_FAILING.")
            for d, exp, act in drift:
                print(f"    {d}: {exp} -> {act}")
            return 1
        print("\nBaseline holds: no regressions, no stale entries.")
        return 0

    if bad:
        print(f"\n{len(bad)} director{'y' if len(bad) == 1 else 'ies'} failed:\n")
        for rel, rc, out in bad:
            print(f"--- {rel} (exit {rc}) " + "-" * max(0, 60 - len(rel)))
            tail = out.strip().splitlines()[-25:]
            print("    " + "\n    ".join(tail) + "\n")
        return 1

    # Vacuity floor. A suite that collects nothing must never report success:
    # every "green" here would be a green that measured no code at all.
    if totals["passed"] == 0:
        print("\nFAIL: zero tests passed anywhere - the suite collected nothing",
              file=sys.stderr)
        return 1

    print("\nAll test directories passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
