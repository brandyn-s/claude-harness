"""Tests for the opt-in native Claude Code release qualifier."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "qualify_claude_release.py"
README = HERE / "README.md"


def load_qualifier():
    spec = importlib.util.spec_from_file_location("qualify_claude_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


Q = load_qualifier()


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_help_documents_explicit_loopback_native_opt_in():
    result = run_cli("--help")

    assert result.returncode == 0, result.stderr
    assert "--run-native" in result.stdout
    assert "--expected-version" in result.stdout
    assert "loopback" in result.stdout.lower()


def test_native_run_rejects_wrong_version_before_other_invocations(tmp_path: Path):
    invocations = tmp_path / "invocations"
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = --version ]; then\n"
        "  printf '%s\\n' '2.1.225 (Claude Code)'\n"
        "  exit 0\n"
        "fi\n"
        f"printf x >> {invocations}\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    result = run_cli(
        "--run-native",
        "--claude",
        str(fake),
        "--expected-version",
        "2.1.226",
    )

    assert result.returncode == 1
    assert "expected 2.1.226" in result.stderr
    assert "found 2.1.225" in result.stderr
    assert not invocations.exists(), "version mismatch must stop before probes"


def test_loopback_environment_uses_non_secret_credential_fixture(tmp_path: Path):
    env = Q._probe_environment(tmp_path, "http://127.0.0.1:12345")
    secret_shaped_prefix = "sk" + "-ant-"

    assert env["ANTHROPIC_API_KEY"] == "loopback-runtime-qualification"
    assert secret_shaped_prefix not in SCRIPT.read_text(encoding="utf-8")


def test_loopback_server_emits_one_declared_tool_then_end_turn():
    scenario = Q.Scenario("declared-tool", "Bash", {"command": "printf ok"})
    with Q.loopback_server(scenario) as loopback:
        assert loopback.base_url.startswith("http://127.0.0.1:")
        first = urllib.request.Request(
            f"{loopback.base_url}/v1/messages?beta=true",
            data=json.dumps(
                {
                    "stream": True,
                    "model": "claude-test",
                    "tools": [{"name": "Bash"}],
                    "messages": [],
                }
            ).encode(),
            headers={"content-type": "application/json"},
        )
        first_body = urllib.request.urlopen(first, timeout=5).read().decode()
        assert '"name":"Bash"' in first_body
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in first_body.splitlines()
            if line.startswith("data: ")
        ]
        delta = next(
            payload["delta"]
            for payload in payloads
            if payload.get("type") == "content_block_delta"
        )
        assert json.loads(delta["partial_json"]) == {"command": "printf ok"}
        assert loopback.requests[0]["model"] == "claude-test"

        second = urllib.request.Request(
            f"{loopback.base_url}/v1/messages?beta=true",
            data=json.dumps(
                {
                    "stream": True,
                    "model": "claude-test",
                    "tools": [{"name": "Bash"}],
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_runtime_qualification",
                                    "content": "ok",
                                }
                            ],
                        }
                    ],
                }
            ).encode(),
            headers={"content-type": "application/json"},
        )
        second_body = urllib.request.urlopen(second, timeout=5).read().decode()
        assert '"stop_reason":"end_turn"' in second_body
        assert '"name":"Bash"' not in second_body

        repeated = urllib.request.urlopen(first, timeout=5).read().decode()
        assert '"name":"Bash"' not in repeated, "a scenario emits its tool once"


def test_fork_argument_plugin_contains_both_runtime_contract_shapes(tmp_path: Path):
    plugin = Q.write_fork_argument_plugin(tmp_path)

    manifest = json.loads(
        (plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    explicit = (plugin / "skills" / "explicit" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    implicit = (plugin / "skills" / "implicit" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert manifest["name"] == Q.FORK_ARGUMENT_PLUGIN
    assert "context: fork" in explicit and "$ARGUMENTS" in explicit
    assert "context: fork" in implicit and "$ARGUMENTS" not in implicit


def test_fork_argument_oracles_require_rendering_and_same_block_append():
    argument = "alpha beta gamma"
    explicit = [
        {
            "messages": [
                {
                    "content": [
                        {
                            "type": "text",
                            "text": f"{Q.FORK_EXPLICIT_PREFIX}{argument}{Q.FORK_EXPLICIT_SUFFIX}",
                        }
                    ]
                }
            ]
        }
    ]
    implicit = [
        {
            "messages": [
                {
                    "content": [
                        {
                            "type": "text",
                            "text": f"{Q.FORK_IMPLICIT_MARKER}\n\nARGUMENTS: {argument}",
                        }
                    ]
                }
            ]
        }
    ]

    Q.require_rendered_fork_arguments(explicit, argument)
    Q.require_appended_fork_arguments(implicit, argument)

    explicit[0]["messages"][0]["content"][0]["text"] = (
        f"{Q.FORK_EXPLICIT_PREFIX}$ARGUMENTS{Q.FORK_EXPLICIT_SUFFIX}"
    )
    with pytest.raises(Q.QualificationError, match="render"):
        Q.require_rendered_fork_arguments(explicit, argument)

    implicit[0]["messages"][0]["content"][0]["text"] = (
        f"{Q.FORK_IMPLICIT_MARKER}\n\n{argument}"
    )
    with pytest.raises(Q.QualificationError, match="ARGUMENTS"):
        Q.require_appended_fork_arguments(implicit, argument)


def test_hook_block_oracle_requires_exit_two_and_non_execution():
    events = [
        {
            "type": "system",
            "subtype": "hook_response",
            "hook_name": "PreToolUse:Bash",
            "stderr": "MATCHED_PUSH_BLOCKING_HOOK",
            "exit_code": 2,
        },
        {
            "type": "user",
            "tool_result_meta": [
                {
                    "id": "toolu_runtime_qualification",
                    "non_execution_kind": "permission-rule",
                }
            ],
        },
    ]

    Q.require_blocked_hook(events, "MATCHED_PUSH_BLOCKING_HOOK")

    events[0]["exit_code"] = 0
    with pytest.raises(Q.QualificationError, match="exit 2"):
        Q.require_blocked_hook(events, "MATCHED_PUSH_BLOCKING_HOOK")
    events[0]["exit_code"] = 2
    events[1]["tool_result_meta"] = []
    with pytest.raises(Q.QualificationError, match="non-execution"):
        Q.require_blocked_hook(events, "MATCHED_PUSH_BLOCKING_HOOK")


def test_hook_nonmatch_oracle_requires_execution_without_hook_events():
    events = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "content": "local-if-probe-executed",
                    }
                ]
            },
        }
    ]

    Q.require_unfiltered_bash(events, "local-if-probe-executed")

    events.append({"type": "system", "subtype": "hook_started"})
    with pytest.raises(Q.QualificationError, match="unexpectedly started"):
        Q.require_unfiltered_bash(events, "local-if-probe-executed")


def test_worker_local_oracle_requires_bash_inside_linked_worktree():
    cwd = "/tmp/fixture/.claude/worktrees/worker-local"
    events = [
        {"type": "system", "subtype": "init", "cwd": cwd, "tools": ["Bash"]},
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "content": cwd, "is_error": False}
                ]
            },
        },
    ]

    Q.require_worker_local(events)

    events[0]["tools"] = []
    with pytest.raises(Q.QualificationError, match="Bash"):
        Q.require_worker_local(events)


def test_worker_fence_oracle_requires_explicit_cross_checkout_refusal():
    events = [
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "content": (
                            "This session is isolated in the worktree /tmp/w, but "
                            "this command redirects git to the shared checkout via "
                            "-C. Refusing to run it."
                        ),
                        "is_error": True,
                    }
                ]
            },
        }
    ]

    Q.require_worker_fence(events)

    events[0]["message"]["content"][0]["is_error"] = False
    with pytest.raises(Q.QualificationError, match="refusal"):
        Q.require_worker_fence(events)


def test_success_oracle_pins_init_and_terminal_release_version():
    events = [
        {
            "type": "system",
            "subtype": "init",
            "claude_code_version": "2.1.226",
        },
        {"type": "result", "subtype": "success", "is_error": False},
    ]

    Q.require_success(events, "2.1.226")

    events[0]["claude_code_version"] = "2.1.225"
    with pytest.raises(Q.QualificationError, match="init reported"):
        Q.require_success(events, "2.1.226")


@pytest.mark.skipif(
    os.environ.get("RUN_CLAUDE_NATIVE_QUALIFICATION") != "1",
    reason="native release qualification is explicitly opt-in",
)
def test_opt_in_native_release_qualification():
    claude = shutil.which("claude")
    assert claude, "claude executable is required for the opt-in qualification"
    expected = os.environ.get("CLAUDE_EXPECTED_VERSION", "2.1.226")

    result = run_cli(
        "--run-native",
        "--claude",
        claude,
        "--expected-version",
        expected,
    )

    assert result.returncode == 0, result.stderr
    for name in (
        "schema-settings",
        "if-push-nonmatch",
        "if-push-block",
        "if-commit-block",
        "worker-local-bash",
        "worker-cross-checkout-fence",
        "fork-skill-rendered-arguments",
        "fork-skill-appended-arguments",
    ):
        assert f"PASS {name}" in result.stdout


def test_readme_publishes_literal_opt_in_command_and_bounded_scenarios():
    text = README.read_text(encoding="utf-8")
    assert "python3 scripts/runtime-qualification/qualify_claude_release.py" in text
    assert "--run-native" in text
    assert "--expected-version 2.1.226" in text
    assert "127.0.0.1" in text
    assert "`Skill` tool" in text
    assert "`args`" in text
    for name in (
        "schema-settings",
        "if-push-nonmatch",
        "if-push-block",
        "if-commit-block",
        "worker-local-bash",
        "worker-cross-checkout-fence",
        "fork-skill-rendered-arguments",
        "fork-skill-appended-arguments",
    ):
        assert name in text
    lowered = text.lower()
    assert "".join(("can", "ary")) not in lowered  # noqa: FLY002
    assert " ".join(("timed", "observation")) not in lowered  # noqa: FLY002
