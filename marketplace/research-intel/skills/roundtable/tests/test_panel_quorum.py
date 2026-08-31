"""The live harness must stop spending when the vendor panel collapses."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest


HARNESS = Path(__file__).resolve().parent.parent / "scripts" / "harness.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("roundtable_harness_quorum", HARNESS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_two_distinct_successful_vendors_meet_quorum():
    harness = _load_harness()
    results = {
        "opus": {"ok": True},
        "grok": {"ok": True},
        "gpt": {"ok": False},
    }

    assert harness.successful_panel_agents(results) == ("opus", "grok")
    assert harness.panel_has_quorum(results) is True


def test_single_survivor_is_not_panel_consensus():
    harness = _load_harness()
    results = {
        "opus": {"ok": True},
        "grok": {"ok": False},
        "gpt": {"ok": False},
    }

    assert harness.successful_panel_agents(results) == ("opus",)
    assert harness.panel_has_quorum(results) is False


def test_run_phase_uses_anthropic_model_effort_headroom(tmp_path, monkeypatch):
    harness = _load_harness()
    observed = {}

    monkeypatch.setenv("ROUNDTABLE_ANTHROPIC_EFFORT", "xhigh")

    def fake_call(agent, _prompt, max_tokens):
        observed[agent] = max_tokens
        return {
            "ok": True,
            "text": f"{agent} result",
            "input_tokens": 10,
            "output_tokens": 5,
            "elapsed_s": 0.1,
            "model": {
                "opus": "claude-fable-5",
                "grok": "grok-4.6",
                "gpt": "gpt-5.6-sol",
            }[agent],
        }

    monkeypatch.setattr(harness, "call_agent", fake_call)

    results, _cost = harness.run_phase(
        1,
        "main",
        "target context",
        tmp_path,
        tmp_path / "transcript.jsonl",
    )

    assert results["opus"]["ok"] is True
    assert observed["opus"] == 64_000
    assert observed["grok"] == 4_000
    assert observed["gpt"] == 32_000

    records = [
        json.loads(line)
        for line in (tmp_path / "transcript.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert {record["runtime_receipt"]["provider"] for record in records} == {
        "anthropic",
        "xai",
        "openai",
    }
    for record in records:
        assert {
            "requested_model",
            "effective_model",
            "effort",
            "provider",
            "context_class",
            "claude_code_version",
            "fallback",
            "switch_reason",
            "refusal",
        } <= record["runtime_receipt"].keys()
        assert record["runtime_receipt"]["context_class"] == "<unavailable>"


def test_run_start_event_contains_nested_runtime_receipt(
    tmp_path, monkeypatch, stub_panel_credentials
):
    harness = _load_harness()
    context = tmp_path / "context.md"
    context.write_text("target", encoding="utf-8")
    output = tmp_path / "run"

    monkeypatch.setattr(
        harness,
        "run_phase",
        lambda *_args, **_kwargs: (
            {agent: {"ok": False} for agent in harness.PANEL_AGENTS},
            0.0,
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness.py",
            "--context",
            str(context),
            "--output",
            str(output),
            "--no-inject-agent-d",
            "--skip-preflight",
        ],
    )

    assert harness.main() == 2
    first = json.loads(
        (output / "transcript.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert first["event"] == "run_start"
    assert first["runtime_receipt"]["provider"] == "anthropic"
    assert first["runtime_receipt"]["requested_model"] == "claude-fable-5"
    assert first["runtime_receipt"]["effective_model"] == "<unavailable>"
    assert first["runtime_receipt"]["context_class"] == "<unavailable>"


def test_harness_records_context_class_only_from_explicit_result_metadata():
    harness = _load_harness()

    unobserved = harness.result_runtime_receipt(
        "opus", {"ok": True, "model": "claude-fable-5"}
    )
    observed = harness.result_runtime_receipt(
        "opus",
        {
            "ok": True,
            "model": "claude-fable-5",
            "context_class": "runtime-observed",
        },
    )

    assert unobserved["context_class"] == "<unavailable>"
    assert observed["context_class"] == "runtime-observed"


def test_harness_rejects_reused_output_directory_before_dispatch(
    tmp_path, monkeypatch
):
    harness = _load_harness()
    context = tmp_path / "context.md"
    context.write_text("target", encoding="utf-8")
    output = tmp_path / "existing-run"
    output.mkdir()
    transcript = output / "transcript.jsonl"
    transcript.write_text('{"event":"run_start"}\n', encoding="utf-8")

    def should_not_dispatch(*_args, **_kwargs):
        raise AssertionError("reused output directory must fail before provider dispatch")

    monkeypatch.setattr(harness, "run_phase", should_not_dispatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness.py",
            "--context",
            str(context),
            "--output",
            str(output),
            "--skip-preflight",
        ],
    )

    assert harness.main() == 2
    assert transcript.read_text(encoding="utf-8") == '{"event":"run_start"}\n'


@pytest.mark.parametrize("guard", ["reused_output_dir", "missing_agent_d_seed"])
def test_cheap_guards_return_2_before_the_credential_gate_when_keyless(
    guard, tmp_path, monkeypatch, no_panel_credentials
):
    """Pin the ORDER of main()'s two cheap guards against the credential gate.

    Both guards `return 2` for a caller error. The credential gate `sys.exit(str)`s,
    which is a SystemExit — a different outcome entirely. So if the gate is ever
    moved back ABOVE them, a keyless host stops reaching them and this fails on the
    SystemExit rather than on a wrong return value.

    The ordering is not cosmetic. Those guards deliberately fire before the output
    directory is created, because a run that poisons its own directory makes the
    rerun they instruct impossible — a credential abort ahead of them defeats that.
    It is also what makes the guards' own tests runnable on a keyless CI runner.

    One case per guard, so each has a fixture only IT covers: a reused directory
    cannot exercise the seed check, and a fresh directory cannot exercise reuse.
    A single combined fixture would let either guard alone keep this green.
    """
    harness = _load_harness()
    context = tmp_path / "context.md"
    context.write_text("target", encoding="utf-8")
    output = tmp_path / "run"
    argv = ["harness.py", "--context", str(context), "--output", str(output),
            "--skip-preflight"]

    if guard == "reused_output_dir":
        # Non-empty and not the permitted Agent D seed. --no-inject-agent-d keeps
        # the seed check out of the way so reuse is the only guard that can fire.
        output.mkdir()
        (output / "transcript.jsonl").write_text('{"event":"run_start"}\n',
                                                 encoding="utf-8")
        argv.append("--no-inject-agent-d")
    else:
        # Fresh directory, injection left at its default (ON since #2218), so the
        # absent round_1/agent_d.md seed is the only guard that can fire.
        assert not output.exists()

    monkeypatch.setattr(
        harness, "run_phase",
        lambda *_a, **_k: pytest.fail("must not dispatch on a caller error"))
    monkeypatch.setattr(sys, "argv", argv)

    assert harness.main() == 2


def test_credential_gate_still_aborts_when_the_cheap_guards_pass(
    tmp_path, monkeypatch, no_panel_credentials
):
    """The other half: reordering must not have made the gate skippable.

    Moving a gate later is one edit away from moving it out of the way. A keyless
    run whose arguments are VALID has no caller error to return 2 on, so it must
    reach the credential gate and abort there. Without this, the reorder above
    would be indistinguishable from deleting the gate — the exact 'green a check
    by narrowing its detector' shape.
    """
    harness = _load_harness()
    context = tmp_path / "context.md"
    context.write_text("target", encoding="utf-8")
    output = tmp_path / "fresh-run"

    monkeypatch.setattr(
        harness, "run_phase",
        lambda *_a, **_k: pytest.fail("must not dispatch without credentials"))
    monkeypatch.setattr(
        sys, "argv",
        ["harness.py", "--context", str(context), "--output", str(output),
         "--skip-preflight", "--no-inject-agent-d"],
    )

    with pytest.raises(SystemExit) as abort:
        harness.main()
    # Assert the IDENTITY of the abort, not merely that something exited: argparse
    # and several later stages also raise SystemExit.
    message = str(abort.value)
    assert "no credential resolved" in message
    for key in ("ANTHROPIC_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY"):
        assert key in message, f"gate must name the unresolved key {key}"
    assert not output.exists(), (
        "the gate must fire before mkdir; a poisoned output dir would make the "
        "retry trip the reuse guard instead of showing the real error"
    )


def test_output_reuse_guard_allows_only_the_documented_agent_d_seed(tmp_path):
    harness = _load_harness()
    output = tmp_path / "agent-d-seed"
    round_one = output / "round_1"
    round_one.mkdir(parents=True)
    (round_one / "agent_d.md").write_text("null control", encoding="utf-8")

    assert harness.output_reuse_error(output, inject_agent_d=True) is None
    assert harness.output_reuse_error(output, inject_agent_d=False) is not None

    (output / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
    assert harness.output_reuse_error(output, inject_agent_d=True) is not None


def test_budget_abort_after_round_one_is_not_recorded_as_run_complete(
    tmp_path, monkeypatch, stub_panel_credentials
):
    harness = _load_harness()
    context = tmp_path / "context.md"
    context.write_text("target", encoding="utf-8")
    output = tmp_path / "budget-run"
    calls = iter((0.5, 0.75))

    def successful_round(*_args, **_kwargs):
        return (
            {agent: {"ok": True} for agent in harness.PANEL_AGENTS},
            next(calls),
        )

    monkeypatch.setattr(harness, "run_phase", successful_round)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness.py",
            "--context",
            str(context),
            "--output",
            str(output),
            "--max-rounds",
            "2",
            "--budget",
            "1",
            "--no-inject-agent-d",
            "--skip-preflight",
        ],
    )

    assert harness.main() == 0
    events = [
        json.loads(line).get("event")
        for line in (output / "transcript.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert events[-1] == "budget_abort"
    assert "run_complete" not in events


def test_missing_agent_d_seed_does_not_poison_the_requested_output_dir(
    tmp_path, monkeypatch
):
    harness = _load_harness()
    context = tmp_path / "context.md"
    context.write_text("target", encoding="utf-8")
    output = tmp_path / "agent-d-run"

    def should_not_dispatch(*_args, **_kwargs):
        raise AssertionError("missing Agent D seed must stop before provider dispatch")

    monkeypatch.setattr(harness, "run_phase", should_not_dispatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness.py",
            "--context",
            str(context),
            "--output",
            str(output),
            "--inject-agent-d",
            "--skip-preflight",
        ],
    )

    assert harness.main() == 2
    assert not (output / "transcript.jsonl").exists()
    assert harness.output_reuse_error(output, inject_agent_d=True) is None


def test_run_phase_does_not_count_a_provider_model_switch_as_quorum(
    tmp_path, monkeypatch
):
    harness = _load_harness()

    def fake_call(agent, _prompt, _max_tokens):
        models = {
            "opus": "claude-fable-5",
            "grok": "grok-unexpected-fallback",
            "gpt": "gpt-5.6-sol",
        }
        return {
            "ok": True,
            "text": f"{agent} result",
            "input_tokens": 1,
            "output_tokens": 1,
            "elapsed_s": 0.1,
            "model": models[agent],
        }

    monkeypatch.setattr(harness, "call_agent", fake_call)

    results, _cost = harness.run_phase(
        1,
        "main",
        "target context",
        tmp_path,
        tmp_path / "transcript.jsonl",
    )

    assert results["grok"]["ok"] is False
    assert results["grok"]["error_type"] == "model_switch"
    assert harness.successful_panel_agents(results) == ("opus", "gpt")
    records = [
        json.loads(line)
        for line in (tmp_path / "transcript.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    grok_record = next(record for record in records if record["agent"] == "grok")
    assert grok_record["ok"] is False
    assert grok_record["runtime_receipt"]["fallback"] is True


def test_null_control_is_injected_by_default(tmp_path, monkeypatch):
    """The Agent D null control is ON by default, so a seedless run must stop.

    This pins the DEFAULT, not the flag: if --inject-agent-d ever reverts to
    store_true, main() sails past the seed check and this test fails. Without
    the null control a convergent finding cannot be distinguished from
    correlated credulity, which is why the default is not a preference.

    Keychain is pinned at its seam so the assertion measures the default rather
    than whether this particular host happens to hold provider keys.
    """
    harness = _load_harness()
    context = tmp_path / "context.md"
    context.write_text("target", encoding="utf-8")
    output = tmp_path / "default-null-control"

    monkeypatch.setattr(harness.keychain, "load_keys", lambda names=None: [])
    monkeypatch.setattr(harness.keychain, "missing_required", lambda: [])

    def should_not_dispatch(*_args, **_kwargs):
        raise AssertionError(
            "a seedless default-on run must stop before provider dispatch"
        )

    monkeypatch.setattr(harness, "run_phase", should_not_dispatch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness.py",
            "--context",
            str(context),
            "--output",
            str(output),
            "--skip-preflight",
        ],
    )

    assert harness.main() == 2
    assert not (output / "transcript.jsonl").exists()
