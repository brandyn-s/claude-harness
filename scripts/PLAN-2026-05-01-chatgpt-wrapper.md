# ChatGPT Direct-API Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a `chatgpt` CLI command that sends a one-shot prompt to OpenAI's Chat Completions API, prints the response on stdout, and reports token usage + estimated cost on stderr.

**Architecture:** A single-file Python 3 script (`~/.claude/scripts/chatgpt.py`) using `requests`. Entry point split into pure functions (`parse_args`, `build_payload`, `estimate_cost`, `read_prompt`) plus an HTTP boundary (`call_api`) and an orchestrator (`main`). A thin Bash wrapper at `~/bin/chatgpt` invokes the script. Pytest covers all pure functions and mocks the HTTP layer.

**Tech Stack:** Python 3.13, `requests` 2.33 (already installed), `argparse` (stdlib), `pytest` + `unittest.mock` for tests, Bash for the wrapper.

**Conventions enforced (from `~/.claude/rules/platform-constraints.md`):**
- `sys.stdout`/`sys.stderr` reconfigured to utf-8 at startup (Windows defaults to cp1252).
- All file I/O uses utf-8.
- No `subprocess(..., text=True)` (not used in this script — wrapper is Bash exec).
- Forward slashes in paths.

---

## Output Convention (resolved 2026-05-01)

**Decision:** everything on stdout.

- Text mode: response text on stdout, followed by `[model] tokens: N in / M out — $X.XXXXXX` on its own line on stdout.
- `-j` mode: raw JSON on stdout (usage already embedded in the response object — no extra line).
- stderr is reserved for errors only.

This means piping into a file captures both the response and the usage line. A `-q`/`--quiet` flag can be added later if needed.

---

## File Structure

| Path | Responsibility |
|------|---------------|
| `~/.claude/scripts/chatgpt.py` | Main script: arg parsing, prompt assembly, HTTP, output. |
| `~/.claude/scripts/test_chatgpt.py` | Pytest suite (run from `~/.claude/scripts/`). |
| `~/bin/chatgpt` | Bash wrapper that execs the Python script. |
| `~/.claude/scripts/PLAN-2026-05-01-chatgpt-wrapper.md` | This plan. |

No new subdirectories. No package init. No external config.

---

## Tasks

### Task 1: Scaffold the script and test files [AFK]

**Files:**
- Create: `~/.claude/scripts/chatgpt.py`
- Create: `~/.claude/scripts/test_chatgpt.py`

- [ ] **Step 1: Create the empty script with module docstring + utf-8 reconfigure**

```python
"""Direct OpenAI Chat Completions wrapper.

Reads OPENAI_API_KEY from env. Prints response on stdout, usage on stderr.
Out of scope: streaming, multi-turn, vision/audio.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests

# Windows default is cp1252; API responses are utf-8.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ENDPOINT = "https://api.openai.com/v1/chat/completions"
TIMEOUT = 60


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Create the empty test file**

```python
"""Tests for chatgpt.py — run from ~/.claude/scripts/ via `pytest test_chatgpt.py`."""
from __future__ import annotations

import io
import sys
from unittest import mock

import pytest

import chatgpt
```

- [ ] **Step 3: Verify pytest can collect the file**

Run: `cd ~/.claude/scripts && pytest test_chatgpt.py --collect-only`
Expected: `0 tests collected` (no error, just empty).

- [ ] **Step 4: Commit**

(No git repo here — skip commit. Mark step done.)

---

### Task 2: Pricing table + `estimate_cost` (TDD) [AFK]

**Files:**
- Modify: `~/.claude/scripts/chatgpt.py`
- Modify: `~/.claude/scripts/test_chatgpt.py`

- [ ] **Step 1: Write failing tests**

Append to `test_chatgpt.py`:

```python
def test_estimate_cost_known_model_simple_math():
    # gpt-4o-mini: $0.150/1M in, $0.600/1M out
    # 1M input + 1M output = 0.150 + 0.600 = $0.750
    assert chatgpt.estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == "$0.750000"


def test_estimate_cost_zero_tokens():
    assert chatgpt.estimate_cost("gpt-4o-mini", 0, 0) == "$0.000000"


def test_estimate_cost_unknown_model():
    assert chatgpt.estimate_cost("future-model", 100, 100) == "(unknown pricing)"
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `cd ~/.claude/scripts && pytest test_chatgpt.py -v`
Expected: FAIL with `AttributeError: module 'chatgpt' has no attribute 'estimate_cost'`.

- [ ] **Step 3: Implement**

Add to `chatgpt.py` after the constants:

```python
# USD per 1M tokens. Source: https://openai.com/api/pricing/
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini":       (0.150,  0.600),
    "gpt-4o":            (2.500, 10.000),
    "gpt-4o-2024-08-06": (2.500, 10.000),
    "gpt-4-turbo":       (10.000, 30.000),
    "o1":                (15.000, 60.000),
    "o1-mini":           (3.000, 12.000),
    "o3-mini":           (1.100,  4.400),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> str:
    if model not in PRICING:
        return "(unknown pricing)"
    in_rate, out_rate = PRICING[model]
    cost = (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000
    return f"${cost:.6f}"
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `pytest test_chatgpt.py -v -k estimate_cost`
Expected: 3 passed.

---

### Task 3: `parse_args` (TDD) [AFK]

**Files:**
- Modify: `~/.claude/scripts/chatgpt.py`
- Modify: `~/.claude/scripts/test_chatgpt.py`

- [ ] **Step 1: Write failing tests**

```python
def test_parse_args_defaults():
    a = chatgpt.parse_args(["hello"])
    assert a.prompt == "hello"
    assert a.model == "gpt-4o-mini"
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
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest test_chatgpt.py -v -k parse_args`
Expected: FAIL on missing `parse_args` attribute.

- [ ] **Step 3: Implement**

Add to `chatgpt.py`:

```python
def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="chatgpt",
        description="One-shot OpenAI Chat Completions wrapper.",
    )
    p.add_argument("prompt", nargs="?", help="Prompt text. If omitted, read from stdin.")
    p.add_argument("-m", "--model", default="gpt-4o-mini", help="Model id (default: gpt-4o-mini).")
    p.add_argument("-s", "--system", default=None, help="System prompt.")
    p.add_argument("-t", "--temperature", type=float, default=None, help="Sampling temperature.")
    p.add_argument("-j", "--json", action="store_true", help="Print raw API JSON to stdout.")
    return p.parse_args(argv)
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `pytest test_chatgpt.py -v -k parse_args`
Expected: 3 passed.

---

### Task 4: `build_payload` (TDD) [AFK]

**Files:**
- Modify: `~/.claude/scripts/chatgpt.py`
- Modify: `~/.claude/scripts/test_chatgpt.py`

- [ ] **Step 1: Write failing tests**

```python
def test_build_payload_user_only():
    a = chatgpt.parse_args(["hello"])
    p = chatgpt.build_payload("hello", a)
    assert p == {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_build_payload_with_system():
    a = chatgpt.parse_args(["-s", "sys", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]


def test_build_payload_with_temperature():
    a = chatgpt.parse_args(["-t", "0.5", "hello"])
    p = chatgpt.build_payload("hello", a)
    assert p["temperature"] == 0.5


def test_build_payload_omits_temperature_when_unset():
    a = chatgpt.parse_args(["hello"])
    p = chatgpt.build_payload("hello", a)
    assert "temperature" not in p
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest test_chatgpt.py -v -k build_payload`
Expected: FAIL on missing `build_payload`.

- [ ] **Step 3: Implement**

```python
def build_payload(prompt: str, args: argparse.Namespace) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": prompt})
    payload: dict[str, Any] = {"model": args.model, "messages": messages}
    if args.temperature is not None:
        payload["temperature"] = args.temperature
    return payload
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `pytest test_chatgpt.py -v -k build_payload`
Expected: 4 passed.

---

### Task 5: `read_prompt` (stdin handling) (TDD) [AFK]

**Files:**
- Modify: `~/.claude/scripts/chatgpt.py`
- Modify: `~/.claude/scripts/test_chatgpt.py`

- [ ] **Step 1: Write failing tests**

```python
def test_read_prompt_positional_wins():
    a = chatgpt.parse_args(["from-arg"])
    assert chatgpt.read_prompt(a) == "from-arg"


def test_read_prompt_from_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("piped prompt"))
    a = chatgpt.parse_args([])
    assert chatgpt.read_prompt(a) == "piped prompt"


def test_read_prompt_no_input_exits(monkeypatch, capsys):
    # io.StringIO.isatty() returns False; force True to simulate interactive shell.
    fake_stdin = io.StringIO("")
    fake_stdin.isatty = lambda: True
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    a = chatgpt.parse_args([])
    with pytest.raises(SystemExit) as exc:
        chatgpt.read_prompt(a)
    assert exc.value.code == 2
    assert "no prompt" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest test_chatgpt.py -v -k read_prompt`
Expected: FAIL on missing `read_prompt`.

- [ ] **Step 3: Implement**

```python
def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    if sys.stdin.isatty():
        sys.stderr.write("error: no prompt provided (pass as arg or pipe stdin)\n")
        sys.exit(2)
    return sys.stdin.read()
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `pytest test_chatgpt.py -v -k read_prompt`
Expected: 3 passed.

---

### Task 6: `call_api` with error mapping (TDD) [AFK]

**Files:**
- Modify: `~/.claude/scripts/chatgpt.py`
- Modify: `~/.claude/scripts/test_chatgpt.py`

- [ ] **Step 1: Write failing tests**

```python
def _fake_response(status: int, body: dict | None = None, text: str = ""):
    r = mock.Mock()
    r.status_code = status
    r.ok = status < 400
    r.text = text
    r.json.return_value = body if body is not None else {}
    return r


def test_call_api_success_returns_json():
    body = {"choices": [{"message": {"content": "hi"}}], "usage": {}}
    with mock.patch("chatgpt.requests.post", return_value=_fake_response(200, body)):
        result = chatgpt.call_api("sk-test", {"model": "gpt-4o-mini", "messages": []})
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
            chatgpt.call_api("sk-test", {"model": "gpt-4o-mini", "messages": []})
        assert exc.value.code == exit_code
    assert frag in capsys.readouterr().err
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest test_chatgpt.py -v -k call_api`
Expected: FAIL on missing `call_api`.

- [ ] **Step 3: Implement**

```python
def call_api(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = requests.post(
        ENDPOINT,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=TIMEOUT,
    )
    if r.status_code == 401:
        sys.stderr.write("error: 401 unauthorized — check OPENAI_API_KEY\n")
        sys.exit(3)
    if r.status_code == 404:
        sys.stderr.write(f"error: 404 model not found — '{payload.get('model')}'\n")
        sys.exit(4)
    if r.status_code == 429:
        sys.stderr.write("error: 429 rate-limited — back off and retry\n")
        sys.exit(5)
    if not r.ok:
        sys.stderr.write(f"error: {r.status_code} — {r.text[:500]}\n")
        sys.exit(6)
    return r.json()
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `pytest test_chatgpt.py -v -k call_api`
Expected: 5 passed (1 success + 4 parametrized error cases).

---

### Task 7: `main()` orchestrator (TDD) [AFK]

**Files:**
- Modify: `~/.claude/scripts/chatgpt.py`
- Modify: `~/.claude/scripts/test_chatgpt.py`

- [ ] **Step 1: Write failing tests**

```python
def test_main_no_api_key(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rc = chatgpt.main(["hello"])
    assert rc == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_main_success_text_output(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    body = {
        "choices": [{"message": {"content": "hi back"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }
    with mock.patch("chatgpt.requests.post", return_value=_fake_response(200, body)):
        rc = chatgpt.main(["hello"])
    out = capsys.readouterr()
    assert rc == 0
    # Both response text AND usage line land on stdout (per output convention).
    assert "hi back" in out.out
    assert "tokens: 5 in / 2 out" in out.out
    assert "gpt-4o-mini" in out.out
    assert out.err == ""


def test_main_json_flag_outputs_full_response(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    body = {
        "choices": [{"message": {"content": "x"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    with mock.patch("chatgpt.requests.post", return_value=_fake_response(200, body)):
        chatgpt.main(["-j", "hello"])
    parsed = __import__("json").loads(capsys.readouterr().out)
    assert parsed == body
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `pytest test_chatgpt.py -v -k main`
Expected: FAIL — `main` raises NotImplementedError.

- [ ] **Step 3: Implement (replace the placeholder `main`)**

```python
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.stderr.write("error: OPENAI_API_KEY not set\n")
        return 1
    prompt = read_prompt(args)
    payload = build_payload(prompt, args)
    data = call_api(api_key, payload)

    if args.json:
        # JSON already includes usage; print it raw and return.
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return 0

    text = data["choices"][0]["message"]["content"]
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")

    usage = data.get("usage", {})
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    cost = estimate_cost(args.model, pt, ct)
    sys.stdout.write(f"[{args.model}] tokens: {pt} in / {ct} out — {cost}\n")
    return 0
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `pytest test_chatgpt.py -v`
Expected: ALL passed (3 main tests + 15 from prior tasks = 18 total).

---

### Task 8: Bash wrapper [AFK]

**Files:**
- Create: `~/bin/chatgpt`

- [ ] **Step 1: Write the wrapper**

```bash
#!/usr/bin/env bash
# Thin wrapper that execs the Python implementation.
# Keeps the user-facing command short and lets the script live with config.
exec python "$HOME/.claude/scripts/chatgpt.py" "$@"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x ~/bin/chatgpt`
Expected: no output, exit 0.

- [ ] **Step 3: Verify it's callable**

Run: `which chatgpt && chatgpt --help`
Expected: prints `/c/Users/you/bin/chatgpt` and the argparse help text.

---

### Task 9: Smoke test against the real API [AFK]

**Files:** none modified.

- [ ] **Step 1: Cheap one-shot call**

Run: `chatgpt -m gpt-4o-mini "Reply with exactly the word: pong"`
Expected on stdout: `pong` (or `pong.`).
Expected on stderr: `[gpt-4o-mini] tokens: N in / M out — $0.0000XX`.

- [ ] **Step 2: Stdin path**

Run: `echo "Reply with exactly: hello" | chatgpt`
Expected: similar to Step 1.

- [ ] **Step 3: System prompt + temperature**

Run: `chatgpt -s "You only say 'ok'" -t 0 "anything"`
Expected: `ok` (or close to it) on stdout.

- [ ] **Step 4: JSON mode**

Run: `chatgpt -j "say hi" | python -c "import json,sys; print(json.load(sys.stdin)['model'])"`
Expected: prints a model id (e.g. `gpt-4o-mini-2024-07-18`).

- [ ] **Step 5: Error path — bad model**

Run: `chatgpt -m totally-fake-model-9000 "hi"; echo "exit=$?"`
Expected: stderr says `404 model not found`, prints `exit=4`.

If any smoke step fails, return to the relevant task to fix.

---

### Task 10: Add to permission allowlist [AFK]

**Files:**
- Modify: `~/.claude/settings.json` (or `~/.claude/settings.local.json`)

- [ ] **Step 1: Invoke the skill**

Run: `/fewer-permission-prompts`

It will scan recent transcripts and propose adding `Bash(chatgpt:*)` to the allowlist. Accept that addition.

- [ ] **Step 2: Verify**

In a fresh prompt, ask Claude to call `chatgpt "test"`. Should run without a permission prompt.

---

## Self-Review

**Spec coverage check:**

| Requirement | Covered by |
|---|---|
| Python script at `~/.claude/scripts/chatgpt.py` | Task 1 |
| Bash wrapper at `~/bin/chatgpt` | Task 8 |
| Reads `OPENAI_API_KEY`, clear error if unset | Task 7 |
| Positional prompt OR stdin | Tasks 3, 5 |
| `-m`, `-s`, `-t`, `-j` flags | Tasks 3, 4, 7 |
| Default model `gpt-4o-mini` | Task 3 |
| Response on stdout, usage on stderr | Task 7 |
| `requests`, 60s timeout | Task 6 |
| 401/429/404/generic error mapping with non-zero exit | Task 6 |
| Tests for arg parsing, stdin, env missing, success, errors | Tasks 2-7 |
| utf-8 (Windows compatibility) | Task 1 (stdout/stderr reconfigure) |

No gaps.

**Placeholder scan:** none — every code step has complete code blocks.

**Type consistency:** `parse_args` returns `argparse.Namespace`; consumed as such by `read_prompt`, `build_payload`, `main`. `call_api` takes `dict[str, Any]` payload, returns same. Pricing dict is `dict[str, tuple[float, float]]` consistently.

---

## Execution Handoff

Plan complete and saved to `~/.claude/scripts/PLAN-2026-05-01-chatgpt-wrapper.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good for keeping the main session lean.
2. **Inline Execution** — Execute tasks in this session using executing-plans. Faster for a small plan like this (10 tasks, mostly mechanical), and you can watch each test go red→green.

For a script this size with full TDD, **inline is probably better** — overhead of spawning subagents per 4-step task is more than the work itself. But your call.

**Open question recap (Task 0):** confirm stdout=text / stderr=usage. Default proceeds otherwise.

**Which approach — inline or subagent-driven?**
