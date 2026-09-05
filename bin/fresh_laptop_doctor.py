#!/usr/bin/env python3
"""Check whether the fresh kernel and optional operator layer are ready.

Config checks run against --config-root (default ~/.claude): settings.json
parses; the permission mode is acceptEdits or auto; the native sandbox
auto-allows Bash without a blanket Bash permission; project MCP servers are
fail-closed; the superpowers plugin is enabled (advisory); every wired command
hook resolves to a file; every *.py directly under hooks/ parses and imports
only names that resolve in this interpreter or beside it (static, hook code
never runs -- added 2026-09-04 after a targeted upgrade left
bash-security-guard.py importing a sibling the install never received, the
guard crashed on import, the fail-closed dispatcher blocked every Bash command,
and this doctor had reported all PASS); and, when the operator layer is
requested, that it is complete. Host checks: Python >= 3.10, git, the Claude
Code version floor, sandbox dependencies. Exit 1 on any FAIL.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_claude_version import validate_version  # noqa: E402 -- resolves via the sys.path insert above


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
    checks.append(inspect_hook_imports(config_root / "hooks"))

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


# ── installed hooks must import only what is installed beside them ─────────

_IMPORT_ERROR_CATCHERS = frozenset({"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(name, ast.Name) and name.id in _IMPORT_ERROR_CATCHERS for name in names)


def _optional_import_ids(tree: ast.AST) -> set[int]:
    """ids of import nodes inside a `try:` whose handlers catch ImportError."""
    try_types = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t is not None)
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, try_types) and any(_catches_import_error(h) for h in node.handlers):
            for statement in node.body:
                ids.update(id(inner) for inner in ast.walk(statement)
                           if isinstance(inner, (ast.Import, ast.ImportFrom)))
    return ids


def _imported_top_level_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.module:
            return [node.module.split(".")[0]]
        return [alias.name for alias in node.names]  # `from . import name`
    return []


def _import_resolves(name: str, hooks_dir: Path) -> bool:
    """Installed beside the hook (<name>.py or <name>/__init__.py), else findable by this interpreter."""
    if (hooks_dir / f"{name}.py").is_file() or (hooks_dir / name / "__init__.py").is_file():
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def inspect_hook_imports(hooks_dir: Path) -> Check:
    """Every *.py directly under hooks_dir must import only what is installed.

    Static: each file is ast-parsed (a syntax error is a FAIL naming file and
    line) and every top-level imported name must resolve beside the hook or via
    importlib.util.find_spec in this interpreter; hook code never runs. An
    import inside `try:` with an `except ImportError` handler is optional and
    is counted, not required. 2026-09-04: an upgraded bash-security-guard.py
    imported a sibling the install had never received, crashed on import, and
    the fail-closed dispatcher blocked every Bash command while this doctor
    reported all PASS.
    """
    hooks = sorted(p for p in hooks_dir.glob("*.py") if p.is_file()) if hooks_dir.is_dir() else []
    failures: list[str] = []
    optional = 0
    for hook in hooks:
        try:
            tree = ast.parse(hook.read_bytes(), filename=str(hook))
        except SyntaxError as exc:
            failures.append(f"hook {hook.name} line {exc.lineno}: syntax error, {exc.msg}")
            continue
        except ValueError as exc:
            failures.append(f"hook {hook.name}: cannot parse ({exc})")
            continue
        optional_ids = _optional_import_ids(tree)
        for node in ast.walk(tree):
            for name in _imported_top_level_names(node):
                if id(node) in optional_ids:
                    optional += 1
                elif not _import_resolves(name, hooks_dir):
                    failures.append(
                        f"hook {hook.name} imports {name}, which is not installed beside it "
                        f"(fix: bash install.sh and upgrade the hooks, or "
                        f"scripts/install-profile.py --install hooks/{name}.py --apply)"
                    )
    if failures:
        more = f" (+{len(failures) - 3} more)" if len(failures) > 3 else ""
        return Check("hook imports", "FAIL", "; ".join(failures[:3]) + more)
    if not hooks:
        return Check("hook imports", "PASS", f"no Python hooks under {hooks_dir}")
    count = f"{len(hooks)} hook{'' if len(hooks) == 1 else 's'}"
    tolerated = "no optional" if not optional else f"{optional} optional"
    return Check(
        "hook imports", "PASS",
        f"{count} import-checked statically; {tolerated} imports (inside try/except catching ImportError)",
    )


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
