#!/usr/bin/env python3
"""No organisation identifier may remain in this export.

The README claims internal identifiers were replaced with neutral placeholders.
Measured 2026-09-03 that was incomplete: an endpoint-security tenant hostname and
object id, an identity-tenant app-id prefix, two employee first names inside an
incident narrative, one programme codename beside a scrubbed one, seven launchd
template filenames, and three claude.ai connector UUIDs survived.

The denylist is stored as SHA-256 digests of lower-cased tokens so that this
test does not itself republish the identifiers it forbids. Structural rules
cover the shapes that cannot be hashed (connector UUIDs inside MCP tool names).

Known-positive control: a planted control token must be detected, or the
scanner is vacuous.

Run: pytest scripts/test_deidentification_residue.py -q
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

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


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                         check=True).stdout
    return [REPO / p.decode("utf-8") for p in out.split(b"\0") if p]


def test_no_organisation_identifiers_in_tracked_files():
    offenders: dict[str, list[str]] = {}
    files = tracked_files()
    assert len(files) > 1000, "git ls-files returned too few files; fixture is wrong"
    for path in files:
        if path.resolve() == SELF:
            continue
        rel = str(path.relative_to(REPO))
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
    assert offenders == {}, (
        f"{len(offenders)} tracked file(s) still carry organisation identifiers:\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(offenders.items()))
    )


def test_scanner_detects_a_planted_control_token(tmp_path):
    """Known-positive: a zero from a scanner that cannot fire proves nothing."""
    planted = tmp_path / "planted.md"
    planted.write_text(f"harmless words {CONTROL_TOKEN} more words\n", encoding="utf-8")
    assert scan_text(planted.read_text(encoding="utf-8")) == [CONTROL_TOKEN]
    assert scan_text("mcp__12345678-1234-1234-1234-123456789abc__tool") != []
    assert scan_text("nothing to see here") == []
