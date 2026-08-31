"""xAI API adapter for Grok 4.6 (Responses API).

Migrated from /v1/chat/completions 2026-07-05: xAI designates the Responses
API the recommended interface and marks Chat Completions "Deprecated (legacy)"
— the gather-grok first-run headline finding (the Live-Search-410 failure
shape, caught pre-breakage this time). Request/response contract follows the
org's known-good production example (bin/x-monitor.py rides POST /v1/responses)
plus docs.x.ai; response parsing walks output[] -> message -> output_text.

Pin bumped grok-4.20-0309-reasoning -> grok-4.6 on 2026-08-19: xAI's current
flagship (created 2026-08-06, catalog-verified + smoke-tested same day).
grok-4.6 is a reasoning model (effort low/medium/high/xhigh, default high);
context 500k, so it clears the panel's long-context needs.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import http_post_json  # noqa: E402

DEFAULT_MODEL = "grok-4.6"


def call(prompt: str, max_tokens: int = 4000,
         model: str | None = None,
         retry_on_transient: bool = True,
         temperature: float = 0.3) -> dict:
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        return {"ok": False, "error": "XAI_API_KEY not set"}

    result = http_post_json(
        url="https://api.x.ai/v1/responses",
        payload={
            "model": model or DEFAULT_MODEL,
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "input": [{"role": "user", "content": prompt}],
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        retry_on_transient=retry_on_transient,
    )

    if "error" in result:
        return {
            "ok": False,
            "error": result["error"],
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
        }

    data = result["response"]
    texts = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
    if not texts:
        # Reasoning models can emit reasoning items with no message on hard
        # truncation — surface that as a failure, not as empty text.
        kinds = [item.get("type") for item in data.get("output", [])]
        return {
            "ok": False,
            "error": f"no output_text in response (output item types: {kinds})",
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
        }

    usage = data.get("usage", {})
    return {
        "ok": True,
        "text": "\n".join(texts),
        "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)),
        "output_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0)),
        "elapsed_s": result["elapsed_s"],
        "model": data.get("model", model or DEFAULT_MODEL),
        "retried": result.get("retried", False),
    }
