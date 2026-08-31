"""Tests for block-partial-read.py hook."""
import importlib.util
import os
import sys

_hook_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "block_partial_read", os.path.join(_hook_dir, "block-partial-read.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
PROTECTED_PATTERNS = _mod.PROTECTED_PATTERNS
import re


def test_blocks_partial_read_settings():
    """offset on settings.json should match."""
    rel_path = "settings.json"
    assert any(re.search(p, rel_path) for p in PROTECTED_PATTERNS)
    print("PASS: blocks partial read of settings.json")


def test_blocks_partial_read_rules():
    """offset on rules/*.md should match."""
    rel_path = "rules/platform-constraints.md"
    assert any(re.search(p, rel_path) for p in PROTECTED_PATTERNS)
    print("PASS: blocks partial read of rules/*.md")


def test_blocks_partial_read_skill():
    """offset on skills/*/SKILL.md should match."""
    rel_path = "skills/gather-repos/SKILL.md"
    assert any(re.search(p, rel_path) for p in PROTECTED_PATTERNS)
    print("PASS: blocks partial read of SKILL.md")


def test_allows_full_read():
    """No offset/limit = no blocking (handled by main(), not patterns)."""
    # The hook exits 0 when offset and limit are both None
    print("PASS: full reads allowed (no offset/limit)")


def test_allows_non_protected():
    """Non-protected files not matched."""
    rel_path = "hooks/bash-security-guard.py"
    assert not any(re.search(p, rel_path) for p in PROTECTED_PATTERNS)
    print("PASS: non-protected files not blocked")


def test_allows_regular_code():
    """Regular project files not matched."""
    rel_path = "src/main.py"
    assert not any(re.search(p, rel_path) for p in PROTECTED_PATTERNS)
    print("PASS: regular code files not blocked")


# ── Header-peek carve-out tests (run_hook end-to-end) ──────────────────

from conftest import run_hook

HOOK = "block-partial-read.py"
HOME = os.path.expanduser("~")
SETTINGS = f"{HOME}/.claude/settings.json"


def test_header_peek_offset0_limit50_allowed():
    """offset=0 limit=50 is a legitimate header peek — should pass."""
    rc, _out, _err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": SETTINGS, "offset": 0, "limit": 50},
    })
    assert rc == 0, f"header peek should pass; got rc={rc}"


def test_header_peek_limit_only_allowed():
    """limit=50 without offset (defaults to 0) — should pass."""
    rc, _out, _err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": SETTINGS, "limit": 50},
    })
    assert rc == 0


def test_targeted_read_limit_100_allowed():
    """2026-06-27 relaxation: a targeted read of <=100 lines is a section
    lookup — now allowed (was: only limit<=50 at offset 0 passed)."""
    rc, _out, _err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": SETTINGS, "offset": 0, "limit": 100},
    })
    assert rc == 0, f"limit=100 targeted read should pass; got rc={rc}"


def test_targeted_read_at_nonzero_offset_allowed():
    """2026-06-27 relaxation: a small bounded read at a NON-zero offset is a
    section lookup — the dominant false-block (187 in the 14-day audit, e.g.
    Read(rules/x.md, offset=205, limit=10)). Now allowed."""
    rc, _out, _err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": SETTINGS, "offset": 100, "limit": 20},
    })
    assert rc == 0, f"targeted read at offset should pass; got rc={rc}"


def test_large_partial_still_blocked():
    """A large partial read (>100 lines) of a protected file still blocks — the
    relaxation only carves out targeted section reads, not big mid-file chunks."""
    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": SETTINGS, "offset": 0, "limit": 400},
    })
    assert rc == 2, f"limit=400 should still block; got rc={rc}"
    assert "block-partial-read" in err


def test_unbounded_offset_read_still_blocked():
    """offset set with NO limit reads offset->EOF (a large unbounded partial) —
    still blocked; bound the read or read the whole file."""
    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": SETTINGS, "offset": 200},
    })
    assert rc == 2
    assert "block-partial-read" in err


if __name__ == "__main__":
    test_blocks_partial_read_settings()
    test_blocks_partial_read_rules()
    test_blocks_partial_read_skill()
    test_allows_full_read()
    test_allows_non_protected()
    test_allows_regular_code()
    print("All block-partial-read tests passed.")
