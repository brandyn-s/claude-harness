"""Tests for chatgpt.py — run from ~/.claude/scripts/ via `pytest test_chatgpt.py`."""
# pyright: reportMissingImports=false
# (chatgpt is a sibling script; pytest resolves it at runtime via rootdir.)
from __future__ import annotations

import io
import json as _json
import sys
from unittest import mock

import pytest

import chatgpt


# ---------- estimate_cost ----------

def test_estimate_cost_known_model_simple_math():
    assert chatgpt.estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == "$0.750000"


def test_estimate_cost_zero_tokens():
    assert chatgpt.estimate_cost("gpt-4o-mini", 0, 0) == "$0.000000"


def test_estimate_cost_unknown_model():
    assert chatgpt.estimate_cost("future-model", 100, 100) == "(unknown pricing)"


# ---------- parse_args ----------

def test_parse_args_defaults():
    a = chatgpt.parse_args(["hello"])
    assert a.prompt == "hello"
    assert a.model == "gpt-5.5"
    assert a.effort is None
    assert a.system is None
    assert a.temperature is None
    assert a.json is False


def test_parse_args_all_flags():
    a = chatgpt.parse_args(["-m", "gpt-4o", "-s", "be terse", "-t", "0.2", "-j", "hi"])
    assert a.model == "gpt-4o"
    assert a.system == "be terse"
    assert a.temperature == 0.2
    assert a.json is True
    assert a.prompt == "hi"


def test_parse_args_no_prompt():
    a = chatgpt.parse_args([])
    assert a.prompt is None


def test_parse_args_max_tokens():
    a = chatgpt.parse_args(["-x", "256", "hello"])
    assert a.max_tokens == 256


def test_parse_args_effort():
    a = chatgpt.parse_args(["-e", "high", "hello"])
    assert a.effort == "high"


def test_parse_args_seed():
    a = chatgpt.parse_args(["--seed", "42", "hello"])
    assert a.seed == 42


def test_parse_args_effort_rejects_invalid():
    with pytest.raises(SystemExit):
        chatgpt.parse_args(["-e", "extreme", "hello"])


# ---------- build_payload (Responses-API shape) ----------

def test_build_payload_user_only():
    a = chatgpt.parse_args(["hello"])
    p = chatgpt.build_payload("hello", a)
    assert p == {
        "model": "gpt-5.5",
        "input": "hello",
        "reasoning": {"effort": "xhigh"},
    }


def test_build_payload_with_system_uses_instructions():
    a = chatgpt.parse_args(["-s", "be terse", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["instructions"] == "be terse"
    assert p["input"] == "hello"
    assert "messages" not in p


def test_build_payload_with_temperature_on_chat_model():
    # Pinned to gpt-4o-mini because reasoning models reject temperature.
    a = chatgpt.parse_args(["-m", "gpt-4o-mini", "-t", "0.5", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["temperature"] == 0.5


def test_build_payload_temperature_dropped_with_warning_on_reasoning_model(capsys):
    # Default model is gpt-5.5 (reasoning) — temperature is rejected by API.
    a = chatgpt.parse_args(["-t", "0.5", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert "temperature" not in p
    err = capsys.readouterr().err
    assert "temperature" in err and "gpt-5.5" in err


def test_build_payload_omits_temperature_when_unset():
    a = chatgpt.parse_args(["hello"])
    p = chatgpt.build_payload("hello", a)
    assert "temperature" not in p


def test_build_payload_max_tokens_uses_max_output_tokens():
    a = chatgpt.parse_args(["-x", "100", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["max_output_tokens"] == 100
    assert "max_completion_tokens" not in p


def test_build_payload_reasoning_is_nested_object():
    a = chatgpt.parse_args(["-e", "low", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["reasoning"] == {"effort": "low"}
    assert "reasoning_effort" not in p


def test_build_payload_defaults_xhigh_for_gpt55():
    a = chatgpt.parse_args(["hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["reasoning"] == {"effort": "xhigh"}


def test_build_payload_defaults_high_for_o3_mini():
    a = chatgpt.parse_args(["-m", "o3-mini", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["reasoning"] == {"effort": "high"}


def test_build_payload_defaults_high_for_gpt5():
    a = chatgpt.parse_args(["-m", "gpt-5", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["reasoning"] == {"effort": "high"}


def test_build_payload_omits_reasoning_for_non_reasoning_model():
    a = chatgpt.parse_args(["-m", "gpt-4o-mini", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert "reasoning" not in p


def test_build_payload_explicit_effort_dropped_with_warning_for_non_reasoning(capsys):
    a = chatgpt.parse_args(["-m", "gpt-4o-mini", "-e", "high", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert "reasoning" not in p
    err = capsys.readouterr().err
    assert "gpt-4o-mini" in err and "reasoning_effort" in err


def test_build_payload_seed_is_dropped_with_warning(capsys):
    a = chatgpt.parse_args(["--seed", "42", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert "seed" not in p
    err = capsys.readouterr().err
    assert "seed" in err


def test_build_payload_combines_all_flags():
    a = chatgpt.parse_args(["-m", "o3-mini", "-e", "high", "-x", "500",
                            "-s", "be terse", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["model"] == "o3-mini"
    assert p["input"] == "hello"
    assert p["reasoning"] == {"effort": "high"}
    assert p["max_output_tokens"] == 500
    assert p["instructions"] == "be terse"


# ---------- extract_text ----------

def test_extract_text_finds_message_skipping_reasoning_item():
    data = {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [
                {"type": "output_text", "text": "hello world"}
            ]},
        ]
    }
    assert chatgpt.extract_text(data) == "hello world"


def test_extract_text_returns_empty_when_no_message():
    data = {"output": [{"type": "reasoning", "summary": []}]}
    assert chatgpt.extract_text(data) == ""


def test_extract_text_returns_empty_on_missing_output():
    assert chatgpt.extract_text({}) == ""


# ---------- read_prompt ----------

def test_read_prompt_positional_wins():
    a = chatgpt.parse_args(["from-arg"])
    assert chatgpt.read_prompt(a) == "from-arg"


def test_read_prompt_from_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("piped prompt"))
    a = chatgpt.parse_args([])
    assert chatgpt.read_prompt(a) == "piped prompt"


def test_read_prompt_no_input_exits(monkeypatch, capsys):
    fake_stdin = io.StringIO("")
    fake_stdin.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    a = chatgpt.parse_args([])
    with pytest.raises(SystemExit) as exc:
        chatgpt.read_prompt(a)
    assert exc.value.code == 2
    assert "no prompt" in capsys.readouterr().err


# ---------- call_api ----------

def _fake_response(status: int, body: dict | None = None, text: str = ""):
    r = mock.Mock()
    r.status_code = status
    r.ok = status < 400
    r.text = text
    r.json.return_value = body if body is not None else {}
    return r


def test_call_api_success_returns_json():
    body = {"output": [], "usage": {}}
    with mock.patch("chatgpt.requests.post", return_value=_fake_response(200, body)):
        result = chatgpt.call_api("sk-test", {"model": "gpt-5.5", "input": "hi"})
    assert result == body


@pytest.mark.parametrize("status,exit_code,frag", [
    (401, 3, "401"),
    (404, 4, "404"),
    (429, 5, "429"),
    (500, 6, "500"),
])
def test_call_api_error_codes(capsys, status, exit_code, frag):
    with mock.patch("chatgpt.requests.post",
                    return_value=_fake_response(status, text=f"err{status}")):
        with pytest.raises(SystemExit) as exc:
            chatgpt.call_api("sk-test", {"model": "gpt-5.5", "input": "hi"})
        assert exc.value.code == exit_code
    assert frag in capsys.readouterr().err


# ---------- main ----------

def test_main_no_api_key(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rc = chatgpt.main(["hello"])
    assert rc == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_main_success_text_output(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    body = {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": "hi back"}]},
        ],
        "usage": {"input_tokens": 5, "output_tokens": 2},
    }
    with mock.patch("chatgpt.requests.post", return_value=_fake_response(200, body)):
        rc = chatgpt.main(["-m", "gpt-4o-mini", "hello"])
    out = capsys.readouterr()
    assert rc == 0
    assert "hi back" in out.out
    assert "tokens: 5 in / 2 out" in out.out
    assert "gpt-4o-mini" in out.out
    assert out.err == ""


def test_main_json_flag_outputs_full_response(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    body = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "x"}]}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    with mock.patch("chatgpt.requests.post", return_value=_fake_response(200, body)):
        chatgpt.main(["-j", "hello"])
    parsed = _json.loads(capsys.readouterr().out)
    assert parsed == body
