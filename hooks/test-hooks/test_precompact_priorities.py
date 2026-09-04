"""Tests for hooks/precompact-priorities.py (PreCompact).

The hook prints a static checklist to stdout. Claude Code 2.1.260 joins the
trimmed stdout of every successful, non-blocking PreCompact hook into
`newCustomInstructions` and appends it to the summarizer's prompt under
`Additional Instructions:` (see the hook docstring for the binary fragments).
These tests pin the delivery contract that makes that channel work:

  * exit 0 on every input -- a non-zero exit or `decision: block` would block
    compaction, which this hook must never do;
  * plain text, not JSON -- output starting with `{` is parsed as a decision
    object (`parseHookOutput`: "Hook output does not start with {, treating as
    plain text"), so the checklist has to start with something else;
  * small and static -- the text is injected into every compaction of every
    session, so it is byte-capped and reads no files.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

from conftest import run_hook

HOOK = "precompact-priorities.py"
HOOKS_DIR = Path(__file__).resolve().parent.parent
REPO = HOOKS_DIR.parent
BYTE_CAP = 3 * 1024


def _module():
    spec = importlib.util.spec_from_file_location("precompact_priorities", HOOKS_DIR / HOOK)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload(trigger: str, custom: str | None = None) -> dict:
    return {
        "session_id": "sess-1",
        "transcript_path": "/tmp/nope.jsonl",
        "cwd": "/tmp",
        "hook_event_name": "PreCompact",
        "trigger": trigger,
        "custom_instructions": custom,
    }


def test_manual_trigger_exits_zero_with_the_checklist():
    rc, out, err = run_hook(HOOK, _payload("manual"))
    assert rc == 0
    assert err == ""
    assert out.startswith("<compaction-priorities>")
    assert out.rstrip("\n").endswith("</compaction-priorities>")


def test_auto_trigger_emits_the_identical_text():
    _, manual, _ = run_hook(HOOK, _payload("manual"))
    _, auto, _ = run_hook(HOOK, _payload("auto"))
    assert manual == auto
    assert auto.strip() != ""


def test_user_custom_instructions_do_not_change_the_output():
    """Claude Code merges the user's /compact text itself (I6t); the hook never
    tries to echo or rewrite it."""
    _, plain, _ = run_hook(HOOK, _payload("manual"))
    _, custom, _ = run_hook(HOOK, _payload("manual", "focus on the tests"))
    assert plain == custom
    assert "focus on the tests" not in custom


def test_output_is_plain_text_not_json():
    _, out, _ = run_hook(HOOK, _payload("auto"))
    assert not out.lstrip().startswith("{"), "a leading { is parsed as a decision object"
    try:
        json.loads(out)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("checklist must not be valid JSON")


def test_output_is_exactly_the_module_constant_plus_newline():
    """The A/B harness imports PRIORITIES to build its with_priorities arm; the
    shipped stdout has to be byte-identical to what was measured."""
    mod = _module()
    _, out, _ = run_hook(HOOK, _payload("manual"))
    assert out == mod.PRIORITIES + "\n"


def test_injected_text_is_under_the_byte_cap_and_ascii():
    _, out, _ = run_hook(HOOK, _payload("manual"))
    raw = out.encode("utf-8")
    assert len(raw) < BYTE_CAP, f"{len(raw)} bytes >= {BYTE_CAP}"
    assert raw.isascii(), "keep the checklist ASCII so Windows consoles cannot mangle it"


def test_substance_covers_the_five_priorities():
    _, out, _ = run_hook(HOOK, _payload("manual"))
    low = out.lower()
    for needle in ("unanswered", "root cause", "ruled out", "verbatim",
                   "commit sha", "subagent", "chosen"):
        assert needle in low, f"missing priority: {needle!r}"


def test_style_no_shouting_and_no_you_must():
    _, out, _ = run_hook(HOOK, _payload("manual"))
    assert "you must" not in out.lower()
    assert not re.search(r"\b[A-Z]{4,}\b", out), "no all-caps words"


def test_malformed_stdin_still_exits_zero():
    res = subprocess.run([sys.executable, str(HOOKS_DIR / HOOK)], input="}{ not json",
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0


def test_empty_stdin_still_exits_zero():
    res = subprocess.run([sys.executable, str(HOOKS_DIR / HOOK)], input="",
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0


def test_other_events_are_silent():
    """Only PreCompact stdout reaches the summarizer; on any other event plain
    stdout would land in the model's context (UserPromptSubmit) or be dropped."""
    for event in ("UserPromptSubmit", "PostCompact", "SessionStart"):
        rc, out, _ = run_hook(HOOK, {"hook_event_name": event, "session_id": "s"})
        assert rc == 0
        assert out == "", event


def test_hook_is_static_stdlib_only():
    """No file reads, no network, no subprocess: the text is a constant."""
    tree = ast.parse((HOOKS_DIR / HOOK).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"json", "sys"}, imported
    calls = {n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "open" not in calls


def _precompact_groups(settings_path: Path) -> list[dict]:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    groups = settings.get("hooks", {}).get("PreCompact", [])
    return [g for g in groups
            if any(HOOK in (h.get("args") or []) for h in g.get("hooks", []))]


def test_wired_on_precompact_in_live_and_example_settings():
    for name in ("settings.json", "settings.example.json"):
        groups = _precompact_groups(REPO / name)
        assert len(groups) == 1, f"{name}: expected exactly one PreCompact group for {HOOK}"
        matcher = groups[0].get("matcher")
        # The documented PreCompact matchers are `manual` and `auto`; omitting
        # the matcher fires on both. `*` happens to work in 2.1.260 but is not
        # documented for this event.
        assert matcher in (None, "", "manual", "auto", "manual|auto"), matcher
        (hook,) = [h for h in groups[0]["hooks"] if HOOK in (h.get("args") or [])]
        assert hook["type"] == "command"
        assert hook["command"].endswith("/hooks/run-hook")
        # bin/architecture-drift-check.py treats PreCompact as a blocking event and
        # fails any timeout at or below its 10s floor (wrapper start-up is 1.4-4.1s);
        # the hook itself runs in milliseconds, so keep the ceiling small.
        assert 10 < hook.get("timeout", 60) <= 30, hook.get("timeout")
