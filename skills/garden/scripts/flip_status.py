#!/usr/bin/env python3
"""garden/flip_status.py — mechanical STATUS-marker mutation for /garden.

The /garden skill's "Open-Status Markers" check has two deterministic
mutations (SKILL.md "Open-Status Markers → auto-flip resolved, auto-date
undated, count the rest"; KB CLAUDE.md "Status markers for state-claims"):

  * auto-flip — an OPEN state-claim whose resolution evidence already sits
    on the SAME page gets flipped in place:
        > **STATUS:** OPEN (since 2026-06-06) — Athena messages empty; ...
      becomes
        > **STATUS:** RESOLVED 2026-06-07 — Athena messages empty; ... [details: entry below / PR #382]
  * auto-date — an OPEN marker missing a `(since YYYY-MM-DD)` gets one
    (covers both the bare form and the `(since ?)` placeholder):
        > **STATUS:** OPEN — bulk scans unavailable
      becomes
        > **STATUS:** OPEN (since 2026-04-02) — bulk scans unavailable

Judgment (WHICH marker is resolved, what evidence resolves it, what
since-date an undated marker should carry) stays with the /garden LLM,
fed by analyze.py's `open_markers` / `undated_open_markers` lists. This
script performs ONLY the mechanical rewrite, so the highest-blast-radius
garden mutation is a tested code path instead of a hand edit.

Usage:
    flip_status.py FILE
        Report-only: list every OPEN marker (line number, dated/undated).
        Never writes.
    flip_status.py FILE --resolved YYYY-MM-DD --details "pointer" \
        [--summary "text"] [--match SUBSTR] [--garden-date YYYY-MM-DD]
        Flip ONE OPEN marker to RESOLVED. The original description is
        carried over (or replaced by --summary); the pointer lands in
        `[details: ...]`.
    flip_status.py FILE --auto-date YYYY-MM-DD \
        [--match SUBSTR] [--garden-date YYYY-MM-DD]
        Give ONE undated OPEN marker a `(since YYYY-MM-DD)`.

Guarantees:
  * In-place and line-scoped: every byte outside the rewritten marker line
    is preserved (files are read/written with newline='' so CRLF/LF
    endings survive untouched).
  * Idempotent: a second identical invocation finds nothing eligible and
    exits 0 without writing.
  * Never bulk-mutates ambiguously: if more than one marker is eligible,
    exits 2 and demands --match. One invocation mutates at most one line.
  * --garden-date appends the SKILL.md session-attribution comment
    (`<!-- garden: DATE action:... -->`) to the rewritten line.
  * Stdlib only.

Exit codes: 0 = success (changed, or legitimately nothing to do);
1 = file error; 2 = ambiguous target / usage error.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

# Marker regexes — keep byte-aligned with scripts/analyze.py (detection)
# so what the analyzer reports as a marker is exactly what this mutator
# will match, and vice versa.
OPEN_MARKER_RE = re.compile(r"^> \*\*STATUS:\*\* OPEN\b(.*)$")
# No closing-paren anchor: annotated forms like "(since 2026-06-09;
# narrowed 2026-06-09)" count as dated markers, not as undated.
SINCE_RE = re.compile(r"\(since (\d{4}-\d{2}-\d{2})")

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_date(value):
    """argparse type: strict, calendar-valid YYYY-MM-DD."""
    if not ISO_DATE_RE.match(value):
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {value!r}")
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"not a calendar-valid date: {value!r}")
    return value


def split_tail(tail):
    """Split an OPEN marker's tail (everything after the literal 'OPEN')
    into (since_group_or_None, description).

    The since group is the raw inside of a LEADING parenthesised group —
    'since 2026-06-06', 'since ?', or an annotated form. The description
    is what remains after dropping that group and any leading dash
    (em/en/hyphen) separator.
    """
    rest = tail.strip()
    since_group = None
    if rest.startswith("("):
        close = rest.find(")")
        if close != -1:
            since_group = rest[1:close].strip()
            rest = rest[close + 1:].strip()
    desc = re.sub(r"^[—–-]+\s*", "", rest).strip()
    return since_group, desc


def find_open_markers(lines):
    """Return [(index, bare_line, tail)] for every OPEN marker line.
    `bare_line` is the line without its trailing newline bytes."""
    found = []
    for i, raw in enumerate(lines):
        bare = raw.rstrip("\r\n")
        m = OPEN_MARKER_RE.match(bare)
        if m:
            found.append((i, bare, m.group(1)))
    return found


def build_parser():
    ap = argparse.ArgumentParser(
        prog="flip_status.py",
        description=(
            "Mechanically flip a '> **STATUS:** OPEN' marker to RESOLVED, "
            "or date an undated OPEN marker, in place. With neither "
            "--resolved nor --auto-date, reports markers and writes nothing."
        ),
    )
    ap.add_argument("file", help="topic file to inspect or mutate")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--resolved", type=iso_date, metavar="YYYY-MM-DD",
        help="flip the marker to RESOLVED on this date (requires --details)")
    mode.add_argument(
        "--auto-date", dest="auto_date", type=iso_date, metavar="YYYY-MM-DD",
        help="give an undated OPEN marker this (since ...) date")
    ap.add_argument(
        "--details", metavar="POINTER",
        help="resolution pointer for '[details: ...]' "
             "(e.g. 'entry below / PR #382'); required with --resolved")
    ap.add_argument(
        "--summary", metavar="TEXT",
        help="replace the carried-over description on the RESOLVED line "
             "(default: keep the original OPEN description)")
    ap.add_argument(
        "--match", metavar="SUBSTR",
        help="substring selecting THE target marker line; required when "
             "more than one marker is eligible")
    ap.add_argument(
        "--garden-date", dest="garden_date", type=iso_date,
        metavar="YYYY-MM-DD",
        help="append the garden attribution comment dated this run")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)

    if args.resolved and not args.details:
        ap.error("--resolved requires --details (the resolution pointer)")
    if args.details and not args.resolved:
        ap.error("--details only applies with --resolved")
    if args.summary and not args.resolved:
        ap.error("--summary only applies with --resolved")

    path = Path(args.file)
    if not path.is_file():
        sys.stderr.write(f"ERROR: not a file: {path}\n")
        return 1
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            original = fh.read()
    except UnicodeDecodeError:
        sys.stderr.write(
            f"ERROR: not UTF-8 text: {path} "
            "(re-encode the file as UTF-8 and retry)\n")
        return 1
    except OSError as exc:
        sys.stderr.write(f"ERROR: cannot read {path}: {exc}\n")
        return 1
    lines = original.splitlines(keepends=True)
    markers = find_open_markers(lines)

    # Report-only mode: list markers, never write.
    if args.resolved is None and args.auto_date is None:
        if not markers:
            print(f"{path.name}: no OPEN STATUS markers")
            return 0
        for i, bare, tail in markers:
            since = SINCE_RE.search(tail)
            tag = f"since {since.group(1)}" if since else "UNDATED"
            print(f"{path.name}:{i + 1}: [{tag}] {bare}")
        return 0

    if args.auto_date:
        # Only undated markers are eligible — already-dated markers are
        # skipped, which is what makes a second identical run a no-op.
        eligible = [(i, bare, tail) for i, bare, tail in markers
                    if not SINCE_RE.search(tail)]
        action = "open-marker-date"
    else:
        eligible = markers
        action = "open-marker-flip"

    if args.match:
        eligible = [t for t in eligible if args.match in t[1]]

    if not eligible:
        suffix = f" matching {args.match!r}" if args.match else ""
        print(f"{path.name}: nothing to do — no eligible OPEN marker{suffix}")
        return 0
    if len(eligible) > 1:
        sys.stderr.write(
            "ERROR: more than one eligible OPEN marker — "
            "pass --match to select exactly one:\n")
        for i, bare, _tail in eligible:
            sys.stderr.write(f"  line {i + 1}: {bare}\n")
        return 2

    idx, bare, tail = eligible[0]
    _since, desc = split_tail(tail)

    if args.resolved:
        body = args.summary if args.summary else desc
        new = f"> **STATUS:** RESOLVED {args.resolved}"
        if body:
            new += f" — {body}"
        new += f" [details: {args.details}]"
    else:
        new = f"> **STATUS:** OPEN (since {args.auto_date})"
        if desc:
            new += f" — {desc}"

    if args.garden_date:
        new += f" <!-- garden: {args.garden_date} action:{action} -->"

    ending = lines[idx][len(bare):]
    lines[idx] = new + ending
    updated = "".join(lines)
    if updated == original:
        print(f"{path.name}: no change")
        return 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(updated)
    print(f"{path.name}:{idx + 1}:\n  - {bare}\n  + {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
