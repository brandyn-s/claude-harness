"""Tests for current-qualification provenance shared by live harnesses."""

import argparse
import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import qualification_provenance as provenance


REPO = Path(__file__).resolve().parents[1]


def test_response_trial_records_effective_model_and_grader_hash():
    response = SimpleNamespace(
        model="claude-opus-5-20260801",
        stop_reason="refusal",
        content=[],
    )
    grader = {"primary_metric": "accuracy", "minimum_delta": 0.05}

    first = provenance.response_trial_provenance(
        response=response,
        requested_model="claude-fable-5-20260715",
        provider="anthropic-api",
        grader_config=grader,
    )

    assert first["requested_model"] == "claude-fable-5-20260715"
    assert first["effective_model"] == "claude-opus-5-20260801"
    assert first["effective_models"] == ["claude-opus-5-20260801"]
    assert first["provider"] == "anthropic-api"
    assert first["fallback_state"] == "used"
    assert first["refusal_state"] == "refused"
    assert first["model_run_state"] == "consistent"
    assert first["response_state"] == "received"
    assert first["grader_config"] == grader
    assert len(first["provenance_hash"]) == 64

    changed_grader = provenance.response_trial_provenance(
        response=response,
        requested_model="claude-fable-5-20260715",
        provider="anthropic-api",
        grader_config={"primary_metric": "accuracy", "minimum_delta": 0.10},
    )
    assert first["provenance_hash"] != changed_grader["provenance_hash"]


def test_metadata_records_runtime_tuple_and_hashes_configuration(tmp_path):
    config = tmp_path / "fixture.json"
    config.write_text('{"version": 1}', encoding="utf-8")
    grader = {"primary_metric": "accuracy", "minimum_delta": 0.05}
    trial = provenance.response_trial_provenance(
        response=SimpleNamespace(
            model="claude-fable-5-20260715",
            stop_reason="end_turn",
            content=[],
        ),
        requested_model="claude-fable-5-20260715",
        provider="anthropic-api",
        grader_config=grader,
    )

    first = provenance.qualification_metadata(
        requested_model="claude-fable-5-20260715",
        effort="high",
        provider="anthropic-api",
        trial_provenance=[trial],
        grader_config=grader,
        config_paths=[config],
        cli_version="2.1.223",
    )
    assert first["qualification_lane"] == "current qualification"
    assert first["requested_model"] == "claude-fable-5-20260715"
    assert first["effective_model"] == "claude-fable-5-20260715"
    assert first["effective_models"] == ["claude-fable-5-20260715"]
    assert first["model_run_state"] == "consistent"
    assert first["qualification_status"] == "valid"
    assert first["fallback_state"] == "not_used"
    assert first["refusal_state"] == "not_refused"
    assert first["trial_count"] == 1
    assert first["grader_config"] == grader
    assert first["effort"] == "high"
    assert first["provider"] == "anthropic-api"
    assert first["claude_cli_version"] == "2.1.223"
    assert len(first["provenance_hash"]) == 64

    config.write_text('{"version": 2}', encoding="utf-8")
    second = provenance.qualification_metadata(
        requested_model="claude-fable-5-20260715",
        effort="high",
        provider="anthropic-api",
        trial_provenance=[trial],
        grader_config=grader,
        config_paths=[config],
        cli_version="2.1.223",
    )
    assert first["provenance_hash"] != second["provenance_hash"]


def test_metadata_marks_mixed_effective_models_explicitly_and_hashes_stably(tmp_path):
    grader = {"primary_metric": "accuracy"}
    requested = "claude-fable-5-20260715"
    first_trial = provenance.response_trial_provenance(
        response=SimpleNamespace(model=requested, stop_reason="end_turn", content=[]),
        requested_model=requested,
        provider="anthropic-api",
        grader_config=grader,
    )
    fallback_trial = provenance.response_trial_provenance(
        response=SimpleNamespace(
            model="claude-sonnet-5-20260729",
            stop_reason="end_turn",
            content=[],
        ),
        requested_model=requested,
        provider="anthropic-api",
        grader_config=grader,
    )

    mixed = provenance.qualification_metadata(
        requested_model=requested,
        effort="high",
        provider="anthropic-api",
        trial_provenance=[first_trial, fallback_trial],
        grader_config=grader,
        config_paths=[tmp_path / "missing-config"],
        cli_version="2.1.223",
    )
    reordered = provenance.qualification_metadata(
        requested_model=requested,
        effort="high",
        provider="anthropic-api",
        trial_provenance=[fallback_trial, first_trial],
        grader_config=grader,
        config_paths=[tmp_path / "missing-config"],
        cli_version="2.1.223",
    )

    assert mixed["qualification_status"] == "valid"
    assert mixed["effective_model"] == "mixed"
    assert mixed["effective_models"] == [requested, "claude-sonnet-5-20260729"]
    assert mixed["model_run_state"] == "mixed"
    assert mixed["fallback_state"] == "mixed"
    assert mixed["provenance_hash"] == reordered["provenance_hash"]


def test_cli_trial_derives_mixed_fallback_and_refusal_from_jsonl():
    output = "\n".join(
        [
            json.dumps(
                {
                    "type": "system",
                    "subtype": "init",
                    "model": "claude-fable-5-20260715",
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "model": "claude-sonnet-5-20260729",
                        "stop_reason": "refusal",
                        "content": [{"type": "refusal"}],
                    },
                }
            ),
        ]
    )

    trial = provenance.claude_cli_trial_provenance(
        output=output,
        requested_model="claude-fable-5-20260715",
        provider="claude-cli",
        grader_config={"metric": "activation_rate"},
    )

    assert trial["effective_model"] == "mixed"
    assert trial["effective_models"] == [
        "claude-fable-5-20260715",
        "claude-sonnet-5-20260729",
    ]
    assert trial["model_run_state"] == "mixed"
    assert trial["fallback_state"] == "used"
    assert trial["refusal_state"] == "refused"
    assert trial["response_state"] == "received"


def test_missing_response_model_is_invalid_not_requested_model():
    grader = {"metric": "activation_rate"}
    trial = provenance.claude_cli_trial_provenance(
        output=json.dumps({"type": "result", "subtype": "error"}),
        requested_model="claude-fable-5-20260715",
        provider="claude-cli",
        grader_config=grader,
    )

    assert trial["effective_model"] == "unavailable"
    assert trial["effective_models"] == []
    assert trial["model_run_state"] == "invalid"
    assert trial["fallback_state"] == "unknown"
    assert trial["refusal_state"] == "unknown"
    assert trial["response_state"] == "invalid"

    aggregate = provenance.qualification_metadata(
        requested_model="claude-fable-5-20260715",
        effort="high",
        provider="claude-cli",
        trial_provenance=[trial],
        grader_config=grader,
        config_paths=[],
        cli_version="2.1.223",
    )
    assert aggregate["qualification_status"] == "invalid"
    assert aggregate["effective_model"] == "unavailable"


def test_failed_trial_preserves_error_state_without_inventing_a_model():
    trial = provenance.failed_trial_provenance(
        requested_model="claude-fable-5-20260715",
        provider="anthropic-api",
        grader_config={"metric": "accuracy"},
        failure="TimeoutExpired",
    )

    assert trial["effective_model"] == "unavailable"
    assert trial["fallback_state"] == "unknown"
    assert trial["refusal_state"] == "unknown"
    assert trial["response_state"] == "error"
    assert trial["failure"] == "TimeoutExpired"
    assert len(trial["provenance_hash"]) == 64


def test_aggregate_rejects_mutated_trial_evidence():
    grader = {"metric": "accuracy"}
    trial = provenance.response_trial_provenance(
        response=SimpleNamespace(
            model="claude-fable-5-20260715",
            stop_reason="end_turn",
            content=[],
        ),
        requested_model="claude-fable-5-20260715",
        provider="anthropic-api",
        grader_config=grader,
    )

    mutations = [
        ("effective_model", "claude-sonnet-5-20260729"),
        ("refusal_state", "refused"),
        ("fallback_state", "used"),
    ]
    for field, value in mutations:
        tampered = copy.deepcopy(trial)
        tampered[field] = value
        with pytest.raises(ValueError, match="provenance_hash"):
            provenance.qualification_metadata(
                requested_model="claude-fable-5-20260715",
                effort="high",
                provider="anthropic-api",
                trial_provenance=[tampered],
                grader_config=grader,
                config_paths=[],
                cli_version="2.1.223",
            )


def test_live_qualification_requires_an_explicit_exact_model():
    parser = argparse.ArgumentParser()
    provenance.add_qualification_arguments(parser, require_model=True)
    args = parser.parse_args(["--model", "claude-fable-5", "--effort", "xhigh"])
    assert args.model == "claude-fable-5"
    assert args.effort == "xhigh"
    assert args.provider == "anthropic-api"


def test_deep_dive_harness_captures_response_provenance_per_trial():
    harness = REPO / "skills" / "deep-dive" / "harness" / "run_live.py"
    text = harness.read_text(encoding="utf-8")

    assert "response_trial_provenance" in text
    assert "failed_trial_provenance" in text
    assert '"_response_provenance"' in text
    assert "trial_provenance=" in text
    assert "grader_config=GRADER_CONFIG" in text
    assert 'HARNESS / "grade.py"' in text
    assert "qualification_metadata(model=" not in text
    assert "output_config=EFFORT_CONFIG" in text
