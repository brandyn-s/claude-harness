#!/usr/bin/env python3
"""Extract the Watching-table issue numbers from the gather-claude report.

gather-claude Step 1b intersects the Watching set against issues closed since
the last run. Hand-transcribing ~85 issue numbers into the intersection script
is the ONE step where a typo silently drops a closure (-> a stale Watching row,
-> a workaround kept for an already-fixed bug). Generate the set instead.

Extraction is ITEM-COLUMN-ONLY (2026-07-05 fix): the Watching table's prose
columns embed inline issue/PR references ("Subsumed by #40929", "PR #1489")
that are NOT tracked rows. Whole-section extraction inflated a 90-row table to
120 numbers; the 2026-07-03 run had to re-derive the clean set by hand with
awk -F'|'. This script now parses table rows and takes only the first cell.
Whole-section regex remains as a FALLBACK for non-table input (e.g. a bare
list piped on stdin) and is labeled as such in the output.

DORMANT IS EXCLUDED BY DEFAULT (2026-08-30 fix): the report nests a
`### Watching (Dormant)` appendix INSIDE `## Watching`, and its own preamble says
it is "Re-scanned only on `full` runs, not on incremental ones". The section
slice below stops at the next TOP-LEVEL `## ` heading, and that lookahead
requires whitespace after the two hashes -- so it can never match a `###`
heading, and every incremental run was silently sweeping the appendix too.
Measured cost: #83731 (a Dormant row, DELETED upstream) was re-extracted every
run and re-reported by reconcile_watching as the "sole recurring NOT FOUND",
which multiple runs then re-investigated. Pass --full to include the appendix,
matching the `full`-run semantics the report documents.

Usage:
    python3 parse_watching.py [REPORT_PATH]      # read a file (active rows only)
    python3 parse_watching.py [REPORT_PATH] --full   # include Dormant appendix
    <report-section> | python3 parse_watching.py -   # read stdin

Default REPORT_PATH:
    ~/Documents/knowledge-base/research/claude-code-anthropic-intelligence.md

HOST CAVEAT (macOS): if the report lives under a sandbox-blocked path (e.g.
~/Documents under macOS TCC, where the Bash tool gets "Operation not
permitted"), this script cannot read it from the Bash tool. In that case read
the report's `## Watching` section via the Read tool and pipe it in on stdin
(`-`), OR extract the `#NNNNN` set deterministically from the Read-tool content
-- never eyeball-transcribe the numbers.

Prints to stdout:
    - a sorted, de-duplicated list of the Item-column `#NNNNN` numbers in the
      report's `## Watching` section (sliced from its header to the next
      top-level `## `)
    - a count line
    - a Python set literal ready to paste into the intersection script
"""
import os
import re
import sys

DEFAULT = os.path.expanduser(
    "~/Documents/knowledge-base/research/claude-code-anthropic-intelligence.md"
)

ISSUE_RE = re.compile(r"#(\d{4,6})\b")


SUBSECTION_RE = re.compile(r"^###\s+\S", re.MULTILINE)


def strip_subsections(section):
    """Truncate at the first `###` subsection heading (e.g. Watching (Dormant)).

    Returns (active_section, dropped_line_count). The top-level slice in
    watching_section() stops only at the next `## ` header, which by
    construction cannot match a `###` heading -- so nested appendices ride
    along. The Dormant appendix is explicitly documented as full-run-only, so
    incremental runs must not extract its rows.
    """
    m = SUBSECTION_RE.search(section)
    if not m:
        return section, 0
    dropped = section[m.start():]
    return section[: m.start()], len(dropped.splitlines())


def watching_section(text, include_dormant=False):
    """Slice `## Watching ...` up to the next top-level `## ` header.

    Falls back to the whole text if no `## Watching` header is present (e.g.
    when only the section itself was piped in on stdin). Unless
    `include_dormant` is set, any nested `###` appendix is dropped.
    """
    m = re.search(r"^##\s+Watching\b.*?(?=^##\s+\S)", text, re.MULTILINE | re.DOTALL)
    if m:
        section = m.group(0)
    else:
        header = re.search(r"^##\s+Watching\b", text, re.MULTILINE)
        if header:
            # header present but no following `## ` (section runs to EOF)
            section = text[header.start():]
        else:
            print(
                "WARNING: no '## Watching' header found; scanning whole input",
                file=sys.stderr,
            )
            section = text
    if include_dormant:
        return section
    section, dropped = strip_subsections(section)
    if dropped:
        print(
            f"note: dropped {dropped} line(s) of nested '###' appendix "
            f"(Dormant is full-run-only; pass --full to include)",
            file=sys.stderr,
        )
    return section


def item_column_numbers(section):
    """Extract issue numbers from the Item column (first cell) of table rows.

    Returns (numbers, used_fallback). Only the first `|`-delimited cell of each
    table row is scanned, so inline references in prose columns ("Subsumed by
    #40929", "PR #1489") are excluded. If the section contains no table rows
    with Item-cell numbers, falls back to a whole-section scan (non-table
    input, e.g. a bare list on stdin) and flags it.
    """
    nums = set()
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = stripped.split("|")
        # cells[0] is the empty string before the leading pipe; cells[1] = Item
        if len(cells) < 2:
            continue
        item = cells[1].strip()
        if set(item) <= {"-", " ", ":"}:  # header separator row
            continue
        nums.update(int(n) for n in ISSUE_RE.findall(item))
    if nums:
        return sorted(nums), False
    fallback = sorted({int(n) for n in ISSUE_RE.findall(section)})
    return fallback, True


def main():
    args = sys.argv[1:]
    if any(a in ("-h", "--help") for a in args):
        print(__doc__)
        return
    include_dormant = "--full" in args
    positional = [a for a in args if not a.startswith("--")]
    arg = positional[0] if positional else DEFAULT
    if arg == "-":
        text = sys.stdin.read()
    else:
        with open(arg, encoding="utf-8") as f:
            text = f.read()
    section = watching_section(text, include_dormant=include_dormant)
    nums, used_fallback = item_column_numbers(section)
    if used_fallback:
        print(
            "WARNING: no table Item-column numbers found; used whole-section scan "
            "(may include inline issue/PR references from prose)",
            file=sys.stderr,
        )
    scope = "active + Dormant appendix" if include_dormant else "active rows only"
    print(f"watching issue numbers ({len(nums)}, {scope}):")
    print(" ".join(f"#{n}" for n in nums))
    print()
    print("# paste into the intersection script:")
    print("watching = {" + ", ".join(str(n) for n in nums) + "}")


if __name__ == "__main__":
    main()
