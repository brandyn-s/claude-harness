"""OpenAI Responses API adapter for GPT-5.6 Sol.

Pin bumped gpt-5.5-pro -> gpt-5.6-sol on 2026-08-19 (catalog-verified +
smoke-tested at reasoning_effort=high same day). Sol is the largest GPT-5.6
size; $5/$30 per 1M short-context — a 6x input / 6x output price DROP from
gpt-5.5-pro's $30/$180. Prompts >272K input tokens bill at 2x input / 1.5x
output for the full request.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import http_post_json  # noqa: E402

DEFAULT_MODEL = "gpt-5.6-sol"


def call(prompt: str, max_tokens: int = 32000,
         model: str | None = None,
         retry_on_transient: bool = True,
         reasoning_effort: str = "high") -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"ok": False, "error": "OPENAI_API_KEY not set"}

    result = http_post_json(
        url="https://api.openai.com/v1/responses",
        payload={
            "model": model or DEFAULT_MODEL,
            "input": prompt,
            "max_output_tokens": max_tokens,
            "reasoning": {"effort": reasoning_effort},
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
    usage = data.get("usage", {})

    # An `incomplete` response is still HTTP 200, so http_post_json passed it
    # through as success. The usual cause: reasoning tokens exhaust
    # max_output_tokens before any visible text is emitted (on /v1/responses,
    # reasoning + visible output share the max_output_tokens budget). Surface it
    # loudly instead of returning a JSON fragment as if it were the answer.
    if data.get("status") == "incomplete":
        reason = (data.get("incomplete_details") or {}).get("reason")
        rtoks = usage.get("output_tokens_details", {}).get("reasoning_tokens")
        return {
            "ok": False,
            "error": (f"OpenAI response incomplete (reason={reason}, "
                      f"reasoning_tokens={rtoks}, max_output_tokens={max_tokens}). "
                      f"Raise max_output_tokens, bound the prompt, or for simpler "
                      f"tasks use model=gpt-5.6-terra with reasoning_effort=low."),
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
        }

    # Extract output_text from the Responses API shape
    text_pieces = []
    for item in data.get("output", []):
        if isinstance(item, dict):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                        text_pieces.append(c.get("text", ""))
    text = "\n\n".join(text_pieces)
    if not text:
        # No visible text on a non-incomplete response — fail loud rather than
        # returning json.dumps(data) as if it were GPT's analysis.
        return {
            "ok": False,
            "error": "OpenAI response had no output_text (only reasoning/tool items).",
            "elapsed_s": result["elapsed_s"],
            "retried": result.get("retried", False),
        }
    return {
        "ok": True,
        "text": text,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "elapsed_s": result["elapsed_s"],
        "model": data.get("model", model or DEFAULT_MODEL),
        "retried": result.get("retried", False),
    }
