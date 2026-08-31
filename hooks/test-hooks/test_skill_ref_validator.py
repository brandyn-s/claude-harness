"""Tests for skill-ref-validator.py (PostToolUse:Write|Edit)."""
from pathlib import Path

import pytest

from conftest import run_hook

HOOK = "skill-ref-validator.py"

# The hook resolves `hooks/<name>.py` references against ~/.claude/hooks/.
# Tests that exercise the "real file present" path only pass if the repo
# is installed at ~/.claude/. Contributors running pytest from a checkout
# (not yet installed) will see a false failure otherwise.
_requires_installed = pytest.mark.skipif(
    not (Path.home() / ".claude" / "hooks" / "pdf-to-text.py").exists(),
    reason="requires the repo installed at ~/.claude/ (hook resolves refs there)",
)


def test_non_skill_md_passthrough():
    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/notes.md"},
    })
    assert rc == 0
    assert err.strip() == ""


def test_non_write_edit_tool_passthrough():
    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_input": {"command": "cat skills/foo/SKILL.md"},
    })
    assert rc == 0
    assert err.strip() == ""


def test_clean_skill_passes_silent(tmp_path):
    # Build a skill dir with SKILL.md that references only existing files
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "# Demo\n\nNothing referenced.\n",
        encoding="utf-8",
    )

    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(skill_file)},
    })
    assert rc == 0
    assert err.strip() == ""


def test_dead_ref_warns(tmp_path):
    skill_dir = tmp_path / "skills" / "bogus"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    # Reference a hook that doesn't exist in ~/.claude/hooks/
    skill_file.write_text(
        "# Bogus skill\n\nRun `python ~/.claude/hooks/nonexistent-xyz.py --run`\n",
        encoding="utf-8",
    )

    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(skill_file)},
    })
    assert rc == 0, f"Should not block, got rc={rc}"
    assert "hooks/nonexistent-xyz.py" in err
    assert "skill-ref-validator" in err


def test_ignores_code_blocks(tmp_path):
    """Refs inside fenced code blocks (examples) should not trigger warnings."""
    skill_dir = tmp_path / "skills" / "example"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "# Example\n\n"
        "```\n"
        "# example output\n"
        "hooks/totally-fake-xyz123.py was deleted\n"
        "```\n"
        "\nReal content.\n",
        encoding="utf-8",
    )

    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(skill_file)},
    })
    assert rc == 0
    # Should NOT warn about hooks/totally-fake-xyz123.py (it's inside a code block)
    assert "totally-fake-xyz123" not in err


@_requires_installed
def test_real_existing_hook_passes(tmp_path):
    """A ref to a real hook in the repo should pass without warning."""
    skill_dir = tmp_path / "skills" / "real"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "# Real skill\n\nUses `hooks/pdf-to-text.py` (exists).\n",
        encoding="utf-8",
    )

    rc, _out, err = run_hook(HOOK, {
        "tool_name": "Write",
        "tool_input": {"file_path": str(skill_file)},
    })
    assert rc == 0
    assert "pdf-to-text.py" not in err
