"""Auto-archive old ## Run Log entries from ~/.claude/assessed-repos.md.

Mechanizes the Step-5 invariant documented in
skills/gather-repos/SKILL.md: move ledger ## Run Log entries older than
30 days into ~/.claude/assessed-repos-archive.md (append-only) so the
main ledger does not grow past ~200 lines.

Usage:
    python _gather_repos_archive.py            # do the archive
    python _gather_repos_archive.py --dry-run  # report what would move, no writes
    python _gather_repos_archive.py -h         # usage

Exit codes:
    0  ran cleanly (whether or not anything moved)
    2  argument misuse
    3  ledger file missing or malformed
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

LEDGER = Path.home() / ".claude" / "assessed-repos.md"
ARCHIVE = Path.home() / ".claude" / "assessed-repos-archive.md"
WINDOW_DAYS = 30
RUN_HEAD_RE = re.compile(r"^### Run (\d{4}-\d{2}-\d{2})", re.MULTILINE)

USAGE = (
    "Usage: python _gather_repos_archive.py [--dry-run]\n"
    "  --dry-run: print what would archive, write nothing\n"
    "  -h | --help: show this message and exit"
)


def _parse_args(argv: list[str]) -> bool:
    if not argv:
        return False
    if argv[0] in {"-h", "--help"}:
        print(USAGE)
        sys.exit(0)
    if argv[0] == "--dry-run" and len(argv) == 1:
        return True
    print(f"ERROR: unrecognized argument(s): {argv}", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    sys.exit(2)


def _split_run_log(text: str) -> tuple[str, str, str]:
    """Return (prefix, run_log_body, suffix). Suffix begins at the next
    top-level heading after ## Run Log, or end-of-file."""
    m = re.search(r"^## Run Log\s*$", text, re.MULTILINE)
    if not m:
        # Exit 3 was previously bare — zero diagnostic output made a
        # malformed ledger indistinguishable from any other failure.
        print(
            "ERROR: ledger has no '## Run Log' heading; cannot split for "
            "archival.\nhint: check the ledger wasn't hand-edited — the "
            "heading must be a top-level '## Run Log' line.",
            file=sys.stderr,
        )
        raise SystemExit(3)
    body_start = m.end()
    after = text[body_start:]
    nxt = re.search(r"^## ", after, re.MULTILINE)
    if nxt:
        body_end = body_start + nxt.start()
    else:
        body_end = len(text)
    return text[: body_start], text[body_start:body_end], text[body_end:]


def _split_runs(body: str) -> list[tuple[_dt.date, str]]:
    """Return list of (run_date, raw_block_including_heading). The text
    before the first ### Run heading is preserved separately by the
    caller (it is the section's preamble/comment block)."""
    matches = list(RUN_HEAD_RE.finditer(body))
    runs: list[tuple[_dt.date, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        date = _dt.date.fromisoformat(m.group(1))
        runs.append((date, body[start:end]))
    return runs


def _preamble(body: str) -> str:
    first = RUN_HEAD_RE.search(body)
    return body if first is None else body[: first.start()]


def archive(dry_run: bool = False) -> int:
    if not LEDGER.exists():
        print(f"ERROR: ledger not found at {LEDGER}", file=sys.stderr)
        return 3
    text = LEDGER.read_text(encoding="utf-8")
    prefix, run_log_body, suffix = _split_run_log(text)
    preamble = _preamble(run_log_body)
    runs = _split_runs(run_log_body)
    if not runs:
        print("No ### Run entries in ## Run Log — nothing to archive.")
        return 0

    cutoff = _dt.date.today() - _dt.timedelta(days=WINDOW_DAYS)
    # Always keep the most recent run, even if older than 30 days
    runs_sorted = sorted(runs, key=lambda x: x[0], reverse=True)
    keep_dates = {runs_sorted[0][0]}
    keep_blocks, archive_blocks = [], []
    for date, block in runs:
        if date in keep_dates or date >= cutoff:
            keep_blocks.append(block)
        else:
            archive_blocks.append(block)

    print(
        f"Ledger has {len(runs)} runs; "
        f"keeping {len(keep_blocks)}, archiving {len(archive_blocks)} "
        f"(cutoff {cutoff.isoformat()})."
    )
    if not archive_blocks:
        return 0
    if dry_run:
        for block in archive_blocks:
            first_line = block.splitlines()[0] if block.strip() else ""
            print(f"  would archive: {first_line}")
        return 0

    new_run_log = preamble + "".join(keep_blocks)
    new_ledger = prefix + new_run_log + suffix
    archived_chunk = (
        f"\n<!-- archived {_dt.date.today().isoformat()} from assessed-repos.md ## Run Log -->\n"
        + "".join(archive_blocks)
    )
    if ARCHIVE.exists():
        ARCHIVE.write_text(
            ARCHIVE.read_text(encoding="utf-8") + archived_chunk,
            encoding="utf-8",
        )
    else:
        ARCHIVE.write_text(
            "# Community Repo Assessments — Archive\n\n"
            "Append-only archive of ## Run Log entries older than 30 days "
            "moved out of ~/.claude/assessed-repos.md by "
            "scripts/_gather_repos_archive.py.\n"
            + archived_chunk,
            encoding="utf-8",
        )
    LEDGER.write_text(new_ledger, encoding="utf-8")
    print(f"Archived {len(archive_blocks)} run(s) to {ARCHIVE}.")
    return 0


if __name__ == "__main__":
    dry = _parse_args(sys.argv[1:])
    sys.exit(archive(dry_run=dry))
