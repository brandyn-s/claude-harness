"""Accessors for the machine-readable model contracts under contracts/.

contracts/model-capabilities.json is the one place that states which Claude
model ids are current, which are superseded, which are Covered Models (30-day
retention), and what request shape each accepts. Tests and tooling read ids
from here instead of repeating literals that go stale at every model rollover.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES_PATH = ROOT / "contracts" / "model-capabilities.json"
RUNTIME_PATH = ROOT / "contracts" / "model-runtime.json"


def capabilities() -> dict:
    return json.loads(CAPABILITIES_PATH.read_text(encoding="utf-8"))


def runtime() -> dict:
    return json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))


def current_models() -> list[dict]:
    return list(capabilities()["models"])


def superseded_models() -> list[dict]:
    return list(capabilities()["superseded"])


def current_ids() -> list[str]:
    return [m["id"] for m in current_models()]


def superseded_ids() -> list[str]:
    return [m["id"] for m in superseded_models()]


def covered_ids() -> list[str]:
    """Covered Models: mandatory 30-day retention, unavailable under ZDR."""
    return [m["id"] for m in current_models() if m["retention"]["covered_model"]]


def model(tier: str) -> dict:
    """The current row for one tier (fable, mythos, opus, sonnet, haiku)."""
    rows = [m for m in current_models() if m["tier"] == tier]
    if len(rows) != 1:
        raise KeyError(f"expected exactly one current {tier!r} row, found {len(rows)}")
    return rows[0]


def model_id(tier: str) -> str:
    return model(tier)["id"]


def display_name(tier: str) -> str:
    return model(tier)["display_name"]


def names(text: str, model_name: str) -> bool:
    """Whether `text` names `model_name` (an id or a display name) as a whole token.

    A plain substring test cannot tell `claude-fable-5` from `claude-fable-5-1`, or
    `Fable 5` from `Fable 5.1`, so every mention of a successor would read as a
    mention of the model it superseded. `us.anthropic.claude-fable-5[1m]` and
    `claude-fable-5.` (end of sentence) still count as naming the model.
    """
    pattern = rf"(?<![\w-]){re.escape(model_name)}(?![\w-])(?!\.\d)"
    return re.search(pattern, text) is not None
