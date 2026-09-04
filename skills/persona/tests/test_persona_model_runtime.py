"""Current-model and qualification-receipt contracts for /persona.

All tests are key-free. Fake SDK responses exercise the production request and
receipt paths without contacting a provider.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import model_contracts as ids

# Expected ids come from contracts/model-capabilities.json, never from literals: a model
# rollover changes the contract once and these assertions follow it.
JUDGE = ids.model_id("opus")  # /persona's independent-judge default tier
OTHER = ids.model_id("sonnet")  # a different current model: env overrides and provider switches
FABLE, MYTHOS = ids.model_id("fable"), ids.model_id("mythos")  # Covered Models (30-day retention)
HAIKU_SNAPSHOT = ids.model("haiku")["dated_snapshot"]  # the economical producer default
SUPERSEDED = ids.superseded_ids()

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_anthropic_script(name: str):
    anthropic_stub = type(sys)("anthropic")
    anthropic_stub.Anthropic = object
    sys.modules["anthropic"] = anthropic_stub
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return _load(name)


class _Messages:
    def __init__(self, response):
        self.response = response
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return self.response


class _Client:
    def __init__(self, response):
        self.messages = _Messages(response)


class _RaisingMessages:
    def create(self, **_kwargs):
        raise RuntimeError("provider unavailable")


class _RaisingClient:
    messages = _RaisingMessages()


def _response(*, model=JUDGE, stop_reason="end_turn", text="ok"):
    return SimpleNamespace(
        model=model,
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )


def _framework():
    return {
        "id": "systems",
        "name": "Systems",
        "group": "engineering",
        "body": "Observe interactions.",
    }


def _failed_result(error_type="refusal"):
    return {
        "framework_id": "systems",
        "framework_name": "Systems",
        "framework_group": "engineering",
        "ok": False,
        "error_type": error_type,
        "error": f"synthetic {error_type}",
        "requested_model": JUDGE,
        "model": JUDGE,
        "effort": "high",
        "runtime_receipt": {
            "requested_model": JUDGE,
            "requested_effort": "high",
            "effective_model": JUDGE,
            "effective_model_source": "response_metadata",
            "fallback": False,
        },
    }


def _successful_result():
    return {
        "framework_id": "systems",
        "framework_name": "Systems",
        "framework_group": "engineering",
        "ok": True,
        "text": "inspect subset",
        "requested_model": JUDGE,
        "model": JUDGE,
        "effort": "high",
        "runtime_receipt": {
            "requested_model": JUDGE,
            "requested_effort": "high",
            "effective_model": JUDGE,
            "effective_model_source": "response_metadata",
            "fallback": False,
        },
    }


def test_operational_model_defaults_are_current_and_environment_configurable(
    monkeypatch,
):
    runtime = _load("model_runtime")
    for env_name in (
        "PERSONA_MODEL",
        "PERSONA_MODEL_EFFORT",
        "PERSONA_JUDGE_MODEL",
        "PERSONA_JUDGE_EFFORT",
    ):
        monkeypatch.delenv(env_name, raising=False)

    assert runtime.resolve_persona_model() == HAIKU_SNAPSHOT
    assert runtime.resolve_persona_effort() is None
    assert runtime.resolve_judge_model() == JUDGE
    assert runtime.resolve_judge_effort() == "high"

    monkeypatch.setenv("PERSONA_MODEL", OTHER)
    monkeypatch.setenv("PERSONA_MODEL_EFFORT", "medium")
    monkeypatch.setenv("PERSONA_JUDGE_MODEL", MYTHOS)
    monkeypatch.setenv("PERSONA_JUDGE_EFFORT", "xhigh")
    monkeypatch.setenv("PERSONA_COVERED_MODEL_RETENTION_APPROVED", "1")
    assert runtime.resolve_persona_model() == OTHER
    assert runtime.resolve_persona_effort() == "medium"
    assert runtime.resolve_judge_model() == MYTHOS
    assert runtime.resolve_judge_effort() == "xhigh"


def test_covered_models_require_explicit_retention_approval(monkeypatch):
    runtime = _load("model_runtime")
    monkeypatch.delenv("PERSONA_COVERED_MODEL_RETENTION_APPROVED", raising=False)

    with pytest.raises(ValueError, match="30-day retention"):
        runtime.resolve_judge_model(FABLE)
    with pytest.raises(ValueError, match="30-day retention"):
        runtime.resolve_persona_model(MYTHOS)

    monkeypatch.setenv("PERSONA_COVERED_MODEL_RETENTION_APPROVED", "1")
    assert runtime.resolve_judge_model(FABLE) == FABLE
    assert runtime.resolve_persona_model(MYTHOS) == MYTHOS


def test_model_aliases_resolve_to_current_contract_ids(monkeypatch):
    """`--model haiku` must reach the API as the exact id the contract maps the tier
    to, never as the alias (the API answers an alias with a 404 at run time)."""
    runtime = _load("model_runtime")
    monkeypatch.setenv("PERSONA_COVERED_MODEL_RETENTION_APPROVED", "1")

    assert runtime.resolve_persona_model("haiku") == HAIKU_SNAPSHOT
    assert runtime.resolve_judge_model("opus") == JUDGE
    assert runtime.resolve_judge_model(" Sonnet ") == OTHER
    assert runtime.resolve_judge_model("fable") == FABLE
    assert runtime.resolve_judge_model("mythos") == MYTHOS
    # Exact current ids and the Haiku dated snapshot pass through unchanged.
    assert runtime.resolve_persona_model(HAIKU_SNAPSHOT) == HAIKU_SNAPSHOT
    assert runtime.resolve_persona_model(ids.model_id("haiku")) == ids.model_id("haiku")
    assert runtime.resolve_judge_model(JUDGE) == JUDGE

    # An alias that lands on a Covered Model still goes through the retention gate.
    monkeypatch.delenv("PERSONA_COVERED_MODEL_RETENTION_APPROVED", raising=False)
    with pytest.raises(ValueError, match="30-day retention"):
        runtime.resolve_judge_model("fable")


def test_unresolvable_model_fails_before_any_request(monkeypatch, capsys):
    runtime = _load("model_runtime")
    with pytest.raises(ValueError, match="claude-opus-9"):
        runtime.resolve_persona_model("claude-opus-9")
    with pytest.raises(ValueError, match="superseded"):
        runtime.resolve_judge_model(SUPERSEDED[0])
    with pytest.raises(ValueError, match="default"):
        runtime.resolve_judge_model("default")
    with pytest.raises(ValueError, match="us.anthropic"):
        runtime.resolve_judge_model(f"us.anthropic.{JUDGE}")

    dispatch = _load_anthropic_script("dispatch")
    monkeypatch.delenv("PERSONA_MODEL", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dispatch.py",
            "discovery",
            "Find the blind spot",
            "--slug",
            "unknown-model",
            "--criteria-met",
            "2",
            "--model",
            "claude-opus-9",
        ],
    )
    monkeypatch.setattr(
        dispatch,
        "run_discovery",
        lambda _args: pytest.fail("dispatch must not start on an unresolvable model"),
    )
    monkeypatch.setattr(
        dispatch.anthropic,
        "Anthropic",
        lambda: pytest.fail("no client may be built before the model resolves"),
    )

    assert dispatch.main() == 2
    err = capsys.readouterr().err.lower()
    assert "configuration error" in err
    assert "claude-opus-9" in err


def test_alias_run_records_the_resolved_id_not_the_alias(monkeypatch):
    dispatch = _load_anthropic_script("dispatch")
    captured = {}
    monkeypatch.delenv("PERSONA_MODEL", raising=False)
    monkeypatch.delenv("PERSONA_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dispatch.py",
            "discovery",
            "Find the blind spot",
            "--slug",
            "alias-run",
            "--criteria-met",
            "2",
            "--model",
            "haiku",
            "--judge-model",
            "opus",
        ],
    )

    def _capture(args):
        captured.update(vars(args))
        return 0

    monkeypatch.setattr(dispatch, "run_discovery", _capture)
    assert dispatch.main() == 0
    assert captured["model"] == HAIKU_SNAPSHOT
    assert captured["judge_model"] == JUDGE

    # The request on the wire and the receipt both carry the resolved id.
    client = _Client(_response(model=HAIKU_SNAPSHOT))
    result = dispatch.dispatch_one(client, _framework(), "Find the blind spot", captured["model"])
    assert client.messages.request["model"] == HAIKU_SNAPSHOT
    assert result["ok"] is True
    assert result["requested_model"] == HAIKU_SNAPSHOT
    assert result["runtime_receipt"]["requested_model"] == HAIKU_SNAPSHOT
    assert result["runtime_receipt"]["effective_model"] == HAIKU_SNAPSHOT


def test_rubric_alias_matching_the_pinned_fixture_is_not_a_conflict(tmp_path, monkeypatch):
    dispatch = _load_anthropic_script("dispatch")
    fixture = tmp_path / "fixture.yaml"
    fixture.write_text(
        "problem: Investigate the plateau\n"
        "provenance:\n"
        "  fixture_author: independent reviewer\n"
        "  inventory_authored_by: curator\n"
        "  independent: true\n"
        "cohort:\n"
        "  n: 1\n"
        "  sampling: bucket\n"
        "models:\n"
        f"  persona: {HAIKU_SNAPSHOT}\n"
        f"  judge: {JUDGE}\n"
        "  judge_effort: high\n",
        encoding="utf-8",
    )
    args = __import__("argparse").Namespace(
        fixture=str(fixture),
        n=None,
        sampling=None,
        model="haiku",
        effort=None,
        judge_model="opus",
        judge_effort=None,
        override_fixture=False,
        slug="fixture-alias",
        frameworks="",
        inventory=None,
        seed=7,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-key")
    monkeypatch.setattr(dispatch, "DEFAULT_RUN_BASE", tmp_path / "runs")
    monkeypatch.setattr(dispatch, "parse_file", lambda _path: [])

    class _StopAfterResolution(Exception):
        pass

    monkeypatch.setattr(
        dispatch,
        "sample",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_StopAfterResolution()),
    )

    with pytest.raises(_StopAfterResolution):
        dispatch.run_rubric(args)

    assert args.model == HAIKU_SNAPSHOT
    assert args.judge_model == JUDGE
    assert not (tmp_path / "runs" / "fixture-alias" / "cli_override_attempt.json").exists()


def test_without_the_contract_exact_ids_pass_and_aliases_fail_fast(tmp_path, monkeypatch):
    """Marketplace bundles ship the skill without contracts/: nothing can validate an
    exact id there, but an alias still must not reach the API."""
    runtime = _load("model_runtime")
    monkeypatch.setattr(
        runtime, "CAPABILITIES_CONTRACT", tmp_path / "contracts" / "model-capabilities.json"
    )
    monkeypatch.delenv("PERSONA_COVERED_MODEL_RETENTION_APPROVED", raising=False)

    assert runtime.resolve_judge_model(JUDGE) == JUDGE
    with pytest.raises(ValueError, match="model-capabilities.json"):
        runtime.resolve_persona_model("haiku")
    with pytest.raises(ValueError, match="30-day retention"):
        runtime.resolve_judge_model(FABLE)


def test_effort_resolution_normalizes_and_rejects_unknown_values(monkeypatch):
    runtime = _load("model_runtime")
    monkeypatch.setenv("PERSONA_JUDGE_EFFORT", " XHIGH ")
    monkeypatch.setenv("PERSONA_MODEL_EFFORT", " Medium ")
    assert runtime.resolve_judge_effort() == "xhigh"
    assert runtime.resolve_persona_effort() == "medium"

    with pytest.raises(ValueError, match="effort must be one of"):
        runtime.resolve_judge_effort("turbo")
    with pytest.raises(ValueError, match="effort must be one of"):
        runtime.resolve_persona_effort("turbo")


def test_runtime_receipt_distinguishes_requested_from_observed_runtime():
    runtime = _load("model_runtime")

    observed = runtime.runtime_receipt(
        requested_model=JUDGE,
        requested_effort="high",
        effective_model=OTHER,
        stop_reason="end_turn",
    )
    assert observed == {
        "requested_model": JUDGE,
        "requested_model_source": "request_configuration",
        "effective_model": OTHER,
        "effective_model_source": "response_metadata",
        "provider": "anthropic",
        "requested_effort": "high",
        "effective_effort": "<unavailable>",
        "effective_effort_source": "unavailable",
        "context_class": "<unavailable>",
        "claude_code_version": "<unavailable>",
        "fallback": True,
        "switch_reason": "provider_response_model_differs",
        "refusal": False,
        "stop_reason": "end_turn",
    }

    unobserved = runtime.runtime_receipt(
        requested_model=JUDGE,
        requested_effort="high",
    )
    assert unobserved["effective_model"] == "<unavailable>"
    assert unobserved["effective_effort"] == "<unavailable>"
    assert unobserved["fallback"] == "<unavailable>"
    assert unobserved["refusal"] == "<unavailable>"


def test_message_request_sends_effort_only_when_explicitly_resolved():
    runtime = _load("model_runtime")
    messages = [{"role": "user", "content": "test"}]

    economical = runtime.message_request(
        model=HAIKU_SNAPSHOT,
        max_tokens=1000,
        messages=messages,
        effort=None,
    )
    assert "output_config" not in economical

    judged = runtime.message_request(
        model=JUDGE,
        max_tokens=1500,
        messages=messages,
        effort="high",
    )
    assert judged["output_config"] == {"effort": "high"}

    with pytest.raises(ValueError, match="effort must be one of"):
        runtime.message_request(
            model=JUDGE,
            max_tokens=1500,
            messages=messages,
            effort="turbo",
        )


def test_output_budget_leaves_headroom_for_adaptive_thinking():
    runtime = _load("model_runtime")
    assert runtime.recommended_max_tokens(
        workload="persona",
        model=HAIKU_SNAPSHOT,
        effort=None,
    ) == 1000
    assert runtime.recommended_max_tokens(
        workload="persona",
        model=JUDGE,
        effort="high",
    ) == 16_000
    assert runtime.recommended_max_tokens(
        workload="judge",
        model=JUDGE,
        effort="high",
    ) == 16_000
    assert runtime.recommended_max_tokens(
        workload="judge",
        model=FABLE,
        effort="high",
    ) == 64_000
    assert runtime.recommended_max_tokens(
        workload="judge",
        model=JUDGE,
        effort="xhigh",
    ) == 64_000


def test_persona_dispatch_records_requested_and_effective_runtime():
    dispatch = _load_anthropic_script("dispatch")
    client = _Client(_response(model=JUDGE))
    framework = {
        "id": "systems",
        "name": "Systems",
        "group": "engineering",
        "body": "Observe interactions.",
    }

    result = dispatch.dispatch_one(
        client,
        framework,
        "Find the blind spot",
        JUDGE,
        effort="high",
    )

    assert client.messages.request["output_config"] == {"effort": "high"}
    assert client.messages.request["max_tokens"] == 16_000
    assert result["ok"] is True
    assert result["requested_model"] == JUDGE
    assert result["model"] == JUDGE
    assert result["effort"] == "high"
    assert result["stop_reason"] == "end_turn"
    assert result["runtime_receipt"]["effective_model"] == JUDGE
    assert result["runtime_receipt"]["fallback"] is False


def test_provider_model_switch_is_failed_qualification_evidence():
    dispatch = _load_anthropic_script("dispatch")
    judge = _load_anthropic_script("score_llm_judge")
    framework = {
        "id": "systems",
        "name": "Systems",
        "group": "engineering",
        "body": "Observe interactions.",
    }
    switched = _response(
        model=OTHER,
        text='{"rc1":"endorse"}',
    )

    producer_result = dispatch.dispatch_one(
        _Client(switched),
        framework,
        "Find the blind spot",
        JUDGE,
        effort="high",
    )
    judge_result = judge.judge(
        _Client(switched),
        {"problem": "plateau", "root_causes": {}, "false_leads": {}},
        "Inspect the subset",
        JUDGE,
        effort="high",
    )

    for result in (producer_result, judge_result):
        assert result["ok"] is False
        assert result["error_type"] == "model_mismatch"
        assert result["requested_model"] == JUDGE
        assert result["model"] == OTHER
        assert result["runtime_receipt"]["fallback"] is True


def test_persona_dispatch_fails_when_effective_model_is_unobserved():
    dispatch = _load_anthropic_script("dispatch")

    result = dispatch.dispatch_one(
        _Client(_response(model=None, text="inspect subset")),
        _framework(),
        "Find the blind spot",
        JUDGE,
        effort="high",
    )

    assert result["ok"] is False
    assert result["error_type"] == "model_unobserved"
    assert result["requested_model"] == JUDGE
    assert result["model"] == "<unavailable>"
    assert result["runtime_receipt"]["effective_model"] == "<unavailable>"
    assert result["runtime_receipt"]["effective_model_source"] == "unavailable"


def test_judge_fails_when_effective_model_is_unobserved():
    judge = _load_anthropic_script("score_llm_judge")

    result = judge.judge(
        _Client(_response(model=None, text='{"rc1":"endorse"}')),
        {"problem": "plateau", "root_causes": {}, "false_leads": {}},
        "Inspect the subset",
        JUDGE,
        effort="high",
    )

    assert result["ok"] is False
    assert result["error_type"] == "model_unobserved"
    assert result["requested_model"] == JUDGE
    assert result["model"] == "<unavailable>"
    assert result["runtime_receipt"]["effective_model"] == "<unavailable>"
    assert result["runtime_receipt"]["effective_model_source"] == "unavailable"


@pytest.mark.parametrize(
    ("stop_reason", "text", "error_type"),
    [
        ("refusal", "cannot help", "refusal"),
        ("max_tokens", "partial", "incomplete_response"),
        ("model_context_window_exceeded", "partial", "incomplete_response"),
        ("end_turn", "", "incomplete_response"),
    ],
)
def test_persona_dispatch_never_scores_refused_or_incomplete_output(
    stop_reason,
    text,
    error_type,
):
    dispatch = _load_anthropic_script("dispatch")
    client = _Client(_response(stop_reason=stop_reason, text=text))
    framework = {
        "id": "systems",
        "name": "Systems",
        "group": "engineering",
        "body": "Observe interactions.",
    }

    result = dispatch.dispatch_one(
        client,
        framework,
        "Find the blind spot",
        JUDGE,
        effort="high",
    )

    assert result["ok"] is False
    assert result["error_type"] == error_type
    assert result["stop_reason"] == stop_reason
    assert result["runtime_receipt"]["refusal"] is (stop_reason == "refusal")


def test_llm_judge_records_current_model_effort_and_effective_runtime():
    judge = _load_anthropic_script("score_llm_judge")
    client = _Client(_response(text='{"rc1":"endorse"}'))
    fixture = {
        "problem": "A metric plateaued",
        "root_causes": {
            "RC1": {
                "short_name": "blind subset",
                "endorsement_criteria": "endorse the subset",
                "rejection_criteria": "reject the subset",
            }
        },
        "false_leads": {},
    }

    result = judge.judge(
        client,
        fixture,
        "Inspect the subset",
        JUDGE,
        effort="high",
    )

    assert client.messages.request["output_config"] == {"effort": "high"}
    assert client.messages.request["max_tokens"] == 16_000
    assert result["ok"] is True
    assert result["requested_model"] == JUDGE
    assert result["model"] == JUDGE
    assert result["effort"] == "high"
    assert result["runtime_receipt"]["effective_model"] == JUDGE
    assert result["runtime_receipt"]["fallback"] is False


@pytest.mark.parametrize(
    ("stop_reason", "text", "error_type"),
    [
        ("refusal", "cannot score", "refusal"),
        ("max_tokens", "{", "incomplete_response"),
        ("model_context_window_exceeded", "{", "incomplete_response"),
        ("end_turn", "", "incomplete_response"),
    ],
)
def test_llm_judge_never_accepts_refused_or_incomplete_evidence(
    stop_reason,
    text,
    error_type,
):
    judge = _load_anthropic_script("score_llm_judge")
    client = _Client(_response(stop_reason=stop_reason, text=text))
    fixture = {"problem": "plateau", "root_causes": {}, "false_leads": {}}

    result = judge.judge(
        client,
        fixture,
        "Inspect the subset",
        JUDGE,
        effort="high",
    )

    assert result["ok"] is False
    assert result["error_type"] == error_type
    assert result["stop_reason"] == stop_reason
    assert result["runtime_receipt"]["refusal"] is (stop_reason == "refusal")


def test_discovery_cli_resolves_environment_runtime_at_run_start(monkeypatch):
    dispatch = _load_anthropic_script("dispatch")
    captured = {}

    monkeypatch.setenv("PERSONA_MODEL", OTHER)
    monkeypatch.setenv("PERSONA_MODEL_EFFORT", "medium")
    monkeypatch.setenv("PERSONA_JUDGE_MODEL", JUDGE)
    monkeypatch.setenv("PERSONA_JUDGE_EFFORT", "xhigh")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dispatch.py",
            "discovery",
            "Find the blind spot",
            "--slug",
            "runtime-contract",
            "--criteria-met",
            "2",
        ],
    )

    def _capture(args):
        captured.update(vars(args))
        return 0

    monkeypatch.setattr(dispatch, "run_discovery", _capture)
    assert dispatch.main() == 0
    assert captured["model"] == OTHER
    assert captured["effort"] == "medium"
    assert captured["judge_model"] == JUDGE
    assert captured["judge_effort"] == "xhigh"


def test_cached_qualification_output_must_match_requested_model_and_effort():
    runtime = _load("model_runtime")
    matching = {
        "ok": True,
        "runtime_receipt": {
            "requested_model": JUDGE,
            "requested_effort": "high",
            "effective_model": JUDGE,
            "effective_model_source": "response_metadata",
            "fallback": False,
        },
    }

    assert runtime.cache_matches_runtime(
        matching,
        requested_model=JUDGE,
        requested_effort="high",
    )
    assert not runtime.cache_matches_runtime(
        matching,
        requested_model=OTHER,
        requested_effort="high",
    )
    assert not runtime.cache_matches_runtime(
        matching,
        requested_model=JUDGE,
        requested_effort="xhigh",
    )
    assert not runtime.cache_matches_runtime(
        {"ok": True, "model": SUPERSEDED[0]},
        requested_model=JUDGE,
        requested_effort="high",
    )
    switched = {
        "ok": True,
        "runtime_receipt": {
            "requested_model": JUDGE,
            "requested_effort": "high",
            "effective_model": OTHER,
            "effective_model_source": "response_metadata",
            "fallback": True,
        },
    }
    assert not runtime.cache_matches_runtime(
        switched,
        requested_model=JUDGE,
        requested_effort="high",
    )


def test_standalone_judge_cli_resolves_runtime_and_writes_receipt(
    tmp_path,
    monkeypatch,
):
    judge = _load_anthropic_script("score_llm_judge")
    client = _Client(_response(text='{"rc1":"endorse"}'))
    run_dir = tmp_path / "run"
    persona_dir = run_dir / "results-by-persona"
    persona_dir.mkdir(parents=True)
    (run_dir / "fixture.yaml").write_text(
        "problem: plateau\n"
        "root_causes:\n"
        "  RC1:\n"
        "    short_name: subset\n"
        "false_leads: {}\n",
        encoding="utf-8",
    )
    persona_path = persona_dir / "persona_01.json"
    persona_path.write_text(
        '{"dispatch":{"ok":true,"text":"inspect subset"}}',
        encoding="utf-8",
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-key")
    monkeypatch.setenv("PERSONA_JUDGE_MODEL", JUDGE)
    monkeypatch.setenv("PERSONA_JUDGE_EFFORT", "xhigh")
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: client)
    monkeypatch.setattr(sys, "argv", ["score_llm_judge.py", str(run_dir)])

    assert judge.main() == 0
    updated = __import__("json").loads(persona_path.read_text(encoding="utf-8"))
    result = updated["scoring"]["llm_judge"]
    assert client.messages.request["model"] == JUDGE
    assert client.messages.request["output_config"] == {"effort": "xhigh"}
    assert result["runtime_receipt"]["requested_model"] == JUDGE
    assert result["runtime_receipt"]["requested_effort"] == "xhigh"


def test_operational_docs_and_templates_use_current_runtime_contract():
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    rubric_template = (SKILL / "templates" / "rubric.yaml").read_text(
        encoding="utf-8"
    )
    prereg = (SKILL / "templates" / "pre-registration.md").read_text(
        encoding="utf-8"
    )
    rubric_mode = (SKILL / "references" / "rubric-mode.md").read_text(
        encoding="utf-8"
    )
    active_code = "\n".join(
        (SCRIPTS / name).read_text(encoding="utf-8")
        for name in ("dispatch.py", "score_llm_judge.py", "model_runtime.py")
    )

    assert "../_shared/model-runtime-policy.md" in skill
    assert "runtime_receipt" in skill
    assert "PERSONA_COVERED_MODEL_RETENTION_APPROVED" in skill
    assert "effective model exactly matches the requested model" in skill
    assert "model_unobserved" in skill
    assert "failed closed" in skill.lower()
    assert "Run complete" in skill
    assert f"judge: {JUDGE}" in rubric_template
    assert "judge_effort: high" in rubric_template
    assert ids.display_name("opus").removeprefix("Claude ") in prereg and "high effort" in prereg
    assert "Current operational default" in rubric_mode
    assert "Historical cost baseline" in rubric_mode
    for superseded in SUPERSEDED:
        assert not ids.names(active_code, superseded)


def test_provider_errors_are_typed_and_keep_unobserved_runtime_unavailable():
    dispatch = _load_anthropic_script("dispatch")
    judge = _load_anthropic_script("score_llm_judge")
    framework = {
        "id": "systems",
        "name": "Systems",
        "group": "engineering",
        "body": "Observe interactions.",
    }

    producer_result = dispatch.dispatch_one(
        _RaisingClient(),
        framework,
        "Find the blind spot",
        JUDGE,
        effort="high",
    )
    judge_result = judge.judge(
        _RaisingClient(),
        {"problem": "plateau", "root_causes": {}, "false_leads": {}},
        "Inspect the subset",
        JUDGE,
        effort="high",
    )

    for result in (producer_result, judge_result):
        assert result["ok"] is False
        assert result["error_type"] == "transport_or_api"
        assert result["runtime_receipt"]["effective_model"] == "<unavailable>"
        assert result["runtime_receipt"]["fallback"] == "<unavailable>"


def test_invalid_judge_json_is_failed_evidence_not_a_success():
    judge = _load_anthropic_script("score_llm_judge")
    client = _Client(_response(text="not-json"))

    result = judge.judge(
        client,
        {"problem": "plateau", "root_causes": {}, "false_leads": {}},
        "Inspect the subset",
        JUDGE,
        effort="high",
    )

    assert result["ok"] is False
    assert result["error_type"] == "invalid_response"
    assert "_parse_error" in result["judgment"]
    assert result["runtime_receipt"]["effective_model"] == JUDGE


def test_rubric_fixture_pins_both_model_and_effort_lanes(tmp_path, monkeypatch):
    dispatch = _load_anthropic_script("dispatch")
    fixture = tmp_path / "fixture.yaml"
    fixture.write_text(
        "problem: Investigate the plateau\n"
        "provenance:\n"
        "  fixture_author: independent reviewer\n"
        "  inventory_authored_by: curator\n"
        "  independent: true\n"
        "cohort:\n"
        "  n: 1\n"
        "  sampling: bucket\n"
        "models:\n"
        f"  persona: {OTHER}\n"
        "  persona_effort: medium\n"
        f"  judge: {JUDGE}\n"
        "  judge_effort: xhigh\n",
        encoding="utf-8",
    )
    args = __import__("argparse").Namespace(
        fixture=str(fixture),
        n=None,
        sampling=None,
        model=None,
        effort=None,
        judge_model=None,
        judge_effort=None,
        override_fixture=False,
        slug="fixture-runtime",
        frameworks="",
        inventory=None,
        seed=7,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-key")
    monkeypatch.setenv("PERSONA_MODEL", HAIKU_SNAPSHOT)
    monkeypatch.setenv("PERSONA_JUDGE_EFFORT", "low")
    monkeypatch.setattr(dispatch, "DEFAULT_RUN_BASE", tmp_path / "runs")
    monkeypatch.setattr(dispatch, "parse_file", lambda _path: [])

    class _StopAfterResolution(Exception):
        pass

    monkeypatch.setattr(
        dispatch,
        "sample",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_StopAfterResolution()),
    )

    with pytest.raises(_StopAfterResolution):
        dispatch.run_rubric(args)

    assert args.model == OTHER
    assert args.effort == "medium"
    assert args.judge_model == JUDGE
    assert args.judge_effort == "xhigh"


def test_discovery_cli_reports_retention_configuration_error_without_dispatch(
    monkeypatch,
    capsys,
):
    dispatch = _load_anthropic_script("dispatch")
    monkeypatch.setenv("PERSONA_MODEL", FABLE)
    monkeypatch.delenv("PERSONA_COVERED_MODEL_RETENTION_APPROVED", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dispatch.py",
            "discovery",
            "Find the blind spot",
            "--slug",
            "retention-refusal",
            "--criteria-met",
            "2",
        ],
    )
    monkeypatch.setattr(
        dispatch,
        "run_discovery",
        lambda _args: pytest.fail("dispatch must not start on invalid retention config"),
    )

    assert dispatch.main() == 2
    assert "configuration error" in capsys.readouterr().err.lower()


def test_standalone_judge_help_does_not_require_api_credentials(monkeypatch):
    judge = _load_anthropic_script("score_llm_judge")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["score_llm_judge.py", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        judge.main()

    assert exc_info.value.code == 0


def test_discovery_run_fails_closed_when_a_persona_dispatch_fails(
    tmp_path,
    monkeypatch,
    capsys,
):
    dispatch = _load_anthropic_script("dispatch")
    run_base = tmp_path / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-key")
    monkeypatch.setattr(dispatch, "DEFAULT_RUN_BASE", run_base)
    monkeypatch.setattr(dispatch, "parse_file", lambda _path: [_framework()])
    monkeypatch.setattr(dispatch, "sample", lambda *_args, **_kwargs: [_framework()])
    monkeypatch.setattr(dispatch.anthropic, "Anthropic", object)
    monkeypatch.setattr(
        dispatch,
        "dispatch_one",
        lambda *_args, **_kwargs: _failed_result("refusal"),
    )
    args = __import__("argparse").Namespace(
        inventory=None,
        seed=7,
        slug="failed-discovery",
        sampling="bucket",
        behaviors="",
        cohort_yaml=None,
        min_confidence="MED",
        n=1,
        problem="Find the blind spot",
        model=JUDGE,
        effort="high",
        inversion=False,
    )

    assert dispatch.run_discovery(args) == 1
    captured = capsys.readouterr()
    assert "Run complete" not in captured.out
    assert "failed closed" in captured.err.lower()
    assert not (run_base / "INDEX.md").exists()
    analysis = run_base / "failed-discovery" / "analysis.md"
    assert analysis.exists()
    assert "DISPATCH FAILED" in analysis.read_text(encoding="utf-8")


def test_rubric_run_fails_closed_before_scoring_when_dispatch_fails(
    tmp_path,
    monkeypatch,
    capsys,
):
    dispatch = _load_anthropic_script("dispatch")
    fixture = tmp_path / "fixture.yaml"
    fixture.write_text(
        "problem: Investigate the plateau\n"
        "provenance:\n"
        "  fixture_author: independent reviewer\n"
        "  inventory_authored_by: curator\n"
        "  independent: true\n"
        "root_causes: {}\n"
        "false_leads: {}\n"
        "cohort:\n"
        "  n: 1\n"
        "  sampling: bucket\n"
        "models:\n"
        f"  persona: {JUDGE}\n"
        "  persona_effort: high\n"
        f"  judge: {JUDGE}\n"
        "  judge_effort: high\n",
        encoding="utf-8",
    )
    run_base = tmp_path / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-key")
    monkeypatch.setattr(dispatch, "DEFAULT_RUN_BASE", run_base)
    monkeypatch.setattr(dispatch, "parse_file", lambda _path: [_framework()])
    monkeypatch.setattr(dispatch, "sample", lambda *_args, **_kwargs: [_framework()])
    monkeypatch.setattr(dispatch.anthropic, "Anthropic", object)
    monkeypatch.setattr(
        dispatch,
        "dispatch_one",
        lambda *_args, **_kwargs: _failed_result("transport_or_api"),
    )
    args = __import__("argparse").Namespace(
        fixture=str(fixture),
        n=None,
        sampling=None,
        model=None,
        effort=None,
        judge_model=None,
        judge_effort=None,
        override_fixture=False,
        slug="failed-rubric-dispatch",
        frameworks="",
        inventory=None,
        seed=7,
    )

    assert dispatch.run_rubric(args) == 1
    captured = capsys.readouterr()
    assert "Run complete" not in captured.out
    assert "failed closed" in captured.err.lower()
    assert not (run_base / "INDEX.md").exists()
    result_path = (
        run_base
        / "failed-rubric-dispatch"
        / "results-by-persona"
        / "persona_01_systems.json"
    )
    assert result_path.exists()


def test_rubric_run_fails_closed_when_a_judgment_is_invalid(
    tmp_path,
    monkeypatch,
    capsys,
):
    dispatch = _load_anthropic_script("dispatch")
    judge_module = _load_anthropic_script("score_llm_judge")
    monkeypatch.setitem(sys.modules, "score_llm_judge", judge_module)
    fixture = tmp_path / "fixture.yaml"
    fixture.write_text(
        "problem: Investigate the plateau\n"
        "provenance:\n"
        "  fixture_author: independent reviewer\n"
        "  inventory_authored_by: curator\n"
        "  independent: true\n"
        "root_causes:\n"
        "  RC1:\n"
        "    short_name: subset\n"
        "    keywords: [subset]\n"
        "false_leads: {}\n"
        "cohort:\n"
        "  n: 1\n"
        "  sampling: bucket\n"
        "models:\n"
        f"  persona: {JUDGE}\n"
        "  persona_effort: high\n"
        f"  judge: {JUDGE}\n"
        "  judge_effort: high\n",
        encoding="utf-8",
    )
    run_base = tmp_path / "runs"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-key")
    monkeypatch.setattr(dispatch, "DEFAULT_RUN_BASE", run_base)
    monkeypatch.setattr(dispatch, "parse_file", lambda _path: [_framework()])
    monkeypatch.setattr(dispatch, "sample", lambda *_args, **_kwargs: [_framework()])
    monkeypatch.setattr(dispatch.anthropic, "Anthropic", object)
    monkeypatch.setattr(dispatch, "dispatch_one", lambda *_args, **_kwargs: _successful_result())
    monkeypatch.setattr(
        judge_module,
        "judge",
        lambda *_args, **_kwargs: _failed_result("invalid_response"),
    )
    args = __import__("argparse").Namespace(
        fixture=str(fixture),
        n=None,
        sampling=None,
        model=None,
        effort=None,
        judge_model=None,
        judge_effort=None,
        override_fixture=False,
        slug="failed-rubric-judge",
        frameworks="",
        inventory=None,
        seed=7,
    )

    assert dispatch.run_rubric(args) == 1
    captured = capsys.readouterr()
    assert "Run complete" not in captured.out
    assert "failed closed" in captured.err.lower()
    assert not (run_base / "INDEX.md").exists()
    result_path = (
        run_base
        / "failed-rubric-judge"
        / "results-by-persona"
        / "persona_01_systems.json"
    )
    updated = __import__("json").loads(result_path.read_text(encoding="utf-8"))
    assert updated["scoring"]["llm_judge"]["ok"] is False


@pytest.mark.parametrize(
    "failure_mode",
    ["refusal", "truncation", "invalid_json", "provider", "model_mismatch"],
)
def test_standalone_judge_cli_fails_closed_on_any_failed_judgment(
    failure_mode,
    tmp_path,
    monkeypatch,
    capsys,
):
    judge = _load_anthropic_script("score_llm_judge")
    run_dir = tmp_path / failure_mode
    persona_dir = run_dir / "results-by-persona"
    persona_dir.mkdir(parents=True)
    (run_dir / "fixture.yaml").write_text(
        "problem: plateau\n"
        "root_causes:\n"
        "  RC1:\n"
        "    short_name: subset\n"
        "false_leads: {}\n",
        encoding="utf-8",
    )
    persona_path = persona_dir / "persona_01.json"
    persona_path.write_text(
        '{"dispatch":{"ok":true,"text":"inspect subset"}}',
        encoding="utf-8",
    )
    response_by_mode = {
        "refusal": _response(stop_reason="refusal", text="cannot score"),
        "truncation": _response(stop_reason="max_tokens", text="{"),
        "invalid_json": _response(text="not-json"),
        "model_mismatch": _response(
            model=OTHER,
            text='{"rc1":"endorse"}',
        ),
    }
    client = (
        _RaisingClient()
        if failure_mode == "provider"
        else _Client(response_by_mode[failure_mode])
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-not-a-key")
    monkeypatch.setenv("PERSONA_JUDGE_MODEL", JUDGE)
    monkeypatch.setenv("PERSONA_JUDGE_EFFORT", "high")
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: client)
    monkeypatch.setattr(sys, "argv", ["score_llm_judge.py", str(run_dir)])

    assert judge.main() == 1
    captured = capsys.readouterr()
    assert "scored 1 new persona outputs" not in captured.out
    assert "failed closed" in captured.err.lower()
    updated = __import__("json").loads(persona_path.read_text(encoding="utf-8"))
    assert updated["scoring"]["llm_judge"]["ok"] is False
