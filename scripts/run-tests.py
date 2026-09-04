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

Run it outside the Claude Code Bash sandbox: some hook tests write probe files
under `hooks/`, open local sockets and call `ps`, which the sandbox denies, so a
run inside it reports environment-caused failures.

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
    args = ap.parse_args()

    dirs = test_dirs()
    if args.filter:
        dirs = [d for d in dirs if args.filter in d]
    if not dirs:
        print("FAIL: discovered no test directories", file=sys.stderr)
        return 1

    print(f"Running {len(dirs)} test director{'y' if len(dirs) == 1 else 'ies'} "
          f"from {ROOT}\n")

    totals = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    bad: list[tuple[str, int, str]] = []

    for rel in dirs:
        try:
            proc = subprocess.run(
                # -rf makes pytest emit a "FAILED <nodeid>" short-summary line
                # per failure. Without it this runner reported only COUNTS, so a
                # baseline movement said "14 -> 18" and nothing about WHICH four
                # tests moved -- the CI log could not answer the only question a
                # regression raises. Measured 2026-08-31: diagnosing a 4-test
                # regression required re-running the suite locally because the CI
                # output had no node IDs in it.
                [sys.executable, "-m", "pytest", rel, "-q", "-rf",
                 "-p", "no:cacheprovider"],
                cwd=ROOT, capture_output=True, text=True, check=False,
                timeout=args.timeout,
            )
            out = proc.stdout + proc.stderr
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            # TimeoutExpired's streams are typed `bytes | str | None` regardless of
            # text=True, and only stdout was guarded here. If either arrives as
            # bytes the concatenation raises TypeError INSIDE the handler, so a
            # timeout would surface as a crash instead of as a timeout -- a second
            # failure masking the first, in the one path that exists to report it.
            def _text(stream: object) -> str:
                if isinstance(stream, bytes):
                    return stream.decode("utf-8", "replace")
                return stream if isinstance(stream, str) else ""

            out = _text(exc.stdout) + _text(exc.stderr)
            out += f"\n\nTIMEOUT after {args.timeout}s"
            returncode = 124
        counts = parse_counts(out)
        for key in totals:
            totals[key] += counts[key]
        # pytest exits 5 when a directory collected nothing. That is not a failure
        # of the code under test, but it IS worth surfacing: a directory of tests
        # that collects zero is usually a broken import, not an empty directory.
        if returncode == 5:
            # Every directory here was selected BECAUSE it holds test_*.py files, so
            # zero collected means discovery is broken (bad import, renamed prefix):
            # a failure, not a quiet EMPTY row (zero-discovery guard, 2026-09-03).
            status = "EMPTY"
            bad.append((rel, returncode, out + "\n\nZERO-DISCOVERY: this directory collected no tests"))
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
