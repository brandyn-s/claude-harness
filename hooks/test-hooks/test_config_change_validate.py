"""Boundary tests for the ConfigChange settings-integrity hook."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from conftest import run_hook

HOOK = "config-change-validate.py"
MAX_SETTINGS_BYTES = 4 * 1024 * 1024
MANIFEST = Path(__file__).resolve().parent.parent / "manifests" / "config-change-validate.yaml"
HOOK_PATH = MANIFEST.parent.parent / HOOK
REPO = HOOK_PATH.parent.parent


def _event(source: str, file_path: str | None) -> dict:
    return {
        "hook_event_name": "ConfigChange",
        "source": source,
        "file_path": file_path,
    }


def _run_raw_event(raw: str) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=raw,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=2,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _protected_user_settings(hooks_dir: Path) -> dict:
    """Smallest active registry that preserves the architecture's safety hooks."""

    def group(matcher, script, timeout=30):
        entry = {
            "hooks": [
                {
                    "type": "command",
                    "command": str(hooks_dir / "run-hook"),
                    "args": [script],
                    "timeout": timeout,
                }
            ]
        }
        if matcher is not None:
            entry["matcher"] = matcher
        return entry

    return {
        "hooks": {
            "ConfigChange": [
                group(
                    "user_settings|project_settings|local_settings",
                    "config-change-validate.py",
                )
            ],
            "PreToolUse": [
                group("Bash", "bash-security-guard.py"),
                group("Bash|PowerShell", "destructive-ops-guard.py"),
                group("Write|Edit", "write-edit-dispatcher.py"),
            ],
            "PostToolUse": [group("Write|Edit", "post-write-edit.py")],
            "SessionStart": [group(None, "session-start.py")],
            "SessionEnd": [group(".*", "session-end.py", 5)],
        }
    }


def test_manifest_registers_user_settings_config_change_guard():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["event"] == "ConfigChange"
    assert manifest["matcher"] == "user_settings|project_settings|local_settings"
    assert manifest["action_type"] == "guard"
    assert manifest["output_format"] == "json"
    assert manifest["exit_codes"] == {
        "0": "allow silently or block via structured decision JSON"
    }
    assert any(
        "CLAUDE_CONFIG_ALLOW_PROTECTED_HOOK_REMOVAL" in item
        for item in manifest["depends_on_env"]
    )


def _object_without_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, f"duplicate JSON object key: {key}"
        result[key] = value
    return result


def test_manifest_registration_is_unique_structured_exec_form_on_both_surfaces():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))

    for settings_name in ("settings.json", "settings.example.json"):
        settings = json.loads(
            (REPO / settings_name).read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
        registrations = settings["hooks"].get(manifest["event"])
        assert isinstance(registrations, list) and len(registrations) == 1
        assert registrations[0]["matcher"] == manifest["matcher"]
        handlers = registrations[0]["hooks"]
        assert isinstance(handlers, list) and len(handlers) == 1
        handler = handlers[0]
        assert handler["type"] == "command"
        assert Path(handler["command"]).is_absolute()
        assert handler["command"].endswith("/.claude/hooks/run-hook")
        assert handler["args"] == ["config-change-validate.py"]
        assert handler["timeout"] == 30


@pytest.mark.parametrize(
    "raw",
    [
        '{"source":"user_settings","value":' + ("9" * 10_000) + "}",
        ("[" * 10_000) + "0" + ("]" * 10_000),
        '{"source":"user_settings","padding":"'
        + ("x" * (1024 * 1024))
        + '"}',
    ],
    ids=["pathological-integer", "pathological-depth", "oversized-event"],
)
def test_malformed_or_oversized_event_is_bounded_and_fails_closed(raw):
    rc, stdout, stderr = _run_raw_event(raw)

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "ConfigChange event cannot be validated; existing policy remains active.",
    }
    assert stderr == ""


@pytest.mark.parametrize("source", ["policy_settings", "skills"])
def test_unblockable_config_sources_exit_cleanly(source, tmp_path):
    missing = tmp_path / "must-not-be-read.json"

    rc, stdout, stderr = run_hook(HOOK, _event(source, str(missing)))

    assert rc == 0
    assert stdout == ""
    assert stderr == ""


def test_unhashable_unknown_config_source_exits_cleanly(tmp_path):
    event = _event("user_settings", str(tmp_path / "must-not-be-read.json"))
    event["source"] = ["unknown_source"]

    rc, stdout, stderr = run_hook(HOOK, event)

    assert rc == 0
    assert stdout == ""
    assert stderr == ""


def test_valid_user_settings_object_is_allowed(tmp_path):
    settings = tmp_path / "settings.json"
    payload = _protected_user_settings(tmp_path / "hooks")
    payload["permissions"] = {"deny": ["Bash(rm -rf:*)"]}
    settings.write_text(json.dumps(payload))

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert stdout == ""
    assert stderr == ""


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"permissions": {"deny": ["Bash(rm -rf:*)"]}},
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/test/.claude/hooks/run-hook",
                                "args": ["bash-security-guard.py"],
                            }
                        ],
                    }
                ]
            }
        },
    ],
)
def test_user_settings_without_protected_active_hook_registry_are_blocked(
    tmp_path, payload
):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(payload), encoding="utf-8")

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings remove required protected hooks; existing hooks remain active.",
    }
    assert stderr == ""


def test_operator_session_can_explicitly_authorize_protected_hook_removal(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")

    rc, stdout, stderr = run_hook(
        HOOK,
        _event("user_settings", str(settings)),
        env={"CLAUDE_CONFIG_ALLOW_PROTECTED_HOOK_REMOVAL": "1"},
    )

    assert rc == 0
    assert stdout == ""
    assert stderr == ""


def test_operator_removal_override_does_not_authorize_disabling_all_hooks(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")

    rc, stdout, stderr = run_hook(
        HOOK,
        _event("user_settings", str(settings)),
        env={"CLAUDE_CONFIG_ALLOW_PROTECTED_HOOK_REMOVAL": "1"},
    )

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings set disableAllHooks=true; existing hooks remain active.",
    }
    assert stderr == ""


def test_settings_content_cannot_activate_operator_removal_override(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {"env": {"CLAUDE_CONFIG_ALLOW_PROTECTED_HOOK_REMOVAL": "1"}}
        ),
        encoding="utf-8",
    )

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings remove required protected hooks; existing hooks remain active.",
    }
    assert stderr == ""


def test_native_windows_exec_form_preserves_protected_registry(tmp_path):
    payload = _protected_user_settings(tmp_path / "hooks")
    for groups in payload["hooks"].values():
        for group in groups:
            for entry in group["hooks"]:
                script = entry["args"][0]
                entry["command"] = r"C:\Program Files\Git\bin\bash.exe"
                entry["args"] = [
                    str(tmp_path / "hooks" / "run-hook"),
                    script,
                ]
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(payload), encoding="utf-8")

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert stdout == ""
    assert stderr == ""


def test_inert_command_that_mentions_protected_script_is_not_accepted(tmp_path):
    payload = _protected_user_settings(tmp_path / "hooks")
    config_entry = payload["hooks"]["ConfigChange"][0]["hooks"][0]
    config_entry["command"] = "/usr/bin/echo"
    config_entry["args"] = ["config-change-validate.py"]
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(payload), encoding="utf-8")

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings remove required protected hooks; existing hooks remain active.",
    }
    assert stderr == ""


@pytest.mark.parametrize(
    "mutation",
    [
        "lookalike_runner",
        "lookalike_script",
        "wrong_runner",
        "conditional_hook",
        "conditional_group",
        "async_hook",
        "once_hook",
        "shell_hook",
        "wrong_timeout",
        "zero_timeout",
        "matcher_superset",
        "config_matcher_subset",
        "never_match_lifecycle",
    ],
)
def test_protected_registry_rejects_non_exact_or_inert_registrations(
    tmp_path, mutation
):
    settings = tmp_path / "settings.json"
    payload = _protected_user_settings(tmp_path / "hooks")

    def find(event, script):
        for group in payload["hooks"][event]:
            for entry in group["hooks"]:
                if entry["args"] == [script]:
                    return group, entry
        raise AssertionError(f"fixture has no {event}/{script}")

    if mutation in {
        "lookalike_runner",
        "lookalike_script",
        "wrong_runner",
        "conditional_hook",
        "conditional_group",
        "async_hook",
        "once_hook",
        "shell_hook",
        "wrong_timeout",
        "zero_timeout",
        "matcher_superset",
    }:
        group, entry = find("PreToolUse", "bash-security-guard.py")
    elif mutation == "config_matcher_subset":
        group, entry = find("ConfigChange", "config-change-validate.py")
    else:
        group, entry = find("SessionStart", "session-start.py")

    if mutation == "lookalike_runner":
        entry["command"] = str(tmp_path / "attacker" / "run-hook")
    elif mutation == "lookalike_script":
        entry["args"] = [str(tmp_path / "attacker" / entry["args"][0])]
    elif mutation == "wrong_runner":
        entry["command"] = sys.executable
    elif mutation == "conditional_hook":
        entry["if"] = "Bash(false)"
    elif mutation == "conditional_group":
        group["if"] = "Bash(false)"
    elif mutation == "async_hook":
        entry["async"] = True
    elif mutation == "once_hook":
        entry["once"] = True
    elif mutation == "shell_hook":
        entry["shell"] = "powershell"
    elif mutation == "wrong_timeout":
        entry["timeout"] += 1
    elif mutation == "zero_timeout":
        entry["timeout"] = 0
    elif mutation == "matcher_superset":
        group["matcher"] += "|Read"
    elif mutation == "config_matcher_subset":
        group["matcher"] = "user_settings"
    elif mutation == "never_match_lifecycle":
        group["matcher"] = "^$"

    settings.write_text(json.dumps(payload), encoding="utf-8")
    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings remove required protected hooks; existing hooks remain active.",
    }
    assert stderr == ""


def test_materialized_runtime_settings_pass_the_protected_registry_guard(tmp_path):
    home = tmp_path / "home"
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    payload = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    installed_runner = str(settings.parent / "hooks" / "run-hook")
    for groups in payload["hooks"].values():
        for group in groups:
            for handler in group.get("hooks", []):
                command = handler.get("command")
                if isinstance(command, str) and command.endswith(
                    "/.claude/hooks/run-hook"
                ):
                    handler["command"] = installed_runner
    settings.write_text(json.dumps(payload), encoding="utf-8")

    rc, stdout, stderr = run_hook(
        HOOK,
        _event("user_settings", str(settings)),
        env={"HOME": str(home)},
    )

    assert rc == 0
    assert stdout == ""
    assert stderr == ""


def test_malformed_user_settings_are_blocked_without_echoing_contents(tmp_path):
    settings = tmp_path / "settings.json"
    secret_marker = "super-secret-marker"
    settings.write_text('{"token":"' + secret_marker + '"', encoding="utf-8")

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert stdout
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings are not valid JSON; existing policy remains active.",
    }
    assert secret_marker not in stdout + stderr


def test_malformed_project_settings_are_blocked(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"permissions":', encoding="utf-8")

    rc, stdout, stderr = run_hook(HOOK, _event("project_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed project settings are not valid JSON; existing policy remains active.",
    }
    assert stderr == ""


def test_non_utf8_user_settings_are_blocked_without_echoing_bytes(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_bytes(b'{"token":"\xffsecret-byte-marker"}')

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings are not valid JSON; existing policy remains active.",
    }
    assert "secret-byte-marker" not in stdout + stderr


def test_oversized_user_settings_are_blocked_before_parsing(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"padding":"' + ("x" * MAX_SETTINGS_BYTES) + '"}', encoding="utf-8"
    )

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings exceed the 4 MiB validation limit; existing policy remains active.",
    }
    assert stderr == ""


def test_pathologically_deep_user_settings_are_blocked(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        ("[" * 500_000) + "0" + ("]" * 500_000), encoding="utf-8"
    )

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings are not valid JSON; existing policy remains active.",
    }
    assert stderr == ""


def test_pathological_integer_user_settings_are_blocked(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"value":' + ("9" * 10_000) + "}", encoding="utf-8")

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings are not valid JSON; existing policy remains active.",
    }
    assert stderr == ""


def test_non_object_user_settings_root_is_blocked(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps([{"permissions": {}}]), encoding="utf-8")

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings must be a JSON object; existing policy remains active.",
    }
    assert stderr == ""


def test_missing_user_settings_file_is_blocked(tmp_path):
    missing = tmp_path / "missing-settings.json"

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(missing)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings cannot be read; existing policy remains active.",
    }
    assert stderr == ""


def test_missing_local_settings_file_is_blocked(tmp_path):
    missing = tmp_path / "missing-settings.local.json"

    rc, stdout, stderr = run_hook(HOOK, _event("local_settings", str(missing)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed local settings cannot be read; existing policy remains active.",
    }
    assert stderr == ""


def test_unreadable_user_settings_path_is_blocked(tmp_path):
    not_a_readable_file = tmp_path / "settings.json"
    not_a_readable_file.mkdir()

    rc, stdout, stderr = run_hook(
        HOOK, _event("user_settings", str(not_a_readable_file))
    )

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings cannot be read; existing policy remains active.",
    }
    assert stderr == ""


def test_symlink_user_settings_path_is_blocked(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    settings_link = tmp_path / "settings.json"
    settings_link.symlink_to(target)

    rc, stdout, stderr = run_hook(
        HOOK, _event("user_settings", str(settings_link))
    )

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings cannot be read; existing policy remains active.",
    }
    assert stderr == ""


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="platform has no FIFO support")
def test_fifo_user_settings_path_is_rejected_without_blocking(tmp_path):
    settings_fifo = tmp_path / "settings.json"
    os.mkfifo(settings_fifo)

    try:
        rc, stdout, stderr = run_hook(
            HOOK, _event("user_settings", str(settings_fifo)), timeout=1
        )
    except subprocess.TimeoutExpired:
        pytest.fail("ConfigChange validation blocked while opening a non-regular file")

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings cannot be read; existing policy remains active.",
    }
    assert stderr == ""


def test_non_string_user_settings_path_is_blocked():
    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", None))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings cannot be read; existing policy remains active.",
    }
    assert stderr == ""


def test_embedded_nul_user_settings_path_is_blocked_without_traceback():
    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", "unsafe\0path"))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings cannot be read; existing policy remains active.",
    }
    assert stderr == ""


def test_disable_all_hooks_true_is_blocked(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings set disableAllHooks=true; existing hooks remain active.",
    }
    assert stderr == ""


def test_explicit_empty_user_hooks_object_is_blocked(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout) == {
        "decision": "block",
        "reason": "Changed user settings explicitly empty the hooks object; existing hooks remain active.",
    }
    assert stderr == ""


# --- provider-prefixed model IDs ---------------------------------------------
#
# A settings file is read by EVERY launcher, so a region-qualified Bedrock ID
# there misroutes the first-party ones. bin/architecture-drift-check.py gates the
# committed file; `/model` writes the live file, which is why this reached a
# running session five times. These tests pin the write-time seam.


def _load_module(name: str, path: Path):
    """Import a hyphenated script by path, failing loudly if it cannot load."""

    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings_with(tmp_path: Path, **overrides) -> Path:
    """A valid protected registry plus the overrides under test."""

    payload = _protected_user_settings(tmp_path / "hooks")
    payload.update(overrides)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(payload), encoding="utf-8")
    return settings


@pytest.mark.parametrize(
    "overrides,surface",
    [
        # The exact value that misrouted on 2026-08-28, verbatim.
        ({"model": "us.anthropic.claude-fable-5"}, "`model`"),
        ({"model": "us.anthropic.claude-opus-5[1m]"}, "`model`"),
        ({"model": "us-gov.anthropic.claude-opus-5[1m]"}, "`model`"),
        ({"model": "eu.anthropic.claude-sonnet-5"}, "`model`"),
        ({"model": "apac.anthropic.claude-sonnet-5"}, "`model`"),
        (
            {"model": "arn:aws:bedrock:us-east-2::foundation-model/x"},
            "`model`",
        ),
        ({"fallbackModel": ["us.anthropic.claude-opus-5[1m]"]}, "`fallbackModel`"),
        ({"fallbackModel": "us.anthropic.claude-opus-5[1m]"}, "`fallbackModel`"),
        (
            # The 2026-08-18 env-block vector: no launcher unset can defend
            # against it, because the CLI injects settings env after the
            # launcher subshell scrub runs.
            {"env": {"ANTHROPIC_DEFAULT_OPUS_MODEL": "us-gov.anthropic.claude-opus-5"}},
            "`env.ANTHROPIC_DEFAULT_OPUS_MODEL`",
        ),
        (
            {"env": {"ANTHROPIC_MODEL": "us.anthropic.claude-opus-5"}},
            "`env.ANTHROPIC_MODEL`",
        ),
    ],
)
def test_provider_prefixed_model_surfaces_are_blocked(tmp_path, overrides, surface):
    settings = _settings_with(tmp_path, **overrides)

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    payload = json.loads(stdout)
    assert payload["decision"] == "block"
    assert surface in payload["reason"]
    assert "existing model configuration remains active" in payload["reason"]
    assert stderr == ""


@pytest.mark.parametrize(
    "source,label",
    [
        ("user_settings", "user settings"),
        ("project_settings", "project settings"),
        ("local_settings", "local settings"),
    ],
)
def test_provider_prefixed_model_is_blocked_on_every_settings_source(
    tmp_path, source, label
):
    # local_settings OUTRANK settings.json in the precedence chain, so gating
    # only the user layer would leave the higher-priority surface open.
    settings = _settings_with(tmp_path, model="us.anthropic.claude-fable-5")

    rc, stdout, stderr = run_hook(HOOK, _event(source, str(settings)))

    assert rc == 0
    payload = json.loads(stdout)
    assert payload["decision"] == "block"
    assert payload["reason"].startswith(f"Changed {label} set `model`")
    assert stderr == ""


@pytest.mark.parametrize(
    "overrides",
    [
        # 1P-format IDs are the CORRECT form and must never be blocked --
        # this is the control that would catch an over-broad prefix match.
        {"model": "claude-fable-5[1m]"},
        {"model": "claude-opus-5[1m]"},
        {"model": "claude-sonnet-5"},
        {"fallbackModel": ["claude-opus-5[1m]"]},
        {"env": {"ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-5[1m]"}},
        # A model name that merely CONTAINS a provider token is not prefixed by
        # one; the check must anchor rather than substring-match (the exact
        # error claude-hud's isBedrockModelId makes).
        {"model": "claude-opus-5-us.anthropic.test"},
        # Unrelated env values must not be dragged in by the env scan.
        {"env": {"BASH_MAX_TIMEOUT_MS": "300000"}},
    ],
)
def test_first_party_model_ids_are_allowed(tmp_path, overrides):
    settings = _settings_with(tmp_path, **overrides)

    rc, stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert stdout == ""
    assert stderr == ""


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": 5},
        {"model": None},
        {"fallbackModel": {"not": "a list"}},
        {"fallbackModel": [None, 7]},
        {"env": {"ANTHROPIC_MODEL": 5}},
        {"env": ["not", "a", "dict"]},
    ],
)
def test_non_string_model_surfaces_do_not_crash_the_gate(tmp_path, overrides):
    # Type validation of these fields is Claude Code's job, not this hook's; the
    # gate must not raise (a traceback here fails the ConfigChange closed).
    settings = _settings_with(tmp_path, **overrides)

    rc, _stdout, stderr = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert stderr == ""


def test_env_scan_names_a_deterministic_surface(tmp_path):
    settings = _settings_with(
        tmp_path,
        env={
            "ZZZ_MODEL": "us.anthropic.claude-opus-5",
            "AAA_MODEL": "us.anthropic.claude-sonnet-5",
        },
    )

    rc, stdout, _ = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    # Sorted scan, so the reason is stable across dict orderings.
    assert "`env.AAA_MODEL`" in json.loads(stdout)["reason"]


def test_model_block_reason_never_echoes_the_offending_value(tmp_path):
    settings = _settings_with(tmp_path, model="us.anthropic.claude-fable-5")

    rc, stdout, _ = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    reason = json.loads(stdout)["reason"]
    assert "us.anthropic.claude-fable-5" not in reason


def test_hook_integrity_block_outranks_the_model_block(tmp_path):
    # Both violations at once: the safety boundary must own the reason, because
    # a caller that only reads the first block must see the more severe one.
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"hooks": {}, "model": "us.anthropic.claude-fable-5"}),
        encoding="utf-8",
    )

    rc, stdout, _ = run_hook(HOOK, _event("user_settings", str(settings)))

    assert rc == 0
    assert json.loads(stdout)["reason"] == (
        "Changed user settings explicitly empty the hooks object; existing hooks remain active."
    )


def test_gate_prefixes_match_the_commit_time_gate():
    """The two gates must agree on what 'provider-specific' means.

    If architecture-drift-check.py grows a prefix and this hook does not, a value
    it rejects at commit time still reaches the running session -- which is the
    exact gap this hook exists to close.
    """

    hook_module = _load_module("cc_validate_prefixes", HOOK_PATH)
    drift_module = _load_module(
        "arch_drift_prefixes", REPO / "bin" / "architecture-drift-check.py"
    )

    assert set(hook_module.PROVIDER_MODEL_PREFIXES) == set(
        drift_module.PROVIDER_MODEL_PREFIXES
    )
