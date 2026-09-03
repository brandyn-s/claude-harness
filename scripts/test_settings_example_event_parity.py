#!/usr/bin/env python3
"""settings.example.json must register every (event, hook) pair that settings.json does.

bin/architecture-drift-check.py compares the SET of wired scripts and the SET of
event names, so a hook wired under two events live but one in the example passed
the gate. Measured 2026-09-03: compaction-continuity.py is registered on
UserPromptSubmit and PostCompact in settings.json but only on PostCompact in the
example -- and its docstring says the UserPromptSubmit leg is the only one that
can inject context, so a fresh install from the example wrote a marker it never
emitted.

Run: pytest scripts/test_settings_example_event_parity.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _pairs(path: Path) -> set[tuple[str, str]]:
    settings = json.loads(path.read_text(encoding="utf-8"))
    pairs: set[tuple[str, str]] = set()
    for event, groups in (settings.get("hooks") or {}).items():
        for group in groups:
            for hook in group.get("hooks", []) or []:
                if hook.get("type") != "command":
                    continue
                args = hook.get("args") or []
                script = next((a for a in args if isinstance(a, str) and a.endswith(".py")), None)
                if script:
                    pairs.add((event, script))
    return pairs


def test_every_live_event_script_pair_is_in_the_example():
    live = _pairs(REPO / "settings.json")
    example = _pairs(REPO / "settings.example.json")
    assert live, "no exec-form hooks found in settings.json; fixture is wrong"
    missing = sorted(live - example)
    assert missing == [], f"wired live but absent from settings.example.json: {missing}"
