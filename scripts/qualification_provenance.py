"""Shared provenance helpers for current-model qualification.

Frozen historical baselines keep their original records. New keyed executions
use the separate ``current qualification`` lane and must name an exact model.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping


EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
MOVING_ALIASES = {"default", "opus", "sonnet", "haiku", "fable"}


def _canonical_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-stable copy, rejecting non-reproducible config values."""

    try:
        return json.loads(json.dumps(dict(value), sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise ValueError("grader_config must contain JSON-serializable values") from exc


def _record_hash(record: Mapping[str, Any]) -> str:
    stable = {key: value for key, value in record.items() if key != "provenance_hash"}
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _response_field(response: Any, name: str) -> Any:
    if isinstance(response, Mapping):
        if name in response:
            return response[name]
        message = response.get("message")
        if isinstance(message, Mapping):
            return message.get(name)
        return None
    return getattr(response, name, None)


def _observed_trial_provenance(
    *,
    requested_model: str,
    effective_models: Iterable[str],
    provider: str,
    grader_config: Mapping[str, Any],
    stop_reasons: Iterable[str],
    refused: bool | None,
    response_state: str,
) -> dict[str, Any]:
    requested = exact_model_id(requested_model)
    effective = sorted({model.strip() for model in effective_models if model.strip()})
    if not effective:
        effective_model = "unavailable"
        model_run_state = "invalid"
        fallback_state = "unknown"
    elif len(effective) == 1:
        effective_model = effective[0]
        model_run_state = "consistent"
        fallback_state = "used" if effective_model != requested else "not_used"
    else:
        effective_model = "mixed"
        model_run_state = "mixed"
        fallback_state = "used" if any(model != requested for model in effective) else "not_used"
    stable: dict[str, Any] = {
        "requested_model": requested,
        "effective_model": effective_model,
        "effective_models": effective,
        "provider": provider,
        "fallback_state": fallback_state,
        "refusal_state": (
            "unknown" if refused is None else "refused" if refused else "not_refused"
        ),
        "model_run_state": model_run_state,
        "response_state": response_state,
        "stop_reasons": sorted({reason for reason in stop_reasons if reason}),
        "grader_config": _canonical_mapping(grader_config),
    }
    stable["provenance_hash"] = _record_hash(stable)
    return stable


def response_trial_provenance(
    *,
    response: Any,
    requested_model: str,
    provider: str,
    grader_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Record the model and refusal state returned by one provider response."""

    effective = _response_field(response, "model")
    if not isinstance(effective, str) or not effective.strip():
        raise ValueError("provider response missing effective model")
    stop_reason = str(_response_field(response, "stop_reason") or "unknown")
    content = _response_field(response, "content") or []
    content_refusal = any(
        (block.get("type") if isinstance(block, Mapping) else getattr(block, "type", None))
        == "refusal"
        for block in content
    )
    return _observed_trial_provenance(
        requested_model=requested_model,
        effective_models=[effective],
        provider=provider,
        grader_config=grader_config,
        stop_reasons=[stop_reason],
        refused=stop_reason.lower() == "refusal" or content_refusal,
        response_state="received",
    )


def claude_cli_trial_provenance(
    *,
    output: str,
    requested_model: str,
    provider: str,
    grader_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive model provenance from one Claude Code stream-json transcript."""

    models: list[str] = []
    stop_reasons: list[str] = []
    refused = False
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, Mapping):
            continue
        candidates = [event]
        message = event.get("message")
        if isinstance(message, Mapping):
            candidates.append(message)
        for candidate in candidates:
            model = candidate.get("model")
            if isinstance(model, str) and model.strip():
                models.append(model.strip())
            reason = candidate.get("stop_reason")
            if isinstance(reason, str) and reason:
                stop_reasons.append(reason)
                refused = refused or reason.lower() == "refusal"
            content = candidate.get("content")
            if isinstance(content, list):
                refused = refused or any(
                    isinstance(block, Mapping) and block.get("type") == "refusal"
                    for block in content
                )
    return _observed_trial_provenance(
        requested_model=requested_model,
        effective_models=models,
        provider=provider,
        grader_config=grader_config,
        stop_reasons=stop_reasons,
        refused=refused if models else None,
        response_state="received" if models else "invalid",
    )


def failed_trial_provenance(
    *,
    requested_model: str,
    provider: str,
    grader_config: Mapping[str, Any],
    failure: str,
) -> dict[str, Any]:
    """Create an explicitly invalid trial record when no response was received."""

    trial = _observed_trial_provenance(
        requested_model=requested_model,
        effective_models=[],
        provider=provider,
        grader_config=grader_config,
        stop_reasons=[],
        refused=None,
        response_state="error",
    )
    trial.pop("provenance_hash")
    trial["failure"] = failure[:200]
    trial["provenance_hash"] = _record_hash(trial)
    return trial


def exact_model_id(value: str) -> str:
    """Reject moving aliases in qualification records."""

    value = value.strip()
    if not value or value.lower() in MOVING_ALIASES or not value.startswith("claude-"):
        raise argparse.ArgumentTypeError(
            "current qualification requires an exact Claude model id, not an alias"
        )
    return value


def detect_claude_cli_version() -> str:
    """Return the local CLI version without making a model request."""

    executable = shutil.which("claude")
    if not executable:
        return "unavailable"
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    value = (proc.stdout or proc.stderr).strip().splitlines()
    return value[0][:200] if value else "unavailable"


def qualification_metadata(
    *,
    requested_model: str,
    effort: str,
    provider: str,
    trial_provenance: Iterable[Mapping[str, Any]],
    grader_config: Mapping[str, Any],
    config_paths: Iterable[Path],
    cli_version: str | None = None,
) -> dict[str, Any]:
    """Build a reproducible provenance tuple for a qualification run."""

    requested = exact_model_id(requested_model)
    grader = _canonical_mapping(grader_config)
    trials = [_canonical_mapping(trial) for trial in trial_provenance]
    for trial in trials:
        reported_hash = str(trial.get("provenance_hash", ""))
        if not reported_hash or not hmac.compare_digest(reported_hash, _record_hash(trial)):
            raise ValueError("trial provenance_hash does not match trial evidence")
        if trial.get("requested_model") != requested:
            raise ValueError("trial requested_model does not match qualification request")
        if trial.get("provider") != provider:
            raise ValueError("trial provider does not match qualification provider")
        if trial.get("grader_config") != grader:
            raise ValueError("trial grader_config does not match qualification grader_config")

    effective_models = sorted(
        {
            model
            for trial in trials
            for model in trial.get("effective_models", [])
            if isinstance(model, str) and model and model != "unavailable"
        }
    )
    response_states = {str(trial.get("response_state", "invalid")) for trial in trials}
    qualification_status = (
        "valid" if trials and response_states == {"received"} and effective_models else "invalid"
    )
    if not effective_models:
        effective_model = "unavailable"
        model_run_state = "invalid"
    elif len(effective_models) == 1:
        effective_model = effective_models[0]
        model_run_state = "consistent"
    else:
        effective_model = "mixed"
        model_run_state = "mixed"

    def aggregate_state(name: str, *, empty: str = "unknown") -> str:
        values = {str(trial.get(name, empty)) for trial in trials}
        if not values:
            return empty
        return next(iter(values)) if len(values) == 1 else "mixed"

    stable: dict[str, Any] = {
        "qualification_lane": "current qualification",
        "qualification_status": qualification_status,
        "requested_model": requested,
        "effective_model": effective_model,
        "effective_models": effective_models,
        "model_run_state": model_run_state,
        "fallback_state": aggregate_state("fallback_state"),
        "refusal_state": aggregate_state("refusal_state"),
        "response_state": aggregate_state("response_state", empty="invalid"),
        "trial_count": len(trials),
        "trial_provenance_hashes": sorted(
            str(trial.get("provenance_hash", "missing")) for trial in trials
        ),
        "grader_config": grader,
        "effort": effort,
        "provider": provider,
        "claude_cli_version": cli_version or detect_claude_cli_version(),
    }
    digest = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    for raw_path in sorted((Path(path) for path in config_paths), key=lambda p: str(p)):
        digest.update(str(raw_path).encode("utf-8"))
        try:
            digest.update(raw_path.read_bytes())
        except OSError as exc:
            digest.update(f"UNREADABLE:{type(exc).__name__}".encode("utf-8"))
    return {**stable, "provenance_hash": digest.hexdigest()}


def add_qualification_arguments(
    parser: argparse.ArgumentParser,
    *,
    require_model: bool,
) -> None:
    """Add the common current-qualification CLI contract."""

    parser.add_argument(
        "--model",
        required=require_model,
        type=exact_model_id,
        help="exact Claude model id for current qualification (moving aliases rejected)",
    )
    parser.add_argument("--effort", choices=EFFORT_LEVELS, default="high")
    parser.add_argument("--provider", default="anthropic-api")
