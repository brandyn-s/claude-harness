#!/usr/bin/env python3
"""Check whether the fresh kernel and optional operator layer are ready."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_claude_version import validate_version  # noqa: E402


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _command_hooks(settings: dict):
    for event, groups in settings.get("hooks", {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                if hook.get("type") == "command":
                    yield event, hook


def inspect_config(config_root: Path) -> list[Check]:
    checks: list[Check] = []
    settings_path = config_root / "settings.json"
    if not settings_path.is_file():
        return [Check("settings", "FAIL", f"missing {settings_path}")]
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Check("settings", "FAIL", f"invalid JSON: {exc}")]

    checks.append(Check("settings", "PASS", "valid JSON"))
    permissions = settings.get("permissions") or {}
    checks.append(
        Check(
            "permission mode",
            "PASS" if permissions.get("defaultMode") in ("acceptEdits", "auto") else "FAIL",
            f"defaultMode={permissions.get('defaultMode')!r}"
            + (" (classifier-judged; deny list and sandbox still apply)" if permissions.get("defaultMode") == "auto" else ""),
        )
    )
    sandbox = settings.get("sandbox") or {}
    sandbox_ok = (
        sandbox.get("enabled") is True
        and sandbox.get("autoAllowBashIfSandboxed", True) is True
        and sandbox.get("allowUnsandboxedCommands") is True
        and "Bash" not in permissions.get("allow", [])
    )
    checks.append(
        Check(
            "native sandbox",
            "PASS" if sandbox_ok else "FAIL",
            "sandboxed Bash is automatic; escape returns to permission review"
            if sandbox_ok
            else "expected sandbox auto-allow without blanket Bash permission",
        )
    )
    mcp_ok = (
        settings.get("enableAllProjectMcpServers") is False
        and settings.get("enabledMcpjsonServers") == []
    )
    checks.append(
        Check(
            "project MCP trust",
            "PASS" if mcp_ok else "FAIL",
            "automatic project MCP activation disabled" if mcp_ok
            else "project MCP servers are not fail-closed",
        )
    )

    plugins = settings.get("enabledPlugins") or {}
    has_superpowers = any(
        str(name).startswith("superpowers@") and enabled for name, enabled in plugins.items()
    ) if isinstance(plugins, dict) else False
    checks.append(
        Check(
            "superpowers plugin",
            "PASS" if has_superpowers else "WARN",
            "companion skills extend superpowers@claude-plugins-official"
            if has_superpowers
            else "not enabled; run /plugin install superpowers@claude-plugins-official "
                 "(debugging-hypotheses, legacy-code-tdd, design-evidence-first and "
                 "review-depth-by-risk extend it)",
        )
    )

    handlers = list(_command_hooks(settings))
    missing: list[str] = []
    for event, hook in handlers:
        command = str(hook.get("command", ""))
        args = hook.get("args") or []
        if Path(command).name == "run-hook" and args:
            target = config_root / "hooks" / str(args[0])
            if not target.is_file():
                missing.append(f"{event}:{args[0]}")
        elif command.startswith(str(config_root)) and not Path(command).is_file():
            missing.append(f"{event}:{command}")
    checks.append(
        Check(
            "hook wiring",
            "PASS" if handlers and not missing else "FAIL",
            f"{len(handlers)} handlers resolve" if handlers and not missing
            else ("missing " + ", ".join(missing[:5]) if missing else "no handlers"),
        )
    )

    operator_rule = config_root / "rules" / "operator-discipline.md"
    operator_requested = (
        "CLAUDE_BASH_POLICY_PACKS" in (settings.get("env") or {})
        or operator_rule.exists()
    )
    if operator_requested:
        packs = {
            item.strip()
            for item in str(
                (settings.get("env") or {}).get("CLAUDE_BASH_POLICY_PACKS", "")
            ).split(",")
            if item.strip()
        }
        # 2026-09-03: the overlay runs the auto-mode classifier; its review
        # boundaries are autoMode.soft_deny prose categories, not ask rules.
        soft_deny = " ".join(
            str(entry).lower()
            for entry in ((settings.get("autoMode") or {}).get("soft_deny") or [])
        )
        required_categories = ("terraform", "iam", "force push", "branch protection")
        review_boundaries_ok = (
            permissions.get("defaultMode") == "auto"
            and all(category in soft_deny for category in required_categories)
        )
        wired_scripts = {
            Path(str((hook.get("args") or [""])[-1])).name
            for _event, hook in handlers
        }
        required_scripts = {
            "loop-detector.py",
            "prompt-secret-scan.py",
            "output-secret-redact.py",
        }
        operator_ok = (
            "delivery" in packs
            and review_boundaries_ok
            and required_scripts.issubset(wired_scripts)
            and operator_rule.is_file()
        )
        checks.append(
            Check(
                "operator layer",
                "PASS" if operator_ok else "FAIL",
                "delivery policy, auto-mode review boundaries, non-progress, and secret controls active"
                if operator_ok
                else "operator layer is partially installed or misconfigured",
            )
        )
    return checks


def inspect_host() -> list[Check]:
    checks: list[Check] = []
    checks.append(
        Check(
            "Python",
            "PASS" if sys.version_info >= (3, 10) else "FAIL",
            platform.python_version(),
        )
    )
    checks.append(
        Check("git", "PASS" if shutil.which("git") else "FAIL", shutil.which("git") or "missing")
    )

    claude = shutil.which("claude")
    if not claude:
        checks.append(Check("Claude Code", "FAIL", "claude command not found"))
    else:
        result = subprocess.run(
            [claude, "--version"], capture_output=True, text=True, timeout=15, check=False
        )
        output = (result.stdout or result.stderr).strip()
        try:
            version = validate_version(output)
            checks.append(Check("Claude Code", "PASS", ".".join(map(str, version))))
        except ValueError as exc:
            checks.append(Check("Claude Code", "FAIL", str(exc)))

    system = platform.system()
    if system == "Linux":
        missing = [name for name in ("bwrap", "socat") if not shutil.which(name)]
        checks.append(
            Check(
                "sandbox dependencies",
                "PASS" if not missing else "FAIL",
                "bubblewrap and socat available" if not missing else "missing " + ", ".join(missing),
            )
        )
    elif system == "Darwin":
        checks.append(Check("sandbox dependencies", "PASS", "macOS Seatbelt is built in"))
    elif system == "Windows":
        checks.append(Check("sandbox dependencies", "FAIL", "use Claude Code inside WSL2"))
    else:
        checks.append(Check("sandbox dependencies", "WARN", f"unqualified platform {system}"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-root",
        type=Path,
        default=Path.home() / ".claude",
    )
    parser.add_argument("--skip-host", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    checks = inspect_config(args.config_root.expanduser().resolve())
    if not args.skip_host:
        checks.extend(inspect_host())
    if args.json:
        print(json.dumps({"checks": [asdict(check) for check in checks]}, indent=2))
    else:
        for check in checks:
            print(f"{check.status:4s}  {check.name}: {check.detail}")
    return 1 if any(check.status == "FAIL" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
