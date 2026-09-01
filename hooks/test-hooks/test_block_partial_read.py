"""Tests for block-partial-read.py hook."""
import os


# ── Header-peek carve-out tests (run_hook end-to-end) ──────────────────

from conftest import run_hook

HOOK = "block-partial-read.py"
HOME = os.path.expanduser("~")
SETTINGS = f"{HOME}/.claude/settings.json"


def _large_partial(path):
    return run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": path, "offset": 0, "limit": 400},
    })


def test_blocks_large_partial_reads_of_control_files():
    paths = (
        SETTINGS,
        f"{HOME}/.claude/rules/platform-constraints.md",
        f"{HOME}/.claude/skills/gather-repos/SKILL.md",
        f"{HOME}/.claude/agents/reviewer.md",
        f"{HOME}/.claude/CLAUDE.md",
    )
    for path in paths:
        rc, _out, err = _large_partial(path)
        assert rc == 2, path
        assert "block-partial-read" in err


def test_allows_full_and_non_control_reads():
    rc, _out, _err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": SETTINGS},
    })
    assert rc == 0

    for path in (f"{HOME}/.claude/hooks/bash-security-guard.py", "/tmp/src/main.py"):
        rc, _out, _err = _large_partial(path)
        assert rc == 0, path


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
