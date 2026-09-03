"""Runtime-model contracts for the LLM-driven skill-eval harness."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "run-skill-llm-evals.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("run_skill_llm_evals", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_must_be_explicit_now_that_settings_pin_nothing():
    """settings.json stopped pinning a model on 2026-09-03 (the runtime picks
    it); an eval run must therefore name its model or fail loudly, never
    invent one."""
    runner = load_runner()
    assert "model" not in json.loads((REPO / "settings.json").read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="--model or CLAUDE_MODEL"):
        runner.resolve_requested_model(None, {})
    assert runner.resolve_requested_model("claude-opus-5", {}) == "claude-opus-5"
    assert runner.resolve_requested_model(
        None, {"CLAUDE_MODEL": "claude-sonnet-5"}
    ) == ("claude-sonnet-5")


def test_runtime_receipt_separates_requested_and_effective_model():
    runner = load_runner()
    events = [
        {
            "type": "assistant",
            "message": {"model": "claude-opus-5", "stop_reason": "refusal"},
        }
    ]

    receipt = runner.runtime_receipt(events, "claude-fable-5", "2.1.226")

    assert receipt["requested_model"] == "claude-fable-5"
    assert receipt["effective_model"] == "claude-opus-5"
    assert receipt["fallback"] is True
    assert receipt["refusal"] is True
    assert receipt["claude_code_version"] == "2.1.226"
    for field in ("provider", "effort", "context_class", "switch_reason"):
        assert receipt[field] == "<unavailable>"


@pytest.mark.parametrize(
    ("exit_code", "effective_model", "stop_reason", "expected_failure"),
    [
        (2, "claude-fable-5", "end_turn", "exited with code 2"),
        (0, "claude-fable-5", "refusal", "provider refusal"),
        (
            0,
            "claude-sonnet-5",
            "end_turn",
            "effective model differed from requested model",
        ),
    ],
)
def test_runtime_outcomes_fail_even_a_negative_activation_trial(
    monkeypatch,
    tmp_path,
    exit_code,
    effective_model,
    stop_reason,
    expected_failure,
):
    runner = load_runner()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    event = {
        "type": "assistant_message",
        "text": "No skill needed.",
        "message": {"model": effective_model, "stop_reason": stop_reason},
    }
    monkeypatch.setattr(runner, "setup_sandbox", lambda _skill: sandbox)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps(event) + "\n",
            stderr="",
            returncode=exit_code,
        ),
    )

    trial = runner.run_live_trial(
        {"skill": "capture"},
        {"invocation": {"prompt": "hello", "expected_skill_fires": False}},
        0,
        "claude-fable-5",
        "2.1.226",
    )

    assert trial["activated"] is False
    assert trial["passed"] is False
    assert any(expected_failure in failure for failure in trial["failures"])


def test_exact_nonrefusal_runtime_can_pass_negative_activation_trial(
    monkeypatch, tmp_path
):
    runner = load_runner()
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    event = {
        "type": "assistant_message",
        "text": "No skill needed.",
        "message": {"model": "claude-fable-5", "stop_reason": "end_turn"},
    }
    monkeypatch.setattr(runner, "setup_sandbox", lambda _skill: sandbox)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps(event) + "\n", stderr="", returncode=0
        ),
    )

    trial = runner.run_live_trial(
        {"skill": "capture"},
        {"invocation": {"prompt": "hello", "expected_skill_fires": False}},
        0,
        "claude-fable-5",
        "2.1.226",
    )

    assert trial["passed"] is True
    assert trial["failures"] == []


def test_active_tier2_evals_do_not_pin_superseded_opus_models():
    offenders = []
    for path in sorted((REPO / "tests").glob("*/**/*.yaml")):
        if "l3-activation-study" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "model: claude-opus-4-7" in text or "model: claude-opus-4-8" in text:
            offenders.append(path.relative_to(REPO).as_posix())

    assert offenders == []


def test_l3_opus_4_7_design_remains_explicitly_historical():
    design = (REPO / "tests" / "l3-activation-study" / "design.yaml").read_text(
        encoding="utf-8"
    )
    readme = (REPO / "tests" / "l3-activation-study" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "Opus 4.7 skill-activation study" in design
    assert "model: claude-opus-4-7" in design
    assert "Pre-registered factorial design" in readme
