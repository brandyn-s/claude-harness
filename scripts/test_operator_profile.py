from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL_PROFILE = ROOT / "scripts" / "install-profile.py"
INSTALLER = ROOT / "install.sh"
DOCTOR = ROOT / "bin" / "fresh_laptop_doctor.py"


def test_operator_profile_composes_on_fresh_kernel(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"

    result = subprocess.run(
        [
            sys.executable,
            str(INSTALL_PROFILE),
            "--profile",
            "fresh-laptop",
            "--profile",
            "brandyn-operator",
            "--target",
            str(target),
            "--apply",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    settings = json.loads(target.read_text(encoding="utf-8"))
    assert settings["sandbox"]["enabled"] is True
    assert settings["permissions"]["defaultMode"] == "acceptEdits"
    assert settings["env"]["CLAUDE_BASH_POLICY_PACKS"] == "delivery"
    assert "Bash(terraform apply:*)" in settings["permissions"]["ask"]


def test_operator_profile_preserves_existing_review_boundaries(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps(
            {
                "permissions": {
                    "ask": [
                        "Bash(custom-production-release:*)",
                        "Bash(terraform apply:*)",
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(INSTALL_PROFILE),
            "--profile",
            "fresh-laptop",
            "--profile",
            "brandyn-operator",
            "--target",
            str(target),
            "--apply",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    asks = json.loads(target.read_text(encoding="utf-8"))["permissions"]["ask"]
    assert "Bash(custom-production-release:*)" in asks
    assert asks.count("Bash(terraform apply:*)") == 1


def test_installer_deploys_operator_rule_and_hooks(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env bash\necho '2.1.223 (Claude Code)'\n",
        encoding="utf-8",
    )
    claude.chmod(0o755)
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        ["bash", str(INSTALLER)],
        input="y\ny\ny\ny\nn\nn\n",
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    config = tmp_path / "home" / ".claude"
    assert (config / "rules" / "operator-discipline.md").is_file()
    for name in (
        "loop-detector.py",
        "prompt-secret-scan.py",
        "output-secret-redact.py",
    ):
        assert (config / "hooks" / name).is_file()
    settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
    installed = {
        (event, hook.get("args", [""])[-1])
        for event, groups in settings["hooks"].items()
        for group in groups
        for hook in group["hooks"]
    }
    assert ("PostToolUse", "loop-detector.py") in installed
    assert ("UserPromptSubmit", "prompt-secret-scan.py") in installed
    assert ("PostToolUse", "output-secret-redact.py") in installed

    doctor = subprocess.run(
        [
            sys.executable,
            str(DOCTOR),
            "--config-root",
            str(config),
            "--skip-host",
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    checks = {
        check["name"]: check
        for check in json.loads(doctor.stdout)["checks"]
    }
    assert checks["operator layer"]["status"] == "PASS"


def test_installed_operator_controls_make_native_decisions(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    claude = fake_bin / "claude"
    claude.write_text(
        "#!/usr/bin/env bash\necho '2.1.223 (Claude Code)'\n",
        encoding="utf-8",
    )
    claude.chmod(0o755)
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    install = subprocess.run(
        ["bash", str(INSTALLER)],
        input="y\ny\ny\ny\nn\nn\n",
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    config = tmp_path / "home" / ".claude"
    settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
    hook_env = {**env, **settings["env"]}
    run_hook = config / "hooks" / "run-hook"

    delivery = subprocess.run(
        [str(run_hook), "bash-security-guard.py"],
        input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 7 --admin"}}
        ),
        cwd=ROOT,
        env=hook_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert delivery.returncode == 2
    assert "admin" in (delivery.stdout + delivery.stderr).lower()

    fake_pat = "ghp_" + "A" * 36
    prompt = subprocess.run(
        [str(run_hook), "prompt-secret-scan.py"],
        input=json.dumps({"prompt": f"please use {fake_pat}"}),
        cwd=ROOT,
        env=hook_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert prompt.returncode == 2

    output = subprocess.run(
        [str(run_hook), "output-secret-redact.py"],
        input=json.dumps(
            {"tool_name": "Bash", "tool_response": {"stdout": fake_pat, "stderr": ""}}
        ),
        cwd=ROOT,
        env=hook_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert output.returncode == 0
    assert "[REDACTED:GitHub PAT]" in output.stdout

    repeated = {"session_id": "operator-canary", "tool_name": "Read", "tool_input": {"file_path": "x"}}
    loop = None
    for _ in range(3):
        loop = subprocess.run(
            [str(run_hook), "loop-detector.py"],
            input=json.dumps(repeated),
            cwd=ROOT,
            env=hook_env,
            capture_output=True,
            text=True,
            check=False,
        )
    assert loop is not None and loop.returncode == 0
    assert "LOOP DETECTED" in loop.stdout
