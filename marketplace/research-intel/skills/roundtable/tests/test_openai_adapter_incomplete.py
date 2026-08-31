"""Regression tests for the openai_adapter incomplete-response guard.

Bug (2026-06-07): on /v1/responses, max_output_tokens caps reasoning + visible
output COMBINED. When reasoning exhausts the budget the response is
status='incomplete' (still HTTP 200) with no message item. The adapter used to
return json.dumps(data)[:1000] as ok:True -> silent garbage in roundtable.
These tests lock in: incomplete -> ok:False; empty -> ok:False; message -> ok:True.
"""
import sys
from pathlib import Path

ADAPTERS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "adapters"
sys.path.insert(0, str(ADAPTERS_DIR))

import openai_adapter  # noqa: E402


def _fake_http(response: dict):
    def _inner(url, payload, headers, retry_on_transient=True):
        return {"response": response, "status_code": 200,
                "retried": False, "elapsed_s": 0.1}
    return _inner


def test_incomplete_returns_ok_false(monkeypatch):
    """The core bug: reasoning exhausted the budget -> must NOT be ok:True."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(openai_adapter, "http_post_json", _fake_http({
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "reasoning", "content": []}],
        "usage": {"output_tokens": 16000,
                  "output_tokens_details": {"reasoning_tokens": 16000}},
        "model": "gpt-5.5-pro",
    }))
    r = openai_adapter.call("hi", max_tokens=16000)
    assert r["ok"] is False
    assert "incomplete" in r["error"].lower()
    assert "16000" in r["error"]  # surfaces the budget that was too small


def test_empty_completed_returns_ok_false(monkeypatch):
    """A 'completed' response with only a reasoning item (no message) is empty."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(openai_adapter, "http_post_json", _fake_http({
        "status": "completed",
        "output": [{"type": "reasoning", "content": []}],
        "usage": {"output_tokens": 50},
        "model": "gpt-5.5-pro",
    }))
    r = openai_adapter.call("hi")
    assert r["ok"] is False
    assert "no output_text" in r["error"].lower()


def test_completed_with_message_returns_ok_true(monkeypatch):
    """Happy path: a real message item is extracted as ok:True."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(openai_adapter, "http_post_json", _fake_http({
        "status": "completed",
        "output": [
            {"type": "reasoning", "content": []},
            {"type": "message",
             "content": [{"type": "output_text", "text": "hello world"}]},
        ],
        "usage": {"input_tokens": 5, "output_tokens": 12},
        "model": "gpt-5.5-pro",
    }))
    r = openai_adapter.call("hi")
    assert r["ok"] is True
    assert r["text"] == "hello world"
    assert r["output_tokens"] == 12
