#!/usr/bin/env python3
"""install.sh --dry-run walks the whole installer, prints every write, touches nothing.

The installer is the one artifact a stranger has to trust before any gate has
run. These tests pin the contract: exit 0, an empty HOME stays empty, every
write the real install would make appears as a [dry-run] line, and the prompts
answer themselves under HARNESS_ASSUME_DEFAULTS=1.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


def _run(tmp_path: Path, *args: str, assume_defaults: bool = True, stdin: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env.pop("CLAUDE_CONFIG_DIR", None)
    if assume_defaults:
        env["HARNESS_ASSUME_DEFAULTS"] = "1"
    return subprocess.run(["bash", str(INSTALLER), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", env=env, cwd=str(ROOT), timeout=300)


def _files_under(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def test_dry_run_writes_nothing_and_exits_zero(tmp_path):
    result = _run(tmp_path, "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _files_under(tmp_path) == [], _files_under(tmp_path)
    assert not (tmp_path / ".claude").exists()


def test_dry_run_names_every_write_class(tmp_path):
    out = _run(tmp_path, "--dry-run").stdout
    for needle in (
        "DRY RUN: nothing below is written",
        "would create",                                   # config root, rules/, hooks/
        "would set settings.json minimumVersion",         # runtime floor
        "mode: preview",                                  # install-profile.py preview, not --apply
        "No files written",
        "would chmod +x",
        "would register hook [PreToolUse|Bash|PowerShell|bash-pretooluse-dispatcher.py|30]",
        "would register hook [PreToolUse|Write|Edit|script-content-guard.py|15]",
        "would register hook [PreToolUse|Read|read-deny-guard.py|15]",
        "would seed",                                     # environment catalog (operator layer)
    ):
        assert needle in out, f"missing {needle!r} in dry-run output:\n{out[-3000:]}"
    assert "--apply" not in out.replace("Re-run with --apply", "")


def test_dry_run_lists_the_files_it_would_copy(tmp_path):
    out = _run(tmp_path, "--dry-run").stdout
    # install-profile.py preview classifies each starter file as NEW in an empty HOME
    assert "install state:" in out and "NEW" in out


def test_help_and_unknown_argument(tmp_path):
    assert _run(tmp_path, "--help").returncode == 0
    bad = _run(tmp_path, "--frobnicate")
    assert bad.returncode == 2
    assert "unknown argument" in bad.stderr


def test_assume_defaults_answers_every_prompt_without_stdin(tmp_path):
    result = _run(tmp_path, "--dry-run", stdin="")
    assert result.returncode == 0
    assert "-> default (y)" in result.stderr or "-> default (y)" in result.stdout
