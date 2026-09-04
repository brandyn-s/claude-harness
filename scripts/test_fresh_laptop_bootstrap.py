from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


def test_recommended_install_builds_portable_core_in_empty_config(tmp_path: Path) -> None:
    config = tmp_path / ".claude"
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["CLAUDE_CONFIG_DIR"] = str(config)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        ["bash", str(INSTALLER)],
        # fresh profile, skip operator overlay, starter core, wire hooks,
        # skip repo githooks, stop before optional components
        input="y\nn\ny\ny\nn\nn\n",
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["defaultMode"] == "acceptEdits"
    assert settings["sandbox"] == {
        **settings["sandbox"],
        "enabled": True,
        "allowUnsandboxedCommands": True,
    }
    assert "Bash" not in settings["permissions"].get("allow", [])
    handlers = [
        hook
        for groups in settings["hooks"].values()
        for group in groups
        for hook in group["hooks"]
    ]
    # Bash safety is one registration: the dispatcher, which runs the two Bash
    # guards and four advisories in-process (the repository's own shape).
    assert {hook["args"][0] for hook in handlers} == {
        "bash-pretooluse-dispatcher.py",
        "config-guard.py",
        "result-injection-guard.py",
        "read-deny-guard.py",
    }
    assert (config / "rules" / "outcome-over-verification.md").is_file()
    assert (config / "rules" / "claude-md-quality.md").is_file()
    for name in (
        "run-hook",
        "hook_input.py",
        "manifest_metrics.py",
        "protected-repos.json",
        "bash_policy_tables.py",
        "_environment_catalog.py",
        "bash-pretooluse-dispatcher.py",
        "bash-security-guard.py",
        "destructive-ops-guard.py",
        "git-destructive-checkout-guard.py",
        "bash-tail-buffering-guard.py",
        "zsh-dialect-guard.py",
        "poll-loop-nudge.py",
        "config-guard.py",
        "result-injection-guard.py",
        "read-deny-guard.py",
    ):
        assert (config / "hooks" / name).is_file(), name

    doctor = subprocess.run(
        [
            os.sys.executable,
            str(ROOT / "bin" / "fresh_laptop_doctor.py"),
            "--config-root",
            str(config),
            "--skip-host",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr


def test_policy_packs_are_opt_in_for_fresh_core_and_all_on_for_author_profile() -> None:
    fresh = json.loads(
        (ROOT / "profiles" / "fresh-laptop" / "settings.json").read_text(
            encoding="utf-8"
        )
    )
    author = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))

    assert "CLAUDE_BASH_POLICY_PACKS" not in fresh.get("env", {})
    assert author["env"]["CLAUDE_BASH_POLICY_PACKS"] == "all"
