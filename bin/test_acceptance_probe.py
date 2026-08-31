"""Regression tests for the local acceptance evidence probe."""

from __future__ import annotations

import json
import subprocess

import acceptance_probe
import pytest


def test_snapshot_schema_version_accounts_for_telemetry_evidence_layers():
    assert acceptance_probe.SNAPSHOT_SCHEMA == "acceptance-probe/4"


def test_otel_probe_never_treats_disable_telemetry_as_otel_kill_switch(monkeypatch):
    for name in acceptance_probe.OTEL_EFFECTIVE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISABLE_TELEMETRY", "1")

    result = acceptance_probe.probe_otel({"DISABLE_TELEMETRY": "1"})

    assert result["effective_startup"]["status"] == "unverified"
    assert result["backend_receipt"]["status"] == "not-probed"
    assert result["disable_telemetry"]["configured"] == "1"
    assert result["disable_telemetry"]["is_otel_control"] is False
    assert "DISABLED" not in result["effective"]


def test_otel_probe_classifies_effective_content_logging_as_unsafe():
    effective_env = {key: "0" for key in acceptance_probe.OTEL_CONTENT_ENV}
    effective_env.update(
        {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
            "OTEL_LOG_RAW_API_BODIES": "1",
            "OTEL_LOGS_EXPORTER": "otlp",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.invalid",
        }
    )

    result = acceptance_probe.probe_otel({}, effective_startup_env=effective_env)

    assert result["effective_startup"]["status"] == "unsafe-content-enabled"
    assert result["effective_startup"]["unsafe_content_flags"] == [
        "OTEL_LOG_RAW_API_BODIES"
    ]
    assert result["backend_receipt"]["status"] == "not-probed"
    assert result["effective"].startswith("UNSAFE:")
    assert result["unverified"] is True


def test_otel_probe_classifies_latent_content_flag_as_unsafe_when_otel_is_off():
    effective_env = {key: "0" for key in acceptance_probe.OTEL_CONTENT_ENV}
    effective_env.update(
        {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "0",
            "OTEL_LOG_TOOL_DETAILS": "1",
        }
    )

    result = acceptance_probe.probe_otel({}, effective_startup_env=effective_env)

    assert result["effective_startup"]["status"] == "unsafe-content-configured"
    assert result["effective_startup"]["unsafe_content_flags"] == [
        "OTEL_LOG_TOOL_DETAILS"
    ]
    assert result["effective"].startswith("UNSAFE:")


@pytest.mark.parametrize(
    ("flag", "value"),
    [(key, "1") for key in acceptance_probe.OTEL_CONTENT_ENV]
    + [("OTEL_LOG_RAW_API_BODIES", "file:/redacted")],
)
def test_otel_content_flag_mutations_are_all_classified_unsafe(flag, value):
    effective_env = {key: "0" for key in acceptance_probe.OTEL_CONTENT_ENV}
    effective_env.update(
        {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
            flag: value,
        }
    )

    result = acceptance_probe.probe_otel({}, effective_startup_env=effective_env)

    assert result["effective_startup"]["content_classification"] == "unsafe"
    assert flag in result["effective_startup"]["unsafe_content_flags"]


def test_otel_metadata_only_startup_still_requires_backend_receipt():
    effective_env = {key: "0" for key in acceptance_probe.OTEL_CONTENT_ENV}
    effective_env.update(
        {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
            "OTEL_LOGS_EXPORTER": "otlp",
        }
    )

    result = acceptance_probe.probe_otel({}, effective_startup_env=effective_env)

    assert result["effective_startup"]["status"] == "metadata-only"
    assert result["backend_receipt"]["status"] == "not-probed"
    assert result["unverified"] is True


def test_otel_probe_rejects_bare_boolean_backend_attestation():
    effective_env = {key: "0" for key in acceptance_probe.OTEL_CONTENT_ENV}
    effective_env["CLAUDE_CODE_ENABLE_TELEMETRY"] = "1"

    with pytest.raises(TypeError):
        acceptance_probe.probe_otel(
            {},
            effective_startup_env=effective_env,
            backend_receipt=True,
        )


def test_model_probe_applies_environment_precedence_without_claiming_effective(
    monkeypatch,
):
    monkeypatch.setenv("ANTHROPIC_MODEL", "opus")
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "xhigh")
    probe = getattr(acceptance_probe, "probe_model_runtime", None)
    assert callable(probe), "acceptance probe has no model runtime dimension"

    result = probe(
        {
            "model": "claude-fable-5",
            "fallback_model": ["claude-sonnet-5[1m]"],
            "effort_level": "high",
            "switch_models_on_flag": False,
        }
    )

    assert result["configured_model"] == "claude-fable-5"
    assert result["requested_model"] == "opus"
    assert result["requested_model_source"] == "environment:ANTHROPIC_MODEL"
    assert result["configured_effort"] == "high"
    assert result["requested_effort"] == "xhigh"
    assert result["requested_effort_source"] == "environment:CLAUDE_CODE_EFFORT_LEVEL"
    assert result["effective_model"] == "runtime-unknown"
    assert result["effective_effort"] == "runtime-unknown"
    assert result["unverified"] is True


def test_model_probe_falls_back_to_settings_request_when_env_is_absent(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_EFFORT_LEVEL", raising=False)

    result = acceptance_probe.probe_model_runtime(
        {
            "model": "claude-fable-5",
            "fallback_model": ["claude-sonnet-5[1m]"],
            "effort_level": "high",
            "switch_models_on_flag": False,
        }
    )

    assert result["requested_model"] == "claude-fable-5"
    assert result["requested_model_source"] == "settings.json:model"
    assert result["requested_effort"] == "high"
    assert result["requested_effort_source"] == "settings.json:effortLevel"
    assert result["configured_fallback_models"] == ["claude-sonnet-5[1m]"]
    assert result["configured_switch_models_on_flag"] is False


def test_parse_mcp_list_records_connected_server_without_transport_details():
    output = """\
Checking MCP server health...
alpha: https://user:secret@example.invalid/mcp --header Authorization:Bearer-secret - ✓ Connected
"""

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result == {
        "probe_rc": 0,
        "probe_state": "completed",
        "server_count": 1,
        "servers": [{"name": "alpha", "status": "connected"}],
        "status_counts": {
            "connected": 1,
            "failed": 0,
            "needs_auth": 0,
            "disabled": 0,
            "unknown": 0,
        },
        "unverified": False,
        "unverified_reason": None,
        "note": (
            "sanitized names and connection classes only; tool inventories and "
            "headless mcp_server_errors require separate live authenticated probes"
        ),
    }


def test_parse_mcp_list_classifies_tools_list_and_http_errors_as_failed():
    output = """\
tools-broken: https://internal.invalid/mcp?token=secret - ✗ Connected transport; tools/list failed: HTTP 500
http-broken: https://private.invalid/mcp --header X-Key:secret - ✗ Failed to connect: HTTP 503 Service Unavailable
"""

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["servers"] == [
        {"name": "http-broken", "status": "failed"},
        {"name": "tools-broken", "status": "unknown"},
    ]
    assert result["server_count"] == 2
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 1,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 1,
    }
    assert result["probe_state"] == "contradictory_output"
    assert result["unverified"] is True
    assert result["unverified_reason"] == "ambiguous_server_status"


def test_parse_mcp_list_anchors_failure_before_trailing_status_words():
    output = """\
last-state: server - ✗ Failed to connect: HTTP 503 - last Connected
oauth-state: server - ✗ Failed to connect: OAuth client disabled
"""

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["servers"] == [
        {"name": "last-state", "status": "failed"},
        {"name": "oauth-state", "status": "failed"},
    ]
    assert result["status_counts"]["failed"] == 2
    assert result["status_counts"]["connected"] == 0
    assert result["status_counts"]["disabled"] == 0


def test_parse_mcp_list_fails_closed_on_multiple_leading_statuses():
    output = "ambiguous: server - ✓ Connected - ✗ Failed to connect\n"

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["servers"] == [{"name": "ambiguous", "status": "unknown"}]
    assert result["probe_state"] == "contradictory_output"
    assert result["status_counts"]["unknown"] == 1
    assert result["unverified"] is True
    assert result["unverified_reason"] == "ambiguous_server_status"


@pytest.mark.parametrize(
    "status_text",
    [
        "✓ Connected, ✗ Failed to connect",
        "Connected; Disabled",
        "Connected | ! Needs authentication",
        "Connected / ✗ Failed to connect",
        "Connected — ○ Disabled",
    ],
)
def test_parse_mcp_list_fails_closed_on_mixed_same_row_status_grammar(
    status_text,
):
    result = acceptance_probe.parse_mcp_list(
        f"ambiguous: server - {status_text}\n",
        probe_rc=0,
    )

    assert result["servers"] == [{"name": "ambiguous", "status": "unknown"}]
    assert result["probe_state"] == "contradictory_output"
    assert result["status_counts"]["unknown"] == 1
    assert result["unverified"] is True
    assert result["unverified_reason"] == "ambiguous_server_status"


@pytest.mark.parametrize(
    "status_text",
    [
        "✗ Connected",
        "✓ Failed to connect",
        "○ Connected",
        "! Disabled",
    ],
)
def test_parse_mcp_list_does_not_invent_health_from_marker_word_conflicts(
    status_text,
):
    result = acceptance_probe.parse_mcp_list(
        f"ambiguous: server - {status_text}\n",
        probe_rc=0,
    )

    assert result["servers"] == [{"name": "ambiguous", "status": "unknown"}]
    assert result["probe_state"] == "contradictory_output"
    assert result["status_counts"]["connected"] == 0
    assert result["status_counts"]["failed"] == 0
    assert result["unverified"] is True
    assert result["unverified_reason"] == "ambiguous_server_status"


@pytest.mark.parametrize("bullet", ["-", "*", "•", "●", "▪", "◦"])
def test_parse_mcp_list_normalizes_bullet_prefixed_conflicting_rows(bullet):
    result = acceptance_probe.parse_mcp_list(
        f"{bullet} alpha: first-server - ✓ Connected\n"
        f"{bullet} alpha: second-server - ✗ Failed to connect\n",
        probe_rc=0,
    )

    assert result["servers"] == [{"name": "alpha", "status": "unknown"}]
    assert result["probe_state"] == "contradictory_output"
    assert result["status_counts"]["unknown"] == 1
    assert result["unverified"] is True
    assert result["unverified_reason"] == "conflicting_statuses_for_server"


def test_parse_mcp_list_distrusts_zero_marker_with_bullet_prefixed_row():
    result = acceptance_probe.parse_mcp_list(
        "• alpha: server - ✓ Connected\n"
        "No MCP servers configured. Use `claude mcp add` to add one.\n",
        probe_rc=0,
    )

    assert result["servers"] == [{"name": "alpha", "status": "connected"}]
    assert result["probe_state"] == "contradictory_output"
    assert result["unverified"] is True
    assert result["unverified_reason"] == "zero_server_marker_with_rows"


def test_parse_mcp_list_distrusts_inventory_with_any_unparsed_server_row():
    result = acceptance_probe.parse_mcp_list(
        "alpha: server - ✓ Connected\n"
        "em-dash: private-command — ✓ Connected\n",
        probe_rc=0,
    )

    assert result["probe_state"] == "partial_unparseable_output"
    assert result["server_count"] == 1
    assert result["servers"] == [{"name": "alpha", "status": "connected"}]
    assert result["unverified"] is True
    assert result["unverified_reason"] == "unparsed_server_row"
    assert "private-command" not in repr(result)


def test_parse_mcp_list_normalizes_ansi_prefixed_rows():
    result = acceptance_probe.parse_mcp_list(
        "\x1b[32mansi-row\x1b[0m: private-command - ✓ Connected\n",
        probe_rc=0,
    )

    assert result["probe_state"] == "completed"
    assert result["servers"] == [{"name": "ansi-row", "status": "connected"}]
    assert result["unverified"] is False
    assert "private-command" not in repr(result)


def test_parse_mcp_list_canonicalizes_row_order_and_exact_duplicates():
    forward = acceptance_probe.parse_mcp_list(
        "alpha: server - ✓ Connected\n"
        "beta: server - ✗ Failed to connect\n",
        probe_rc=0,
    )
    reversed_with_duplicate = acceptance_probe.parse_mcp_list(
        "beta: server - ✗ Failed to connect\n"
        "alpha: server - ✓ Connected\n"
        "alpha: repeated-server - ✓ Connected\n",
        probe_rc=0,
    )

    assert reversed_with_duplicate == forward
    assert forward["servers"] == [
        {"name": "alpha", "status": "connected"},
        {"name": "beta", "status": "failed"},
    ]
    assert forward["status_counts"]["connected"] == 1
    assert forward["status_counts"]["failed"] == 1


def test_parse_mcp_list_fails_closed_on_contradictory_rows_for_one_server():
    result = acceptance_probe.parse_mcp_list(
        "alpha: first-endpoint - ✓ Connected\n"
        "alpha: duplicate-endpoint - ✓ Connected\n"
        "alpha: conflicting-endpoint - ✗ Failed to connect\n",
        probe_rc=0,
    )

    assert result["probe_state"] == "contradictory_output"
    assert result["server_count"] == 1
    assert result["servers"] == [{"name": "alpha", "status": "unknown"}]
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 1,
    }
    assert result["unverified"] is True
    assert result["unverified_reason"] == "conflicting_statuses_for_server"
    assert "endpoint" not in repr(result)


def test_parse_mcp_list_classifies_auth_required_without_retaining_endpoint():
    output = (
        "oauth-pending: https://oauth.invalid/mcp?code=secret "
        "- ! Needs authentication\n"
    )

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["servers"] == [
        {"name": "oauth-pending", "status": "needs_auth"}
    ]
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 0,
        "needs_auth": 1,
        "disabled": 0,
        "unknown": 0,
    }
    assert "oauth.invalid" not in repr(result)
    assert "secret" not in repr(result)


def test_parse_mcp_list_classifies_disabled_server():
    output = "paused: /usr/local/bin/server --api-key secret - ○ Disabled\n"

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["servers"] == [{"name": "paused", "status": "disabled"}]
    assert result["server_count"] == 1
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 1,
        "unknown": 0,
    }


def test_parse_mcp_list_preserves_unknown_status_as_explicitly_unverified():
    output = "mystery: custom-server --credential secret - ? Starting\n"

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["servers"] == [{"name": "mystery", "status": "unknown"}]
    assert result["server_count"] == 1
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 1,
    }
    assert result["unverified"] is True
    assert result["unverified_reason"] == "unknown_server_status"
    assert "custom-server" not in repr(result)
    assert "secret" not in repr(result)


def test_parse_mcp_list_classifies_only_the_displayed_status_suffix():
    output = """\
arg-word: server --profile connected - ? Starting
url-word: https://example.invalid/failed - ✓ Connected
"""

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["servers"] == [
        {"name": "arg-word", "status": "unknown"},
        {"name": "url-word", "status": "connected"},
    ]
    assert result["status_counts"] == {
        "connected": 1,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 1,
    }
    assert result["unverified"] is True
    assert result["unverified_reason"] == "unknown_server_status"


def test_parse_mcp_list_marks_successful_command_without_output_unverified():
    result = acceptance_probe.parse_mcp_list("", probe_rc=0)

    assert result["probe_rc"] == 0
    assert result["probe_state"] == "no_output"
    assert result["server_count"] is None
    assert result["servers"] is None
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 0,
    }
    assert result["unverified"] is True
    assert result["unverified_reason"] == "no_output"


def test_parse_mcp_list_records_explicit_zero_server_result_as_verified():
    output = "No MCP servers configured. Use `claude mcp add` to add one.\n"

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["probe_state"] == "completed_zero_servers"
    assert result["server_count"] == 0
    assert result["servers"] == []
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 0,
    }
    assert result["unverified"] is False
    assert result["unverified_reason"] is None


def test_parse_mcp_list_requires_a_standalone_zero_server_marker():
    output = (
        "alpha: server --label 'No MCP servers configured' - ✓ Connected\n"
    )

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["probe_state"] == "completed"
    assert result["server_count"] == 1
    assert result["servers"] == [{"name": "alpha", "status": "connected"}]
    assert result["unverified"] is False
    assert result["unverified_reason"] is None


def test_parse_mcp_list_distrusts_zero_marker_that_conflicts_with_rows():
    output = """\
alpha: server - ✓ Connected
No MCP servers configured. Use `claude mcp add` to add one.
"""

    result = acceptance_probe.parse_mcp_list(output, probe_rc=0)

    assert result["probe_state"] == "contradictory_output"
    assert result["server_count"] == 1
    assert result["servers"] == [{"name": "alpha", "status": "connected"}]
    assert result["status_counts"]["connected"] == 1
    assert result["unverified"] is True
    assert result["unverified_reason"] == "zero_server_marker_with_rows"


def test_parse_mcp_list_marks_timeout_without_output_unverified():
    result = acceptance_probe.parse_mcp_list(None, probe_rc=None)

    assert result["probe_rc"] is None
    assert result["probe_state"] == "probe_error"
    assert result["server_count"] is None
    assert result["servers"] is None
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 0,
    }
    assert result["unverified"] is True
    assert result["unverified_reason"] == "probe_not_completed"


def test_probe_mcp_distinguishes_timeout_from_spawn_failure(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["claude", "mcp", "list"], timeout=60)

    monkeypatch.setattr(acceptance_probe.subprocess, "run", timeout)

    timed_out = acceptance_probe.probe_mcp()

    assert timed_out["probe_state"] == "timeout"
    assert timed_out["unverified_reason"] == "timeout"

    def spawn_failure(*_args, **_kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(acceptance_probe.subprocess, "run", spawn_failure)

    spawn_failed = acceptance_probe.probe_mcp()

    assert spawn_failed["probe_state"] == "probe_error"
    assert spawn_failed["unverified_reason"] == "spawn_error"


def test_parse_mcp_list_marks_nonzero_exit_without_output_unverified():
    result = acceptance_probe.parse_mcp_list("", probe_rc=2)

    assert result["probe_rc"] == 2
    assert result["probe_state"] == "command_failed"
    assert result["server_count"] is None
    assert result["servers"] is None
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 0,
    }
    assert result["unverified"] is True
    assert result["unverified_reason"] == "nonzero_exit"


def test_parse_mcp_list_retains_sanitized_rows_but_not_trust_on_nonzero_exit():
    output = "partial: https://private.invalid/mcp?token=secret - ✓ Connected\n"

    result = acceptance_probe.parse_mcp_list(output, probe_rc=3)

    assert result["probe_rc"] == 3
    assert result["probe_state"] == "command_failed"
    assert result["server_count"] == 1
    assert result["servers"] == [{"name": "partial", "status": "connected"}]
    assert result["status_counts"]["connected"] == 1
    assert result["unverified"] is True
    assert result["unverified_reason"] == "nonzero_exit"
    assert "private.invalid" not in repr(result)
    assert "secret" not in repr(result)


def test_parse_mcp_list_does_not_treat_unparseable_output_as_zero_servers():
    result = acceptance_probe.parse_mcp_list(
        "Checking MCP server health...\nUnexpected formatter output\n",
        probe_rc=0,
    )

    assert result["probe_state"] == "unparseable_output"
    assert result["server_count"] is None
    assert result["servers"] is None
    assert result["status_counts"] == {
        "connected": 0,
        "failed": 0,
        "needs_auth": 0,
        "disabled": 0,
        "unknown": 0,
    }
    assert result["unverified"] is True
    assert result["unverified_reason"] == "no_server_rows_or_zero_server_marker"
    assert "Unexpected formatter output" not in repr(result)


def test_probe_mcp_delegates_cli_evidence_to_sanitizing_parser(monkeypatch):
    output = "alpha: https://private.invalid/mcp?token=secret - ✓ Connected"

    def fake_run(command, timeout):
        assert command == ["claude", "mcp", "list"]
        assert timeout == 60
        return 0, output, None

    monkeypatch.setattr(acceptance_probe, "_run_with_outcome", fake_run)

    result = acceptance_probe.probe_mcp()

    assert result == acceptance_probe.parse_mcp_list(output, probe_rc=0)
    assert "private.invalid" not in repr(result)
    assert "secret" not in repr(result)


def test_main_prints_mcp_probe_state_nonzero_counts_and_reason(monkeypatch, capsys):
    mcp = acceptance_probe.parse_mcp_list(
        "broken: server - ✗ Failed to connect\n"
        "oauth: server - ! Needs authentication\n",
        probe_rc=0,
    )
    snapshot = {
        "claude_version": {"effective": "2.1.223"},
        "user_settings": {
            "present": True,
            "hook_events": [],
            "default_mode": "default",
            "permission_allow_count": 0,
            "permission_deny_count": 0,
            "permission_ask_count": 0,
            "enableAllProjectMcpServers": False,
            "sandbox_enabled": False,
        },
        "thinking_budget": {
            "configured": None,
            "model_hint": "opus",
            "effective": "not set",
        },
        "otel": {"effective": "NOT ENABLED"},
        "subagent_limits": {
            "configured_concurrent": None,
            "configured_per_session": None,
            "configured_depth": None,
            "effective": "UNVERIFIED",
            "unverified": True,
        },
        "mcp": mcp,
    }
    monkeypatch.setattr(acceptance_probe, "build_snapshot", lambda _repo: snapshot)

    assert acceptance_probe.main([]) == 0

    output = capsys.readouterr().out
    assert "MCP probe state: completed" in output
    assert "MCP status counts: failed=1, needs_auth=1" in output
    assert "MCP unverified reason: none" in output
    assert "connected=0" not in output
    assert "disabled=0" not in output


def test_subagent_probe_records_all_native_ceilings(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "8")
    monkeypatch.setenv("CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION", "50")
    monkeypatch.setenv("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH", "1")

    result = acceptance_probe.probe_subagent_limits()

    assert result["configured_concurrent"] == "8"
    assert result["configured_per_session"] == "50"
    assert result["configured_depth"] == "1"
    assert result["pinned"] is True
    assert result["unverified"] is True


def test_subagent_probe_does_not_infer_missing_runtime_limits(monkeypatch):
    for name in (
        "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS",
        "CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION",
        "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
    ):
        monkeypatch.delenv(name, raising=False)

    result = acceptance_probe.probe_subagent_limits()

    assert result["configured_concurrent"] is None
    assert result["configured_per_session"] is None
    assert result["configured_depth"] is None
    assert result["pinned"] is False
    assert "UNVERIFIED" in result["effective"]


def test_behavioural_environment_includes_every_subagent_ceiling():
    assert {
        "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS",
        "CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION",
        "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
    }.issubset(acceptance_probe.BEHAVIOURAL_ENV)


def test_settings_probe_reports_exec_form_hook_script_from_args(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/absolute/hooks/run-hook",
                                    "args": ["bash-security-guard.py", "payload.py"],
                                    "timeout": 30,
                                },
                                {
                                    "type": "command",
                                    "command": "C:/Git/bin/bash.exe",
                                    "args": [
                                        "C:/Users/example/.claude/hooks/run-hook",
                                        "windows-guard.py",
                                    ],
                                    "timeout": 30,
                                },
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = acceptance_probe.probe_settings(str(settings))

    assert [
        row["script"] for row in result["hook_registrations"]["PreToolUse"]
    ] == ["bash-security-guard.py", "windows-guard.py"]


def test_settings_probe_keeps_legacy_shell_form_hook_identity(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "python /absolute/hooks/session-start.py "
                                        "--mode strict payload.py"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = acceptance_probe.probe_settings(str(settings))

    assert result["hook_registrations"]["SessionStart"][0]["script"] == "session-start.py"
