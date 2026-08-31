"""Model-era contracts for the roundtable Anthropic adapter."""

import importlib.util
from pathlib import Path

ADAPTER_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "adapters"
    / "anthropic_adapter.py"
)


def _load_adapter():
    spec = importlib.util.spec_from_file_location("roundtable_anthropic_adapter", ADAPTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_model_is_current_and_runtime_configurable(monkeypatch):
    adapter = _load_adapter()

    monkeypatch.delenv("ROUNDTABLE_ANTHROPIC_MODEL", raising=False)
    assert adapter.DEFAULT_MODEL == "claude-fable-5"
    assert adapter.resolve_model() == "claude-fable-5"

    monkeypatch.setenv("ROUNDTABLE_ANTHROPIC_MODEL", "claude-sonnet-5")
    assert adapter.resolve_model() == "claude-sonnet-5"


def test_effort_defaults_high_and_is_sent_explicitly(monkeypatch):
    adapter = _load_adapter()
    captured = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return {
            "response": {
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-fable-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            "elapsed_s": 0.1,
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ROUNDTABLE_ANTHROPIC_EFFORT", raising=False)
    monkeypatch.setattr(adapter, "http_post_json", fake_post)

    result = adapter.call("review this")

    assert result["ok"] is True
    assert captured["payload"]["output_config"] == {"effort": "high"}
    assert result["runtime_receipt"] == {
        "requested_model": "claude-fable-5",
        "requested_model_source": "request_configuration",
        "effective_model": "claude-fable-5",
        "effective_model_source": "response_metadata",
        "provider": "anthropic",
        "effort": "high",
        "context_class": "<unavailable>",
        "claude_code_version": "<unavailable>",
        "fallback": False,
        "switch_reason": "<unavailable>",
        "refusal": False,
    }


def test_context_class_requires_an_explicit_runtime_observation():
    adapter = _load_adapter()

    unobserved = adapter.runtime_receipt(
        requested_model="claude-opus-5",
        effective_model="claude-opus-5",
        effort="high",
        stop_reason="end_turn",
    )
    observed = adapter.runtime_receipt(
        requested_model="claude-opus-5",
        effective_model="claude-opus-5",
        effort="high",
        stop_reason="end_turn",
        context_class="observed-1m",
    )

    assert unobserved["context_class"] == "<unavailable>"
    assert observed["context_class"] == "observed-1m"


def test_explicit_effort_receipt_overrides_later_ambient_value(monkeypatch):
    adapter = _load_adapter()
    captured = {}

    def fake_post(**kwargs):
        captured.update(kwargs)
        return {
            "response": {
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-fable-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            "elapsed_s": 0.1,
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ROUNDTABLE_ANTHROPIC_EFFORT", "low")
    monkeypatch.setattr(adapter, "http_post_json", fake_post)

    result = adapter.call("review this", effort="xhigh")

    assert result["ok"] is True
    assert result["effort"] == "xhigh"
    assert captured["payload"]["output_config"] == {"effort": "xhigh"}


def test_max_tokens_headroom_tracks_model_and_effort(monkeypatch):
    adapter = _load_adapter()

    monkeypatch.delenv("ROUNDTABLE_ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ROUNDTABLE_ANTHROPIC_EFFORT", raising=False)

    # Default arm is Fable 5 at high effort -> deep-reasoning headroom applies
    # even at the defaults (COVERED_MODELS + high raises the ceiling to 64K).
    assert adapter.recommended_max_tokens("main") == 64_000
    assert adapter.recommended_max_tokens("prereg") == 64_000

    # A non-covered model at high effort keeps the base workload budgets.
    monkeypatch.setenv("ROUNDTABLE_ANTHROPIC_MODEL", "claude-opus-5")
    assert adapter.recommended_max_tokens("main") == 16_000
    assert adapter.recommended_max_tokens("jrh") == 16_000

    # xhigh raises the ceiling on any supported arm.
    monkeypatch.setenv("ROUNDTABLE_ANTHROPIC_EFFORT", "xhigh")
    assert adapter.recommended_max_tokens("main") == 64_000


def test_http_200_refusal_is_a_typed_failure(monkeypatch):
    adapter = _load_adapter()

    def fake_post(**_kwargs):
        return {
            "response": {
                "content": [],
                "model": "claude-fable-5",
                "stop_reason": "refusal",
                "stop_details": {
                    "type": "refusal",
                    "category": "cyber",
                    "explanation": "declined",
                },
                "usage": {"input_tokens": 5, "output_tokens": 0},
            },
            "elapsed_s": 0.2,
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(adapter, "http_post_json", fake_post)

    result = adapter.call("review this")

    assert result["ok"] is False
    assert result["error_type"] == "refusal"
    assert result["stop_reason"] == "refusal"
    assert result["stop_details"]["category"] == "cyber"
    assert result["runtime_receipt"]["refusal"] is True
    assert result["runtime_receipt"]["effective_model"] == "claude-fable-5"


def test_max_tokens_is_incomplete_not_a_success(monkeypatch):
    adapter = _load_adapter()

    def fake_post(**_kwargs):
        return {
            "response": {
                "content": [{"type": "text", "text": "partial assessment"}],
                "model": "claude-fable-5",
                "stop_reason": "max_tokens",
                "usage": {"input_tokens": 5, "output_tokens": 4000},
            },
            "elapsed_s": 1.0,
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(adapter, "http_post_json", fake_post)

    result = adapter.call("review this", max_tokens=4000)

    assert result["ok"] is False
    assert result["error_type"] == "incomplete_response"
    assert result["stop_reason"] == "max_tokens"
    assert result["runtime_receipt"]["refusal"] is False


def test_context_window_limit_is_incomplete_not_a_success(monkeypatch):
    adapter = _load_adapter()

    def fake_post(**_kwargs):
        return {
            "response": {
                "content": [{"type": "text", "text": "partial assessment"}],
                "model": "claude-fable-5",
                "stop_reason": "model_context_window_exceeded",
                "usage": {"input_tokens": 999_000, "output_tokens": 1_000},
            },
            "elapsed_s": 1.0,
        }

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(adapter, "http_post_json", fake_post)

    result = adapter.call("review this")

    assert result["ok"] is False
    assert result["error_type"] == "incomplete_response"
    assert result["stop_reason"] == "model_context_window_exceeded"


def test_covered_models_need_no_retention_env_gate(monkeypatch):
    """Retired 2026-08-19: org 30-day retention is confirmed, so covered models
    (Fable/Mythos) pass configuration validation without any approval env var.
    A retention regression surfaces as the API's own 400, not a local gate."""
    adapter = _load_adapter()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ROUNDTABLE_ANTHROPIC_MODEL", "claude-mythos-5")
    monkeypatch.delenv(
        "ROUNDTABLE_COVERED_MODEL_RETENTION_APPROVED", raising=False
    )
    monkeypatch.setattr(
        adapter,
        "http_post_json",
        lambda **_kwargs: {
            "response": {
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-mythos-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            "elapsed_s": 0.1,
        },
    )

    result = adapter.call("review this")

    assert result["ok"] is True
    assert result["model"] == "claude-mythos-5"


def test_unsupported_model_fails_before_network(monkeypatch):
    adapter = _load_adapter()

    def should_not_call(**_kwargs):
        raise AssertionError("network should not be called for invalid configuration")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ROUNDTABLE_ANTHROPIC_MODEL", "claude-opus-4-8")
    monkeypatch.setattr(adapter, "http_post_json", should_not_call)

    result = adapter.call("review this")

    assert result["ok"] is False
    assert result["error_type"] == "configuration"
    assert result["requested_model"] == "claude-opus-4-8"
    assert result["runtime_receipt"]["effective_model"] == "<unavailable>"
    assert result["runtime_receipt"]["context_class"] == "<unavailable>"
    assert result["runtime_receipt"]["fallback"] == "<unavailable>"
    assert result["runtime_receipt"]["refusal"] == "<unavailable>"


def test_pre_response_failures_still_return_a_complete_nested_receipt(monkeypatch):
    adapter = _load_adapter()
    required = {
        "requested_model",
        "requested_model_source",
        "effective_model",
        "effective_model_source",
        "provider",
        "effort",
        "context_class",
        "claude_code_version",
        "fallback",
        "switch_reason",
        "refusal",
    }

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    missing_key = adapter.call("review this")

    assert missing_key["ok"] is False
    assert required <= missing_key["runtime_receipt"].keys()
    assert missing_key["runtime_receipt"]["effective_model"] == "<unavailable>"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        adapter,
        "http_post_json",
        lambda **_kwargs: {
            "error": "network unavailable",
            "elapsed_s": 0.1,
            "retried": True,
        },
    )
    transport_failure = adapter.call("review this")

    assert transport_failure["ok"] is False
    assert required <= transport_failure["runtime_receipt"].keys()
    assert transport_failure["runtime_receipt"]["effective_model"] == "<unavailable>"


def test_no_text_failure_records_observed_model_and_non_refusal(monkeypatch):
    adapter = _load_adapter()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        adapter,
        "http_post_json",
        lambda **_kwargs: {
            "response": {
                "content": [],
                "model": "claude-fable-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
            "elapsed_s": 0.1,
        },
    )

    result = adapter.call("review this")

    assert result["ok"] is False
    assert result["runtime_receipt"]["effective_model"] == "claude-fable-5"
    assert result["runtime_receipt"]["refusal"] is False


def test_provider_model_switch_is_typed_not_an_unqualified_success(monkeypatch):
    adapter = _load_adapter()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        adapter,
        "http_post_json",
        lambda **_kwargs: {
            "response": {
                "content": [{"type": "text", "text": "fallback answer"}],
                "model": "claude-sonnet-5",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            "elapsed_s": 0.1,
        },
    )

    result = adapter.call("review this", model="claude-opus-5")

    assert result["ok"] is False
    assert result["error_type"] == "model_switch"
    assert result["runtime_receipt"]["fallback"] is True
    assert result["runtime_receipt"]["effective_model"] == "claude-sonnet-5"
