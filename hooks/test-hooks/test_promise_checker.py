"""Tests for promise-checker.py Stop hook."""
import importlib.util
import json
import os
import sys
import tempfile

from conftest import run_hook

# Load the module from hyphenated filename
_hook_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "promise_checker", os.path.join(_hook_dir, "promise-checker.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
PROMISE_PATTERNS = _mod.PROMISE_PATTERNS
WRITE_TOOLS = _mod.WRITE_TOOLS

HOOK = "promise-checker.py"


# ── Pattern-list unit checks ──────────────────────────────────────────

def test_blocks_promise_without_write():
    """Promise found, no Write/Edit tool call -> should detect."""
    text = "i've noted that for future reference."
    found = [p for p in PROMISE_PATTERNS if p in text.lower()]
    assert len(found) > 0, f"Should match promise pattern, got {found}"


def test_allows_promise_with_write():
    """Write tool is in WRITE_TOOLS set."""
    assert "Write" in WRITE_TOOLS
    assert "Edit" in WRITE_TOOLS


def test_allows_no_promise():
    """No promise patterns in normal text."""
    text = "here's the analysis of the code you asked about."
    found = [p for p in PROMISE_PATTERNS if p in text.lower()]
    assert len(found) == 0, f"Should not match, got {found}"


def test_memory_tool_counts():
    """memory_search counts as a write tool."""
    assert "mcp__memory-search__memory_search" in WRITE_TOOLS


# ── End-to-end transcript parsing ─────────────────────────────────────
# These exercise main()'s JSONL parsing against the REAL Claude Code
# transcript schema (type "user"/"assistant" with content nested under
# entry["message"]["content"]). The hook previously filtered on
# "user_message"/"assistant_message" and read top-level content, so it
# silently no-op'd on every Stop — these tests are the regression guard.

def _assistant_text(text):
    return {"type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _assistant_tool_use(name):
    return {"type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "name": name, "input": {}}]}}


def _tool_result():
    return {"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "content": "ok"}]}}


def _human(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _run(entries):
    """Write entries as JSONL, invoke the hook with that transcript_path."""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return run_hook(HOOK, {"transcript_path": path})
    finally:
        os.unlink(path)


def test_e2e_blocks_banned_phrase():
    rc, _, stderr = _run([
        _human("are we done?"),
        _assistant_text("This is a good stopping point. Let's wrap up for now."),
    ])
    assert rc == 2, f"banned phrase should block (rc=2), got {rc}: {stderr}"
    assert "promise-checker" in stderr


def test_e2e_blocks_promise_without_write():
    rc, _, stderr = _run([
        _human("remember the API quirk"),
        _assistant_text("Got it. I've noted that for future reference."),
    ])
    assert rc == 2, f"unfulfilled promise should block (rc=2), got {rc}: {stderr}"


def test_e2e_allows_promise_with_write_earlier_in_turn():
    """The fulfilling Write precedes its tool_result (a type=='user' entry).
    The tool_result must NOT end the turn, or this is a false-positive block."""
    rc, _, stderr = _run([
        _human("save the gotcha to the topic file"),
        _assistant_tool_use("Write"),
        _tool_result(),
        _assistant_text("Done — I've saved that to crowdstrike.md."),
    ])
    assert rc == 0, f"promise WITH a Write in-turn must pass, got {rc}: {stderr}"


def test_e2e_allows_clean_completion():
    rc, _, _ = _run([
        _human("summarize the findings"),
        _assistant_text("Here is the analysis you asked for: ..."),
    ])
    assert rc == 0


def test_e2e_banned_phrase_in_prior_turn_ignored():
    """A banned phrase from a previous turn (before the last human message)
    must not block the current clean turn."""
    rc, _, _ = _run([
        _assistant_text("good stopping point"),   # old turn
        _human("no, keep going"),                 # human boundary
        _assistant_text("Continuing with the next step now."),
    ])
    assert rc == 0


def test_e2e_no_transcript_path_exits_zero():
    rc, _, _ = run_hook(HOOK, {})
    assert rc == 0


def test_e2e_empty_stdin_exits_zero():
    rc, _, _ = run_hook(HOOK, {})
    assert rc == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS: {name}")
    print("All promise-checker tests passed.")
