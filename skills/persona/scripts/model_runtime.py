"""Model selection and evidence receipts shared by /persona runtime paths."""
from __future__ import annotations

import os

DEFAULT_PERSONA_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_JUDGE_MODEL = "claude-opus-5"
DEFAULT_JUDGE_EFFORT = "high"
UNAVAILABLE = "<unavailable>"
SUPPORTED_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
COVERED_MODELS = frozenset({"claude-fable-5", "claude-mythos-5"})
RETENTION_APPROVAL_ENV_VAR = "PERSONA_COVERED_MODEL_RETENTION_APPROVED"
BASE_MAX_TOKENS = {"persona": 1_000, "judge": 16_000}
ADAPTIVE_THINKING_MIN_TOKENS = 16_000
DEEP_REASONING_MIN_TOKENS = 64_000


def _environment_value(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _require_retention_approval(model: str) -> str:
    if model in COVERED_MODELS and os.environ.get(RETENTION_APPROVAL_ENV_VAR) != "1":
        raise ValueError(
            f"{RETENTION_APPROVAL_ENV_VAR}=1 is required before using {model}; "
            "Fable 5 and Mythos 5 require 30-day retention and are unavailable under ZDR"
        )
    return model


def resolve_persona_model(explicit: str | None = None) -> str:
    model = explicit or _environment_value("PERSONA_MODEL") or DEFAULT_PERSONA_MODEL
    return _require_retention_approval(model)


def resolve_persona_effort(explicit: str | None = None) -> str | None:
    value = explicit or _environment_value("PERSONA_MODEL_EFFORT")
    return _validate_effort(value)


def resolve_judge_model(explicit: str | None = None) -> str:
    model = explicit or _environment_value("PERSONA_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
    return _require_retention_approval(model)


def resolve_judge_effort(explicit: str | None = None) -> str:
    value = explicit or _environment_value("PERSONA_JUDGE_EFFORT") or DEFAULT_JUDGE_EFFORT
    resolved = _validate_effort(value)
    assert resolved is not None
    return resolved


def _validate_effort(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_EFFORTS:
        allowed = ", ".join(sorted(SUPPORTED_EFFORTS))
        raise ValueError(f"effort must be one of: {allowed}")
    return normalized


def runtime_receipt(
    *,
    requested_model: str,
    requested_effort: str | None,
    effective_model: str | None = None,
    stop_reason: str | None = None,
) -> dict:
    """Record request provenance separately from provider observations."""
    observed = effective_model is not None
    fallback: bool | str = (
        effective_model != requested_model if observed else UNAVAILABLE
    )
    return {
        "requested_model": requested_model,
        "requested_model_source": "request_configuration",
        "effective_model": effective_model or UNAVAILABLE,
        "effective_model_source": "response_metadata" if observed else "unavailable",
        "provider": "anthropic",
        "requested_effort": requested_effort or UNAVAILABLE,
        "effective_effort": UNAVAILABLE,
        "effective_effort_source": "unavailable",
        "context_class": UNAVAILABLE,
        "claude_code_version": UNAVAILABLE,
        "fallback": fallback,
        "switch_reason": (
            "provider_response_model_differs" if fallback is True else UNAVAILABLE
        ),
        "refusal": stop_reason == "refusal" if stop_reason is not None else UNAVAILABLE,
        "stop_reason": stop_reason or UNAVAILABLE,
    }


def recommended_max_tokens(
    *,
    workload: str,
    model: str,
    effort: str | None,
) -> int:
    """Leave room for adaptive thinking plus the visible persona output."""
    if workload not in BASE_MAX_TOKENS:
        allowed = ", ".join(sorted(BASE_MAX_TOKENS))
        raise ValueError(f"workload must be one of: {allowed}")
    resolved_effort = _validate_effort(effort)
    base = BASE_MAX_TOKENS[workload]
    if resolved_effort in {"xhigh", "max"} or (
        model in COVERED_MODELS and resolved_effort == "high"
    ):
        return max(base, DEEP_REASONING_MIN_TOKENS)
    if resolved_effort is not None:
        return max(base, ADAPTIVE_THINKING_MIN_TOKENS)
    return base


def message_request(
    *,
    model: str,
    max_tokens: int,
    messages: list[dict],
    effort: str | None,
) -> dict:
    """Build one Messages request without sending unsupported implicit controls."""
    request = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if effort is not None:
        normalized = effort.strip().lower()
        if normalized not in SUPPORTED_EFFORTS:
            allowed = ", ".join(sorted(SUPPORTED_EFFORTS))
            raise ValueError(f"effort must be one of: {allowed}")
        request["output_config"] = {"effort": normalized}
    return request


def cache_matches_runtime(
    result: dict,
    *,
    requested_model: str,
    requested_effort: str | None,
) -> bool:
    """Return true only for successful evidence from the same request lane."""
    receipt = result.get("runtime_receipt")
    if not result.get("ok") or not isinstance(receipt, dict):
        return False
    return (
        receipt.get("requested_model") == requested_model
        and receipt.get("requested_effort") == (requested_effort or UNAVAILABLE)
        and receipt.get("effective_model") == requested_model
        and receipt.get("effective_model_source") == "response_metadata"
        and receipt.get("fallback") is False
    )
