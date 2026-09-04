"""Model selection and evidence receipts shared by /persona runtime paths."""
from __future__ import annotations

import json
import os
from pathlib import Path

# contracts/model-capabilities.json states which ids are current, which tier
# (Claude Code's moving alias: fable, mythos, opus, sonnet, haiku) each belongs
# to, and which are Covered Models. skills/persona/scripts sits three levels
# below the repository root. Marketplace bundles ship the skill without
# contracts/, so every lookup below degrades explicitly when the file is absent.
CAPABILITIES_CONTRACT = (
    Path(__file__).resolve().parents[3] / "contracts" / "model-capabilities.json"
)
# Claude Code's moving aliases; without the contract they cannot be resolved.
MOVING_ALIASES = frozenset({"default", "fable", "mythos", "opus", "sonnet", "haiku"})

DEFAULT_PERSONA_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_JUDGE_MODEL = "claude-opus-5"
DEFAULT_JUDGE_EFFORT = "high"
UNAVAILABLE = "<unavailable>"
SUPPORTED_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
RETENTION_APPROVAL_ENV_VAR = "PERSONA_COVERED_MODEL_RETENTION_APPROVED"
BASE_MAX_TOKENS = {"persona": 1_000, "judge": 16_000}
ADAPTIVE_THINKING_MIN_TOKENS = 16_000
DEEP_REASONING_MIN_TOKENS = 64_000


def _environment_value(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _contract() -> dict | None:
    """The capabilities contract, or None where the repository is not checked out."""
    try:
        return json.loads(CAPABILITIES_CONTRACT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def covered_models() -> frozenset[str]:
    """Covered Models (30-day retention, unavailable under ZDR) per the contract."""
    contract = _contract()
    if contract is None:
        return frozenset()
    return frozenset(
        model_id
        for row in contract["models"]
        if row["retention"]["covered_model"]
        for model_id in (row["id"], row.get("dated_snapshot"))
        if model_id
    )


def _is_covered(model: str) -> bool:
    if _contract() is None:
        # No contract on disk: fall back to the families the vendor designates as
        # Covered Models (api-and-data-retention, verified 2026-09-04: every Fable
        # and Mythos model). Wrong only in the safe direction (an approval prompt).
        lowered = model.lower()
        return "fable" in lowered or "mythos" in lowered
    return model in covered_models()


def resolve_model_id(requested: str) -> str:
    """The exact API model id for an operator-supplied model value.

    A tier alias (`haiku`, `opus`, ...) resolves to the contract's current row for
    that tier, pinned to its dated snapshot when the contract records one. An exact
    current id (or dated snapshot) passes through. Anything else -- a superseded id,
    Claude Code's `default`, a provider-prefixed id, a typo -- raises ValueError
    here, before a client exists, instead of surfacing as a 404 after the run
    directory and fixture were already prepared.
    """
    value = requested.strip()
    contract = _contract()
    if contract is None:
        if value.lower() in MOVING_ALIASES:
            raise ValueError(
                f"model alias {value!r} cannot be resolved: {CAPABILITIES_CONTRACT} is not "
                "available (marketplace bundles omit contracts/); pass the exact API model id"
            )
        return value  # nothing to validate against here; the API is the oracle
    current = {row["id"]: row for row in contract["models"]}
    by_tier = {row["tier"]: row for row in contract["models"]}
    snapshots = {row["dated_snapshot"] for row in contract["models"] if row.get("dated_snapshot")}
    if value.lower() in by_tier:
        row = by_tier[value.lower()]
        return row.get("dated_snapshot") or row["id"]
    if value in current or value in snapshots:
        return value
    aliases = ", ".join(sorted(by_tier))
    current_ids = ", ".join(sorted(current))
    superseded = {row["id"]: row["superseded_by"] for row in contract["superseded"]}
    if value in superseded:
        raise ValueError(
            f"{value} is superseded by {superseded[value]} in {CAPABILITIES_CONTRACT.name}; "
            f"pass a current model id ({current_ids}) or a tier alias ({aliases})"
        )
    raise ValueError(
        f"unknown model {value!r}: pass a current API model id ({current_ids}) or a tier "
        f"alias ({aliases}) from {CAPABILITIES_CONTRACT.name}"
    )


def _require_retention_approval(model: str) -> str:
    if _is_covered(model) and os.environ.get(RETENTION_APPROVAL_ENV_VAR) != "1":
        raise ValueError(
            f"{RETENTION_APPROVAL_ENV_VAR}=1 is required before using {model}; "
            "Covered Models (the Fable and Mythos families) require 30-day retention "
            "and are unavailable under ZDR"
        )
    return model


def resolve_persona_model(explicit: str | None = None) -> str:
    requested = explicit or _environment_value("PERSONA_MODEL") or DEFAULT_PERSONA_MODEL
    return _require_retention_approval(resolve_model_id(requested))


def resolve_persona_effort(explicit: str | None = None) -> str | None:
    value = explicit or _environment_value("PERSONA_MODEL_EFFORT")
    return _validate_effort(value)


def resolve_judge_model(explicit: str | None = None) -> str:
    requested = explicit or _environment_value("PERSONA_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
    return _require_retention_approval(resolve_model_id(requested))


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
        _is_covered(model) and resolved_effort == "high"
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
