"""Tests for session-start.py (SessionStart).

Note: This hook is complex (38KB, multiple external calls). These tests
verify core behavior without mocking all externals. Full integration
testing requires live repos and MCP configs.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
HOOK = HOOKS_DIR / "session-start.py"


def test_exits_zero():
    """Session-start should always exit 0."""
    result = subprocess.run(
        [PYTHON, str(HOOK)],
        input="{}",
        capture_output=True, text=True, encoding="utf-8",
        timeout=120,
        cwd=str(HOOKS_DIR.parent),
    )
    assert result.returncode == 0


def test_produces_system_message():
    """Should output a JSON object with systemMessage key."""
    result = subprocess.run(
        [PYTHON, str(HOOK)],
        input="{}",
        capture_output=True, text=True, encoding="utf-8",
        timeout=120,
        cwd=str(HOOKS_DIR.parent),
    )
    assert result.returncode == 0
    # stdout should contain valid JSON with systemMessage
    if result.stdout.strip():
        data = json.loads(result.stdout)
        assert "systemMessage" in data


def test_linear_ops_menu_removed():
    """The static linear-ops command menu must NOT appear — removed
    2026-06-11 (noise: a menu is not a status check)."""
    result = subprocess.run(
        [PYTHON, str(HOOK)],
        input="{}",
        capture_output=True, text=True, encoding="utf-8",
        timeout=120,
        cwd=str(HOOKS_DIR.parent),
    )
    if result.stdout.strip():
        data = json.loads(result.stdout)
        assert "linear-ops" not in data.get("systemMessage", "")


# --- check_global_model_default (provider-namespaced global model guard) ---

_MODEL_WARN = "GLOBAL MODEL DEFAULT IS PROVIDER-SPECIFIC"
_MODEL_HEAL = "HEALED GLOBAL MODEL DEFAULT"


def _system_message_with_model(home_dir, model_value):
    """Run session-start under an isolated HOME whose settings.json carries
    `model_value` (or no model key when None). Returns the systemMessage string.

    Sets BOTH HOME and USERPROFILE so home isolation holds on Windows too
    (Path.home() reads USERPROFILE there) — see tdd-quality rule #10.
    """
    claude = Path(home_dir) / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    settings = {} if model_value is None else {"model": model_value}
    (claude / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    result = subprocess.run(
        [PYTHON, str(HOOK)],
        input="{}",
        capture_output=True, text=True, encoding="utf-8",
        timeout=120,
        cwd=str(HOOKS_DIR.parent),
        env={**os.environ, "HOME": str(home_dir), "USERPROFILE": str(home_dir)},
    )
    assert result.returncode == 0
    if not result.stdout.strip():
        return ""
    return json.loads(result.stdout).get("systemMessage", "")


def _model_after_run(home_dir):
    """settings.json `model` AFTER the run (the auto-heal may have rewritten it)."""
    p = Path(home_dir) / ".claude" / "settings.json"
    return json.loads(p.read_text(encoding="utf-8")).get("model")


def test_global_model_healed_on_bedrock_format(tmp_path):
    """A commercial-Bedrock inference-profile ID as the global default is
    self-healed to its 1P form (the us.anthropic. prefix is stripped), and the
    session reports the heal."""
    msg = _system_message_with_model(tmp_path, "us.anthropic.claude-opus-4-8[1m]")
    assert _MODEL_HEAL in msg
    assert _model_after_run(tmp_path) == "claude-opus-4-8[1m]"


def test_global_model_healed_on_gov_format(tmp_path):
    """A GovCloud-format ID is healed to 1P: the region prefix AND the trailing
    `-vN:M` Bedrock version are stripped."""
    msg = _system_message_with_model(
        tmp_path, "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    assert _MODEL_HEAL in msg
    assert _model_after_run(tmp_path) == "claude-sonnet-4-5-20250929"


def test_global_model_warns_not_heals_on_arn(tmp_path):
    """An arn:aws:* model can't be confidently mapped to a 1P id — warn, and
    leave the value unchanged (never guess a rewrite)."""
    arn = "arn:aws:bedrock:us-east-2:0:inference-profile/claude-x"
    msg = _system_message_with_model(tmp_path, arn)
    assert _MODEL_WARN in msg
    assert _model_after_run(tmp_path) == arn  # unchanged (not rewritten)


def test_global_model_silent_on_1p_format(tmp_path):
    """A bare 1P-format claude-* ID is the correct global default — no warn/heal,
    left untouched."""
    msg = _system_message_with_model(tmp_path, "claude-opus-4-8[1m]")
    assert _MODEL_WARN not in msg
    assert _MODEL_HEAL not in msg
    assert _model_after_run(tmp_path) == "claude-opus-4-8[1m]"


def test_global_model_silent_without_model_key(tmp_path):
    """No model key (uses account default) — no warn/heal."""
    msg = _system_message_with_model(tmp_path, None)
    assert _MODEL_WARN not in msg
    assert _MODEL_HEAL not in msg


def test_mutating_startup_modules_are_opt_in(tmp_path):
    """repo sync, MCP process cleanup, keychain OAuth healing, pruning, index
    healing and worktree GC all mutate the host. They run only when
    CLAUDE_SESSION_START_MUTATIONS=1; a default start must say they were skipped."""
    home_dir = tmp_path / "home"
    (home_dir / ".claude").mkdir(parents=True)
    env = {**os.environ, "HOME": str(home_dir), "USERPROFILE": str(home_dir)}
    env.pop("CLAUDE_SESSION_START_MUTATIONS", None)
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input="{}", capture_output=True, text=True, timeout=120, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "startup mutations disabled" in proc.stdout
