"""Tests for pdf-to-text.py (PreToolUse:Read)."""
from conftest import run_hook

HOOK = "pdf-to-text.py"


def test_non_pdf_passthrough():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": "$HOME/Documents/notes.txt"},
    })
    assert rc == 0
    assert err.strip() == ""


def test_non_read_tool_passthrough():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_input": {"command": "cat report.pdf"},
    })
    assert rc == 0


def test_nonexistent_pdf_passthrough():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_input": {"file_path": "C:/nonexistent/file.pdf"},
    })
    assert rc == 0
