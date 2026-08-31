"""Contract for automated, local-only SessionEnd receipt enrichment."""

# validate-hook-paths-target: templates/launchd/com.example.claude.session-receipt-enrichment.plist

from __future__ import annotations

import plistlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLIST = (
    ROOT
    / "templates"
    / "launchd"
    / "com.example.claude.session-receipt-enrichment.plist"
)


def test_receipt_enrichment_job_is_bounded_local_and_runnable():
    payload = plistlib.loads(PLIST.read_bytes())
    assert payload["Label"] == "com.example.claude.session-receipt-enrichment"
    assert payload["RunAtLoad"] is True
    assert 60 <= payload["StartInterval"] <= 900
    command = payload["ProgramArguments"][-1]
    assert "enrich-session-end-receipts.py" in command
    assert "$HOME/.claude/bin/" in command
    for forbidden in ("claude -p", "curl ", "http://", "https://"):
        assert forbidden not in command


def test_enricher_exists_and_defaults_to_the_session_receipt_directory():
    source = (ROOT / "bin" / "enrich-session-end-receipts.py").read_text(
        encoding="utf-8"
    )
    assert "session-end-receipts" in source
    assert "processed=" in source
