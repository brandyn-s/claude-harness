"""Smoke tests for destructive-ops-guard.py.

Covers the three incident classes from the 2026-04-29 → 2026-05-23
insights report: data/index deletion, MCP process kill, and Windows
registry deletion.
"""
import os

from conftest import make_bash_input, make_powershell_input, run_hook

HOOK = "destructive-ops-guard.py"


# ── Allow paths (no destructive patterns) ────────────────────────────

def test_allow_plain_ls():
    rc, _, _ = run_hook(HOOK, make_bash_input("ls -la"))
    assert rc == 0


def test_allow_rm_non_data_path():
    rc, _, _ = run_hook(HOOK, make_bash_input("rm -rf /tmp/build-output"))
    assert rc == 0


def test_allow_rm_without_recursive_force():
    rc, _, _ = run_hook(HOOK, make_bash_input("rm voyage_indexes.log"))
    assert rc == 0


def test_allow_kill_non_mcp_process():
    rc, _, _ = run_hook(HOOK, make_bash_input("kill 12345"))
    assert rc == 0


def test_allow_pkill_unrelated_name():
    rc, _, _ = run_hook(HOOK, make_bash_input("pkill nginx"))
    assert rc == 0


def test_allow_powershell_get_childitem():
    rc, _, _ = run_hook(HOOK, make_powershell_input("Get-ChildItem ."))
    assert rc == 0


def test_allow_non_bash_non_powershell_tool():
    payload = {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}
    rc, _, _ = run_hook(HOOK, payload)
    assert rc == 0


# ── Block: rm/Remove-Item of data/index paths ────────────────────────

def test_block_rm_rf_indexes_dir():
    rc, _, stderr = run_hook(HOOK, make_bash_input("rm -rf ./indexes"))
    assert rc == 2
    assert "destructive-ops-guard" in stderr
    assert "data/index" in stderr or "voyage" in stderr


def test_block_rm_rf_voyage_path():
    rc, _, stderr = run_hook(HOOK, make_bash_input("rm -rf ./voyage_cache"))
    assert rc == 2
    assert "destructive-ops-guard" in stderr


def test_block_rm_rf_fts5_db():
    rc, _, stderr = run_hook(HOOK, make_bash_input("rm -rf .cache/fts5.db"))
    assert rc == 2


def test_block_rm_rf_manifests_dir():
    rc, _, stderr = run_hook(HOOK, make_bash_input("rm -rf manifests/"))
    assert rc == 2


def test_block_rm_fr_flag_order():
    rc, _, _ = run_hook(HOOK, make_bash_input("rm -fr ./indexes"))
    assert rc == 2


def test_block_rm_long_flags():
    rc, _, _ = run_hook(
        HOOK, make_bash_input("rm --recursive --force ./indexes")
    )
    assert rc == 2


def test_block_remove_item_recurse_force_indexes():
    rc, _, _ = run_hook(
        HOOK, make_powershell_input("Remove-Item -Recurse -Force ./indexes")
    )
    assert rc == 2


def test_block_remove_item_force_recurse_voyage():
    rc, _, _ = run_hook(
        HOOK, make_powershell_input("Remove-Item -Force -Recurse ./voyage_cache")
    )
    assert rc == 2


def test_allow_remove_item_without_force():
    rc, _, _ = run_hook(
        HOOK, make_powershell_input("Remove-Item -Recurse ./indexes")
    )
    assert rc == 0


# ── Block: MCP process kill ──────────────────────────────────────────

def test_block_kill_mcp_process():
    rc, _, stderr = run_hook(HOOK, make_bash_input("kill $(pgrep -f mcp-server)"))
    assert rc == 2
    assert "MCP" in stderr


def test_block_pkill_fastmcp():
    rc, _, _ = run_hook(HOOK, make_bash_input("pkill -f fastmcp"))
    assert rc == 2


def test_block_pkill_code_search():
    rc, _, _ = run_hook(HOOK, make_bash_input("pkill -f code-search"))
    assert rc == 2


def test_block_taskkill_mcp():
    rc, _, _ = run_hook(
        HOOK, make_bash_input("taskkill /F /IM mcp-server.exe")
    )
    assert rc == 2


def test_block_taskkill_node():
    rc, _, _ = run_hook(HOOK, make_powershell_input("taskkill /F /IM node.exe"))
    assert rc == 2


def test_block_stop_process_mcp():
    rc, _, _ = run_hook(
        HOOK, make_powershell_input("Stop-Process -Name mcp-server")
    )
    assert rc == 2


def test_block_stop_process_python_by_name():
    rc, _, _ = run_hook(HOOK, make_powershell_input("Stop-Process -Name python"))
    assert rc == 2


# ── Block: Windows registry deletion ─────────────────────────────────

def test_block_reg_delete_hkcu():
    rc, _, stderr = run_hook(
        HOOK,
        make_bash_input(r'reg delete "HKCU\Software\Anthropic\Claude" /f'),
    )
    assert rc == 2
    assert "registry" in stderr.lower() or "hive" in stderr.lower()


def test_block_reg_delete_powershell():
    rc, _, _ = run_hook(
        HOOK,
        make_powershell_input(r'reg delete "HKLM\SOFTWARE\Policies\Claude" /f'),
    )
    assert rc == 2


def test_block_remove_item_hklm():
    rc, _, _ = run_hook(
        HOOK,
        make_powershell_input("Remove-Item -Path HKLM:\\SOFTWARE\\Policies\\Claude"),
    )
    assert rc == 2


def test_block_remove_item_hkcu():
    rc, _, _ = run_hook(
        HOOK,
        make_powershell_input("Remove-Item HKCU:\\Software\\Anthropic"),
    )
    assert rc == 2


def test_block_remove_itemproperty_hklm():
    rc, _, _ = run_hook(
        HOOK,
        make_powershell_input(
            "Remove-ItemProperty -Path HKLM:\\SOFTWARE\\Policies\\Claude -Name DevToolsLockdown"
        ),
    )
    assert rc == 2


# ── Bypass paths ─────────────────────────────────────────────────────

def test_bypass_with_confirm_token():
    rc, _, _ = run_hook(
        HOOK, make_bash_input("rm -rf ./indexes  # confirmed-destructive")
    )
    assert rc == 0


def test_bypass_with_env_var(monkeypatch=None):
    # conftest's run_hook spawns a subprocess, so we set the env before.
    os.environ["CLAUDE_DESTRUCTIVE_CONFIRM"] = "1"
    try:
        rc, _, _ = run_hook(HOOK, make_bash_input("rm -rf ./indexes"))
        assert rc == 0
    finally:
        os.environ.pop("CLAUDE_DESTRUCTIVE_CONFIRM", None)


# ── False-positive prevention: quoted/heredoc content ───────────────

def test_allow_pattern_inside_quoted_commit_message():
    # `git commit -m` with patterns in the message should pass.
    cmd = (
        'git commit -m "Fix: rm -rf ./indexes was wrong; restored from backup"'
    )
    rc, _, _ = run_hook(HOOK, make_bash_input(cmd))
    assert rc == 0


def test_allow_pattern_inside_heredoc():
    cmd = (
        "git commit -m \"$(cat <<'EOF'\n"
        "Notes on past incident\n"
        "rm -rf indexes was the wrong move; document the postmortem\n"
        "EOF\n"
        ")\""
    )
    rc, _, _ = run_hook(HOOK, make_bash_input(cmd))
    assert rc == 0


# ── Malformed input ──────────────────────────────────────────────────

def test_allow_empty_command():
    rc, _, _ = run_hook(HOOK, {"tool_name": "Bash", "tool_input": {"command": ""}})
    assert rc == 0


def test_allow_missing_tool_input():
    rc, _, _ = run_hook(HOOK, {"tool_name": "Bash"})
    assert rc == 0


def test_allow_malformed_json():
    # run_hook always serializes a dict, so simulate empty payload here:
    import subprocess
    import sys
    from pathlib import Path

    hook_path = Path(__file__).resolve().parent.parent / HOOK
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="not valid json",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
