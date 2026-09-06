#!/usr/bin/env python3
"""The de-identification residue scanner: no organisation identifier may leave.

This repository is the public core; the organisation that runs it does so from a
private overlay (docs/consuming-from-a-private-overlay.md). Lessons travel from
the overlay into the core only with the instance stripped -- and the failure
mode, an organisation's name in a public commit, is not reversible. So the
identifiers that have leaked before are held here as SHA-256 digests of the
lower-cased tokens (the scanner must not itself republish what it forbids) and
checked in three places:

  every tracked file        scripts/test_deidentification_residue.py (the suite, CI)
  every commit message      .githooks/commit-msg (locally, at commit time) and the
                            CI step over a pull request's commits
  staged files              .githooks/pre-commit

Structural rules cover the shapes that cannot be hashed (a claude.ai per-org
connector UUID inside an MCP tool name).

USAGE
  python3 scripts/deidentification_residue.py                    # every tracked file
  python3 scripts/deidentification_residue.py --staged           # files staged for commit
  python3 scripts/deidentification_residue.py --message-file F   # a commit message (commit-msg hook)
  python3 scripts/deidentification_residue.py --commits A..B     # the messages of a commit range (CI)
  python3 scripts/deidentification_residue.py --stdin            # arbitrary text
  ... --reveal                                                   # print the offending token itself

Findings are printed MASKED by default (first character, length) because CI logs
of a public repository are public; --reveal is for the author at the keyboard.
Exit 1 on any finding, 0 when clean, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
TEST_FILE = REPO / "scripts" / "test_deidentification_residue.py"

# sha256(token.lower()) for each forbidden single token.
FORBIDDEN_TOKEN_DIGESTS = {
    "f5718edfe3217e987a5663ac27151ca5d4fb8e7e369e4a6dfde95284bfba50af",  # organisation name
    "b39bc6b762f5f41e54364fd1eb6cca90a68dd3669ea3aecaac042aed4ab377a1",  # endpoint-security tenant id
    "46e0416c94c2b38ee131680b7bf56ba1a4480f716cb41884b520790afd4a227c",  # blocklist object id
    "c59d241e69cf03baed729d632bb5219cb53946c3a5601a937cf89797b2f87a99",  # identity app-id prefix
    "305ea4c4b0498edb1eb1a92e1265e3a9b0d48d9ea3fdad40e4beb4a1e9717121",  # programme codename
    "e1fc45f7880e0505ff0b6a079b9af149f225e260f59b1d20225357a8cce8ffd8",  # employee first name
    "a6ac558e3cc659a5e6cbd200141d984ffd3c06f357101f411cc78624f212a976",  # employee first name
    "0667fd2fd65e20d958f5a491218c748038bd5526be2f9c2e00a786a827a2f1a5",  # programme codename (short)
    "22c53e368287f5aaaddc8e29cad2be60297132f5b1d6a46e9234a45843f8ac9b",  # CONTROL token (test only)
}
CONTROL_TOKEN = "residue-control-token-8f2a"

# Shapes that identify an organisation without a memorable token.
STRUCTURAL = [
    # A UUID whose first group repeats one hex digit (00000000-, ffffffff-) is an
    # obvious placeholder; that is the fixture convention used in this repo.
    (re.compile(r"mcp__(?!([0-9a-f])\1{7}-)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}__"),
     "claude.ai per-org connector UUID used as an MCP server name"),
]

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]|[A-Za-z0-9]")


def _digest(token: str) -> str:
    return hashlib.sha256(token.lower().encode("utf-8")).hexdigest()


def scan_text(text: str) -> list[str]:
    """Return the offending tokens/shapes found in one text blob."""
    hits: list[str] = []
    tokens = set(_TOKEN_RE.findall(text))
    # Hyphenated compounds are checked whole AND by part (`example-<codename>`).
    tokens |= {part for token in list(tokens) if "-" in token for part in token.split("-") if part}
    for token in tokens:
        if _digest(token) in FORBIDDEN_TOKEN_DIGESTS:
            hits.append(token)
    for pattern, why in STRUCTURAL:
        if pattern.search(text):
            hits.append(f"<{why}>")
    return sorted(hits)


def mask(hit: str) -> str:
    if hit.startswith("<"):
        return hit
    return f"{hit[0]}{'*' * (len(hit) - 1)} ({len(hit)} chars)"


def tracked_files(repo: Path = REPO) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True).stdout
    return [repo / p.decode("utf-8") for p in out.split(b"\0") if p]


def staged_files(repo: Path = REPO) -> list[Path]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                         cwd=repo, capture_output=True, check=True).stdout
    return [repo / p.decode("utf-8") for p in out.split(b"\0") if p]


def scan_files(files: list[Path], repo: Path = REPO) -> dict[str, list[str]]:
    """{relative path: hits} over file NAMES and contents. The scanner and its test
    are skipped: they hold the control token by design."""
    offenders: dict[str, list[str]] = {}
    for path in files:
        if path.resolve() in (SELF, TEST_FILE):
            continue
        rel = str(path.relative_to(repo)) if path.is_absolute() else str(path)
        name_hits = scan_text(rel)
        if name_hits:
            offenders[rel] = [f"<filename> {h}" for h in name_hits]
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = scan_text(text)
        if hits:
            offenders.setdefault(rel, []).extend(hits)
    return offenders


def commit_messages(rev_range: str, repo: Path = REPO) -> list[tuple[str, str]]:
    """[(sha, full message)] for every commit in the range."""
    out = subprocess.run(["git", "log", "--format=%H%x00%B%x1e", rev_range], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    result = []
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        sha, _, body = record.partition("\x00")
        result.append((sha.strip(), body))
    return result


def _report(offenders: dict[str, list[str]], reveal: bool, what: str) -> int:
    if not offenders:
        print(f"residue scan: clean ({what})")
        return 0
    print(f"residue scan: {len(offenders)} {what} carry organisation identifiers:", file=sys.stderr)
    for where, hits in sorted(offenders.items()):
        shown = ", ".join(h if reveal else mask(h) for h in hits)
        print(f"  {where}: {shown}", file=sys.stderr)
    if not reveal:
        print("  (tokens masked; re-run with --reveal at your own keyboard)", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="scan the files staged for commit")
    mode.add_argument("--message-file", metavar="FILE", help="scan one commit message (commit-msg hook)")
    mode.add_argument("--commits", metavar="RANGE", help="scan the messages of every commit in a git range")
    mode.add_argument("--stdin", action="store_true", help="scan text from stdin")
    ap.add_argument("--reveal", action="store_true", help="print the offending tokens themselves")
    ap.add_argument("--repo", default=str(REPO), help="repository root (default: this checkout)")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    try:
        if args.message_file:
            text = Path(args.message_file).read_text(encoding="utf-8", errors="replace")
            # Lines git itself will strip from the message are not part of it.
            text = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
            hits = scan_text(text)
            return _report({"commit message": hits} if hits else {}, args.reveal, "commit message")
        if args.stdin:
            hits = scan_text(sys.stdin.read())
            return _report({"stdin": hits} if hits else {}, args.reveal, "text")
        if args.commits:
            offenders = {}
            for sha, body in commit_messages(args.commits, repo):
                hits = scan_text(body)
                if hits:
                    offenders[f"commit {sha[:12]}"] = hits
            return _report(offenders, args.reveal, "commit message(s)")
        files = staged_files(repo) if args.staged else tracked_files(repo)
        return _report(scan_files(files, repo), args.reveal, "staged file(s)" if args.staged else "tracked file(s)")
    except subprocess.CalledProcessError as exc:
        print(f"residue scan: git failed: {exc.stderr or exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
