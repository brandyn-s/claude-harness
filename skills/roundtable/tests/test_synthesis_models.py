"""Synthesis must describe the models that actually produced the run."""

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "synthesize.py"


def _load_synthesize():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("roundtable_synthesize", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transcript_models_override_later_ambient_defaults(tmp_path):
    synthesize = _load_synthesize()
    transcript = tmp_path / "transcript.jsonl"
    records = [
        {
            "event": "run_start",
            "no_prereg": False,
            "inject_agent_d": False,
            "anthropic_model": "claude-opus-5",
            "anthropic_effort": "xhigh",
        },
        {"round": 1, "agent": "opus", "ok": True, "model": "claude-fable-5"},
        {"round": 1, "agent": "grok", "ok": True, "model": "grok-qualified"},
        {"round": 1, "agent": "gpt", "ok": True, "model": "gpt-qualified"},
    ]
    transcript.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    metadata = synthesize.read_transcript_metadata(transcript)

    assert metadata["participant_models"]["opus"] == {"claude-fable-5"}
    assert metadata["participant_models"]["grok"] == {"grok-qualified"}
    assert metadata["participant_models"]["gpt"] == {"gpt-qualified"}
    assert metadata["run_anthropic_model"] == "claude-opus-5"
    assert metadata["run_anthropic_effort"] == "xhigh"
    assert synthesize.coverage_summary(metadata) == "R1=gpt,grok,opus"
    valid, contract, heading = synthesize.coverage_contract(metadata)
    assert valid is True
    assert "3-of-3 claims still require finding-level support" in contract
    assert "3-of-3 eligible" in heading


def test_transcript_metadata_prefers_nested_runtime_receipts(tmp_path):
    synthesize = _load_synthesize()
    transcript = tmp_path / "transcript.jsonl"
    records = [
        {
            "event": "run_start",
            "runtime_receipt": {
                "requested_model": "claude-sonnet-5",
                "effort": "medium",
            },
        },
        {
            "round": 1,
            "phase": "main",
            "agent": "opus",
            "ok": True,
            "runtime_receipt": {"effective_model": "claude-sonnet-5"},
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    metadata = synthesize.read_transcript_metadata(transcript)

    assert metadata["run_anthropic_model"] == "claude-sonnet-5"
    assert metadata["run_anthropic_effort"] == "medium"
    assert metadata["participant_models"]["opus"] == {"claude-sonnet-5"}


def test_synthesis_downgrades_wording_when_one_arm_is_missing(tmp_path):
    synthesize = _load_synthesize()
    transcript = tmp_path / "transcript.jsonl"
    records = [
        {"round": 1, "phase": "main", "agent": "opus", "ok": True, "model": "claude-opus-5"},
        {"round": 1, "phase": "main", "agent": "grok", "ok": True, "model": "grok-qualified"},
        {"round": 1, "phase": "main", "agent": "gpt", "ok": False},
    ]
    transcript.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    metadata = synthesize.read_transcript_metadata(transcript)
    valid, contract, heading = synthesize.coverage_contract(metadata)

    assert valid is True
    assert synthesize.coverage_summary(metadata) == "R1=grok,opus"
    assert "do not claim 3-of-3" in contract
    assert "3-of-3" not in heading


def test_synthesis_rejects_subquorum_transcript(tmp_path):
    synthesize = _load_synthesize()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {"round": 1, "phase": "main", "agent": "opus", "ok": True, "model": "claude-opus-5"}
        )
        + "\n",
        encoding="utf-8",
    )

    metadata = synthesize.read_transcript_metadata(transcript)
    valid, contract, heading = synthesize.coverage_contract(metadata)

    assert valid is False
    assert "fewer than two" in contract
    assert "INVALID PANEL" in heading


def test_synthesis_rejects_transcript_without_run_complete(
    tmp_path, monkeypatch, stub_panel_credentials
):
    synthesize = _load_synthesize()
    output = tmp_path / "unfinished"
    round_one = output / "round_1"
    round_one.mkdir(parents=True)
    for agent in ("opus", "grok", "gpt"):
        (round_one / f"{agent}.md").write_text(
            f"{agent} assessment\n", encoding="utf-8"
        )
    records = [
        {
            "event": "run_start",
            "anthropic_model": "claude-opus-5",
            "anthropic_effort": "high",
        },
        *[
            {
                "round": 1,
                "phase": "main",
                "agent": agent,
                "ok": True,
                "model": f"{agent}-model",
            }
            for agent in ("opus", "grok", "gpt")
        ],
    ]
    (output / "transcript.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    def should_not_call(*_args, **_kwargs):
        raise AssertionError("unfinished run must not dispatch synthesis")

    monkeypatch.setattr(synthesize.anthropic_adapter, "call", should_not_call)
    monkeypatch.setattr(sys, "argv", ["synthesize.py", "--output", str(output)])

    assert synthesize.main() == 2


def test_synthesis_requires_run_complete_to_be_the_last_transcript_record(
    tmp_path, monkeypatch, stub_panel_credentials
):
    synthesize = _load_synthesize()
    output = tmp_path / "contaminated"
    round_one = output / "round_1"
    round_one.mkdir(parents=True)
    for agent in ("opus", "grok", "gpt"):
        (round_one / f"{agent}.md").write_text(
            f"{agent} assessment\n", encoding="utf-8"
        )
    records = [
        {
            "event": "run_start",
            "anthropic_model": "claude-opus-5",
            "anthropic_effort": "high",
        },
        *[
            {
                "round": 1,
                "phase": "main",
                "agent": agent,
                "ok": True,
                "model": f"{agent}-model",
            }
            for agent in ("opus", "grok", "gpt")
        ],
        {"event": "run_complete", "rounds_executed": 1},
        {"event": "diagnostic_after_completion"},
    ]
    (output / "transcript.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    def should_not_call(*_args, **_kwargs):
        raise AssertionError("non-terminal run_complete must not authorize synthesis")

    monkeypatch.setattr(synthesize.anthropic_adapter, "call", should_not_call)
    monkeypatch.setattr(sys, "argv", ["synthesize.py", "--output", str(output)])

    assert synthesize.main() == 2


def test_synthesis_preserves_later_zero_survivor_quorum_abort(tmp_path):
    synthesize = _load_synthesize()
    transcript = tmp_path / "transcript.jsonl"
    records = [
        {"round": 1, "phase": "main", "agent": agent, "ok": True, "model": f"{agent}-model"}
        for agent in ("opus", "grok", "gpt")
    ] + [
        {
            "event": "quorum_abort",
            "round": 2,
            "successful_agents": [],
            "required_agents": 2,
        }
    ]
    transcript.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    metadata = synthesize.read_transcript_metadata(transcript)
    valid, contract, _heading = synthesize.coverage_contract(metadata)

    assert metadata["rounds_completed"] == 2
    assert metadata["terminal_event"] == "quorum_abort"
    assert synthesize.coverage_summary(metadata) == "R1=gpt,grok,opus; R2=none"
    assert valid is False
    assert "fewer than two" in contract


def test_synthesis_dispatch_uses_run_start_model_and_effort(
    tmp_path, monkeypatch, stub_panel_credentials
):
    synthesize = _load_synthesize()
    output = tmp_path / "run"
    round_one = output / "round_1"
    round_one.mkdir(parents=True)
    for agent in ("opus", "grok", "gpt"):
        (round_one / f"{agent}.md").write_text(
            f"{agent} assessment\n", encoding="utf-8"
        )
    records = [
        {
            "event": "run_start",
            "anthropic_model": "claude-opus-5",
            "anthropic_effort": "xhigh",
            "no_prereg": True,
            "inject_agent_d": False,
        }
    ] + [
        {
            "round": 1,
            "phase": "main",
            "agent": agent,
            "ok": True,
            "model": f"{agent}-effective",
        }
        for agent in ("opus", "grok", "gpt")
    ] + [{"event": "run_complete", "rounds_executed": 1, "total_cost": 0.0}]
    (output / "transcript.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    captured = {}

    def fake_call(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return {
            "ok": True,
            "text": "qualified synthesis",
            "input_tokens": 1,
            "output_tokens": 1,
            "model": kwargs["model"],
            "effort": kwargs["effort"],
        }

    monkeypatch.setattr(synthesize.anthropic_adapter, "call", fake_call)
    monkeypatch.setattr(
        synthesize.anthropic_adapter,
        "pricing_for_model",
        lambda _model: {"in": 1.0, "out": 1.0},
    )
    monkeypatch.setattr(
        sys, "argv", ["synthesize.py", "--output", str(output)]
    )

    assert synthesize.main() == 0
    assert captured["model"] == "claude-opus-5"
    assert captured["effort"] == "xhigh"
    assert captured["max_tokens"] == 64_000
    assert "R1=gpt,grok,opus" in captured["prompt"]
