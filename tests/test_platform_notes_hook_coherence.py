"""Keep the platform note aligned with the executable ruff hook contract."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT / "hooks" / "post-write-edit.py"
NOTES_PATH = ROOT / "docs" / "PLATFORM_NOTES.md"


def _ruff_argv(source: str) -> list[str]:
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.List):
            continue
        values = [item.value for item in node.elts if isinstance(item, ast.Constant)]
        if values[:2] == ["ruff", "check"]:
            return values
    raise AssertionError("post-write-edit has no literal `ruff check` argv")


def _format_on_save_note(notes: str) -> str:
    match = re.search(
        r"\*\*Edit/Write format-on-save fix \(v2\.1\.90\)\*\*:(.*?)(?=\n\n\*\*|\Z)",
        notes,
        re.DOTALL,
    )
    assert match, "v2.1.90 format-on-save note is missing"
    return match.group(1)


def assert_ruff_docs_match_runtime(hook_source: str, notes: str) -> None:
    argv = _ruff_argv(hook_source)
    note = _format_on_save_note(notes)
    assert "--fix" in argv
    assert "`ruff check --fix`" in note
    assert "`--check` mode" not in note


def test_platform_note_matches_executable_ruff_mode() -> None:
    assert_ruff_docs_match_runtime(
        HOOK_PATH.read_text(encoding="utf-8"),
        NOTES_PATH.read_text(encoding="utf-8"),
    )


@pytest.mark.parametrize("mutation", ("hook", "notes"))
def test_ruff_mode_coherence_mutations_are_killed(mutation: str) -> None:
    hook = HOOK_PATH.read_text(encoding="utf-8")
    notes = NOTES_PATH.read_text(encoding="utf-8")
    if mutation == "hook":
        hook = hook.replace('"--fix", "--quiet"', '"--quiet"', 1)
    else:
        notes = notes.replace("`ruff check --fix`", "`--check` mode", 1)
    with pytest.raises(AssertionError):
        assert_ruff_docs_match_runtime(hook, notes)
