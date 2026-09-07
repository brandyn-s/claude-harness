#!/usr/bin/env python3
"""scripts/migrate-to-core.py: a kitchen-sink settings.json to the core posture."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "migrate-to-core.py"
_spec = importlib.util.spec_from_file_location("migrate_to_core", TOOL)
mtc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mtc
_spec.loader.exec_module(mtc)

KITCHEN_SINK = {
    "permissions": {
        "defaultMode": "auto",
        "allow": ["Bash", "Edit(*)", "Read", "Bash(git *)", "Read(~/Documents/**)", "mcp__github__list_issues"],
        "deny": ["Bash(rm -rf /)"],
    },
    "sandbox": {"enabled": False},
    "skipDangerousModePermissionPrompt": True,
    "hooks": {
        "Stop": [{"hooks": [
            {"type": "command", "command": "/x/run-hook", "args": ["promise-checker.py"], "timeout": 10},
            {"type": "command", "command": "/x/run-hook", "args": ["session-stop.py"], "timeout": 10},
        ]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/x/run-hook", "args": ["bash-pretooluse-dispatcher.py"]}]}],
    },
    "mcpServers": {"github": {"command": "gh-mcp"}},
    "env": {"FOO": "bar"},
}


def test_plan_takes_the_sink_to_the_operator_posture():
    new, changes = mtc.plan(json.loads(json.dumps(KITCHEN_SINK)), "operator")
    steps = {c["step"] for c in changes}
    assert steps == {1, 2, 3, 4, 5, 6}
    assert new["sandbox"]["enabled"] is True and new["sandbox"]["autoAllowBashIfSandboxed"] is True
    assert "~/.ssh" in new["sandbox"]["filesystem"]["denyRead"]
    assert "skipDangerousModePermissionPrompt" not in new
    assert new["permissions"]["allow"] == ["Bash(git *)", "Read(~/Documents/**)", "mcp__github__list_issues"]
    assert "Bash(rm -rf ~)" in new["permissions"]["deny"] and "Bash(rm -rf /)" in new["permissions"]["deny"]
    assert new["permissions"]["defaultMode"] == "auto", "operator keeps auto"
    assert "soft_deny" in new["autoMode"] and "$defaults" in new["autoMode"]["allow"]
    stop_names = [a for g in new["hooks"]["Stop"] for e in g["hooks"] for a in e["args"]]
    assert stop_names == ["session-stop.py"], "the phrase blocker goes; the other Stop hook stays"
    assert new["hooks"]["PreToolUse"] == KITCHEN_SINK["hooks"]["PreToolUse"]
    assert new["mcpServers"] == KITCHEN_SINK["mcpServers"] and new["env"] == KITCHEN_SINK["env"]
    kept = [c for c in changes if c["key"] == "hooks.Stop (kept)"]
    assert kept and kept[0]["after"] == ["/x/run-hook session-stop.py"]


def test_fresh_laptop_target_moves_auto_to_accept_edits_without_an_automode_block():
    new, changes = mtc.plan(json.loads(json.dumps(KITCHEN_SINK)), "fresh-laptop")
    assert new["permissions"]["defaultMode"] == "acceptEdits"
    assert "autoMode" not in new
    assert any(c["key"] == "permissions.defaultMode" and c["before"] == "auto" for c in changes)


def test_bypass_permissions_is_replaced_and_the_core_posture_is_a_fixed_point():
    sink = json.loads(json.dumps(KITCHEN_SINK))
    sink["permissions"]["defaultMode"] = "bypassPermissions"
    new, _ = mtc.plan(sink, "operator")
    assert new["permissions"]["defaultMode"] == "auto"
    again, changes = mtc.plan(json.loads(json.dumps(new)), "operator")
    assert [c for c in changes if c["key"] != "hooks.Stop (kept)"] == [], "a second pass changes nothing"
    assert again == new


def test_blanket_detection_is_exact():
    assert mtc._is_blanket("Bash") and mtc._is_blanket("Bash(*)") and mtc._is_blanket("Edit(**)") and mtc._is_blanket("Read()")
    assert not mtc._is_blanket("Bash(git *)") and not mtc._is_blanket("Read(~/x/**)") and not mtc._is_blanket("mcp__x__y")
    assert not mtc._is_blanket("WebSearch"), "not in the blanket list; left alone"


def test_cli_preview_writes_nothing_and_apply_backs_up(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(KITCHEN_SINK, indent=2), encoding="utf-8")
    before = path.read_bytes()
    res = subprocess.run([sys.executable, str(TOOL), "--settings", str(path)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0 and "preview; nothing written" in res.stdout and "[3] permissions.allow" in res.stdout
    assert path.read_bytes() == before
    res = subprocess.run([sys.executable, str(TOOL), "--settings", str(path), "--apply", "--json"], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["applied"] is True and Path(out["backup"]).read_bytes() == before
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["sandbox"]["enabled"] is True and "skipDangerousModePermissionPrompt" not in written
    res = subprocess.run([sys.executable, str(TOOL), "--settings", str(tmp_path / "missing.json")], capture_output=True, text=True, timeout=60)
    assert res.returncode == 2
