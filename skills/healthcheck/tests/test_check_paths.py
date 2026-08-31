"""Unit tests for healthcheck/references/check_paths.py (Check 5).

Pins the shlex-based path extraction (the documented fix for the greedy regex
that pulled `hooks/foo.py` out of a quoted `"$HOME/.claude/hooks/foo.py"` token
and resolved it against the wrong base) and the existing-vs-missing resolution
in check_file.
"""
import json
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_paths",
    Path(__file__).resolve().parent.parent / "references" / "check_paths.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


def test_extract_quoted_path_is_one_whole_token():
    # THE BUG: the old regex pulled the substring `hooks/foo.py` out of the
    # quoted token. shlex must yield exactly one whole-token path.
    paths = hc._extract_script_paths('python3 "$HOME/.claude/hooks/foo.py"')
    assert paths == ["$HOME/.claude/hooks/foo.py"]
    assert "hooks/foo.py" not in paths


def test_extract_run_hook_name_only():
    paths = hc._extract_script_paths("$HOME/.claude/hooks/run-hook foo.py")
    assert paths == ["foo.py"]


def test_extract_ignores_non_script_tokens():
    assert hc._extract_script_paths("git status -s") == []


def _settings(tmp_path, command, args=None):
    claude = tmp_path / ".claude"
    (claude / "hooks").mkdir(parents=True)
    sp = claude / "settings.json"
    sp.write_text(json.dumps(
        {"hooks": {"PreToolUse": [{"hooks": [{
            "command": command,
            "args": args or [],
        }]}]}}), encoding="utf-8")
    return claude, sp


def test_check_file_accepts_existing_hook_script(tmp_path, monkeypatch):
    claude, sp = _settings(tmp_path, "run-hook foo.py")
    (claude / "hooks" / "foo.py").write_text("# hook", encoding="utf-8")
    monkeypatch.setattr(hc, "CLAUDE_DIR", str(claude))
    raw, bad = hc.check_file(str(sp), hc.walk_hooks)
    assert raw == ["foo.py"]
    assert bad == []


def test_check_file_flags_missing_hook_script(tmp_path, monkeypatch):
    claude, sp = _settings(tmp_path, "run-hook ghost.py")
    monkeypatch.setattr(hc, "CLAUDE_DIR", str(claude))
    raw, bad = hc.check_file(str(sp), hc.walk_hooks)
    assert raw == ["ghost.py"]
    assert len(bad) == 1 and bad[0][0] == "ghost.py"


def test_check_file_accepts_exec_form_hook_args(tmp_path, monkeypatch):
    claude, sp = _settings(
        tmp_path,
        str(tmp_path / ".claude" / "hooks" / "run-hook"),
        ["foo.py"],
    )
    (claude / "hooks" / "foo.py").write_text("# hook", encoding="utf-8")
    monkeypatch.setattr(hc, "CLAUDE_DIR", str(claude))
    raw, bad = hc.check_file(str(sp), hc.walk_hooks)
    assert raw == ["foo.py"]
    assert bad == []
