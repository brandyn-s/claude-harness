"""Hook output contract: derived from the installed Claude Code binary, enforced on our hooks.

Twice on 2026-09-03 hooks were found emitting shapes the runtime silently ignores
(top-level decision/updated_input, message/result, systemMessage used as a
model-facing channel). This test pins the contract in contracts/hook-output-contract.json,
checks it against the installed binary when one is present (the enum, the keys and every
event we wire must exist in it), and scans every hook source for the legacy shapes so
the bug class cannot return unnoticed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "hook-output-contract.json"
HOOK_DIRS = [ROOT / "hooks", ROOT / "hooks" / "session_start_modules"]

# Shapes the runtime ignores, as emitted by a Python hook (dict literal or json.dumps).
LEGACY_PATTERNS = {
    "snake_case updated_input": re.compile(r'["\']updated_input["\']\s*:'),
    "top-level decision approve/warn/pass": re.compile(r'["\']decision["\']\s*:\s*["\'](approve|warn|pass|info)["\']'),
    "top-level result": re.compile(r'\{\s*["\']result["\']\s*:'),
    "top-level message": re.compile(r'\{\s*["\']message["\']\s*:'),
    "top-level ok": re.compile(r'\{\s*["\']ok["\']\s*:'),
}


def find_binary() -> Path | None:
    env = os.environ.get("CLAUDE_BINARY")
    if env and Path(env).is_file():
        return Path(env)
    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    if versions.is_dir():
        candidates = sorted((p for p in versions.iterdir() if p.is_file()),
                            key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", p.name)])
        if candidates:
            return candidates[-1]
    which = shutil.which("claude")
    return Path(which).resolve() if which else None


def code_lines(text: str):
    """Yield (lineno, line) for lines that are neither comments nor inside docstrings."""
    in_doc = None
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if in_doc:
            if in_doc in stripped:
                in_doc = None
            continue
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                if stripped.count(q) == 1:
                    in_doc = q
                break
        else:
            if not stripped.startswith("#"):
                yield i, line


def legacy_offenders(text: str) -> list[str]:
    hits = []
    for lineno, line in code_lines(text):
        for name, rx in LEGACY_PATTERNS.items():
            if rx.search(line):
                hits.append(f"line {lineno}: {name}: {line.strip()[:100]}")
    return hits


def wired_events() -> set[str]:
    events = set()
    for name in ("settings.json", "settings.example.json"):
        events |= set(json.loads((ROOT / name).read_text(encoding="utf-8")).get("hooks", {}).keys())
    return events


def test_contract_file_is_well_formed():
    c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert c["permissionDecision"] == ["allow", "deny", "ask", "defer"]
    assert {"hookEventName", "permissionDecision", "permissionDecisionReason", "updatedInput", "additionalContext"} <= set(c["hookSpecificOutput_keys"])
    assert {"continue", "stopReason", "suppressOutput", "systemMessage", "decision", "reason", "hookSpecificOutput"} <= set(c["top_level_keys"])
    assert wired_events() <= set(c["events"]), wired_events() - set(c["events"])


def test_contract_matches_the_installed_binary():
    binary = find_binary()
    if binary is None:
        pytest.skip("no Claude Code binary on this machine; set CLAUDE_BINARY to check the contract")
    data = binary.read_bytes()
    c = json.loads(CONTRACT.read_text(encoding="utf-8"))
    enum = "\"" + "\" | \"".join(c["permissionDecision"]) + "\""   # "allow" | "deny" | "ask" | "defer"
    assert enum.encode() in data, f"permissionDecision enum drifted in {binary.name}"
    for key in c["hookSpecificOutput_keys"] + c["top_level_keys"]:
        assert key.encode() in data, f"{key!r} not found in {binary.name}: contract drifted"
    for event in c["events"]:
        assert event.encode() in data, f"event {event!r} unknown to {binary.name}"


def test_no_hook_emits_a_legacy_shape():
    offenders = {}
    for d in HOOK_DIRS:
        for f in sorted(d.glob("*.py")):
            hits = legacy_offenders(f.read_text(encoding="utf-8", errors="replace"))
            if hits:
                offenders[str(f.relative_to(ROOT))] = hits
    assert not offenders, json.dumps(offenders, indent=1)


def test_legacy_scanner_catches_the_known_bad_shapes():
    bad = '''
import json
def main():
    print(json.dumps({"decision": "approve", "updated_input": {"command": "x"}}))
    print(json.dumps({"result": "pass"}))
    print(json.dumps({"message": "hi"}))
    print(json.dumps({"ok": True}))
'''
    kinds = {h.split(": ")[1] for h in legacy_offenders(bad)}
    assert kinds == set(LEGACY_PATTERNS), kinds


def test_legacy_scanner_ignores_comments_and_docstrings():
    text = '''
"""The former {"decision": "approve", "updated_input": ...} shape was IGNORED."""
# {"result": "pass"} never reached the model
def main():
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}))
'''
    assert legacy_offenders(text) == []
