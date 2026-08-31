"""JRH qualification must fail closed and preserve model-era headroom."""

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "jrh_harness.py"


def _load_jrh():
    spec = importlib.util.spec_from_file_location("roundtable_jrh_contracts", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_jrh_anthropic_arm_uses_model_effort_headroom():
    jrh = _load_jrh()
    observed = {}

    class FakeAnthropic:
        @staticmethod
        def recommended_max_tokens(workload):
            assert workload == "jrh"
            return 64_000

        @staticmethod
        def call(prompt, max_tokens):
            observed.update(prompt=prompt, max_tokens=max_tokens)
            return {
                "ok": True,
                "text": "VERDICT: SUPPORTED",
                "input_tokens": 1,
                "output_tokens": 1,
                "model": "claude-opus-5",
            }

        @staticmethod
        def pricing_for_model(_model):
            return {"in": 5.0, "out": 25.0}

    jrh.anthropic_adapter = FakeAnthropic

    result = jrh.judge("opus", "classify")

    assert result["ok"] is True
    assert observed == {"prompt": "classify", "max_tokens": 64_000}
    assert result["runtime_receipt"]["provider"] == "anthropic"
    assert result["runtime_receipt"]["effective_model"] == "claude-opus-5"
    assert result["runtime_receipt"]["context_class"] == "<unavailable>"


def test_jrh_provider_failure_invalidates_the_run():
    jrh = _load_jrh()

    class FailingAnthropic:
        @staticmethod
        def recommended_max_tokens(_workload):
            return 16_000

        @staticmethod
        def call(_prompt, max_tokens):
            return {
                "ok": False,
                "error_type": "incomplete_response",
                "stop_reason": "max_tokens",
                "error": f"truncated at {max_tokens}",
            }

    jrh.anthropic_adapter = FailingAnthropic

    with pytest.raises(jrh.JRHInvalidRun, match="incomplete_response.*max_tokens"):
        jrh.judge("opus", "classify")


def test_jrh_unparseable_verdict_invalidates_the_run(monkeypatch):
    jrh = _load_jrh()
    monkeypatch.setattr(
        jrh,
        "judge",
        lambda _model, _prompt: {"ok": True, "text": "I cannot choose."},
    )

    with pytest.raises(jrh.JRHInvalidRun, match="unparseable.*claim"):
        jrh.ask_claim("opus", "A claim")


def test_jrh_raw_call_record_keeps_nested_runtime_receipt():
    jrh = _load_jrh()
    receipt = {
        "requested_model": "claude-opus-5",
        "effective_model": "claude-opus-5",
        "provider": "anthropic",
        "context_class": "<unavailable>",
    }
    result = {"ok": True, "runtime_receipt": receipt}

    jrh.record_raw_call(
        "opus",
        result,
        test="paraphrase",
        item="C1",
        variant="original",
        verdict="SUPPORTED",
    )

    assert jrh.raw == [
        {
            "test": "paraphrase",
            "model": "opus",
            "item": "C1",
            "variant": "original",
            "verdict": "SUPPORTED",
            "runtime_receipt": receipt,
        }
    ]


def test_jrh_main_writes_one_receipted_event_per_provider_call(
    tmp_path, monkeypatch
):
    jrh = _load_jrh()
    receipt = {
        "requested_model": "claude-opus-5",
        "effective_model": "claude-opus-5",
        "provider": "anthropic",
        "context_class": "<unavailable>",
    }
    result = {"ok": True, "runtime_receipt": receipt}

    monkeypatch.setattr(jrh, "_setup", lambda: None)
    monkeypatch.setattr(jrh, "_models", lambda: [("opus", "claude-opus-5")])
    monkeypatch.setattr(jrh, "OUT", tmp_path)
    monkeypatch.setattr(jrh, "PAIRS", [jrh.PAIRS[0]])
    monkeypatch.setattr(jrh, "CLAIMS", [jrh.CLAIMS[1]])
    monkeypatch.setattr(
        jrh,
        "ask_pair",
        lambda *_args, **_kwargs: ("A", dict(result)),
    )
    monkeypatch.setattr(
        jrh,
        "ask_claim",
        lambda *_args, **_kwargs: ("SUPPORTED", dict(result)),
    )

    jrh.main()

    records = [
        json.loads(line)
        for line in (tmp_path / "raw.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert len(records) == 8
    assert all(record["runtime_receipt"] == receipt for record in records)


def test_jrh_invalid_call_cannot_emit_a_judge_card(tmp_path, monkeypatch):
    jrh = _load_jrh()
    monkeypatch.setattr(jrh, "_setup", lambda: None)
    monkeypatch.setattr(jrh, "_models", lambda: [("opus", "claude-opus-5")])
    monkeypatch.setattr(jrh, "OUT", tmp_path)
    monkeypatch.setattr(jrh, "PAIRS", [jrh.PAIRS[0]])
    monkeypatch.setattr(jrh, "CLAIMS", [])

    def fail(*_args, **_kwargs):
        raise jrh.JRHInvalidRun("opus judge call failed: incomplete_response")

    monkeypatch.setattr(jrh, "ask_pair", fail)

    with pytest.raises(jrh.JRHInvalidRun, match="incomplete_response"):
        jrh.main()
    assert not (tmp_path / "judge_card.json").exists()


def test_jrh_rejects_reused_output_before_any_provider_call(tmp_path, monkeypatch):
    jrh = _load_jrh()
    stale = tmp_path / "judge_card.json"
    stale.write_text('{"old":true}\n', encoding="utf-8")
    monkeypatch.setattr(jrh, "_setup", lambda: None)
    monkeypatch.setattr(jrh, "OUT", tmp_path)

    def should_not_resolve_models():
        raise AssertionError("reused JRH output must fail before provider setup")

    monkeypatch.setattr(jrh, "_models", should_not_resolve_models)

    with pytest.raises(jrh.JRHInvalidRun, match="not empty"):
        jrh.main()
    assert stale.read_text(encoding="utf-8") == '{"old":true}\n'


def test_jrh_rejects_output_path_that_is_not_a_directory(tmp_path, monkeypatch):
    jrh = _load_jrh()
    output_file = tmp_path / "not-a-directory"
    output_file.write_text("old output\n", encoding="utf-8")
    monkeypatch.setattr(jrh, "OUT", output_file)

    def should_not_setup():
        raise AssertionError("invalid output path must fail before provider setup")

    monkeypatch.setattr(jrh, "_setup", should_not_setup)

    with pytest.raises(jrh.JRHInvalidRun, match="not a directory"):
        jrh.main()


def test_jrh_budget_overrun_invalidates_instead_of_emitting_partial_evidence(
    monkeypatch
):
    jrh = _load_jrh()

    class FakeAnthropic:
        @staticmethod
        def recommended_max_tokens(_workload):
            return 16_000

        @staticmethod
        def call(_prompt, max_tokens):
            return {
                "ok": True,
                "text": "VERDICT: SUPPORTED",
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "model": "claude-opus-5",
                "effort": "high",
            }

        @staticmethod
        def pricing_for_model(_model):
            return {"in": 25.0, "out": 25.0}

    jrh.anthropic_adapter = FakeAnthropic
    monkeypatch.setattr(jrh, "BUDGET_USD", 20.0)

    with pytest.raises(jrh.JRHInvalidRun, match="budget exceeded"):
        jrh.judge("opus", "classify")


def test_jrh_provider_model_switch_invalidates_the_run():
    jrh = _load_jrh()

    class SwitchedAnthropic:
        @staticmethod
        def recommended_max_tokens(_workload):
            return 16_000

        @staticmethod
        def call(_prompt, max_tokens):
            return {
                "ok": True,
                "text": "VERDICT: SUPPORTED",
                "input_tokens": 1,
                "output_tokens": 1,
                "model": "claude-sonnet-5",
                "runtime_receipt": {
                    "requested_model": "claude-opus-5",
                    "effective_model": "claude-sonnet-5",
                    "provider": "anthropic",
                    "fallback": True,
                    "context_class": "<unavailable>",
                },
            }

        @staticmethod
        def pricing_for_model(_model):
            return {"in": 5.0, "out": 25.0}

    jrh.anthropic_adapter = SwitchedAnthropic

    with pytest.raises(jrh.JRHInvalidRun, match="model switch"):
        jrh.judge("opus", "classify")


def test_jrh_records_context_class_only_from_explicit_result_metadata():
    jrh = _load_jrh()

    unobserved = {"ok": True, "model": "claude-opus-5"}
    observed = {
        "ok": True,
        "model": "claude-opus-5",
        "context_class": "runtime-observed",
    }

    assert (
        jrh.ensure_runtime_receipt("opus", unobserved)["context_class"]
        == "<unavailable>"
    )
    assert (
        jrh.ensure_runtime_receipt("opus", observed)["context_class"]
        == "runtime-observed"
    )


def test_jrh_cli_returns_nonzero_for_invalid_run(monkeypatch, capsys):
    jrh = _load_jrh()

    def invalid():
        raise jrh.JRHInvalidRun("unparseable claim verdict")

    monkeypatch.setattr(jrh, "main", invalid)

    assert jrh.cli() == 2
    assert "JRH INVALID" in capsys.readouterr().err
