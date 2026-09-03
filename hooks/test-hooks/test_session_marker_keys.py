# validate-hook-paths-target: hooks/auto-topic-loader.py
"""Per-session marker files must key on the hook payload's session_id.

Claude Code delivers `session_id` on stdin and does not export CLAUDE_SESSION_ID
to hook processes, so markers keyed on that env var collapsed every session into
one `...-default.*` file (review 2026-09-03). Each session-scoped hook must accept
the payload id and fall back to the env var only when none is given.
"""
import importlib.util
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HOOKS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_auto_topic_loader_marker_uses_payload_session(tmp_path, monkeypatch):
    mod = _load("auto-topic-loader.py")
    monkeypatch.setattr(mod, "SESSION_MARKER_DIR", tmp_path)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    assert mod.get_marker_path("session-aaaa").name == "topics-loaded-session-aaaa.json"
    assert mod.get_marker_path("session-bbbb").name == "topics-loaded-session-bbbb.json"


def test_env_var_remains_the_fallback(tmp_path, monkeypatch):
    mod = _load("auto-topic-loader.py")
    monkeypatch.setattr(mod, "SESSION_MARKER_DIR", tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "env-session-1")
    assert mod.get_marker_path().name == "topics-loaded-env-session-.json"
