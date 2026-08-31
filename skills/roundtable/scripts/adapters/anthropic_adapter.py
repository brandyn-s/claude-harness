"""Anthropic API adapter for the roundtable's configured Claude model."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import http_post_json  # noqa: E402

DEFAULT_MODEL = "claude-fable-5"
MODEL_ENV_VAR = "ROUNDTABLE_ANTHROPIC_MODEL"
SUPPORTED_MODELS = frozenset({
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-sonnet-5",
})
# Fable/Mythos require 30-day retention (unavailable under ZDR). The org's
# 30-day retention was user-confirmed 2026-08-19, so the former per-run
# ROUNDTABLE_COVERED_MODEL_RETENTION_APPROVED gate is retired: an org whose
# retention configuration regresses gets a 400 from the API, which call()
# already surfaces as a typed transport_or_api failure.
COVERED_MODELS = frozenset({"claude-fable-5", "claude-mythos-5"})
DEFAULT_EFFORT = "high"
EFFORT_ENV_VAR = "ROUNDTABLE_ANTHROPIC_EFFORT"
SUPPORTED_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
BASE_MAX_TOKENS = {
    "main": 16_000,
    "prereg": 8_000,
    "synthesis": 16_000,
    "jrh": 16_000,
}
DEEP_REASONING_MIN_TOKENS = 64_000
UNAVAILABLE = "<unavailable>"
TOKEN_PRICING_USD_PER_MTOK = {
    "claude-fable-5": {"in": 10.0, "out": 50.0},
    "claude-mythos-5": {"in": 10.0, "out": 50.0},
    "claude-opus-5": {"in": 5.0, "out": 25.0},
    # Conservative standard rate. A time-limited introductory rate may apply;
    # do not use the estimator as a billing oracle.
    "claude-sonnet-5": {"in": 3.0, "out": 15.0},
}


def resolve_model() -> str:
    """Resolve the requested model at call time so per-run overrides are visible."""
    model = os.environ.get(MODEL_ENV_VAR, "").strip() or DEFAULT_MODEL
    if model not in SUPPORTED_MODELS:
        allowed = ", ".join(sorted(SUPPORTED_MODELS))
        raise ValueError(f"{MODEL_ENV_VAR} must be one of: {allowed}")
    return model


def pricing_for_model(model: str) -> dict[str, float]:
    """Return conservative base-token pricing for a supported current model."""
    return TOKEN_PRICING_USD_PER_MTOK[model]


def resolve_effort(explicit: str | None = None) -> str:
    """Resolve and validate effort rather than silently sending an invalid value."""
    effort = (
        explicit.strip().lower()
        if explicit is not None
        else os.environ.get(EFFORT_ENV_VAR, "").strip().lower() or DEFAULT_EFFORT
    )
    if effort not in SUPPORTED_EFFORTS:
        allowed = ", ".join(sorted(SUPPORTED_EFFORTS))
        raise ValueError(f"{EFFORT_ENV_VAR} must be one of: {allowed}")
    return effort


def recommended_max_tokens(
    workload: str,
    *,
    model: str | None = None,
    effort: str | None = None,
) -> int:
    """Return model/effort-aware headroom for thinking plus visible output."""
    if workload not in BASE_MAX_TOKENS:
        allowed = ", ".join(sorted(BASE_MAX_TOKENS))
        raise ValueError(f"workload must be one of: {allowed}")

    requested_model = model or resolve_model()
    if requested_model not in SUPPORTED_MODELS:
        allowed = ", ".join(sorted(SUPPORTED_MODELS))
        raise ValueError(f"model must be one of: {allowed}")

    requested_effort = resolve_effort(effort)
    base = BASE_MAX_TOKENS[workload]
    if requested_effort in {"xhigh", "max"} or (
        requested_model in COVERED_MODELS and requested_effort == "high"
    ):
        return max(base, DEEP_REASONING_MIN_TOKENS)
    return base


def runtime_receipt(
    *,
    requested_model: str,
    effort: str | None,
    effective_model: str | None = None,
    stop_reason: str | None = None,
    context_class: str | None = None,
) -> dict:
    """Build a receipt; context class is recorded only when explicitly observed."""
    effective = effective_model or UNAVAILABLE
    fallback = (
        effective_model != requested_model
        if effective_model is not None
        else UNAVAILABLE
    )
    return {
        "requested_model": requested_model,
        "requested_model_source": "request_configuration",
        "effective_model": effective,
        "effective_model_source": (
            "response_metadata" if effective_model is not None else "unavailable"
        ),
        "provider": "anthropic",
        "effort": effort or UNAVAILABLE,
        "context_class": context_class or UNAVAILABLE,
        "claude_code_version": UNAVAILABLE,
        "fallback": fallback,
        "switch_reason": (
            "provider_response_model_differs" if fallback is True else UNAVAILABLE
        ),
        "refusal": stop_reason == "refusal" if stop_reason is not None else UNAVAILABLE,
    }


def call(prompt: str, max_tokens: int = 4000,
         model: str | None = None,
         effort: str | None = None,
         retry_on_transient: bool = True) -> dict:
    requested_model = model or os.environ.get(MODEL_ENV_VAR, "").strip() or DEFAULT_MODEL
    requested_effort = None
    try:
        if requested_model not in SUPPORTED_MODELS:
            allowed = ", ".join(sorted(SUPPORTED_MODELS))
            raise ValueError(f"model must be one of: {allowed}")
        requested_effort = resolve_effort(effort)
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "requested_model": requested_model,
            "error_type": "configuration",
            "runtime_receipt": runtime_receipt(
                requested_model=requested_model,
                effort=requested_effort,
            ),
        }
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "ANTHROPIC_API_KEY not set",
            "requested_model": requested_model,
            "effort": requested_effort,
            "error_type": "configuration",
            "runtime_receipt": runtime_receipt(
                requested_model=requested_model,
                effort=requested_effort,
            ),
        }
    result = http_post_json(
        url="https://api.anthropic.com/v1/messages",
        payload={
            "model": requested_model,
            "max_tokens": max_tokens,
            "output_config": {"effort": requested_effort},
            "messages": [{"role": "user", "content": prompt}],
        },
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        retry_on_transient=retry_on_transient,
    )

    if "error" in result:
        return {
            "ok": False,
            "error": result["error"],
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
            "requested_model": requested_model,
            "effort": requested_effort,
            "error_type": "transport_or_api",
            "runtime_receipt": runtime_receipt(
                requested_model=requested_model,
                effort=requested_effort,
            ),
        }

    data = result["response"]
    stop_reason = data.get("stop_reason")
    effective_model = data.get("model")
    if effective_model is not None and effective_model != requested_model:
        return {
            "ok": False,
            "error": (
                "Anthropic response model differed from the requested panel arm: "
                f"requested={requested_model}, effective={effective_model}"
            ),
            "error_type": "model_switch",
            "stop_reason": stop_reason,
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
            "requested_model": requested_model,
            "effort": requested_effort,
            "model": effective_model,
            "runtime_receipt": runtime_receipt(
                requested_model=requested_model,
                effective_model=effective_model,
                effort=requested_effort,
                stop_reason=stop_reason,
            ),
        }
    if stop_reason == "refusal":
        details = data.get("stop_details") or {"type": "refusal"}
        return {
            "ok": False,
            "error": details.get("explanation") or "Anthropic model refused the request",
            "error_type": "refusal",
            "stop_reason": stop_reason,
            "stop_details": details,
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
            "requested_model": requested_model,
            "effort": requested_effort,
            "model": effective_model,
            "runtime_receipt": runtime_receipt(
                requested_model=requested_model,
                effective_model=effective_model,
                effort=requested_effort,
                stop_reason=stop_reason,
            ),
        }

    if stop_reason in {"max_tokens", "model_context_window_exceeded"}:
        reason = (
            "max_tokens"
            if stop_reason == "max_tokens"
            else "the model context window"
        )
        return {
            "ok": False,
            "error": f"Anthropic response exhausted {reason} before completing",
            "error_type": "incomplete_response",
            "stop_reason": stop_reason,
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
            "requested_model": requested_model,
            "effort": requested_effort,
            "model": effective_model,
            "runtime_receipt": runtime_receipt(
                requested_model=requested_model,
                effective_model=effective_model,
                effort=requested_effort,
                stop_reason=stop_reason,
            ),
        }

    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    )
    if not text:
        return {
            "ok": False,
            "error": f"Anthropic response had no text content (stop_reason={stop_reason!r})",
            "error_type": "incomplete_response",
            "stop_reason": stop_reason,
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
            "requested_model": requested_model,
            "effort": requested_effort,
            "model": effective_model,
            "runtime_receipt": runtime_receipt(
                requested_model=requested_model,
                effective_model=effective_model,
                effort=requested_effort,
                stop_reason=stop_reason,
            ),
        }
    if effective_model is None:
        return {
            "ok": False,
            "error": "Anthropic response omitted effective model metadata",
            "error_type": "missing_runtime_metadata",
            "stop_reason": stop_reason,
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
            "requested_model": requested_model,
            "effort": requested_effort,
            "runtime_receipt": runtime_receipt(
                requested_model=requested_model,
                effort=requested_effort,
                stop_reason=stop_reason,
            ),
        }
    usage = data.get("usage", {})
    return {
        "ok": True,
        "text": text,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "elapsed_s": result["elapsed_s"],
        "model": effective_model,
        "requested_model": requested_model,
        "effort": requested_effort,
        "stop_reason": stop_reason,
        "retried": result.get("retried", False),
        "runtime_receipt": runtime_receipt(
            requested_model=requested_model,
            effective_model=effective_model,
            effort=requested_effort,
            stop_reason=stop_reason,
        ),
    }
