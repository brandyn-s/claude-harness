#!/usr/bin/env python3
"""bin/codex-posture-check.py: the four posture keys, profiles, project overrides, both parsers."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "codex-posture-check.py"
_spec = importlib.util.spec_from_file_location("codex_posture_check", TOOL)
cpc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cpc
_spec.loader.exec_module(cpc)

ALIGNED = '''
model = "gpt-5.6"
approval_policy = "on-request"          # ask before actions outside the sandbox
sandbox_mode = "workspace-write"
approvals_reviewer = "auto_review"

[sandbox_workspace_write]
network_access = false
writable_roots = ["/tmp"]

[mcp_servers.github]
command = "gh-mcp"
'''
UNSAFE = '''
approval_policy = "never"
sandbox_mode = "danger-full-access"

[profiles.careful]
approval_policy = "on-request"
sandbox_mode = "workspace-write"
'''


def test_aligned_config_passes(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(ALIGNED, encoding="utf-8")
    res = cpc.check(cfg, None)
    assert res["aligned"] and not res["hard_fail"]
    assert {r["key"]: r["verdict"] for r in res["rows"]} == {
        "approval_policy": "ok", "sandbox_mode": "ok", "approvals_reviewer": "ok",
        "sandbox_workspace_write.network_access": "ok"}


def test_unsafe_config_is_a_hard_fail_and_profiles_are_judged(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(UNSAFE, encoding="utf-8")
    res = cpc.check(cfg, None)
    assert res["hard_fail"]
    by = {(r["scope"], r["key"]): r["verdict"] for r in res["rows"]}
    assert by[("user", "approval_policy")] == "UNSAFE" and by[("user", "sandbox_mode")] == "UNSAFE"
    assert by[("profile careful", "approval_policy")] == "ok" and by[("profile careful", "sandbox_mode")] == "ok"
    assert by[("user", "approvals_reviewer")] == "unset"


def test_unset_enforcement_keys_are_a_hard_fail(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('model = "gpt-5.6"\n', encoding="utf-8")
    res = cpc.check(cfg, None)
    assert res["hard_fail"]


def test_project_override_of_network_is_the_documented_exception(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(ALIGNED, encoding="utf-8")
    proj = tmp_path / "repo"
    (proj / ".codex").mkdir(parents=True)
    (proj / ".codex" / "config.toml").write_text("[sandbox_workspace_write]\nnetwork_access = true\n", encoding="utf-8")
    res = cpc.check(cfg, proj)
    proj_rows = {r["key"]: r for r in res["rows"] if r["scope"].startswith("project")}
    assert proj_rows["sandbox_workspace_write.network_access"]["ok"]
    assert res["aligned"]
    (proj / ".codex" / "config.toml").write_text('sandbox_mode = "danger-full-access"\n', encoding="utf-8")
    assert cpc.check(cfg, proj)["hard_fail"], "a project that turns the sandbox off is the drift, wherever it lives"


def test_minimal_parser_agrees_with_tomllib_on_the_posture_keys():
    mini = cpc._minimal_toml(ALIGNED)
    assert mini["approval_policy"] == "on-request" and mini["sandbox_mode"] == "workspace-write"
    assert mini["sandbox_workspace_write"]["network_access"] is False
    assert "writable_roots" not in mini["sandbox_workspace_write"], "arrays are skipped, not mis-parsed"
    assert mini["mcp_servers"]["github"]["command"] == "gh-mcp"
    if cpc._toml is not None:
        full = cpc._toml.loads(ALIGNED)
        for key in ("approval_policy", "sandbox_mode", "approvals_reviewer"):
            assert full[key] == mini[key]


def test_cli_exit_codes(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(UNSAFE, encoding="utf-8")
    res = subprocess.run([sys.executable, str(TOOL), "--config", str(cfg)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 1 and "DRIFT" in res.stdout
    cfg.write_text(ALIGNED, encoding="utf-8")
    res = subprocess.run([sys.executable, str(TOOL), "--config", str(cfg), "--json"], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0 and json.loads(res.stdout)["aligned"] is True
    res = subprocess.run([sys.executable, str(TOOL), "--config", str(tmp_path / "missing.toml")], capture_output=True, text=True, timeout=60)
    assert res.returncode == 2
